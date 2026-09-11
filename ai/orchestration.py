import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

from analytics.instrumentation import track_llm_call
from analytics.services import record_event
from integrations.climate import ClimateProviderError, get_climate_provider
from recommendations.scoring import (
    RecommendationRequest,
    ScoredDestination,
    generate_recommendations,
)
from travel.geography import CONTINENT_CHOICES
from travel.models import (
    COST_OF_LIVING_CHOICES,
    TRIP_TYPE_CHOICES,
    CountryEntryRequirement,
    Destination,
)
from travel.services import (
    ENTRY_REQUIREMENT_DISCLAIMER,
    find_destination_slugs_by_name,
    get_entry_requirements,
    resolve_country_name,
)
from trips.models import FEEDBACK_TAG_CHOICES, Feedback, TravelHistoryEntry, Trip
from users.currency import convert_to_usd
from users.models import TravelerProfile

from . import memory
from .prompts import SYSTEM_PROMPT
from .provider import AIMessage, AIProvider, AIProviderError, get_ai_provider

logger = logging.getLogger(__name__)

# Caps how many destinations the AI ever explains and how many cards
# reach the UI - keeps token spend and traveler cognitive load bounded
# even against a 384-destination catalog that can return dozens of
# matches on a broad trip_type. One constant governs both, kept in sync
# on purpose - stream_travel_recommendation slices `results` down to this
# exactly once.
MAX_RECOMMENDATIONS = 10
FEEDBACK_TAG_KEYS = {key for key, _label in FEEDBACK_TAG_CHOICES}
# Pulled from travel.models rather than duplicated here - a standalone
# copy of these choices drifted out of sync with the real model once
# already, so travel.models stays the one source of truth.
TRIP_TYPE_CODES = [code for code, _label in TRIP_TYPE_CHOICES]
CONTINENT_CODES = [code for code, _label in CONTINENT_CHOICES]
MAX_COST_OF_LIVING_TIER = len(COST_OF_LIVING_CHOICES)

FALLBACK_REPLY = (
    "I'm having trouble reaching my reasoning engine right now. Please try again in a moment."
)
NEEDS_LOGIN_REPLY = (
    "I'd love to remember that for you, but you'll need to log in or create an "
    "account first so I can save it to your profile."
)

INTENT_EXTRACTION_SYSTEM_PROMPT = (
    "You classify a traveler's message and extract structured information "
    "from it. Judge message_type using ONLY what the CURRENT message itself "
    "says - conversation history is context to help you understand the "
    "current message (e.g. what a vague reply is answering), never a "
    "pattern to keep repeating. If an earlier message was off_topic or "
    "unclear, that has no bearing on how you classify this new message; "
    "re-read this message on its own merits every time. Set message_type "
    "to exactly one of:\n"
    "- 'recommendation': the user wants a travel suggestion right now - "
    "this includes short, plain expressions of wanting to travel with no "
    "other detail yet (e.g. 'I want to travel', 'quero viajar', 'I need a "
    "vacation'). These are real, if incomplete, travel requests - almost "
    "never off_topic.\n"
    "- 'feedback': the user is describing a place THEY THEMSELVES have "
    "personally already visited - a rating, likes/dislikes, a comment "
    "about a trip they took. This requires a clear signal that they are "
    "recounting their own past visit (e.g. past tense - 'fui a', 'visitei', "
    "'estive em', 'I went to', 'we stayed in', 'when I was there') AND a "
    "specific place. A request for the assistant to evaluate, rank, rate, "
    "or list places in general (e.g. 'what are the 5 worst places to visit "
    "in winter', 'quais os piores destinos') is NEVER feedback, even though "
    "it uses evaluative words like 'worst' or 'rate' - the user is asking "
    "FOR information, not GIVING an account of their own trip. That is "
    "'recommendation' instead (see below - it covers any request for "
    "travel information or suggestions, not just positive ones).\n"
    "- 'future_intent': the user, unprompted, brings up an actual place (a "
    "city, country, or region) as their own standing goal or plan to visit "
    "someday, without asking for a recommendation right now (e.g. 'I've "
    "always wanted to see Kyoto', 'planejo ir para o Chile um dia'). This "
    "requires a real named destination AND the user themselves introducing "
    "it as a personal intent - wanting to travel, changing your mind, or "
    "expressing eagerness/excitement is not future_intent by itself, and "
    "neither is simply naming a place. A message that only states timing "
    "(a month, a season, 'someday', 'sometime soon') or only expresses "
    "wanting or deciding to travel with no destination named at all (e.g. "
    "'I want to go', 'quero viajar', 'mudei de ideia, quero ir em abril' / "
    "'I changed my mind, I want to go in April') is NOT future_intent, "
    "even if it uses words like 'someday' or 'quero' - it is almost always "
    "the user answering or updating what month they want to travel for an "
    "ongoing recommendation request, so classify it as 'recommendation' "
    "instead and extract the month from it. The same applies even when a "
    "destination IS named, and even when a concrete near-term timeframe "
    "(a specific month, season, or 'this year') is named alongside it, as "
    "long as the message doesn't actually frame it as a someday/standing "
    "goal: 'quero ir pra Tailândia', 'I want to go to Thailand', 'quiero "
    "ir a Tailandia', 'je veux visiter le Portugal', 'je veux visiter le "
    "Portugal cet été' (this summer), 'I want to go to Japan in March' "
    "are all present-tense statements of wanting to go, not different in "
    "kind from 'quero viajar' above except that a place (and sometimes a "
    "timeframe) is filled in - classify these as 'recommendation' too, "
    "extracting the named place into country/continent below and any "
    "concrete month into month, exactly as if they had said 'I want to go "
    "to Thailand, any suggestions?'. Only use future_intent when the "
    "message itself frames the place as something "
    "to visit eventually/someday rather than a trip to help plan right "
    "now - explicit markers like 'algum dia', 'um dia', 'someday', 'one "
    "day', 'my dream is to...', 'I've always wanted to...', or a stated "
    "longer-term timeframe ('ano que vem', 'next year'). Crucially: if your own "
    "immediately preceding reply just suggested destinations or asked "
    "which of them interests the traveler, and the current message is "
    "just naming one of them (or a short reaction to it, e.g. 'Bahia', "
    "'I like that one', 'tell me more about that one'), that is the "
    "traveler picking from YOUR suggestions to keep narrowing down an "
    "ongoing search - classify it as 'recommendation', not future_intent, "
    "even though a place is named. future_intent is reserved for the "
    "traveler spontaneously raising a place as their own goal, never for "
    "selecting from options you just gave them.\n"
    "- 'off_topic': the message itself is not about travel at all (e.g. a "
    "question about something unrelated, small talk with no travel intent "
    "at all like a bare greeting). Only use this when the message truly "
    "has nothing to do with travel - a vague or short travel-related "
    "message is 'recommendation', not this.\n"
    "When a message is genuinely ambiguous between 'recommendation' and "
    "any other category, prefer 'recommendation' - it is the safest "
    "default (never blocks on login, never dead-ends the conversation) "
    "and keeps things moving toward a real answer; reserve 'feedback' and "
    "'future_intent' for messages that clearly and unambiguously fit their "
    "stricter definitions above.\n"
    "Only fill in the fields relevant to the chosen message_type - leave "
    "every other field at its default (null, false, or an empty list). "
    "The traveler may write in any language - understand it and extract "
    "from it the same way regardless of language.\n"
    "Conversation history, when present, includes your OWN prior replies - "
    "these often mention specific numbers (a destination's exact "
    "temperature, its cost tier) or ask about climate/budget as part of a "
    "question. Never treat a number YOU stated earlier as something the "
    "traveler asked for, and never treat the traveler answering ONE part "
    "of a multi-part question you asked (e.g. picking a trip_type from a "
    "list that also asked about timing and budget) as if they'd also "
    "answered the other parts - if they only said 'praia'/'beach' in "
    "reply to a question that also asked about climate or budget, that "
    "still only sets trip_type; min_temp_c and max_cost_of_living stay "
    "null exactly as they would with zero conversation history at all. "
    "Every field below is extracted only from what the traveler themselves "
    "explicitly wrote, in this message or earlier ones - if they only "
    "reacted to a suggestion (e.g. 'sounds good', a bare month, 'yes') "
    "without restating a preference, do not infer temperature or budget "
    "thresholds from the destinations or questions you happened to "
    "mention.\n\n"
    "--- Fields for message_type = 'recommendation' ---\n"
    "Extract whatever the traveler actually gave you - never ask a "
    "follow-up question and never treat any field as required. A real "
    "person will rarely state every dimension (month, climate, budget, "
    "trip type) in one message, and should never be blocked from getting "
    "a real answer because of that - every field below is optional, and "
    "leaving one null just means the application treats that dimension as "
    "not relevant/unconstrained, not as something missing to chase.\n"
    "month: extract only if stated or clearly implied - never guess one. "
    "If the user names a range of two consecutive months (e.g. 'September "
    "or October', 'between September and October'), extract the earlier "
    "of the two. If no month is stated at all, leave it null - the "
    "application already assumes a reasonable month automatically in that "
    "case, so this is never something to ask about.\n"
    "For temperature and budget, the user will often describe them "
    "qualitatively rather than with an exact number - translate that "
    "description into a concrete threshold using these anchors, so the "
    "application can actually filter on it, but ONLY when the user's own "
    "words actually describe that dimension. A trip_type alone never "
    "implies a temperature or budget, no matter how strongly it's "
    "stereotypically associated with one - 'praia'/'beach' by itself does "
    "NOT mean min_temp_c=28; a beach trip can be mild, off-season, or the "
    "traveler simply may not care about the exact temperature. The same "
    "goes for budget: naming a destination or trip_type never implies a "
    "cost tier by itself. A trip_type combined with a month is still not "
    "a temperature statement - e.g. 'praia em julho'/'beach in July' has "
    "a trip_type and a month but says nothing about temperature, so "
    "min_temp_c stays null; do not reason 'they mentioned a month for a "
    "beach trip, so they probably want to know it'll be warm then' - only "
    "set min_temp_c when the message itself contains a temperature word "
    "or number. The same applies when the message also mentions food, "
    "relaxation, or a general vibe alongside the trip_type - e.g. 'a "
    "relaxing beach trip with great food' names a trip_type and a mood, "
    "but still no temperature word, so min_temp_c stays null there too; "
    "'relaxing' describes pace, not warmth. Set these two fields only from "
    "words that are themselves about temperature or money:\n"
    "- Temperature (min_temp_c): 'hot' -> 28, 'warm' -> 22, 'mild' -> 18. "
    "If the user wants somewhere cool or cold, or says nothing at all about "
    "temperature, leave min_temp_c null - this includes messages that only "
    "name a trip_type, destination, or month with no temperature words at "
    "all.\n"
    "- Upper temperature bound (max_temp_c): the mirror image of "
    "min_temp_c, for when the user wants an upper limit instead of (or as "
    "well as) a lower one - 'not too hot'/'nothing extreme' -> 30, "
    "'cool'/'mild, not hot' -> 22, 'cold'/'chilly'/'somewhere cool and "
    "crisp' -> 15. Only set this from words that are themselves about an "
    "upper temperature limit or wanting it cool/cold - never infer it from "
    "a trip_type, destination, or month alone, exactly like min_temp_c "
    "above. A message can set both min_temp_c and max_temp_c together "
    "(e.g. 'mild, not too hot and not too cold') or just one.\n"
    "- Budget (max_cost_of_living, a 1-5 scale where 1 is cheapest): "
    "'very cheap'/'budget'/'affordable' -> 2, 'cheap'/'not too expensive'/"
    "'inexpensive' -> 3, 'moderate'/'mid-range' -> 4. If the user wants "
    "luxury, or says nothing at all about budget, leave max_cost_of_living "
    "null - this includes messages that only name a trip_type, "
    "destination, or month with no budget words at all. Words describing "
    "a travel style or atmosphere - 'refined'/'refinado', 'upscale', "
    "'elegant', 'sophisticated', 'classy' - are NOT budget words: they "
    "describe the kind of place someone wants, not what they're willing "
    "to pay, and fall under the same 'wants luxury' case above - leave "
    "max_cost_of_living null for these unless the message also contains "
    "an actual price/affordability word from the anchors above.\n"
    "Only leave min_temp_c or max_cost_of_living null when the user gave no "
    "indication at all for that dimension - do not leave it null just "
    "because they used words instead of a number.\n"
    "For trip_type, only set it when the message clearly matches one of "
    "exactly these four categories: 'beach' (beach/coastal holiday), "
    "'city' (city break/urban trip), 'nature' (outdoors/adventure/hiking), "
    "'culture' (history/museums/cultural immersion). Leave it null if the "
    "request doesn't clearly match one of these four, or matches more than "
    "one - do not force-fit a vibe like 'romantic' or 'family-friendly' "
    "into one of these categories just because you have to pick something. "
    "This includes 'a family trip with young children'/'viagem em família "
    "com crianças pequenas' - having young kids says nothing about beach "
    "vs. city vs. nature vs. culture (any of the four can be great for a "
    "family), so trip_type stays null here too unless a real category word "
    "is also present. It also includes 'planning a romantic honeymoon "
    "trip'/'lua de mel romântica' on its own - a honeymoon can just as "
    "easily be a beach, city, nature, or culture trip, so 'romantic'/"
    "'honeymoon' alone is never enough to pick one; trip_type stays null "
    "here too unless a real category word is also present. The same "
    "applies to 'relaxing'/'relaxante'/"
    "'rilassante'/'relajante' and similar pace words on their own (e.g. "
    "'a relaxing trip to Japan', 'quero uma viagem relaxante para o "
    "Japão', 'qualcosa di rilassante') - relaxing describes pace, not a "
    "category, and is NOT a signal to pick whichever of the four "
    "categories is stereotypically associated with the named destination "
    "(e.g. do not set 'nature' for a relaxing trip to Japan, or 'beach' "
    "for a relaxing trip to Greece) - trip_type stays null here too "
    "unless a real category word is also present.\n"
    "continent: set this when the traveler names or clearly implies ONE "
    "continent/region as where they want to go - a continent name itself "
    "('Europe', 'Ásia'), a well-known colloquial term for a trip there "
    "('Eurotrip', 'Eurotour' -> 'europe'), or a specific country/city that "
    "unambiguously belongs to one continent ('Japan', 'quero ir a Roma' -> "
    "'asia'/'europe' respectively). Use exactly one of: 'europe', 'asia', "
    "'africa', 'north_america', 'south_america', 'oceania'. Leave it null "
    "if no continent/region/country was named or implied, or if what was "
    "named doesn't map to a single continent (e.g. 'somewhere warm', "
    "'anywhere with beaches').\n"
    "country: set this ONLY when the traveler names or clearly asks for "
    "ONE specific country (e.g. 'quero ir pra Tailândia', 'somewhere in "
    "Japan') - always give the country's standard English name (e.g. "
    "'Alemanha' -> 'Germany', 'Tailândia' -> 'Thailand', 'Japan' stays "
    "'Japan'), regardless of what language the traveler used, since this "
    "value is matched against a destination catalog that stores every "
    "country name in English - any other language's spelling would "
    "silently match nothing and the traveler would wrongly get zero "
    "results. This is narrower and more specific than continent: naming "
    "a single country sets BOTH country and continent together (e.g. "
    "'Thailand' sets country='Thailand' AND continent='asia'), since a single-"
    "country request should never quietly return results from OTHER "
    "countries in the same continent/region. Leave country null for "
    "anything broader than one country - a multi-country region or "
    "colloquial regional term ('Europe', 'Eurotrip', 'Southeast Asia', "
    "'the Caribbean', 'Scandinavia'/'Escandinávia') sets continent only, "
    "never country, since those genuinely span many countries. Also "
    "null if no specific country was named at all.\n"
    "If the user asks to avoid or exclude specific places, countries, or "
    "regions, list the place/country names they mentioned in "
    "excluded_place_names (e.g. ['Marrakech', 'Morocco']). Leave it as an "
    "empty list if they mentioned no exclusions.\n\n"
    "--- Fields for message_type = 'feedback' ---\n"
    "feedback_destination_name: the name of the place they're giving "
    "feedback about, as they wrote it. Null if unclear.\n"
    "feedback_rating: a 1-10 rating if the user gave or clearly implied one "
    "(e.g. 'amazing' ~ 9, 'terrible' ~ 2). Null if no sentiment was expressed "
    "at all - never invent a rating from a neutral factual statement.\n"
    "feedback_tags: choose zero or more from exactly these values - "
    "excellent_food, great_value, friendly_locals, beautiful_scenery, "
    "too_crowded, overpriced, poor_weather, hard_to_get_around. Only include "
    "a tag when the message clearly supports it.\n"
    "feedback_comment: a short paraphrase of any free-form remark they made, "
    "or null.\n\n"
    "--- Fields for message_type = 'future_intent' ---\n"
    "future_destination_name: the name of the place they want to visit "
    "someday, as written. Null if unclear.\n\n"
    "--- is_recall_request (independent of message_type, check this for "
    "any message) ---\n"
    "true when the traveler is asking you to repeat, recall, or remind "
    "them what YOU (the assistant) already said earlier in this same "
    "conversation - e.g. 'quais praias você tinha sugerido?', 'what were "
    "those options again?', 'lembra o que você falou antes?', 'voltando, "
    "quais eram mesmo?'. This is specifically about recalling your own "
    "prior replies from the history above, never about looking up "
    "anything new. False for everything else, including a message that "
    "reuses a word from earlier but is actually asking for something new "
    "or different - 'me dá mais opções de praia' asks for MORE/NEW "
    "options, not a recall of the old ones, so that stays false.\n\n"
    "--- is_visa_or_entry_question (independent of message_type) ---\n"
    "true when the traveler is asking about visa, vaccine, travel "
    "insurance, or other entry requirements for one or more countries - "
    "either a general question ('quais países não precisam de visto para "
    "brasileiros', 'which countries require mandatory travel insurance') "
    "or about one specific destination ('do I need a visa for Japan?'). "
    "False for everything else, including a normal destination-"
    "recommendation request that happens to also mention wanting to "
    "avoid a visa (that stays 'recommendation' - only set this true when "
    "the visa/entry question IS the point of the message, not an "
    "incidental filter on a search).\n"
    "visa_question_country: if the question names ONE specific "
    "destination country, that country's standard English name (e.g. "
    "'Japão' -> 'Japan'), regardless of what language the traveler used "
    "- the verified entry-requirements data is looked up by this exact "
    "English name, so any other language's spelling would silently find "
    "nothing even when real data exists. Null if the "
    "question is general/not about one specific country, or if "
    "is_visa_or_entry_question is false.\n"
    "visa_question_nationality: the traveler's own nationality/home "
    "country, ONLY if explicitly stated in THIS message (e.g. 'sendo "
    "brasileiro' -> 'Brazil', 'as a US citizen' -> 'United States'). "
    "Null if not stated in this message - never guess a nationality that "
    "wasn't actually mentioned here; the application checks the "
    "traveler's saved profile separately as a fallback.\n\n"
    "--- is_booking_request (independent of message_type) ---\n"
    "true when the traveler is explicitly asking to book, reserve, or "
    "purchase something concrete right now - a flight, a hotel, a "
    "package, tickets (e.g. 'reserve um voo pra mim', 'book me a "
    "hotel', 'quero comprar essas passagens'). False for a question "
    "that's merely informational about flights/hotels/prices without "
    "asking to actually book anything (e.g. 'how much does a flight "
    "cost' or 'quais hotéis existem em Roma' is false - only an actual "
    "request to book/reserve/purchase is true).\n\n"
    "--- is_video_request (independent of message_type) ---\n"
    "true when the traveler wants to see a video of a place - either "
    "asking unprompted ('tem algum vídeo do Japão?', 'can I see a video "
    "of Portugal?') or agreeing to an offer YOU made earlier in the "
    "conversation to show one (e.g. your prior reply asked 'gostaria de "
    "ver um vídeo de Bali?' and the traveler just replied 'sim'/'quero'/"
    "'show me'). False for everything else.\n"
    "video_place_name: the place the traveler wants a video of. If they "
    "simply agreed to an offer you made ('sim', 'quero ver') without "
    "naming a place themselves, use the place YOU offered in your own "
    "prior reply (check the history above). If the place is a country, "
    "give its standard English name (e.g. 'Japão' -> 'Japan'), same "
    "reason as the country field above - the video data is looked up by "
    "its English country name. If it's a city/landmark rather than a "
    "whole country (e.g. 'Lisboa', 'Bali'), leave it as written - that "
    "gets resolved to its country separately. Null if is_video_request "
    "is false, or if it's true but no place can be identified either "
    "way.\n\n"
    "--- is_activity_question (independent of message_type) ---\n"
    "true when the traveler is asking what there is to see/do at a place "
    "already established in this conversation (yours or theirs) - things "
    "to do, sights, food, culture, day trips, safety, practicalities, "
    "'what's it like there', etc - NOT asking where they should go. "
    "Examples: 'o que tem de bom pra fazer lá?', 'what's there to see in "
    "Hoi An?', 'vale a pena visitar os templos?', 'é seguro andar à "
    "noite?'. This is about a place the traveler already has in mind - "
    "if they're instead asking for new destination suggestions (even "
    "with extra criteria like climate/budget/trip type), that's the "
    "normal recommendation flow, not this. False for everything else.\n"
    "activity_place_name: the place being asked about, as written in "
    "this message if named there, otherwise the most recently discussed "
    "specific place from the conversation above (your prior reply or "
    "the traveler's). Null if is_activity_question is false, or if it's "
    "true but no specific place can be identified either way."
)

INTENT_SCHEMA = {
    "name": "travel_message",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "message_type": {
                "type": "string",
                "enum": ["recommendation", "feedback", "future_intent", "off_topic"],
            },
            "month": {"type": ["integer", "null"]},
            "min_temp_c": {"type": ["number", "null"]},
            "max_temp_c": {"type": ["number", "null"]},
            "max_cost_of_living": {"type": ["integer", "null"]},
            "trip_type": {
                "type": ["string", "null"],
                "enum": [*TRIP_TYPE_CODES, None],
            },
            "continent": {
                "type": ["string", "null"],
                "enum": [*CONTINENT_CODES, None],
            },
            "country": {"type": ["string", "null"]},
            "excluded_place_names": {"type": "array", "items": {"type": "string"}},
            "feedback_destination_name": {"type": ["string", "null"]},
            "feedback_rating": {"type": ["integer", "null"]},
            "feedback_tags": {"type": "array", "items": {"type": "string"}},
            "feedback_comment": {"type": ["string", "null"]},
            "future_destination_name": {"type": ["string", "null"]},
            "is_recall_request": {"type": "boolean"},
            "is_visa_or_entry_question": {"type": "boolean"},
            "visa_question_country": {"type": ["string", "null"]},
            "visa_question_nationality": {"type": ["string", "null"]},
            "is_booking_request": {"type": "boolean"},
            "is_video_request": {"type": "boolean"},
            "video_place_name": {"type": ["string", "null"]},
            "is_activity_question": {"type": "boolean"},
            "activity_place_name": {"type": ["string", "null"]},
        },
        "required": [
            "message_type",
            "month",
            "min_temp_c",
            "max_temp_c",
            "max_cost_of_living",
            "trip_type",
            "continent",
            "country",
            "excluded_place_names",
            "feedback_destination_name",
            "feedback_rating",
            "feedback_tags",
            "feedback_comment",
            "future_destination_name",
            "is_recall_request",
            "is_visa_or_entry_question",
            "visa_question_country",
            "visa_question_nationality",
            "is_video_request",
            "video_place_name",
            "is_booking_request",
            "is_activity_question",
            "activity_place_name",
        ],
        "additionalProperties": False,
    },
}

# min_temp_c/max_temp_c/max_cost_of_living get extracted a second time
# here, from the current message alone, no history - overwrites whatever
# INTENT_SCHEMA's combined call produced for the same three fields (see
# the call site below). sanitize_reply_for_context() in ai/memory.py
# stops the model from repeating its own literal numbers back, but it
# could still infer warmth from a destination name alone once history was
# in play at all ("Phuket" implies warm, no digits needed) - prompt
# tweaks to fix that kept breaking other cases, so this call just gets no
# history to work with, full stop. Multi-turn combining still works
# through ai.memory.update_climate_budget()'s accumulator instead.
CLIMATE_BUDGET_SCHEMA = {
    "name": "climate_budget_signal",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "min_temp_c": {"type": ["number", "null"]},
            "max_temp_c": {"type": ["number", "null"]},
            "max_cost_of_living": {"type": ["integer", "null"]},
        },
        "required": ["min_temp_c", "max_temp_c", "max_cost_of_living"],
        "additionalProperties": False,
    },
}

CLIMATE_BUDGET_SYSTEM_PROMPT = (
    "Extract a temperature preference and/or a budget preference from THIS "
    "ONE MESSAGE ALONE. You are deliberately given no conversation history "
    "and must judge only the words in front of you - if this message alone "
    "doesn't state a climate or budget preference, leave the corresponding "
    "field(s) null, even if you suspect earlier turns in the conversation "
    "might have mentioned one; a separate mechanism outside this call "
    "carries a real earlier preference forward, so you never need to (and "
    "should not try to) guess or recall one here.\n"
    "The traveler may write in any language - understand it and extract "
    "from it the same way regardless of language.\n"
    "- Temperature (min_temp_c): 'hot' -> 28, 'warm' -> 22, 'mild' -> 18. "
    "If the user wants somewhere cool or cold, or says nothing at all "
    "about temperature, leave min_temp_c null.\n"
    "- Upper temperature bound (max_temp_c): the mirror image of "
    "min_temp_c, for when the user wants an upper limit instead of (or as "
    "well as) a lower one - 'not too hot'/'nothing extreme' -> 30, "
    "'cool'/'mild, not hot' -> 22, 'cold'/'chilly'/'somewhere cool and "
    "crisp' -> 15. Only set this from words that are themselves about an "
    "upper temperature limit or wanting it cool/cold. A message can set "
    "both min_temp_c and max_temp_c together (e.g. 'mild, not too hot and "
    "not too cold') or just one.\n"
    "- Budget (max_cost_of_living, a 1-5 scale where 1 is cheapest): "
    "'very cheap'/'budget'/'affordable' -> 2, 'cheap'/'not too expensive'/"
    "'inexpensive' -> 3, 'moderate'/'mid-range' -> 4. If the user wants "
    "luxury, or says nothing at all about budget, leave max_cost_of_living "
    "null. Words describing a travel style or atmosphere - 'refined'/"
    "'refinado', 'upscale', 'elegant', 'sophisticated', 'classy' - are NOT "
    "budget words: they describe the kind of place someone wants, not "
    "what they're willing to pay, and fall under the same 'wants luxury' "
    "case above - leave max_cost_of_living null for these too.\n"
    "Naming a destination, a trip type (beach/city/nature/culture), or a "
    "month never by itself implies a temperature or budget, no matter how "
    "strongly it's stereotypically associated with one - only set these "
    "fields from words that are themselves about temperature or money. If "
    "min_temp_c and max_temp_c would contradict each other (min above "
    "max), leave both null instead."
)


@dataclass(frozen=True)
class OrchestrationResult:
    reply: str
    recommendations: list[ScoredDestination]


@dataclass(frozen=True)
class StreamingOrchestrationResult:
    recommendations: list[ScoredDestination]
    reply_chunks: Iterator[str]
    # True only for the single-destination "choose this trip" detail
    # reply - lets ai/views.py show "Save this trip" instead of "Choose
    # this trip" for that one response without re-deriving it from context.
    is_destination_detail: bool = False
    # The deterministic filters behind `recommendations`, so ai/views.py
    # can enrich its analytics event without knowing anything about intent
    # extraction. None on every other branch (nothing to report).
    recommendation_constraints: dict | None = None


def stream_travel_recommendation(
    message: str,
    *,
    user=None,
    session_key: str | None = None,
    ai_provider: AIProvider | None = None,
    climate_provider=None,
    history_override: list[dict] | None = None,
    focus_destination_slug: str | None = None,
) -> StreamingOrchestrationResult:
    """Handle one chat message: a recommendation request, feedback about a
    past visit, a stated future travel intention, or an off-topic message.

    Pipeline: intent extraction -> (per type) travel data + constraints ->
    scoring -> a streamed AI explanation, OR for feedback/future_intent, a
    direct save plus a templated reply (no second AI call needed).
    get_travel_recommendation() is just a non-streaming wrapper around
    this.

    Loads prior turns for this conversation (ai.memory) and feeds them to
    intent extraction, so a short reply like "sometime in fall" answering
    an earlier "what month?" gets understood in context instead of judged
    alone. `session_key` identifies an anonymous visitor; logged-in users
    go by account instead. Every branch appends its own turn before
    returning, failures included, so the next message still has context.
    This is short-term conversation context only, not the persistent
    profile/feedback/history data.

    Recommendation philosophy: people ask for things we have no
    deterministic model for ("romantic", "family-friendly"). Rather than
    trying to enumerate every such category, those dimensions get left for
    the AI to reason about with its own general knowledge - see the "do
    not force-fit" instruction below. We just log those cases so real
    usage can tell us what's actually worth formalizing later.

    `history_override`: when the caller is continuing an already-saved
    conversation, it passes that conversation's own stored messages here
    instead of pulling from ai.memory's Redis-backed short-term cache -
    the saved copy is the more complete source of truth, so this skips
    reading and writing Redis for that call entirely.

    `focus_destination_slug`: set only by the "Choose this trip" button,
    which already knows the destination, so this skips intent extraction
    and goes straight there instead of asking the AI to re-guess what
    "tell me more" refers to. A stale/bogus slug just falls through to
    normal message handling, as if it were never sent.
    """
    ai_provider = ai_provider or get_ai_provider()
    profile = _traveler_profile(user)
    if history_override is not None:
        conv_key = None
        history = history_override
    else:
        conv_key = memory.conversation_key(user=user, session_key=session_key)
        history = memory.get_history(conv_key)

    def _remember(reply: str) -> None:
        if conv_key is not None:
            memory.append_turn(conv_key, user_message=message, assistant_reply=reply)

    if focus_destination_slug:
        destination = Destination.objects.filter(slug=focus_destination_slug).first()
        if destination is not None:
            return _handle_focus_destination(
                message,
                destination,
                profile=profile,
                history=history,
                ai_provider=ai_provider,
                climate_provider=climate_provider,
                remember=_remember,
                conversation_key=conv_key,
            )
        # else: bogus/stale slug - fall through to normal intent-based
        # handling below.

    try:
        with track_llm_call(operation="extract_intent", conversation_key=conv_key):
            intent = _extract_intent(message, ai_provider=ai_provider, history=history)
    except AIProviderError:
        logger.warning("Could not extract intent - AI provider failure. message=%r", message)
        _remember(FALLBACK_REPLY)
        return StreamingOrchestrationResult([], iter([FALLBACK_REPLY]))

    # Checked before message_type branching - a request to recall what we
    # already said is orthogonal to message_type, and re-running
    # generate_recommendations() here would defeat the point: the
    # traveler's asking about the conversation, not asking for anything
    # new.
    if intent["is_recall_request"]:
        recall_messages = _build_recall_messages(message, history)
        recall_reply = _stream_ai_reply(
            recall_messages,
            message,
            ai_provider=ai_provider,
            remember=_remember,
            conversation_key=conv_key,
        )
        return StreamingOrchestrationResult([], recall_reply)

    # Same idea, checked next - a visa/entry question is the point of the
    # message no matter what message_type came back as, and needs the
    # real CountryEntryRequirement data, not pure general knowledge.
    if intent["is_visa_or_entry_question"]:
        visa_messages = _build_visa_question_messages(message, intent, profile, history)
        # temperature=0 - default temperature let this contradict the
        # verified data we handed it in the prompt now and then (e.g.
        # claiming a visa's required for a nationality the data excludes).
        # This is transcription, not creative writing - no reason to let
        # it vary.
        visa_reply = _stream_ai_reply(
            visa_messages,
            message,
            ai_provider=ai_provider,
            remember=_remember,
            conversation_key=conv_key,
            temperature=0,
        )
        return StreamingOrchestrationResult([], visa_reply)

    # Forces the "we can't actually book anything" disclosure for an
    # explicit booking request - leaving it to whatever path the message
    # would otherwise land in meant it got mentioned inconsistently.
    if intent["is_booking_request"]:
        booking_messages = _build_booking_request_messages(message, history)
        booking_reply = _stream_ai_reply(
            booking_messages,
            message,
            ai_provider=ai_provider,
            remember=_remember,
            conversation_key=conv_key,
        )
        return StreamingOrchestrationResult([], booking_reply)

    # Same pattern again for video requests/offers - real data only, no
    # live search fallback when nothing's on file. A guessed video link
    # would be worse than just admitting we don't have one.
    if intent["is_video_request"]:
        video_messages = _build_video_reply_messages(message, intent, history)
        video_reply = _stream_ai_reply(
            video_messages,
            message,
            ai_provider=ai_provider,
            remember=_remember,
            conversation_key=conv_key,
        )
        return StreamingOrchestrationResult([], video_reply)

    # "What's good to do there?" about a place already in the
    # conversation kept getting forced into the destination-comparison
    # table instead of a real answer. This skips generate_recommendations()
    # entirely and lets the AI just answer from general knowledge - it's
    # not a "where should I go" question.
    if intent["is_activity_question"]:
        activity_messages = _build_activity_question_messages(message, intent, history)
        activity_reply = _stream_ai_reply(
            activity_messages,
            message,
            ai_provider=ai_provider,
            remember=_remember,
            conversation_key=conv_key,
        )
        return StreamingOrchestrationResult([], activity_reply)

    message_type = intent["message_type"]

    if message_type == "off_topic":
        # A real AI reply, not a canned one - SYSTEM_PROMPT already knows
        # how to handle this naturally, just hand it the message.
        off_topic_messages = _build_off_topic_messages(message, history)
        off_topic_reply = _stream_ai_reply(
            off_topic_messages,
            message,
            ai_provider=ai_provider,
            remember=_remember,
            conversation_key=conv_key,
        )
        return StreamingOrchestrationResult([], off_topic_reply)

    if message_type == "feedback":
        # Same pattern as future_intent below - _handle_feedback returns
        # None for a real destination our catalog doesn't have, and gets
        # the same real-reply treatment instead of a dead-end note.
        quick_feedback_reply = _handle_feedback(
            intent, user=user, message=message, history=history, ai_provider=ai_provider
        )
        if quick_feedback_reply is not None:
            _remember(quick_feedback_reply)
            return StreamingOrchestrationResult([], iter([quick_feedback_reply]))

        unrecognized_feedback_messages = _build_unrecognized_feedback_destination_messages(
            message, intent["feedback_destination_name"], history
        )
        unrecognized_feedback_reply = _stream_ai_reply(
            unrecognized_feedback_messages,
            message,
            ai_provider=ai_provider,
            remember=_remember,
            conversation_key=conv_key,
        )
        return StreamingOrchestrationResult([], unrecognized_feedback_reply)

    if message_type == "future_intent":
        # _handle_future_intent returns None when the destination is real
        # but not in our catalog - no row to attach a Trip to. That case
        # gets a real AI reply from general knowledge instead of a flat
        # "I don't have it, but noted" - same treatment as an unmatched
        # recommendation request gets.
        quick_reply = _handle_future_intent(
            intent, user=user, message=message, history=history, ai_provider=ai_provider
        )
        if quick_reply is not None:
            _remember(quick_reply)
            return StreamingOrchestrationResult([], iter([quick_reply]))

        unrecognized_messages = _build_unrecognized_future_destination_messages(
            message, intent["future_destination_name"], history
        )
        unrecognized_reply = _stream_ai_reply(
            unrecognized_messages,
            message,
            ai_provider=ai_provider,
            remember=_remember,
            conversation_key=conv_key,
        )
        return StreamingOrchestrationResult([], unrecognized_reply)

    # message_type == "recommendation", also the safe fallback. No
    # clarification gate here on purpose - people rarely state every
    # dimension in one message and shouldn't be blocked from an answer for
    # it; month gets defaulted below, and every other field treats
    # "unspecified" as "not relevant," not "missing."
    #
    # min_temp_c/max_cost_of_living are strong enough signals alone to
    # search immediately - nobody states a temperature or budget without
    # meaning it. trip_type alone counts too now that the catalog's big
    # enough (384 destinations) for it to actually differentiate results,
    # rather than dumping most of the catalog back. A bare month or an
    # exclusion alone still isn't enough by itself - neither one narrows
    # things down the way a trip_type does, so those still route through
    # the same "ask a real follow-up, or suggest if invited to guess" path
    # as a blank opener.
    #
    # min_temp_c/max_temp_c/max_cost_of_living get re-derived here from
    # this message alone (see CLIMATE_BUDGET_SYSTEM_PROMPT), overwriting
    # whatever the combined extraction above produced, then merged with
    # whatever the conversation already had - so a real multi-turn
    # preference still combines even though this call never sees history.
    climate_budget = _extract_climate_budget_signal(
        message, ai_provider=ai_provider, conversation_key=conv_key
    )
    if conv_key is not None:
        climate_budget = memory.update_climate_budget(conv_key, **climate_budget)
    intent["min_temp_c"] = climate_budget["min_temp_c"]
    intent["max_temp_c"] = climate_budget["max_temp_c"]
    intent["max_cost_of_living"] = climate_budget["max_cost_of_living"]

    has_enough_signal = (
        intent["min_temp_c"] is not None
        or intent["max_temp_c"] is not None
        or intent["max_cost_of_living"] is not None
        or intent["trip_type"] is not None
        or intent["continent"] is not None
        or intent["country"] is not None
    )
    if not has_enough_signal:
        logger.info(
            "Not enough signal yet to differentiate destinations - letting the AI keep "
            "gathering information instead of running an unfiltered search. message=%r "
            "month=%s trip_type=%s",
            message,
            intent["month"],
            intent["trip_type"],
        )
        open_ended_messages = _build_open_ended_messages(message, intent, history, profile)
        open_ended_reply = _stream_ai_reply(
            open_ended_messages,
            message,
            ai_provider=ai_provider,
            remember=_remember,
            conversation_key=conv_key,
        )
        return StreamingOrchestrationResult([], open_ended_reply)

    # Confirm profile-derived context before suggesting anything - a
    # saved TravelerProfile could be stale for this particular trip (solo
    # last time, a group now; an old budget), so we never use it to shape
    # a suggestion silently. Gated to once per conversation via a small
    # Redis flag, separate from the turn history - asking every message
    # would bring back the friction this module has otherwise removed.
    # The next message goes straight to real suggestions no matter how
    # the traveler answered.
    confirmation_key = memory.conversation_key(user=user, session_key=session_key)
    if _has_confirmable_profile_data(profile) and not memory.is_profile_confirmed(confirmation_key):
        memory.mark_profile_confirmed(confirmation_key)
        confirmation_messages = _build_profile_confirmation_messages(message, profile, history)
        confirmation_reply = _stream_ai_reply(
            confirmation_messages,
            message,
            ai_provider=ai_provider,
            remember=_remember,
            conversation_key=conv_key,
        )
        return StreamingOrchestrationResult([], confirmation_reply)

    request = RecommendationRequest(
        month=intent["month"],
        min_temp_c=intent["min_temp_c"],
        max_temp_c=intent["max_temp_c"],
        max_cost_of_living=intent["max_cost_of_living"],
        trip_type=intent["trip_type"],
        continent=intent["continent"],
        country=intent["country"],
        excluded_slugs=find_destination_slugs_by_name(intent["excluded_place_names"]),
        user=user,
    )
    results = generate_recommendations(request, climate_provider=climate_provider)

    if not results:
        logger.info(
            "No destinations matched constraints. message=%r month=%s min_temp_c=%s "
            "max_temp_c=%s max_cost_of_living=%s trip_type=%s continent=%s country=%s",
            message,
            intent["month"],
            intent["min_temp_c"],
            intent["max_temp_c"],
            intent["max_cost_of_living"],
            intent["trip_type"],
            intent["continent"],
            intent["country"],
        )
        # Rather than a dead end, let the AI actually try to help - reason
        # from general knowledge, same as it does for vibes the
        # deterministic model doesn't cover, treating whatever constraint
        # made everything unmatchable as relaxable rather than a wall.
        no_match_messages = _build_no_matches_messages(message, intent, history, profile)
        no_match_reply = _stream_ai_reply(
            no_match_messages,
            message,
            ai_provider=ai_provider,
            remember=_remember,
            conversation_key=conv_key,
        )
        return StreamingOrchestrationResult([], no_match_reply)

    # Capped once, here, before either the AI's prompt or the UI cards see
    # `results` - a broad trip_type-only match can return dozens of real
    # candidates. total_matches keeps the real, uncapped count so the
    # explanation can honestly say there's more available, rather than
    # presenting 10 as the whole story.
    total_matches = len(results)
    results = results[:MAX_RECOMMENDATIONS]

    messages = _build_explanation_messages(
        message,
        results,
        history,
        month_was_assumed=intent["month_was_assumed"],
        month=intent["month"],
        profile=profile,
        total_matches=total_matches,
    )
    return StreamingOrchestrationResult(
        results,
        _stream_ai_reply(
            messages,
            message,
            ai_provider=ai_provider,
            remember=_remember,
            conversation_key=conv_key,
        ),
        recommendation_constraints={
            "month": intent["month"],
            "trip_type": intent["trip_type"],
            "continent": intent["continent"],
            "country": intent["country"],
        },
    )


def _handle_focus_destination(
    message: str,
    destination: Destination,
    *,
    profile: TravelerProfile | None,
    history: list[dict] | None,
    ai_provider: AIProvider,
    climate_provider,
    remember,
    conversation_key: str | None = None,
) -> StreamingOrchestrationResult:
    """The "choose this trip" detail path: the traveler already picked one
    destination from a browse-stage card, so there's nothing left to
    search or rank - just a real, grounded conversation about this one
    place, using fields (best_season/short_description/points_of_interest)
    the generic explanation path never sends. "Save this trip" only shows
    up once this reply comes back (ai/views.py checks
    is_destination_detail) - deterministic, not an AI judgment call."""
    climate_provider = climate_provider or get_climate_provider()
    try:
        summary = climate_provider.get_monthly_climate(
            latitude=float(destination.latitude),
            longitude=float(destination.longitude),
            month=date.today().month,
        )
        avg_high_c, avg_low_c = summary.avg_high_c, summary.avg_low_c
    except ClimateProviderError:
        avg_high_c, avg_low_c = None, None

    scored = ScoredDestination(
        destination=destination,
        avg_high_c=avg_high_c,
        avg_low_c=avg_low_c,
        preference_fit=0,
        budget_fit=0,
        temperature_fit=0,
        repetition_penalty=0,
        score=0,
    )
    messages = _build_destination_detail_messages(
        message, destination, avg_high_c=avg_high_c, profile=profile, history=history
    )
    reply = _stream_ai_reply(
        messages,
        message,
        ai_provider=ai_provider,
        remember=remember,
        conversation_key=conversation_key,
    )
    return StreamingOrchestrationResult([scored], reply, is_destination_detail=True)


def _build_destination_detail_messages(
    message: str,
    destination: Destination,
    *,
    avg_high_c: float | None,
    profile: TravelerProfile | None,
    history: list[dict] | None,
) -> list[AIMessage]:
    poi = ", ".join(destination.points_of_interest) if destination.points_of_interest else ""
    climate_line = f"\n- Current typical avg high: {avg_high_c}C" if avg_high_c is not None else ""
    traveler_note = _traveler_context_note(profile)
    entry_requirements_note = _entry_requirements_note(profile, [destination])
    video_note = _video_availability_note([destination])

    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f"The traveler chose to hear more about {destination.name}, "
                f'{destination.country} (they clicked "Choose this trip" on it). '
                "Here is everything real we know about it - do not invent any "
                "other facts beyond what is listed here:\n"
                f"- Trip type: {destination.get_trip_type_display()}\n"
                f"- Cost of living: {destination.get_cost_of_living_display()}\n"
                f"- Best season: {destination.best_season}\n"
                f"- Worst season: {destination.worst_season}\n"
                f"- Description: {destination.short_description}\n"
                f"- Points of interest: {poi}"
                f"{climate_line}"
                f"{traveler_note}"
                f"{entry_requirements_note}"
                f"{video_note}\n\n"
                f'Their message alongside choosing it was: "{message}"\n\n'
                "Have a genuine, detailed conversation about this one place - "
                "bring the description and points of interest to life, answer "
                "naturally, and invite a real follow-up question, the way a "
                "thoughtful travel consultant would once a client has settled "
                "on somewhere to talk through in depth. If a real video is "
                "noted as being on file above, you may offer to show it - "
                "only when one was actually noted as available, never "
                "speculatively. Do not mention saving this as a trip or any "
                "button/UI element - the interface already offers that "
                "separately once you reply. Reply in the same language the "
                "traveler has been using in this conversation (check the "
                "history above, not just this message)."
            ),
        )
    )
    return messages


def _stream_ai_reply(
    messages: list[AIMessage],
    message: str,
    *,
    ai_provider: AIProvider,
    remember,
    temperature: float | None = None,
    conversation_key: str | None = None,
) -> Iterator[str]:
    """Stream one AI reply, saving the full text to memory once it's done
    (or fails partway) - shared by every branch above, they all need the
    same streaming/fallback/memory behavior.

    temperature stays None (provider default) for most callers - some
    variety is fine or even good in a normal explanation. Pass 0 only when
    the job is faithfully relaying already-verified facts, not writing
    creatively (see the visa-question caller).

    This is the only place in the codebase that calls
    AIProvider.stream_reply, so wrapping it here with track_llm_call
    covers every branch for free. A client disconnecting mid-stream raises
    GeneratorExit, which isn't an Exception subclass, so it skips
    track_llm_call's except clause and no event gets recorded for that
    turn - same as if this instrumentation didn't exist. The `finally`
    below still always runs regardless."""
    collected = []
    try:
        with track_llm_call(operation="stream_reply", conversation_key=conversation_key):
            for chunk in ai_provider.stream_reply(messages, temperature=temperature):
                collected.append(chunk)
                yield chunk
    except AIProviderError:
        # A partial reply may already be out there before a mid-stream
        # failure - falling back to the generic message beats losing the
        # request entirely.
        logger.warning("AI provider failed mid-stream. message=%r", message)
        collected.append(FALLBACK_REPLY)
        yield FALLBACK_REPLY
    finally:
        # Runs even if the caller never finishes consuming the stream (a
        # disconnected client, say) - the conversation still gets whatever
        # was produced instead of silently losing the turn.
        remember("".join(collected))


def get_travel_recommendation(
    message: str,
    *,
    user=None,
    session_key: str | None = None,
    ai_provider: AIProvider | None = None,
    climate_provider=None,
) -> OrchestrationResult:
    """Non-streaming convenience wrapper around stream_travel_recommendation() -
    joins all chunks into one string. Useful for tests and any caller that
    doesn't need incremental output.
    """
    streaming_result = stream_travel_recommendation(
        message,
        user=user,
        session_key=session_key,
        ai_provider=ai_provider,
        climate_provider=climate_provider,
    )
    reply = "".join(streaming_result.reply_chunks)
    return OrchestrationResult(reply, streaming_result.recommendations)


def _localize_reply(
    fact: str, *, message: str, history: list[dict] | None = None, ai_provider: AIProvider
) -> str:
    """Phrase a fixed, already-decided confirmation in the traveler's own
    language and tone, via one small non-streaming AI call.

    Feedback/future-intent acknowledgments (_handle_feedback,
    _handle_future_intent below) were deliberately templated, non-AI
    strings (2026-08-29 - "no need for a second AI call for these
    confirmations"), which meant they stayed hardcoded English even in an
    otherwise fully Portuguese conversation - a real inconsistency found
    live during the 2026-08-31 AI-intelligence testing pass. Raised with
    the user as a product decision (this reopens that 2026-08-29 choice,
    not a pure bug) rather than fixed unilaterally; the user chose to
    accept the extra AI call over the language inconsistency. This call
    only *phrases* a fact the application has already fully decided (what
    changed, whether it succeeded) - it is never asked to decide anything
    itself, unlike every other AI call in this module.
    """
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler just wrote: "{message}"\n\n'
                "Say exactly this, in your own natural words, in the same "
                "language the traveler has been using in this conversation "
                "(check the history above if this message alone is short "
                "or ambiguous, e.g. just a name) - preserve the exact "
                "meaning, not just the general idea (in particular, if the "
                "fact says something was ALREADY saved before now, not "
                "just added this moment, your phrasing must make that "
                "clear too - 2026-09-03 QA finding: a paraphrase that "
                "dropped this distinction read like a brand new addition "
                "instead of a reminder that it was already there) - "
                "this applies just as much to English as to any other "
                f"language: {fact}"
            ),
        )
    )
    try:
        return ai_provider.generate_reply(messages).content
    except AIProviderError:
        # Degrade to the correct-but-unlocalized English fact rather than
        # losing the confirmation entirely - the traveler still learns
        # what happened, just not in their own language this one time.
        logger.warning("Could not localize confirmation reply - using it as-is. fact=%r", fact)
        return fact


def _handle_feedback(
    intent: dict,
    *,
    user,
    message: str,
    history: list[dict] | None = None,
    ai_provider: AIProvider,
) -> str | None:
    """Persist feedback shared conversationally, and register that the
    trip actually happened - giving feedback implies a visit occurred, per
    the user's explicit request that the AI register travel that occurred.

    Returns None specifically when the traveler gave feedback about a
    real destination our curated catalog doesn't have - see
    _handle_future_intent's docstring for the identical pattern; the
    caller (stream_travel_recommendation) then builds a real AI reply
    from general knowledge instead of a canned acknowledgment."""
    destination_name = intent["feedback_destination_name"]
    if not destination_name:
        # Ask before gating on login: we don't yet know there's anything
        # real to save, so there's nothing to require an account for. Also
        # a safety net against an intent misclassification (e.g. a
        # timing-only message that isn't really feedback at all) leaving
        # an anonymous user stuck behind a login wall for no reason - the
        # chat should never dead-end just because of that.
        return _localize_reply(
            "I'd love to hear about your trip - which destination are you talking about?",
            message=message,
            history=history,
            ai_provider=ai_provider,
        )

    if user is None or not user.is_authenticated:
        return _localize_reply(
            NEEDS_LOGIN_REPLY, message=message, history=history, ai_provider=ai_provider
        )

    destination = _resolve_destination(destination_name)
    if destination is None:
        # Same reasoning as future_intent above - no Destination row means
        # no real TravelHistoryEntry to register against.
        logger.info(
            "Feedback mentioned an unrecognized destination - answering from general "
            "knowledge instead of a canned note. name=%r",
            destination_name,
        )
        return None

    # Register that this travel occurred, regardless of whether a rating was given.
    TravelHistoryEntry.objects.get_or_create(user=user, destination=destination)

    rating = intent["feedback_rating"]
    if rating is None:
        return _localize_reply(
            f"Got it - I've noted that you've visited {destination.name}. Feel free to tell me "
            "how you'd rate it (1-10) if you'd like!",
            message=message,
            history=history,
            ai_provider=ai_provider,
        )

    Feedback.objects.update_or_create(
        user=user,
        destination=destination,
        trip=None,
        defaults={
            "rating": rating,
            "tags": intent["feedback_tags"],
            "comment": intent["feedback_comment"] or "",
        },
    )
    record_event(
        "feedback_submitted",
        user=user,
        metadata={"destination_slug": destination.slug, "rating": rating, "source": "chat"},
    )
    return _localize_reply(
        f"Thanks! I've recorded your feedback on {destination.name}: {rating}/10.",
        message=message,
        history=history,
        ai_provider=ai_provider,
    )


def _handle_future_intent(
    intent: dict,
    *,
    user,
    message: str,
    history: list[dict] | None = None,
    ai_provider: AIProvider,
) -> str | None:
    """Returns None specifically when the traveler named a real, valid
    destination that just isn't in our curated catalog - the caller
    (stream_travel_recommendation) then builds a real AI reply from
    general knowledge instead of the quick templated acknowledgments
    every other case here returns directly."""
    destination_name = intent["future_destination_name"]
    if not destination_name:
        # Same reasoning as _handle_feedback: don't gate on login before
        # confirming there's an actual destination to save - keeps the
        # chat going instead of dead-ending on a misclassified message.
        return _localize_reply(
            "That sounds exciting - which destination did you have in mind?",
            message=message,
            history=history,
            ai_provider=ai_provider,
        )

    if user is None or not user.is_authenticated:
        return _localize_reply(
            NEEDS_LOGIN_REPLY, message=message, history=history, ai_provider=ai_provider
        )

    destination = _resolve_destination(destination_name)
    if destination is None:
        # No Destination row means no Trip can be persisted either - the
        # caller handles this with a real AI reply from general knowledge
        # instead of a flat "not in my catalog" note.
        logger.info(
            "Future travel intent mentioned an unrecognized destination - answering from "
            "general knowledge instead of a canned note. name=%r",
            destination_name,
        )
        return None

    _trip, created = Trip.objects.get_or_create(
        user=user,
        destination=destination,
        status="planned",
        defaults={"name": f"Someday: {destination.name}"},
    )
    if created:
        record_event(
            "trip_created",
            user=user,
            metadata={"destination_slug": destination.slug, "status": "planned", "source": "chat"},
        )
        return _localize_reply(
            f"Got it! I've added {destination.name} to your trips to plan for someday.",
            message=message,
            history=history,
            ai_provider=ai_provider,
        )
    return _localize_reply(
        f"You already have {destination.name} noted as a future trip - I'll keep it there!",
        message=message,
        history=history,
        ai_provider=ai_provider,
    )


def _resolve_destination(name: str):
    slugs = find_destination_slugs_by_name([name])
    return Destination.objects.filter(slug__in=slugs).first()


def _history_messages(history: list[dict] | None) -> list[AIMessage]:
    """Turn stored conversation-memory turns (ai.memory) into AIMessages.

    Shared by every AI call in this module, not just intent extraction -
    a reply-generation call given only the current message had no way to
    tell what language the conversation was in when that message was
    itself ambiguous (a bare "Bahia," say), and silently answered in
    English mid-Portuguese conversation. Every call the traveler
    experiences as part of one conversation should actually see it.
    """
    return [AIMessage(role=turn["role"], content=turn["content"]) for turn in history or []]


def _traveler_profile(user) -> TravelerProfile | None:
    """The signed-in traveler's profile, or None for anonymous/no-profile-
    yet - a cheap lookup shared by every prompt builder that wants
    home_country/travelers_count/budget. Never raises on a missing
    profile, same "not filled in yet" treatment as any other optional
    field."""
    if user is None or not user.is_authenticated:
        return None
    return TravelerProfile.objects.filter(user=user).first()


def _has_confirmable_profile_data(profile: TravelerProfile | None) -> bool:
    """Whether there's anything on the profile worth confirming before
    suggesting a destination - mirrors exactly what _traveler_context_note
    below would mention, so the confirmation gate never fires for a
    profile with nothing to confirm."""
    if profile is None:
        return False
    return bool(
        profile.home_country
        or profile.travelers_count
        or profile.preferred_trip_types
        or profile.preferred_cost_of_living
        or (profile.budget_amount and profile.budget_period and profile.budget_currency)
    )


def _traveler_context_note(profile: TravelerProfile | None, *, always_mention: bool = False) -> str:
    """A short free-text note the AI can factor into its reasoning when
    relevant - never a hard constraint, those stay message-only via
    RecommendationRequest. budget_amount always goes through
    users.currency.convert_to_usd first, never the raw currency-ambiguous
    number, and is always labeled a rough estimate rather than a precise
    figure - same "reason from what's actually known, don't invent
    precision" approach as every other dimension here.

    always_mention=True is for the one caller
    (_build_profile_confirmation_messages) whose whole job is to state
    these details every time, not just when relevant - the default
    phrasing's "don't force it in" caveat is right for every other caller
    but was undercutting that one, since a confirmation reply is supposed
    to actually confirm the profile, not skip it."""
    if profile is None:
        return ""
    bits = []
    if profile.preferred_trip_types:
        # The AI used to claim it had no access to the profile at all,
        # even though this field already fed recommendations.scoring's
        # preference_fit bonus - it just was never actually told. Labels
        # are capitalized for form display ("Beach") - lowercased here
        # for the same mid-sentence reason as period_phrase below.
        trip_type_labels = dict(TRIP_TYPE_CHOICES)
        preferred = [
            str(trip_type_labels.get(code, code)).lower() for code in profile.preferred_trip_types
        ]
        joined = (
            preferred[0]
            if len(preferred) == 1
            else f"{', '.join(preferred[:-1])} and {preferred[-1]}"
        )
        bits.append(f"generally prefers {joined} trips")
    if profile.preferred_cost_of_living:
        cost_label = dict(COST_OF_LIVING_CHOICES).get(profile.preferred_cost_of_living)
        if cost_label:
            bits.append(f"generally prefers a {str(cost_label).lower()} cost of living")
    if profile.home_country:
        bits.append(f"traveling from {profile.home_country}")
    if profile.travelers_count:
        bits.append(
            f"usually travels with {profile.travelers_count} people total (including themselves)"
        )
    if profile.budget_amount and profile.budget_period and profile.budget_currency:
        # Lowercase, mid-sentence phrasing instead of reusing
        # BUDGET_PERIOD_CHOICES's form label directly - "... per Per day"
        # read wrong inline, this local map avoids it.
        period_phrase = {"day": "day", "week": "week", "month": "month"}.get(
            profile.budget_period, profile.budget_period
        )
        usd_estimate = convert_to_usd(profile.budget_amount, profile.budget_currency)
        if usd_estimate is not None:
            bits.append(
                f"has a self-reported typical budget of about ${usd_estimate:.0f} USD per "
                f"{period_phrase} (converted from {profile.budget_amount} "
                f"{profile.budget_currency} using an approximate exchange rate - treat this as "
                "a rough estimate, not a precise constraint)"
            )
        else:
            # Shouldn't really happen - budget_currency always matches
            # users.currency's rate table - but degrade gracefully instead
            # of silently dropping the budget context.
            bits.append(
                f"has a self-reported typical budget around {profile.budget_amount} "
                f"{profile.budget_currency} per {period_phrase} (couldn't convert this "
                "currency to a common figure - treat as a rough personal reference point)"
            )
    if not bits:
        return ""
    if always_mention:
        return (
            "\n\nTraveler profile context to confirm (state all of this - confirming it is "
            "the entire point of this reply, do not omit any of it): " + "; ".join(bits) + "."
        )
    return (
        "\n\nTraveler profile context (use only when relevant to this reply, don't force it "
        "in every time): " + "; ".join(bits) + "."
    )


def _entry_requirements_note(
    profile: TravelerProfile | None, destinations: list[Destination]
) -> str:
    """Real, verified visa-requirement facts for the traveler's own
    nationality against each candidate's country, from
    travel.CountryEntryRequirement. A deterministic lookup, not AI
    knowledge - we only ever hand the model data our dataset actually
    has. Only meaningful for real ScoredDestination candidates; the
    no-matches/open-ended paths suggest from the AI's own knowledge
    instead, so there's no real Destination row to check here."""
    if profile is None or not profile.home_country:
        return ""
    lines = []
    seen_countries = set()
    for destination in destinations:
        country = destination.country
        if country in seen_countries:
            continue
        seen_countries.add(country)
        requirement = get_entry_requirements(country)
        if requirement is None:
            continue
        needs_visa = any(
            profile.home_country.strip().lower() == nationality.strip().lower()
            for nationality in requirement.visa_required_nationalities
        )
        visa_bit = (
            "a visa IS required"
            if needs_visa
            else "a visa is generally NOT required (see notes for exceptions/programs)"
        )
        lines.append(
            f"- {destination.name} ({country}): for a traveler from {profile.home_country}, "
            f"{visa_bit}. Notes: {requirement.visa_notes or 'none on file'}."
        )
    if not lines:
        return ""
    return (
        "\n\nEntry-requirement data on file for the traveler's own nationality (from our "
        "verified dataset, not general knowledge) - mention briefly ONLY if genuinely "
        "relevant to this reply, and if you do, always include this disclaimer: "
        f'"{ENTRY_REQUIREMENT_DISCLAIMER}"\n' + "\n".join(lines)
    )


def _extract_intent(
    message: str, *, ai_provider: AIProvider, history: list[dict] | None = None
) -> dict:
    messages = [AIMessage(role="system", content=INTENT_EXTRACTION_SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(AIMessage(role="user", content=message))
    # temperature=0 - this feeds straight into deterministic logic (which
    # branch runs, what gets queried), so it needs to be consistent, not
    # creative. Without it, the same message + history could extract a
    # different value from one call to the next - we actually saw an
    # already-established month silently vanish on a later turn.
    data = ai_provider.generate_structured_reply(messages, json_schema=INTENT_SCHEMA, temperature=0)
    return _validate_intent(data)


def _extract_climate_budget_signal(
    message: str, *, ai_provider: AIProvider, conversation_key: str | None = None
) -> dict:
    """Derive min_temp_c/max_temp_c/max_cost_of_living from this message
    alone - no conversation history at all. A history-aware version of
    this let the model reconstruct a climate/budget assumption from
    destination names the AI itself had mentioned earlier, even with the
    literal numbers stripped out. No history closes that off
    structurally, not just by instruction."""
    messages = [
        AIMessage(role="system", content=CLIMATE_BUDGET_SYSTEM_PROMPT),
        AIMessage(role="user", content=message),
    ]
    try:
        # Wrapped inside the try/except, not around the call site - this
        # function already catches AIProviderError and degrades to an
        # all-None signal, so instrumenting from outside would always
        # record success=True even when the provider actually failed.
        with track_llm_call(
            operation="extract_climate_budget_signal", conversation_key=conversation_key
        ):
            data = ai_provider.generate_structured_reply(
                messages, json_schema=CLIMATE_BUDGET_SCHEMA, temperature=0
            )
    except AIProviderError:
        logger.warning(
            "Could not extract an isolated climate/budget signal - AI provider failure. message=%r",
            message,
        )
        data = {"min_temp_c": None, "max_temp_c": None, "max_cost_of_living": None}
    return _validate_climate_budget(data)


def _validate_climate_budget(data: dict) -> dict:
    """The max_cost_of_living range check and min_temp_c/max_temp_c
    contradiction check - shared by _validate_intent (the combined call)
    and _extract_climate_budget_signal (the isolated call), so both apply
    the exact same rules rather than risking the two drifting apart."""
    max_cost_of_living = data.get("max_cost_of_living")
    if max_cost_of_living is not None and not (1 <= max_cost_of_living <= MAX_COST_OF_LIVING_TIER):
        max_cost_of_living = None

    min_temp_c = data.get("min_temp_c")
    max_temp_c = data.get("max_temp_c")
    if min_temp_c is not None and max_temp_c is not None and min_temp_c > max_temp_c:
        # A contradictory extraction (e.g. "warm but not too hot" landing
        # min > max) - drop both rather than pass a range hard_constraints
        # in scoring.py would filter every destination out on.
        min_temp_c = None
        max_temp_c = None

    return {
        "min_temp_c": min_temp_c,
        "max_temp_c": max_temp_c,
        "max_cost_of_living": max_cost_of_living,
    }


def _validate_intent(data: dict) -> dict:
    # Response Validation (09_AI_ORCHESTRATION.md §9): never trust the
    # model's structured output blindly, even with a schema.
    if data.get("message_type") not in {"recommendation", "feedback", "future_intent", "off_topic"}:
        data["message_type"] = "recommendation"

    month = data.get("month")
    month_is_valid = isinstance(month, int) and 1 <= month <= 12
    data["month"] = month if month_is_valid else None
    data["month_was_assumed"] = False

    if data.get("message_type") == "recommendation" and not month_is_valid:
        # Month is the only thing RecommendationRequest needs for real
        # climate data, but people rarely state every dimension in one
        # message - rather than blocking on it, default to the current
        # month and say so transparently, same as every other unspecified
        # field just meaning "not relevant" instead of "missing."
        data["month"] = date.today().month
        data["month_was_assumed"] = True

    data.update(_validate_climate_budget(data))

    if data.get("trip_type") not in {*TRIP_TYPE_CODES, None}:
        data["trip_type"] = None

    country = data.get("country")
    data["country"] = country if isinstance(country, str) and country.strip() else None

    data["excluded_place_names"] = _clean_string_list(data.get("excluded_place_names"))

    feedback_rating = data.get("feedback_rating")
    if feedback_rating is not None and not (1 <= feedback_rating <= 10):
        data["feedback_rating"] = None

    cleaned_tags = _clean_string_list(data.get("feedback_tags"))
    data["feedback_tags"] = [tag for tag in cleaned_tags if tag in FEEDBACK_TAG_KEYS]

    data["is_recall_request"] = bool(data.get("is_recall_request"))

    data["is_visa_or_entry_question"] = bool(data.get("is_visa_or_entry_question"))
    visa_country = data.get("visa_question_country")
    data["visa_question_country"] = (
        visa_country if isinstance(visa_country, str) and visa_country.strip() else None
    )
    visa_nationality = data.get("visa_question_nationality")
    data["visa_question_nationality"] = (
        visa_nationality if isinstance(visa_nationality, str) and visa_nationality.strip() else None
    )
    data["is_booking_request"] = bool(data.get("is_booking_request"))

    data["is_video_request"] = bool(data.get("is_video_request"))
    video_place_name = data.get("video_place_name")
    data["video_place_name"] = (
        video_place_name if isinstance(video_place_name, str) and video_place_name.strip() else None
    )

    data["is_activity_question"] = bool(data.get("is_activity_question"))
    activity_place_name = data.get("activity_place_name")
    data["activity_place_name"] = (
        activity_place_name
        if isinstance(activity_place_name, str) and activity_place_name.strip()
        else None
    )

    return data


def _clean_string_list(value) -> list:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _build_profile_confirmation_messages(
    message: str, profile: TravelerProfile, history: list[dict] | None = None
) -> list[AIMessage]:
    """Built once per conversation, the first time there's enough signal
    to suggest something and the traveler has relevant profile details on
    file. Asks them to confirm or correct that context before anything
    gets suggested, rather than trusting stored preferences that might not
    apply to this trip. Only ever built once - see the
    memory.is_profile_confirmed gate above - the next message goes
    straight to real suggestions no matter how they answered."""
    traveler_note = _traveler_context_note(profile, always_mention=True)
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler just said: "{message}" - this looks like enough to search for '
                "real destinations. Before suggesting anything, first briefly confirm the "
                "details already on file for this traveler still apply to this trip - ask "
                "naturally, in one short warm message, not a form or a checklist."
                f"{traveler_note}\n\n"
                "Mention only the details actually listed above - never invent or ask about "
                "one that isn't there. Do not suggest or list any destinations in this reply; "
                "that comes next, right after they confirm or correct these details. Reply in "
                "the same language the traveler has been using in this conversation (check the "
                "history above, not just this message) - this applies just as much to English "
                "as to any other language."
            ),
        )
    )
    return messages


def _video_availability_note(destinations: list[Destination]) -> str:
    """Which of these candidates' countries have a real video on file -
    lets the explanation offer one with actual confidence, instead of a
    blind guess that dead-ends into "sorry, no video" a turn later. The
    model rarely volunteered the offer at all when it had no idea whether
    one existed; naming a real candidate makes it both more likely to
    offer and honest when it does, same pattern as
    _entry_requirements_note above."""
    countries_with_videos = []
    seen_countries = set()
    for destination in destinations:
        country = destination.country
        if country in seen_countries:
            continue
        seen_countries.add(country)
        requirement = get_entry_requirements(country)
        if requirement is not None and requirement.videos:
            countries_with_videos.append(country)
    if not countries_with_videos:
        return ""
    countries_list = ", ".join(countries_with_videos)
    return (
        f"\n\nA real video is on file for: {countries_list} - a good, "
        "grounded candidate to offer showing (see the closing-question "
        "instruction below), since we can actually deliver on it."
    )


def _build_explanation_messages(
    message: str,
    results: list[ScoredDestination],
    history: list[dict] | None = None,
    *,
    month_was_assumed: bool = False,
    month: int | None = None,
    profile: TravelerProfile | None = None,
    total_matches: int | None = None,
) -> list[AIMessage]:
    top_results = results[:MAX_RECOMMENDATIONS]
    candidates_summary = "\n".join(
        f"- {r.destination.name}, {r.destination.country}: avg high {r.avg_high_c}C, "
        f"cost tier {r.destination.cost_of_living}/5, trip type {r.destination.trip_type}"
        for r in top_results
    )
    assumed_month_note = (
        f"\n\nThe traveler didn't say what month, so we assumed month {month} "
        "(the current one) to be able to look up real climate data - mention "
        "this briefly and let them know they can give a different month if "
        "they have one in mind."
        if month_was_assumed
        else ""
    )
    traveler_note = _traveler_context_note(profile)
    entry_requirements_note = _entry_requirements_note(
        profile, [r.destination for r in top_results]
    )
    video_note = _video_availability_note([r.destination for r in top_results])
    # When the real match count exceeds what we show, say so honestly
    # instead of presenting the capped list as if it were everything.
    more_matches_note = (
        f"\n\nThis request actually matched {total_matches} destinations in our data - "
        f"only the top {MAX_RECOMMENDATIONS} are listed above to keep this focused. "
        "Mention briefly that there are more options beyond these, and that narrowing "
        "the request further (dates, budget, a stronger preference) would help pick a "
        "better-tailored set rather than just a longer list."
        if total_matches is not None and total_matches > MAX_RECOMMENDATIONS
        else ""
    )

    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler asked: "{message}"\n\n'
                "Here are the top matching destinations, already filtered and "
                "ranked by the application. Do not invent any other destinations "
                "or facts beyond what is listed here:\n"
                f"{candidates_summary}"
                f"{assumed_month_note}"
                f"{traveler_note}"
                f"{entry_requirements_note}"
                f"{video_note}"
                f"{more_matches_note}\n\n"
                "This ranking is by climate/cost/trip-type fit only - it "
                "does not filter by region or country. If the traveler's "
                "message (check the conversation above too) names a "
                "specific region, country, or place, first check whether "
                "any of the candidates above are actually there (by their "
                "listed country) - present those. If none of them are, say "
                "so plainly rather than presenting the top candidates as if "
                "they satisfy that request (2026-09-03 QA finding: a reply "
                "presented destinations from unrelated countries as the "
                "answer to a region-specific request, without flagging the "
                "mismatch at all)."
                "\n\nPresent the best 1-3 options as a compact Markdown table "
                "(standard pipe syntax) comparing them side by side - pick "
                "columns that actually matter here (e.g. destination, "
                "climate, cost, a standout pro, a real downside or "
                "trade-off to weigh) rather than a fixed template every "
                "time. A short sentence or two of context before or after "
                "the table is fine, but the comparison itself belongs in "
                "the table, not paragraphs of prose. After the table, "
                "don't just stop at the options - close with ONE genuine "
                "next step: normally a follow-up question that would help "
                "narrow the search further (something not yet known: a "
                "preference, a priority between the options, anything "
                "relevant) the way a real consultant keeps refining even "
                "after giving a first real answer. If a real video is "
                "noted as being on file above for one of the destinations "
                "you're presenting, prefer offering to show it instead "
                "(e.g. 'gostaria de ver um vídeo de Bali?') - it's a good, "
                "concrete thing you can actually deliver on. Don't stack "
                "both in the same reply; pick whichever single one fits, "
                "and only offer a video when one was actually noted as "
                "available above - never offer one speculatively. Reply "
                "in the same language the traveler has been using in "
                "this conversation (check the history above, not just "
                "this message) - this applies just as much to English as "
                "to any other language."
            ),
        )
    )
    return messages


def _build_recall_messages(message: str, history: list[dict] | None = None) -> list[AIMessage]:
    """Built when intent extraction detects is_recall_request - the
    traveler is asking to hear what the assistant already said, not
    asking for anything new (2026-09-03 QA finding: "voltando, quais
    praias você tinha sugerido?" previously fell through to a normal
    fresh search, which - since generate_recommendations() re-ranks
    independently and the explanation call isn't deterministic about
    which 1-3 it features - came back sharing only 1 of the original 3
    destinations, not an actual recollection of what was said). No
    database search happens here at all; the only source of truth handed
    to the model is the conversation history itself."""
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler just said: "{message}" - they are asking you to '
                "recall or repeat something you already told them earlier in "
                "this conversation. Look at your own previous replies above and "
                "accurately restate what you actually said - the same "
                "destinations, facts, or options, not a fresh or different "
                "set. Do not run a new search or invent anything not already "
                "in the conversation above. If you genuinely can't tell what "
                "they're referring to from the history, say so honestly and "
                "ask them to clarify, rather than guessing. Reply in the same "
                "language the traveler has been using in this conversation."
            ),
        )
    )
    return messages


def _visa_verified_data_note(intent: dict, profile: TravelerProfile | None) -> str:
    """Real, verified visa/vaccine/insurance data for a visa/entry
    question - deterministic database lookups, not AI general knowledge,
    per 05_AI_DESIGN.md §7 (2026-09-03 QA finding: a bare informational
    visa question previously got zero access to travel.CountryEntryRequirement
    at all, answering entirely from the model's own general knowledge -
    demonstrably unreliable, since the exact same underlying fact about
    Japan got contradictory answers depending only on how the question
    was phrased). Falls back to an empty string (letting the caller's
    prompt reason from general knowledge instead, with a disclaimer) when
    the traveler's nationality genuinely isn't known from anywhere -
    there's no verified per-nationality answer to give without it."""
    nationality = intent.get("visa_question_nationality") or (
        profile.home_country if profile else None
    )
    if not nationality:
        return ""

    country = intent.get("visa_question_country")
    if country:
        requirement = get_entry_requirements(country)
        if requirement is None:
            return ""
        needs_visa = any(
            nationality.strip().lower() == n.strip().lower()
            for n in requirement.visa_required_nationalities
        )
        visa_bit = (
            "a visa IS required"
            if needs_visa
            else "a visa is generally NOT required (see notes for exceptions/programs)"
        )
        return (
            f"\n\nVerified data on file for {country} (from our own dataset, not "
            f"general knowledge) - use this instead of guessing: for a traveler "
            f"from {nationality}, {visa_bit}. Visa notes: "
            f"{requirement.visa_notes or 'none on file'}. Vaccine requirements: "
            f"{', '.join(requirement.vaccine_requirements) or 'none on file'}. "
            f"Insurance required: {'yes' if requirement.insurance_required else 'no'}"
            f"{' - ' + requirement.insurance_notes if requirement.insurance_notes else ''}. "
            f"Other requirements: "
            f"{', '.join(requirement.other_requirements) or 'none on file'}. Always "
            f'include this disclaimer if you use this data: "{ENTRY_REQUIREMENT_DISCLAIMER}"'
        )

    # No single country named - a general "which countries..." question.
    # Summarize every country we actually have verified data for, rather
    # than letting the model enumerate an unverified list from memory
    # (the exact failure mode found live: a general list confidently
    # named Japan as visa-free, contradicting the correct, specific
    # answer given one message later).
    lines = []
    for req in CountryEntryRequirement.objects.all():
        needs_visa = any(
            nationality.strip().lower() == n.strip().lower()
            for n in req.visa_required_nationalities
        )
        status = "visa required" if needs_visa else "visa generally not required"
        lines.append(f"- {req.country}: {status}")
    if not lines:
        return ""
    return (
        f"\n\nVerified data on file for a traveler from {nationality}, covering "
        f"{len(lines)} countries (from our own dataset - this list is NOT "
        "exhaustive, only what we actually have verified data for; many other "
        "countries simply aren't listed here) - use this instead of guessing for "
        "any country below:\n" + "\n".join(lines) + "\nIf the traveler asks about "
        "a country not in this list, general knowledge is fine but must be "
        "clearly flagged as unverified, separately from the list above. Always "
        f'include this disclaimer if you use the list above: "{ENTRY_REQUIREMENT_DISCLAIMER}"'
    )


def _build_visa_question_messages(
    message: str,
    intent: dict,
    profile: TravelerProfile | None,
    history: list[dict] | None = None,
) -> list[AIMessage]:
    """Built when intent extraction detects is_visa_or_entry_question -
    hands the model real, verified travel.CountryEntryRequirement data
    when the traveler's nationality is known (from the message itself or
    their saved profile), rather than leaving a legally-consequential
    question entirely to unverified general knowledge (2026-09-03 QA
    finding, see _visa_verified_data_note's docstring for the specific
    self-contradiction that motivated this)."""
    verified_note = _visa_verified_data_note(intent, profile)
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler asked: "{message}" - a question about visa, '
                "vaccine, insurance, or other entry requirements."
                f"{verified_note}\n\n"
                "Answer helpfully and directly. If no verified data was given "
                "to you above, answer from your own general knowledge but be "
                "honest that it isn't independently verified and could be "
                "outdated - recommend the traveler confirm with an official "
                "government or embassy source before booking or traveling, "
                "rather than stating anything as certain. Reply in the same "
                "language the traveler has been using in this conversation."
            ),
        )
    )
    return messages


def _build_booking_request_messages(
    message: str, history: list[dict] | None = None
) -> list[AIMessage]:
    """Built when intent extraction detects is_booking_request - a
    traveler explicitly asking to book/reserve/purchase a flight, hotel,
    or similar. 2026-09-03 QA finding: only 1 of 10 flight/hotel tests
    ever mentioned that booking isn't an actual feature - the other 9
    just launched into the normal recommendation flow with no
    disclosure at all. Forces the honest disclosure every time instead
    of leaving it to chance."""
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler just said: "{message}" - asking to book, reserve, '
                "or purchase something directly (a flight, hotel, package, or "
                "similar). You cannot actually make bookings or purchases - be "
                "upfront and clear about that near the start of your reply, in "
                "your own natural words (not a canned sentence), without over-"
                "apologizing. Then pivot to being genuinely helpful with what "
                "you CAN do instead - e.g. help them think through "
                "destinations, timing, or general travel planning. Reply in "
                "the same language the traveler has been using in this "
                "conversation."
            ),
        )
    )
    return messages


def _build_video_reply_messages(
    message: str, intent: dict, history: list[dict] | None = None
) -> list[AIMessage]:
    """Built when intent extraction detects is_video_request - hands the
    model real, verified CountryEntryRequirement.videos data (2026-09-07)
    when any exists for the resolved country, never left to invent a link.
    Deliberately no live search fallback when nothing is on file (direct
    user decision) - same 'be honest about the gap' framing already used
    by _build_visa_question_messages for missing entry-requirement data."""
    place_name = intent["video_place_name"]
    country = resolve_country_name(place_name) if place_name else None
    requirement = get_entry_requirements(country) if country else None
    videos = requirement.videos if requirement is not None else []

    if videos:
        videos_summary = "\n".join(f"- {url} (language: {lang})" for url, lang in videos)
        data_note = (
            f"\n\nReal videos on file for {country}, each with the language "
            f"it's actually in:\n{videos_summary}\n\n"
            "Share the most relevant one (or a couple, if more than one "
            "fits). Never invent a URL beyond what's listed above. If the "
            "video's own language doesn't match the language the traveler "
            "has been using in this conversation, say so honestly (e.g. "
            "'this one's in English') rather than implying it matches - "
            "still share it, just don't misrepresent its language."
        )
    else:
        where = f" for {country}" if country else ""
        data_note = (
            f"\n\nNo video is on file{where} yet - say so honestly and "
            "plainly. Do not invent, guess, or describe a video/URL that "
            "wasn't given to you above."
        )

    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler asked: "{message}" - wanting to see a video of a '
                f"place (check the conversation above if the place isn't named "
                f"here directly).{data_note}\n\n"
                "Reply in the same language the traveler has been using in "
                "this conversation (check the history above, not just this "
                "message)."
            ),
        )
    )
    return messages


def _build_activity_question_messages(
    message: str, intent: dict, history: list[dict] | None = None
) -> list[AIMessage]:
    """Built when intent extraction detects is_activity_question - the
    traveler is asking what there is to see/do/know about a place already
    established in the conversation, not asking for new destination
    suggestions. Deliberately skips generate_recommendations() and the
    comparison-table format entirely: per the already-approved
    recommendation philosophy (2026-08-29), anything the deterministic
    scoring model doesn't cover is answered from the model's own general
    knowledge, and "what's good to do there" is exactly that kind of
    question, not a request to pick between destinations."""
    place_name = intent["activity_place_name"]
    place_note = (
        f' about "{place_name}"' if place_name else " (check the history above for which place)"
    )
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler just said: "{message}" - a follow-up question'
                f"{place_note}, asking about things to do/see, culture, food, "
                "safety, or practicalities there, NOT asking for new "
                "destination suggestions. Answer directly and conversationally "
                "from your own general travel knowledge - do not force this "
                "into a destination-comparison table or a list of alternative "
                "places, and do not redirect to 'where should you go' framing. "
                "A short, natural, genuinely useful answer is exactly right "
                "here, the way a real travel-savvy friend would answer. Reply "
                "in the same language the traveler has been using in this "
                "conversation."
            ),
        )
    )
    return messages


def _build_off_topic_messages(message: str, history: list[dict] | None = None) -> list[AIMessage]:
    """Built when the message isn't about travel at all. SYSTEM_PROMPT
    already tells the model how to handle this naturally - briefly and
    honestly engage with a reasonable question about the assistant itself,
    or warmly redirect (in its own words, never a fixed sentence) when the
    message is genuinely unrelated to both travel and the assistant. This
    just hands it the real message rather than returning a canned reply -
    2026-08-30, direct user feedback: always returning the identical
    sentence, even for something as mundane as "are you an AI?", was the
    clearest sign this "doesn't feel like an AI, just an if/else".

    The short reminder appended after the message (2026-09-03 QA finding)
    is new: a genuinely travel-related but informational question routes
    here too (e.g. "quais companhias aéreas voam para Bali?"), and without
    it the model answered confidently with a specific, invented airline
    route table - SYSTEM_PROMPT already says never to invent specifics,
    but that rule stated once at a distance was measurably less reliable
    than reinforcing it right where the reply actually gets generated,
    the same pattern already used for the language-matching instruction
    elsewhere in this module."""
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f"{message}\n\n"
                "(Answer naturally, per your instructions. If a good answer "
                "would need a specific real-world fact you're not actually "
                "confident about - an exact current price, a specific company "
                "or airline name and route, live availability or a schedule - "
                "say so plainly and keep the answer general, rather than "
                "stating an invented specific as if it were verified.)"
            ),
        )
    )
    return messages


def _build_open_ended_messages(
    message: str,
    intent: dict,
    history: list[dict] | None = None,
    profile: TravelerProfile | None = None,
) -> list[AIMessage]:
    """Built when a recommendation-type message doesn't yet give enough to
    actually differentiate destinations by (see has_enough_signal in
    stream_travel_recommendation - a bare month or an exclusion alone
    still land here, not just a fully blank opener; trip_type alone no
    longer does as of 2026-09-02, now that it's real signal against a
    384-destination catalog).
    2026-08-30/31, direct user feedback: jumping straight to specific
    destination suggestions here felt presumptuous, and kept happening
    even with very little actually known - a real travel consultant
    naturally gathers more first instead of immediately listing
    destinations. 2026-08-31, further direct feedback ("ele precisa
    tentar pegar mais informações antes de tentar sugerir algo, quando o
    usuario pedir ajuda faz tipo um questionario bonitinho com emojis de
    praia, neve, viagem etc"): make that gathering step itself feel like a
    warm, quick little quiz with relevant emojis, not a plain sentence.
    This still shouldn't rigidly always ask, though - if the message
    already explicitly invites a guess (e.g. "surprise me", "you decide"),
    suggesting something is the more natural response. Both of these
    remain the AI's own judgment call, not a fixed rule encoded in Python.
    `intent` carries whatever weaker signal (month, trip_type, exclusions)
    was already extracted, so the model can acknowledge it and ask only
    about what's still missing instead of re-asking about it."""
    known_bits = []
    if intent["trip_type"]:
        known_bits.append(f"they want a {intent['trip_type']} trip")
    if intent["month"] and not intent["month_was_assumed"]:
        known_bits.append(f"they mentioned month {intent['month']}")
    if intent["excluded_place_names"]:
        known_bits.append(f"they want to avoid: {', '.join(intent['excluded_place_names'])}")
    known_note = (
        "\n\nYou already know this much from the conversation - don't ask "
        f"about it again, just build on it: {'; '.join(known_bits)}."
        if known_bits
        else ""
    )
    traveler_note = _traveler_context_note(profile)

    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler said: "{message}"\n\n'
                "You don't have enough yet to actually differentiate "
                "destinations - at minimum you're still missing climate/"
                f"temperature or budget preference.{known_note}{traveler_note}\n\n"
                "If this reads like an early point in the conversation "
                "(check the history - don't do this again if you already "
                "asked something like it recently), gather more with a "
                "short, warm, quiz-like message instead of a plain "
                "question: use relevant emojis for the main options you "
                "mention (e.g. beach, city, nature/adventure, culture, "
                "snow/mountain - adapt to what actually fits) and ask "
                "about trip type, rough timing/season, and budget "
                "together in one friendly message - do not re-ask about "
                "anything already known from the conversation. Do not "
                "list destinations yet in this case. If instead the "
                "message already explicitly invites you to just pick "
                "something or proceed - either a direct invitation (e.g. "
                "'surprise me', 'you decide', 'anywhere is fine') OR an "
                "affirmative reply to a gathering question YOU yourself "
                "just asked (e.g. 'sim', 'yes', 'pode buscar', 'go ahead', "
                "'tá bom, procura aí') when they aren't adding any new "
                "specifics of their own - treat both the same way: "
                "suggest 2-3 real destinations from your own general "
                "travel knowledge instead, confidently - making sure they "
                "actually satisfy anything specific the traveler stated "
                "(a named region, country, or place in particular), not "
                "just whatever's easiest to suggest. Every destination "
                "you name must be a real, actual place you're genuinely "
                "confident exists - never invent a plausible-sounding "
                "name to satisfy the request, especially if some part of "
                "it doesn't actually make physical sense (say so honestly "
                "in a sentence and suggest real places that get as close "
                "as a real destination can, rather than inventing one "
                "that supposedly matches exactly). Present them "
                "as a compact Markdown table (standard pipe syntax) "
                "comparing them side by side rather than paragraphs of "
                "prose, and mention in passing that these come from your "
                "own knowledge rather than verified data, without opening "
                "with an apology or a caveat about not having data. Either "
                "way, write your "
                "reply in the same language the traveler has been using "
                "in this conversation (check the history above for this "
                "- judge it from the whole conversation, not just their "
                "latest short message) - this applies just as much to "
                "English as to any other language; do not default away "
                "from it."
            ),
        )
    )
    return messages


def _build_no_matches_messages(
    message: str,
    intent: dict,
    history: list[dict] | None = None,
    profile: TravelerProfile | None = None,
) -> list[AIMessage]:
    """Built when hard constraints eliminated every curated destination.

    Per the Phase 11 recommendation philosophy and direct user feedback
    (2026-08-30 - never just ask for more when a real answer is possible),
    this tries to actually help rather than dead-ending: reason from
    general travel knowledge instead, and treat whichever constraint made
    everything unmatchable as the one to relax, exactly like a hard filter
    our own scoring never even had to apply here would have been treated
    as a soft preference.

    Revised 2026-09-08, direct user feedback on a real conversation ("neve,
    talvez no Egito" - snow, maybe in Egypt): the reply confidently listed
    3 specific unverified destinations (one, "Amina Moutiers, França",
    isn't even a real place) in a table with fake-precise numbers ("Frio
    (setembro)", specific cost tiers) as if it were real climate-provider
    data, for a request the traveler themselves had already hedged as
    uncertain ("talvez"). Direct instruction: "o chat não deve sugerir
    destinos se a informação for duvidosa, deve confirmar com o usuário
    sempre" - don't suggest destinations when the underlying data is
    dubious, always confirm with the user first. This only reverses the
    2026-08-30 "lead with confident help" framing for the specific
    sub-case where the request itself is contradictory or the traveler
    signaled their own uncertainty - a real, coherent request that our
    catalog simply doesn't happen to cover still gets a real (but now
    honestly-framed, non-tabular) answer, per the original 2026-08-30
    decision."""
    constraints = []
    if intent["month"]:
        constraints.append(f"month={intent['month']}")
    if intent["trip_type"]:
        constraints.append(f"trip_type={intent['trip_type']}")
    if intent["continent"]:
        constraints.append(f"continent={intent['continent']}")
    if intent["country"]:
        constraints.append(f"country={intent['country']}")
    if intent["min_temp_c"] is not None:
        constraints.append(f"min_temp_c={intent['min_temp_c']}")
    if intent["max_temp_c"] is not None:
        constraints.append(f"max_temp_c={intent['max_temp_c']}")
    if intent["max_cost_of_living"] is not None:
        constraints.append(
            f"max_cost_of_living={intent['max_cost_of_living']}/{MAX_COST_OF_LIVING_TIER}"
        )
    if intent["excluded_place_names"]:
        constraints.append(f"excluded={', '.join(intent['excluded_place_names'])}")
    constraints_summary = ", ".join(constraints) if constraints else "no specific constraints"
    traveler_note = _traveler_context_note(profile)

    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler asked: "{message}"\n\n'
                "Our own curated destination data has no match for this "
                f"({constraints_summary}) - taken together, these "
                "constraints are too narrow for what we have on file. Note "
                "that this list only covers what our own structured data "
                "tracks (month/trip-type/temperature/budget/exclusions) - "
                "if the traveler's actual message (check the conversation "
                "above too) also names something more specific we don't "
                "track as a field, like a particular region, country, or "
                "place, that still fully applies and must be honored in "
                "what you suggest (2026-09-03 QA finding: a reply "
                "correctly said we had no data for a named region, then "
                "suggested destinations from elsewhere entirely without "
                "flagging the mismatch - don't do that; either suggest "
                "real places that actually satisfy it, or say plainly you "
                "can't find a good match there instead of substituting "
                "somewhere else silently)."
                f"{traveler_note}\n\n"
                "First, decide whether the request itself is coherent, or "
                "whether it doesn't really add up (e.g. asking for snow "
                "in a country that never gets any, a beach in a "
                "landlocked place) or the traveler themselves signaled "
                "uncertainty about it ('talvez'/'maybe', 'não sei bem', "
                "'ou seja lá o que for').\n\n"
                "If the request doesn't add up or the traveler hedged it "
                "themselves: do NOT substitute your own guess for real "
                "destinations. Say plainly and specifically what doesn't "
                "add up (e.g. 'o Egito não tem neve'), and ask directly "
                "what they'd actually like instead (e.g. a cold "
                "destination elsewhere, or Egypt without the snow) - "
                "confirm with them before naming any place. This is "
                "always better than presenting invented-sounding "
                "specifics as if they were a real answer.\n\n"
                "If the request IS coherent and just isn't something our "
                "own catalog happens to cover (a real, sensible "
                "combination of month/budget/place that's simply outside "
                "what we track): still genuinely help, relaxing whichever "
                "constraint seems least essential to what they actually "
                "care about (never ask them to do this for you). Every "
                "destination you name must be a real, actual place you're "
                "genuinely confident exists - never invent a "
                "plausible-sounding name. Since you have no real "
                "climate-provider or cost data for these (that's exactly "
                "why they're not in our own results), describe them in "
                "plain prose using qualitative terms ('bastante frio', "
                "'custo alto') rather than specific numbers or a "
                "comparison table - a precise-looking figure you made up "
                "yourself would misrepresent a guess as measured data. "
                "State clearly, as part of the answer (not a caveat that "
                "opens the reply, and never starting with something like "
                "'unfortunately I don't have data for this'), that these "
                "come from your own general knowledge rather than our "
                "verified dataset, so the traveler knows to double-check "
                "current details. Ask one genuine follow-up question "
                "afterward that would help narrow the search further, the "
                "way a real consultant keeps refining even after giving a "
                "first real answer.\n\n"
                "Reply in the same language the traveler has been using "
                "in this conversation (check the history above, not just "
                "this message) - this applies just as much to English as "
                "to any other language."
            ),
        )
    )
    return messages


def _build_unrecognized_future_destination_messages(
    message: str, destination_name: str, history: list[dict] | None = None
) -> list[AIMessage]:
    """Built when a future_intent message names a real destination our
    curated catalog doesn't have (2026-09-02, direct user feedback: a
    canned "I don't have it, but I've noted it" reply was unhelpful and
    contradicted the Phase 11 recommendation philosophy - the AI should
    reason from its own general knowledge here too, the same way an
    unmatched recommendation request already does). No Trip is persisted
    for this - Trip.destination is a real FK, and there is no valid
    Destination row to attach it to (never invent catalog data,
    05_AI_DESIGN.md §7) - the reply says so honestly in passing, without
    dwelling on it as an apology."""
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler just said: "{message}" - naming {destination_name} as '
                "somewhere they'd like to go someday. This destination isn't in our "
                "curated dataset, so it can't be formally tracked as a saved future trip "
                "the way a catalog destination would be. Respond warmly and helpfully "
                "using your own general travel knowledge about it - share a genuine, "
                "useful detail or two (what it's known for, a good time to visit, "
                "something practical) the way a knowledgeable travel consultant would, "
                "rather than just acknowledging the message. Mention in passing, without "
                "opening with an apology, that you can't formally save it as a tracked "
                "trip yet since it's outside your verified catalog - but you're glad to "
                "help them think it through. Reply in the same language the traveler has "
                "been using in this conversation (check the history above, not just this "
                "message) - this applies just as much to English as to any other "
                "language."
            ),
        )
    )
    return messages


def _build_unrecognized_feedback_destination_messages(
    message: str, destination_name: str, history: list[dict] | None = None
) -> list[AIMessage]:
    """Built when a feedback message is about a real destination our
    curated catalog doesn't have (2026-09-02 review - the same "use AI
    general knowledge instead of a canned dead-end" fix already applied
    to future_intent, for the identical underlying situation). No
    TravelHistoryEntry/Feedback row is persisted for this -
    TravelHistoryEntry.destination is a real FK, and there is no valid
    Destination row to attach it to (never invent catalog data,
    05_AI_DESIGN.md §7) - the reply says so honestly in passing, without
    dwelling on it as an apology."""
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler just said: "{message}" - sharing their own experience of '
                f"{destination_name}, a place they've visited. This destination isn't in "
                "our curated dataset, so their visit can't be formally recorded in their "
                "travel history the way a catalog destination would be. Respond warmly - "
                "genuinely engage with what they shared (using your own general travel "
                "knowledge about the place to react to it naturally, the way a real "
                "travel consultant who knows the destination would), rather than just "
                "acknowledging the message. Mention in passing, without opening with an "
                "apology, that you can't formally log it in their travel history yet "
                "since it's outside your verified catalog - but thank them for sharing. "
                "Reply in the same language the traveler has been using in this "
                "conversation (check the history above, not just this message) - this "
                "applies just as much to English as to any other language."
            ),
        )
    )
    return messages
