import logging
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

from django.db.models import Q

from analytics.instrumentation import track_llm_call
from analytics.services import record_event
from integrations.climate import ClimateProviderError, get_climate_provider
from recommendations.scoring import (
    RecommendationRequest,
    ScoredDestination,
    generate_recommendations,
)
from travel.geography import CONTINENT_CHOICES
from travel.geography_aliases import canonicalize_country_name
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
    is_catalog_country_name,
    is_known_country,
    resolve_country_name,
)
from trips.models import FEEDBACK_TAG_CHOICES, Feedback, TravelHistoryEntry, Trip
from users.currency import convert_to_usd
from users.models import TravelerProfile

from . import memory, trip_details
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

# Shared verbatim between INTENT_EXTRACTION_SYSTEM_PROMPT (the combined,
# history-aware call) and CLIMATE_BUDGET_SYSTEM_PROMPT (the isolated,
# history-free call) - both need the model to make the exact same
# beach/city/nature/culture judgment call from a single message, and a
# shorter, independently-worded version of this in the isolated prompt
# measurably regressed the single-request evaluation corpus's "ambiguous"
# category (e.g. AMB-001, "quero algo relaxante... tipo um lugar
# tranquilo" started getting force-fit into 'nature') - this specific
# wording is what the corpus is tuned against, so it's the one source of
# truth for the judgment, not duplicated prose that can drift out of sync.
_TRIP_TYPE_GUIDANCE = (
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
)

# Calibrated against evaluations/selected_destination_calibration.py: the field
# is a judgment the model makes inside the combined call, and the examples must
# never reuse a place from that set (a test checks).
#
# This paragraph is appended at the END of INTENT_EXTRACTION_SYSTEM_PROMPT on
# purpose. Placed in the middle, next to the country/trip_type instructions,
# it made the model lose a trip-type correction half the time ("quero uma
# praia", then "não, quis dizer uma cidade mesmo" kept the beach: 8/8 -> 4/8
# on replay), and a longer or in-place wording never recovered it; the same
# short text at the end costs nothing there. Keep it short and keep it last.
SELECTED_DESTINATION_PROMPT = (
    "selected_destination_name: the one specific named place the traveler "
    "says they are going to or planning to go to, e.g. 'quero ir para "
    "Salzburg', 'vou para Lyon', 'estou pensando em ir para Hoi An', 'na "
    "verdade quero Lyon'. It is in addition to country and continent. "
    "Standard English name. Null for a country, a multi-country region or a "
    "continent, a place only mentioned, compared, asked about, visited, avoided or "
    "dreamed of for someday, a bare place name unless it picks an option you "
    "just presented, and whenever they are still asking where to go."
)

NEAR_TERM_PLAN_PROMPT = (
    "A plain statement that they ARE going, or are planning or thinking of "
    "going, to a named place soon or with no 'someday' marker ('vamos "
    "passar o feriado em Salzburg', 'estou pensando em ir para Hoi An', "
    "'we're going to Tallinn in June') is a present trip plan, not a "
    "someday goal - classify those as 'recommendation' too, extracting the "
    "place as described below. "
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
    "Portugal cet été' (this summer), 'I want to go to Japan in March', "
    "'voglio andare in Portogallo', 'voglio andare in Grecia' "
    "are all present-tense statements of wanting to go, not different in "
    "kind from 'quero viajar' above except that a place (and sometimes a "
    "timeframe) is filled in - classify these as 'recommendation' too, "
    "extracting the named place into country/continent below and any "
    "concrete month into month, exactly as if they had said 'I want to go "
    "to Thailand, any suggestions?'. This rule applies identically no "
    "matter which specific country fills the slot - 'voglio andare in "
    "Portogallo' and 'voglio andare in Brasile'/'in Egitto'/'in Marocco'/"
    "'in Italia' are the exact same construction with only the country "
    "swapped, so they get the exact same classification; do not let which "
    "particular country is named push this toward future_intent on its "
    "own, in Italian or any other language - the country name itself is "
    "never a signal about how eventual or immediate the trip is. Only use "
    "future_intent when the message itself frames the place as something "
    "to visit eventually/someday rather than a trip to help plan right "
    "now - explicit markers like 'algum dia', 'um dia', 'someday', 'one "
    "day', 'my dream is to...', 'I've always wanted to...', or a stated "
    "longer-term timeframe ('ano que vem', 'next year'). "
    + NEAR_TERM_PLAN_PROMPT
    + "Crucially: if your own "
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
    + _TRIP_TYPE_GUIDANCE
    + "continent: set this when the traveler names or clearly implies ONE "
    "continent/region as where they want to go - a continent name itself "
    "('Europe', 'Ásia'), a well-known colloquial term for a trip there "
    "('Eurotrip', 'Eurotour' -> 'europe'), or a specific country/city that "
    "unambiguously belongs to one continent ('Japan', 'quero ir a Roma' -> "
    "'asia'/'europe' respectively). Use exactly one of: 'europe', 'asia', "
    "'africa', 'north_america', 'south_america', 'oceania'. Leave it null "
    "if no continent/region/country was named or implied, or if what was "
    "named doesn't map to a single continent (e.g. 'somewhere warm', "
    "'anywhere with beaches').\n"
    "country: whenever the traveler names or clearly implies a place "
    "narrower than a whole continent - either ONE specific country (e.g. "
    "'quero ir pra Tailândia', 'somewhere in Japan') OR a multi-country "
    "region/colloquial term that is still narrower than a full continent "
    "('Scandinavia', 'the Balkans', 'Benelux', 'Southeast Asia', 'the "
    "Caribbean') - put exactly that name here, always given as the "
    "standard English name (e.g. 'Alemanha' -> 'Germany', 'Tailândia' -> "
    "'Thailand', 'Escandinávia' -> 'Scandinavia'), regardless of what "
    "language the traveler used, since this value is matched against a "
    "destination catalog that stores every country name in English - any "
    "other language's spelling would silently match nothing. Don't try "
    "to judge here whether the name is 'a single real country' our "
    "catalog actually has data for - that's resolved downstream against "
    "the real data, not by you; just capture whatever specific "
    "place/region term the traveler actually used. Always also set "
    "continent to match (e.g. 'Thailand' sets country='Thailand' AND "
    "continent='asia'; 'Scandinavia' sets country='Scandinavia' AND "
    "continent='europe'), since a request naming something narrower than "
    "a continent should never quietly return results from unrelated "
    "parts of that continent. Leave country null ONLY when nothing "
    "narrower than a whole continent was named at all (e.g. 'Europe', "
    "'Eurotrip', 'somewhere in Asia' with no further specifics) - "
    "continent alone still applies in that case.\n"
    "If the user asks to avoid or exclude specific places, countries, or "
    "regions, list the place/country names they mentioned in "
    "excluded_place_names (e.g. ['Marrakech', 'Morocco']). This also "
    "covers a place the traveler says they've ALREADY VISITED when "
    "they're now asking for somewhere DIFFERENT/NEW/ELSE this time - "
    "e.g. 'ja fui pra Roma e Praga antes, quero outro lugar' -> "
    "excluded_place_names=['Rome', 'Prague']; 'I've already been to "
    "Tokyo and Osaka, want a different city' -> "
    "excluded_place_names=['Tokyo', 'Osaka']. Do NOT treat a past visit "
    "as an exclusion when the traveler describes it positively and asks "
    "for something SIMILAR or in the same spirit instead - 'I've been "
    "to Rome and loved it, something similar would be great' must NOT "
    "exclude Rome or anything related to it, since they're asking to "
    "repeat that experience, not avoid it. Always give each name in its "
    "standard English form (e.g. 'Tailandia' -> 'Thailand'), the same "
    "way as the country field above - a name left in another language "
    "would silently fail to match our English-language catalog. Leave "
    "it as an empty list if they mentioned no exclusions.\n"
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
    "true but no specific place can be identified either way.\n\n"
    "--- is_accommodation_request (independent of message_type) ---\n"
    "true when the traveler wants accommodation/hotel/stay suggestions "
    "for ONE specific place already established in this conversation - "
    "named by them just now, or the place most recently discussed - NOT "
    "asking to book/reserve one (that's is_booking_request above), just "
    "wanting to know about places to stay there. Examples: 'quero "
    "hospedagens em Tóquio', 'me sugira hotéis em Lisboa', 'where should "
    "I stay in Rome?', 'any hotel recommendations for Bali?', or (after "
    "already discussing Tokyo) simply 'só quero hospedagens'/'just show "
    "me places to stay'. Also true when the traveler is simply replying "
    "with a number of people, continuing an accommodation conversation "
    "you already started - e.g. you asked how many people the stay is "
    "for and they replied '3' or 'somos 3 pessoas'. False when the "
    "traveler is instead asking for NEW destination suggestions, even "
    "ones filtered by budget, climate, or trip type - that's the normal "
    "recommendation flow, not this: e.g. 'accommodations for a warm "
    "beach trip' with no specific place named or previously established "
    "is false, since there's no single place yet to search stays for. "
    "Also false when only a whole country/region was named or "
    "established, with no single specific city/destination - a country "
    "has many possible places to stay, so this only fires for one "
    "specific destination.\n"
    "accommodation_place_name: the specific place being asked about, as "
    "written in this message if named there, otherwise the most "
    "recently discussed specific place from the conversation above "
    "(your prior reply or the traveler's). Always give its standard "
    "English name (e.g. 'Xangai' -> 'Shanghai', 'Toquio' -> 'Tokyo'), "
    "regardless of what language the traveler used - same reason as the "
    "country field above, this is matched against a destination catalog "
    "that stores every place name in English, and any other language's "
    "spelling would silently match nothing. Null if is_accommodation_"
    "request is false, or if it's true but no specific place can be "
    "identified either way.\n"
    "How many people the stay is for, and when, is not extracted here - "
    "a separate step reads that from the traveler's own words.\n\n" + SELECTED_DESTINATION_PROMPT
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
            "selected_destination_name": {
                "type": ["string", "null"],
                "description": (
                    "The one specific city, town or island the traveler says they are "
                    "going to or planning to go to. Null for a country or region, a "
                    "someday aspiration, a comparison or question about a place, or a "
                    "passing mention."
                ),
            },
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
            "is_accommodation_request": {"type": "boolean"},
            "accommodation_place_name": {"type": ["string", "null"]},
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
            "selected_destination_name",
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
            "is_accommodation_request",
            "accommodation_place_name",
        ],
        "additionalProperties": False,
    },
}

# This call extracts a second time, from the current message alone, no
# history - overwrites whatever INTENT_SCHEMA's combined call produced for
# the same fields (see the call site below). sanitize_reply_for_context()
# in ai/memory.py stops the model from repeating its own literal numbers
# back, but it could still infer warmth from a destination name alone once
# history was in play at all ("Phuket" implies warm, no digits needed) -
# prompt tweaks to fix that kept breaking other cases, so this call just
# gets no history to work with, full stop. Multi-turn combining works
# through ai.memory.update_climate_budget()'s accumulator instead - which
# is also where a value keeps mattering after the message that raised it
# scrolls out of the 12-message window.
#
# Started out covering only min_temp_c/max_temp_c/max_cost_of_living
# (hence the name); grew to also cover trip_type/continent/country/
# excluded_place_names once those turned out to need an identical
# accumulator (see update_climate_budget's docstring in ai/memory.py for
# why this is one mechanism, not two). Each of the four newer fields gets
# a companion "_cleared" flag (or, for the list-valued exclusions, add/
# remove/cleared) so the model can distinguish "this message didn't
# mention it" from "the traveler just explicitly dropped it" - the same
# distinction min_temp_c/max_temp_c/max_cost_of_living never had, which
# was itself a real gap (see the accumulator's own docstring).
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

# Byte-for-byte the original Cycle 1 prompt - restored deliberately
# (Cycle 2 Improvement 1 regression fix). An earlier version of this
# cycle's work first tried adding clear-detection fields to THIS same
# schema/prompt - even with the added text kept in its own section
# afterward rather than woven into the anchors, and even after trying a
# schema with no trip_type/continent/country fields at all, the mere
# presence of extra required fields (any of them) measurably shifted
# this call's temperature/budget calibration on some messages, confirmed
# by direct side-by-side testing (e.g. "quero relaxar numa praia no
# marrocos em maio" went from a clean null/null 10/10 times on this exact
# schema to a false min_temp_c=28 several times out of 5 with anything
# else added to the schema, regardless of prompt wording). So this call
# stays exactly as it always was; explicit-clear detection now lives in
# STATE_CLEAR_SCHEMA/_extract_state_clear_signal, a wholly separate call
# with its own schema and its own prompt, sharing nothing with this one.
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

# A genuinely separate call from CLIMATE_BUDGET_SCHEMA/
# CLIMATE_BUDGET_SYSTEM_PROMPT above - see that constant's own comment
# for why a shared schema/prompt couldn't be made safe no matter how the
# added text was worded or positioned. This call never sees the
# temperature/budget anchors at all, so it has nothing to contaminate
# them with; it only ever answers "did the traveler explicitly take back
# a preference this message," a plain yes/no judgment for each of the
# persistent fields (plus removing one name from the exclusion
# list), never a value judgment.
STATE_CLEAR_SCHEMA = {
    "name": "traveler_state_clear_signal",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "min_temp_c_cleared": {"type": "boolean"},
            "max_temp_c_cleared": {"type": "boolean"},
            "max_cost_of_living_cleared": {"type": "boolean"},
            "trip_type_cleared": {"type": "boolean"},
            "continent_cleared": {"type": "boolean"},
            "country_cleared": {"type": "boolean"},
            "excluded_place_names_remove": {"type": "array", "items": {"type": "string"}},
            "excluded_place_names_cleared": {"type": "boolean"},
            "selected_destination_cleared": {"type": "boolean"},
        },
        "required": [
            "min_temp_c_cleared",
            "max_temp_c_cleared",
            "max_cost_of_living_cleared",
            "trip_type_cleared",
            "continent_cleared",
            "country_cleared",
            "excluded_place_names_remove",
            "excluded_place_names_cleared",
            "selected_destination_cleared",
        ],
        "additionalProperties": False,
    },
}

STATE_CLEAR_SYSTEM_PROMPT = (
    "The traveler has an ongoing set of trip preferences (temperature, "
    "budget, trip type, continent/country, places to avoid). Read THIS "
    "ONE MESSAGE ALONE - no conversation history - and decide only "
    "whether the traveler is EXPLICITLY taking one of those preferences "
    "back. This is not about guessing what their preferences currently "
    "are, and not about extracting any new value - only about detecting "
    "an explicit retraction of an earlier one. If the message doesn't "
    "clearly do that for a given field, its flag is false (or, for "
    "excluded_place_names_remove, an empty list) - never true just "
    "because the message doesn't happen to repeat a preference.\n"
    "The traveler may write in any language - understand it and judge it "
    "the same way regardless of language.\n"
    "- min_temp_c_cleared / max_temp_c_cleared: true only for an explicit "
    "statement that temperature no longer matters or that an earlier "
    "limit is dropped ('never mind the temperature', 'a temperatura não "
    "importa mais', 'esquece o clima').\n"
    "- max_cost_of_living_cleared: true only for an explicit statement "
    "that price/budget no longer matters or that an earlier limit is "
    "dropped - including saying comfort/quality now matters more than "
    "price ('actually, price doesn't matter', 'esquece o orçamento', "
    "'comfort matters more than price now', 'conforto importa mais que "
    "preço agora').\n"
    "- trip_type_cleared: true only for an explicit statement that any "
    "kind of trip is fine now, or dropping a specific type ('any kind of "
    "trip works', 'esquece o tipo de viagem').\n"
    "- continent_cleared / country_cleared: true only for an explicit "
    "statement that any region/country is fine now, or dropping one "
    "('anywhere really', 'não importa o país agora').\n"
    "- excluded_place_names_remove: a place the traveler explicitly takes "
    "back OFF an earlier exclusion list ('actually Rome would be nice "
    "after all'). Give each name in its standard English form. Empty if "
    "this message doesn't do that.\n"
    "- excluded_place_names_cleared: true only for an explicit request to "
    "drop ALL exclusions at once ('forget what I said, show me "
    "everything', 'never mind, no exclusions').\n"
    "- selected_destination_cleared: the traveler may already have picked "
    "one specific place to go to. True only when this message reopens the "
    "choice of WHERE to go instead of continuing with that place - asking "
    "for other/different/more options or another city, saying they "
    "haven't decided or changed their mind without naming a new place "
    "('mostra outras opções', 'quero outra cidade', 'na verdade ainda não "
    "decidi', 'show me other places'), or starting a fresh search by "
    "region or type ('quero uma cidade na Espanha', 'I want a beach "
    "somewhere warm'). False for naming a different specific place to go "
    "to (that replaces the choice by itself) and for anything that just "
    "continues with the same place - follow-up questions, budget, "
    "practical or timing refinements ('conte-me mais', 'e hospedagem?', "
    "'quero algo mais barato')."
)

# Fallback for _resolve_destination() when the cheap DB substring lookup
# (find_destination_slugs_by_name) finds nothing - a traveler shouldn't
# need to spell a place correctly, or in English, just to reach it
# (2026-09-24, direct user request: "um usuario nao deve precisar saber
# escrever corretamente o lugar aonde ele quer ir"). Constrained to
# picking a real slug from the actual catalog (never inventing one) -
# the caller re-verifies the returned slug against the database before
# trusting it (09_AI_ORCHESTRATION.md §9's "never trust structured output
# blindly", same discipline as every other extraction in this module), so
# a hallucinated or malformed slug just falls back to "not found" rather
# than being treated as valid.
DESTINATION_RESOLUTION_SYSTEM_PROMPT = (
    "A traveler wrote a place name that didn't match anything in our real "
    "destination catalog by a simple substring lookup - it may be "
    "misspelled, a nickname, or written in a different language than the "
    "catalog uses. You'll be given the traveler's exact text and the full "
    "list of real destinations on file (slug: name, country). Decide "
    "whether the traveler's text is clearly a misspelling, alternate "
    "spelling, or translation of EXACTLY ONE destination in that list - "
    "not a guess about what they might like, only a real identification "
    "of the same place under a different spelling/language. If so, return "
    "that destination's exact slug from the list. If it could plausibly "
    "match more than one, or doesn't clearly match any of them, return "
    "null - never guess."
)

DESTINATION_RESOLUTION_SCHEMA = {
    "name": "destination_resolution",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"slug": {"type": ["string", "null"]}},
        "required": ["slug"],
        "additionalProperties": False,
    },
}

# Separate from DESTINATION_RESOLUTION_* above on purpose - that one
# matches against our closed catalog (only ever returns a real slug or
# null); this one answers a different question entirely ("does this place
# exist at all?") for the case _resolve_destination already gave up on.
# A live accommodation search doesn't need catalog data - only a name and
# country to hand Booking.com's own free-text search - so a place failing
# the catalog match shouldn't also block a real search link.
FREEFORM_PLACE_SYSTEM_PROMPT = (
    "A traveler asked about accommodation in a place that isn't in our "
    "curated destination catalog. Decide whether the place they named is "
    "a genuine, real-world city, town, or region a traveler could "
    "realistically book a stay in - not whether we have data on it, just "
    "whether it exists. If so, return its name and country using their "
    "standard English names (the way an English-language hotel search "
    "would recognize them), correcting obvious typos or translating from "
    "another language if needed. If you're not confident it's real, or "
    "it's fictional, made up, or too vague to identify (e.g. a generic "
    "word with no specific place attached), set is_real_place to false "
    "and leave name/country null - never invent a place that doesn't "
    "exist just to give an answer."
)

FREEFORM_PLACE_SCHEMA = {
    "name": "freeform_place_resolution",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "is_real_place": {"type": "boolean"},
            "name": {"type": ["string", "null"]},
            "country": {"type": ["string", "null"]},
        },
        "required": ["is_real_place", "name", "country"],
        "additionalProperties": False,
    },
}


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
    # True when that detail reply answers a stays request: the place is reused
    # for the accommodation feature, not chosen or replaced, so ai/views.py
    # must not record a destination_selected event for it.
    is_accommodation_reply: bool = False
    # The deterministic filters behind `recommendations`, so ai/views.py
    # can enrich its analytics event without knowing anything about intent
    # extraction. None on every other branch (nothing to report).
    recommendation_constraints: dict | None = None
    # What is known about the trip - dates, stay length, who is going - resolved
    # once for this turn. ai/views.py builds the "Search stays" link and the
    # caption under it from this one object, so the link carries exactly what
    # is known and nothing Booking.com would have to guess.
    trip: trip_details.ResolvedTrip | None = None
    # Set only when is_accommodation_request named a place _resolve_destination
    # couldn't match in the catalog, but _resolve_freeform_place confirmed is
    # real - e.g. Wuhan, which Wanderes has no scored Destination row for but
    # is still a real city Booking.com can search. ai/views.py builds a
    # minimal card from these two strings directly (no ScoredDestination, no
    # slug, no "Save this trip" - trips.Trip.destination is a hard FK to
    # travel.Destination and a freeform place was never written there).
    accommodation_freeform_name: str | None = None
    accommodation_freeform_country: str | None = None


def stream_travel_recommendation(
    message: str,
    *,
    user=None,
    session_key: str | None = None,
    ai_provider: AIProvider | None = None,
    climate_provider=None,
    history_override: list[dict] | None = None,
    focus_destination_slug: str | None = None,
    intent_sink: dict | None = None,
    state_sink: dict | None = None,
    thread_id: int | str | None = None,
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
    the saved copy is the more complete source of truth, so the history the
    AI sees always comes from here, never from Redis, on such a turn.

    `thread_id`: which conversation this turn belongs to, as far as the
    caller can vouch for it - a saved conversation's id (int), a pending
    token (ai.memory.new_pending_owner) for the first turn of a conversation
    that's about to be saved, or None for one that isn't tracked. It only
    matters for the accumulated traveler state, which lives under a
    per-user key that several conversations could otherwise believe is
    theirs. With a history_override, the state is read and written only when
    `thread_id` is a saved conversation that provably owns it (or that can
    atomically claim an empty slot - see ai.memory); otherwise the turn runs
    stateless, as it always did, and leaves whatever state is there alone.
    Without a history_override it stamps the state it writes as that
    thread's (None clears any earlier owner).

    `focus_destination_slug`: set only by the "Choose this trip" button,
    which already knows the destination, so this skips intent extraction
    and goes straight there instead of asking the AI to re-guess what
    "tell me more" refers to. A stale/bogus slug just falls through to
    normal message handling, as if it were never sent.

    `intent_sink`: when given a dict, gets updated with the final
    validated intent this call actually used (post climate/budget
    overwrite on the recommendation path) - lets evaluations.runner
    measure real extraction accuracy without a second, possibly
    non-deterministic, separate extraction call. None (the default)
    costs nothing extra and changes no behavior for any other caller;
    never populated on the focus_destination_slug path, which skips
    extraction entirely. It is extraction, not persisted state: on every
    branch that returns before the accumulator merge it's just what this
    one message yielded - see state_sink for what actually persists.

    `state_sink`: when given a dict, gets updated with the accumulated
    traveler state (the seven fields ai.memory.update_climate_budget
    merges) exactly as it's persisted once this turn's own writes are
    done, whichever branch handled the message. Where intent_sink shows
    what this one message yielded, this shows what the conversation will
    carry into the next turn - the thing a state-retention check actually
    cares about. Stays empty when the turn ran stateless (a
    history_override turn whose conversation doesn't own the state). One
    cache read, no model calls.
    """
    # Which key, if any, this turn's structured state lives under. A
    # history_override turn gets one only when its conversation provably
    # owns the state (or claims an empty slot); with no thread_id it never
    # does, which is exactly how such turns behaved before ownership existed.
    conv_key = memory.conversation_key(user=user, session_key=session_key)
    if history_override is None:
        state_key = conv_key
    elif isinstance(thread_id, int) and not isinstance(thread_id, bool):
        state_key = conv_key if memory.claim_state_for_conversation(conv_key, thread_id) else None
    else:
        state_key = None

    result = _route_turn(
        message,
        user=user,
        session_key=session_key,
        ai_provider=ai_provider,
        climate_provider=climate_provider,
        history_override=history_override,
        focus_destination_slug=focus_destination_slug,
        intent_sink=intent_sink,
        state_key=state_key,
        thread_id=thread_id,
    )
    # An override turn reports the state only while it still owns it: one that
    # lost the state to another thread during its model calls ran stateless,
    # and what's persisted now is that other thread's.
    if (
        state_sink is not None
        and state_key is not None
        and (history_override is None or memory.state_owned_by(state_key, thread_id))
    ):
        persisted = memory.get_climate_budget(state_key)
        # Copied so a caller can't reach back into the shared blank-state
        # default through the exclusions list.
        state_sink.update(persisted, excluded_place_names=list(persisted["excluded_place_names"]))
    return result


def _route_turn(
    message: str,
    *,
    user=None,
    session_key: str | None = None,
    ai_provider: AIProvider | None = None,
    climate_provider=None,
    history_override: list[dict] | None = None,
    focus_destination_slug: str | None = None,
    intent_sink: dict | None = None,
    state_key: str | None = None,
    thread_id: int | str | None = None,
) -> StreamingOrchestrationResult:
    """The routing and handling behind stream_travel_recommendation(), split
    out so that function can report the post-turn state once, after
    whichever of the many return paths below was taken. `state_key` is
    where this turn's structured state lives (None = this turn runs
    stateless); stream_travel_recommendation() has already decided that."""
    ai_provider = ai_provider or get_ai_provider()
    profile = _traveler_profile(user)
    conv_key = state_key
    if history_override is not None:
        history = history_override
    else:
        history = memory.get_history(conv_key)

    def _remember(reply: str) -> None:
        if conv_key is None:
            return
        if history_override is not None:
            # A saved conversation's text lives in its SavedConversation, not
            # in Redis - only the state's (and its owner's) lifetime needs
            # keeping in step with the conversation.
            memory.refresh_state_lifetime(conv_key)
        else:
            memory.append_turn(conv_key, user_message=message, assistant_reply=reply)

    def _state_write_key() -> str | None:
        # Where this turn may write structured state right now. A plain
        # (non-override) turn always may. An override turn was given the key
        # only because its conversation owned the state when the turn began;
        # the model calls since then take seconds, so ownership is checked
        # again just before writing - if another thread has taken the state
        # in the meantime, this turn stays stateless rather than write over it.
        #
        # This narrows the race, it doesn't close it: ownership can still
        # change between this check and the state operation that follows it,
        # because the cache has no multi-key compare-and-write. A turn caught
        # there would merge the other writer's state into its own - that is
        # not a fail-closed outcome. See "Who owns the accumulated state" in
        # ai/memory.py for why it's accepted rather than locked against.
        if conv_key is None:
            return None
        if history_override is None or memory.state_owned_by(conv_key, thread_id):
            return conv_key
        return None

    if focus_destination_slug:
        destination = Destination.objects.filter(slug=focus_destination_slug).first()
        if destination is not None:
            # The button is the most explicit choice there is, so it counts
            # as one for the follow-ups too.
            write_key = _state_write_key()
            if write_key is not None:
                memory.update_climate_budget(
                    write_key,
                    selected_destination={
                        "slug": destination.slug,
                        "name": destination.name,
                        "country": destination.country,
                    },
                    owner=thread_id,
                )
            return _handle_focus_destination(
                message,
                destination,
                profile=profile,
                history=history,
                ai_provider=ai_provider,
                climate_provider=climate_provider,
                remember=_remember,
                conversation_key=conv_key,
                trip_turn=_stored_trip_turn(write_key),
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
    _drop_unoffered_bare_selection(message, intent, history)
    if intent_sink is not None:
        intent_sink.update(intent)

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

    # What the traveler says about the trip itself - when, for how long, who
    # is going - is read by its own narrow call, and only when the message has
    # something to read or a stays search is waiting on exactly this. It is
    # resolved once here and then drives the link, the caption under it and
    # what the reply may say, so those three can't disagree.
    trip_turn = _read_trip_details(
        message,
        intent,
        history=history,
        ai_provider=ai_provider,
        state_write_key=_state_write_key,
        thread_id=thread_id,
        conversation_key=conv_key,
    )

    # A traveler who already named/settled on one specific destination and
    # now just wants accommodation suggestions for it (not new destination
    # options) needs to land on the same single-destination detail path
    # "Choose this trip" produces - that's the only reply that carries the
    # real "Search stays" link (ai/views.py only attaches
    # accommodation_search_url to a detail_shown card). Without this
    # branch, a typed follow-up like "só quero hospedagens" after naming
    # Tokyo fell through to generate_recommendations() with whatever
    # broader country/continent constraint got extracted, silently
    # re-litigating "which Japan destination" instead of answering the
    # actual question about the one already chosen (2026-09-23, direct
    # user report).
    if intent["is_accommodation_request"]:
        accommodation_place_name = intent["accommodation_place_name"]
        if accommodation_place_name:
            accommodation_destination = _resolve_destination(
                accommodation_place_name, ai_provider=ai_provider, conversation_key=conv_key
            )
            if accommodation_destination is not None:
                if trip_turn.trip.adults is None:
                    # Ask once, up front, before generating any "Search
                    # stays" link - Booking.com's own default (2 adults)
                    # when a search omits a count at all doesn't match
                    # whatever the traveler actually stated elsewhere in
                    # the conversation, so silently degrading to a
                    # destination-only link here would produce a link
                    # for the wrong number of people (2026-09-24, direct
                    # user report: asked for 3, got a link for 2).
                    party_size_messages = _build_accommodation_party_size_question_messages(
                        message,
                        f"{accommodation_destination.name}, {accommodation_destination.country}",
                        history,
                        trip_turn,
                    )
                    party_size_reply = _stream_ai_reply(
                        party_size_messages,
                        message,
                        ai_provider=ai_provider,
                        remember=_remember,
                        conversation_key=conv_key,
                    )
                    return StreamingOrchestrationResult([], party_size_reply)
                return _handle_focus_destination(
                    message,
                    accommodation_destination,
                    profile=profile,
                    history=history,
                    ai_provider=ai_provider,
                    climate_provider=climate_provider,
                    remember=_remember,
                    conversation_key=conv_key,
                    accommodation_focus=True,
                    trip_turn=trip_turn,
                )
            # Not in our curated catalog - but a live accommodation search
            # doesn't actually need catalog data (no scoring, no climate,
            # no description), only a name Booking.com's own free-text
            # search can resolve. Confirm it's a genuine place before
            # offering a search for it (2026-09-25, direct user report:
            # asked about Wuhan, a real city with no Destination row, and
            # got a canned "can't search" reply instead of a real link).
            freeform_place = _resolve_freeform_place(
                accommodation_place_name, ai_provider=ai_provider, conversation_key=conv_key
            )
            if freeform_place is not None:
                freeform_name, freeform_country = freeform_place
                if trip_turn.trip.adults is None:
                    freeform_label = (
                        f"{freeform_name}, {freeform_country}"
                        if freeform_country
                        else freeform_name
                    )
                    party_size_messages = _build_accommodation_party_size_question_messages(
                        message, freeform_label, history, trip_turn
                    )
                    party_size_reply = _stream_ai_reply(
                        party_size_messages,
                        message,
                        ai_provider=ai_provider,
                        remember=_remember,
                        conversation_key=conv_key,
                    )
                    return StreamingOrchestrationResult([], party_size_reply)
                freeform_messages = _build_freeform_accommodation_messages(
                    message,
                    freeform_name,
                    freeform_country,
                    trip_turn=trip_turn,
                    profile=profile,
                    history=history,
                )
                freeform_reply = _stream_ai_reply(
                    freeform_messages,
                    message,
                    ai_provider=ai_provider,
                    remember=_remember,
                    conversation_key=conv_key,
                )
                return StreamingOrchestrationResult(
                    [],
                    freeform_reply,
                    trip=trip_turn.trip,
                    accommodation_freeform_name=freeform_name,
                    accommodation_freeform_country=freeform_country,
                )
            unrecognized_accommodation_messages = (
                _build_unrecognized_accommodation_destination_messages(
                    message, accommodation_place_name, history
                )
            )
            unrecognized_accommodation_reply = _stream_ai_reply(
                unrecognized_accommodation_messages,
                message,
                ai_provider=ai_provider,
                remember=_remember,
                conversation_key=conv_key,
            )
            return StreamingOrchestrationResult([], unrecognized_accommodation_reply)
        # else: flagged as an accommodation request but no place could be
        # identified either way (shouldn't happen per the prompt's own
        # contract, but never trust it blindly) - fall through to normal
        # message_type handling below rather than dead-ending here.

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
        #
        # With a destination already chosen, the follow-ups the model files
        # here ("quanto custa?", "obrigado", "por que presumiu 4 pessoas?")
        # are still about that trip, so they get the same grounded,
        # message-first prompt as any other turn on it - the generic reply
        # was inventing price ranges for them.
        write_key = _state_write_key()
        stored_selection = (
            memory.get_climate_budget(write_key)["selected_destination"]
            if write_key is not None
            else None
        )
        if stored_selection is not None:
            slug = stored_selection.get("slug")
            stored_destination = Destination.objects.filter(slug=slug).first() if slug else None
            if not slug or stored_destination is not None:
                return _stream_carried_reply(
                    message,
                    stored_selection,
                    stored_destination,
                    history,
                    trip_turn,
                    ai_provider=ai_provider,
                    remember=_remember,
                    conversation_key=conv_key,
                )
        off_topic_reply = _stream_ai_reply(
            _build_off_topic_messages(message, history),
            message,
            ai_provider=ai_provider,
            remember=_remember,
            conversation_key=conv_key,
        )
        return StreamingOrchestrationResult([], off_topic_reply)

    if message_type == "feedback":
        # "Already been to Tokyo, don't want to go back" is feedback, not
        # a recommendation request, so this branch returns before ever
        # reaching the state-delta accumulator below - but intent's own
        # excluded_place_names (from the combined call, which already
        # knows not to exclude a place the traveler describes positively)
        # is sitting right here regardless of message_type. Persisting it
        # now is what lets that exclusion still apply several turns
        # later, once the conversation actually turns into a search - the
        # MEM-series conversation evaluation scenarios exist because this
        # used to just get dropped on the floor.
        write_key = _state_write_key()
        if write_key is not None and intent["excluded_place_names"]:
            memory.update_climate_budget(
                write_key,
                excluded_place_names_add=intent["excluded_place_names"],
                owner=thread_id,
            )

        # Same pattern as future_intent below - _handle_feedback returns
        # None for a real destination our catalog doesn't have, and gets
        # the same real-reply treatment instead of a dead-end note.
        quick_feedback_reply = _handle_feedback(
            intent,
            user=user,
            message=message,
            history=history,
            ai_provider=ai_provider,
            conversation_key=conv_key,
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
            intent,
            user=user,
            message=message,
            history=history,
            ai_provider=ai_provider,
            conversation_key=conv_key,
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
    # whatever the combined extraction above produced for the same three
    # fields - that isolated re-extraction is what the accumulator merges
    # on, unchanged from before this cycle.
    #
    # trip_type/continent/country/excluded_place_names take their VALUE
    # from the combined call above instead of a second isolated guess -
    # unlike temperature/budget, there's no evidence that field ever gets
    # contaminated by history (destination names in an earlier AI reply
    # don't silently imply a category the way they imply a temperature),
    # and the isolated call's classification of these turned out to be
    # measurably less reliable than the combined call's - it dropped a
    # literal "cidade" ("city") from "cidade fria e barata na europa" a
    # few times in a row at temperature=0, something the combined call has
    # never been seen to do. What's still needed for all seven fields is
    # what the accumulator was built for either way: distinguishing "this
    # message didn't mention it" from "the traveler explicitly dropped
    # it" - a much simpler yes/no judgment than picking the right value,
    # and the combined call has no vocabulary for it at all. That signal
    # comes from _extract_state_clear_signal, a call with its own schema
    # and prompt sharing nothing with _extract_climate_budget_signal - an
    # earlier attempt at putting both in one call, even with the two
    # concerns kept in clearly separate prompt sections, still measurably
    # leaked into this call's temperature/budget calibration on some
    # messages (see CLIMATE_BUDGET_SYSTEM_PROMPT's own comment).
    state_delta = _extract_climate_budget_signal(
        message, ai_provider=ai_provider, conversation_key=conv_key
    )
    state_delta.update(
        _extract_state_clear_signal(message, ai_provider=ai_provider, conversation_key=conv_key)
    )
    state_delta["trip_type"] = intent["trip_type"]
    state_delta["continent"] = intent["continent"]
    state_delta["country"] = intent["country"]
    state_delta["excluded_place_names_add"] = intent["excluded_place_names"]
    # A place the traveler named as their choice is resolved once, here, and
    # kept in the state as a record; a name that turns out to be neither a
    # catalog destination nor a real place is simply not a selection (the
    # turn then behaves as it did before this field existed).
    selected_record = _resolve_selected_destination(
        intent["selected_destination_name"],
        country_hint=intent["country"],
        ai_provider=ai_provider,
        conversation_key=conv_key,
    )
    selection_unresolved = (
        intent["selected_destination_name"] is not None and selected_record is None
    )
    state_delta["selected_destination"] = selected_record
    write_key = _state_write_key()
    # What was chosen before this message, to tell a choice made now from one
    # merely carried over (the model restates the place on many follow-ups).
    # With no state to read - a stateless turn - the choice can only have come
    # from this message, so it counts as made now.
    prior_selection = (
        memory.get_climate_budget(write_key)["selected_destination"]
        if write_key is not None
        else None
    )
    if write_key is not None:
        traveler_state = memory.update_climate_budget(write_key, owner=thread_id, **state_delta)
    else:
        traveler_state = memory.resolve_state_delta(**state_delta)
    selection_is_fresh = selected_record is not None and not _same_place(
        selected_record, prior_selection
    )
    intent["min_temp_c"] = traveler_state["min_temp_c"]
    intent["max_temp_c"] = traveler_state["max_temp_c"]
    intent["max_cost_of_living"] = traveler_state["max_cost_of_living"]
    intent["trip_type"] = traveler_state["trip_type"]
    intent["continent"] = traveler_state["continent"]
    intent["country"] = traveler_state["country"]
    intent["excluded_place_names"] = traveler_state["excluded_place_names"]
    intent["selected_destination"] = traveler_state["selected_destination"]
    intent["trip_details"] = traveler_state["trip_details"]
    if intent_sink is not None:
        intent_sink.update(intent)

    # Someone who has already chosen where they're going isn't searching:
    # this turn - and every later one, until they reopen the choice or pick
    # somewhere else - is a conversation about that place, not another
    # country-level ranking.
    if traveler_state["selected_destination"] is not None and not selection_unresolved:
        selected_result = _handle_selected_destination(
            message,
            traveler_state["selected_destination"],
            profile=profile,
            history=history,
            ai_provider=ai_provider,
            climate_provider=climate_provider,
            remember=_remember,
            conversation_key=conv_key,
            fresh=selection_is_fresh,
            trip_turn=trip_turn,
        )
        if selected_result is not None:
            return selected_result

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

    if intent["unmatched_region_name"]:
        # The extracted country doesn't match anything real in the
        # catalog - almost always a multi-country region name
        # ("Scandinavia") that isn't stored as a single country. Falling
        # back to continent alone here would be too broad (climate/budget
        # scoring across an entire continent, diluting out whatever the
        # traveler actually asked about) and the AI would have no signal
        # left to even notice the mismatch. Route it the same way as a
        # genuine zero-match search instead - _build_no_matches_messages
        # already knows to lean on general knowledge for a named region
        # rather than silently substituting unrelated destinations. Logged
        # here not to solve this particular term, but so real usage shows
        # which regions come up often enough to be worth real data later.
        logger.info(
            "Extracted country did not match any real catalog country - treating as an "
            "unmatched region/place name and falling back to a general-knowledge reply. "
            "message=%r unmatched_region_name=%r continent=%s",
            message,
            intent["unmatched_region_name"],
            intent["continent"],
        )
        no_match_messages = _build_no_matches_messages(message, intent, history, profile)
        no_match_reply = _stream_ai_reply(
            no_match_messages,
            message,
            ai_provider=ai_provider,
            remember=_remember,
            conversation_key=conv_key,
        )
        return StreamingOrchestrationResult([], no_match_reply)

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
    accommodation_focus: bool = False,
    chosen_destination: bool = False,
    trip_turn: trip_details.TripTurn | None = None,
) -> StreamingOrchestrationResult:
    """The "choose this trip" detail path: the traveler already picked one
    destination from a browse-stage card, so there's nothing left to
    search or rank - just a real, grounded conversation about this one
    place, using fields (best_season/short_description/points_of_interest)
    the generic explanation path never sends. "Save this trip" only shows
    up once this reply comes back (ai/views.py checks
    is_destination_detail) - deterministic, not an AI judgment call.

    `accommodation_focus` is set by the is_accommodation_request branch
    (a typed "hospedagens em Tóquio", not a button click) reusing this
    same path for its one real payoff: the "Search stays" link only ever
    attaches to a detail_shown card. Threaded through so the prompt can
    say what actually happened instead of falsely claiming a button
    click, and nudge the reply toward what's useful for choosing where
    to stay. The stays branch only reaches this function once the number
    of adults is known (it asks first when it isn't).

    `trip_turn` is the trip state for this turn (dates, stay length, who is
    going). The reply is told exactly those facts, and the same resolved trip
    rides on the result so ai/views.py builds the link and its caption from
    the very same object.

    `chosen_destination` is set when the traveler typed their choice ("quero
    ir pra Barcelona", or a follow-up on a destination chosen earlier)
    rather than clicking the button - same reply path, but the prompt says
    what happened and treats the destination as already decided."""
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
        message,
        destination,
        avg_high_c=avg_high_c,
        profile=profile,
        history=history,
        accommodation_focus=accommodation_focus,
        chosen_destination=chosen_destination,
        trip_turn=trip_turn,
    )
    reply = _stream_ai_reply(
        messages,
        message,
        ai_provider=ai_provider,
        remember=remember,
        conversation_key=conversation_key,
    )
    return StreamingOrchestrationResult(
        [scored],
        reply,
        is_destination_detail=True,
        is_accommodation_reply=accommodation_focus,
        trip=trip_turn.trip if trip_turn is not None else None,
    )


def _handle_selected_destination(
    message: str,
    selected: dict,
    *,
    profile: TravelerProfile | None,
    history: list[dict] | None,
    ai_provider: AIProvider,
    climate_provider,
    remember,
    conversation_key: str | None = None,
    fresh: bool = True,
    trip_turn: trip_details.TripTurn | None = None,
) -> StreamingOrchestrationResult | None:
    """Answer a message for a traveler who has already chosen where they're
    going (the `selected_destination` record in the accumulated state), so
    nothing is searched or ranked.

    `fresh` says the choice was made by THIS message. Then a catalog
    destination gets the same single-destination reply "Choose this trip"
    produces, and a real place outside the catalog gets a general-knowledge
    reply with the same "search stays" card the accommodation flow offers for
    such places. Otherwise the destination is only carried from earlier turns:
    it is background for answering what the traveler just said, not the
    subject of every reply, so the answer is led by their message (see
    _build_carried_destination_messages) and no destination card or
    selection event goes with it.

    Returns None when the record points at a catalog entry that no longer
    exists, so the caller carries on as if nothing had been chosen."""
    slug = selected.get("slug")
    destination = None
    if slug:
        destination = Destination.objects.filter(slug=slug).first()
        if destination is None:
            return None
    if not fresh:
        return _stream_carried_reply(
            message,
            selected,
            destination,
            history,
            trip_turn,
            ai_provider=ai_provider,
            remember=remember,
            conversation_key=conversation_key,
        )
    if destination is not None:
        return _handle_focus_destination(
            message,
            destination,
            profile=profile,
            history=history,
            ai_provider=ai_provider,
            climate_provider=climate_provider,
            remember=remember,
            conversation_key=conversation_key,
            chosen_destination=True,
            trip_turn=trip_turn,
        )
    name = selected["name"]
    country = selected.get("country") or ""
    reply = _stream_ai_reply(
        _build_selected_freeform_destination_messages(message, name, country, history, trip_turn),
        message,
        ai_provider=ai_provider,
        remember=remember,
        conversation_key=conversation_key,
    )
    return StreamingOrchestrationResult(
        [],
        reply,
        trip=trip_turn.trip if trip_turn is not None else None,
        accommodation_freeform_name=name,
        accommodation_freeform_country=country,
    )


def _stream_carried_reply(
    message: str,
    selected: dict,
    destination: Destination | None,
    history: list[dict] | None,
    trip_turn: trip_details.TripTurn | None,
    *,
    ai_provider: AIProvider,
    remember,
    conversation_key: str | None,
) -> StreamingOrchestrationResult:
    """The reply to a turn on a destination that is only carried over, with
    no card and no selection event - except when this message changed the trip
    details. Then the stays action goes out again with the new link and
    caption, because the one the traveler last saw no longer matches what is
    known (it is the same kind of reply as a stays request: it neither
    chooses nor replaces a place)."""
    reply = _stream_ai_reply(
        _build_carried_destination_messages(message, selected, destination, history, trip_turn),
        message,
        ai_provider=ai_provider,
        remember=remember,
        conversation_key=conversation_key,
    )
    if trip_turn is None or not trip_turn.changed:
        return StreamingOrchestrationResult([], reply)
    if destination is not None:
        scored = ScoredDestination(
            destination=destination,
            avg_high_c=None,
            avg_low_c=None,
            preference_fit=0,
            budget_fit=0,
            temperature_fit=0,
            repetition_penalty=0,
            score=0,
        )
        return StreamingOrchestrationResult(
            [scored],
            reply,
            is_destination_detail=True,
            is_accommodation_reply=True,
            trip=trip_turn.trip,
        )
    return StreamingOrchestrationResult(
        [],
        reply,
        trip=trip_turn.trip,
        accommodation_freeform_name=selected["name"],
        accommodation_freeform_country=selected.get("country") or "",
    )


def _same_place(first: dict | None, second: dict | None) -> bool:
    """Whether two selected-destination records are the same place: the same
    catalog entry, or the same name and country for one outside the catalog."""
    if not first or not second:
        return False
    if first.get("slug") or second.get("slug"):
        return first.get("slug") == second.get("slug")
    return " ".join(_plain_words(first["name"])) == " ".join(_plain_words(second["name"])) and (
        (first.get("country") or "").lower() == (second.get("country") or "").lower()
    )


def _build_carried_destination_messages(
    message: str,
    selected: dict,
    destination: Destination | None,
    history: list[dict] | None,
    trip_turn: trip_details.TripTurn | None = None,
) -> list[AIMessage]:
    """The reply for a turn on which the chosen destination is only carried
    over from earlier ones. The traveler's message leads: a complaint, a
    correction or a question about an earlier reply is answered itself rather
    than with a tour of the place, and the destination's facts are reference
    material - used when they help, never recited. Unlike the reply to the
    turn that made the choice, this one gets no climate line, no video offer
    and no closing-question instruction, because each of those turned every
    follow-up into another description of the place.

    The grounding rule is spelled out here as well as in SYSTEM_PROMPT because
    this is where it bites: a traveler who reports a wrong date or number of
    travelers on the booking link must hear that Wanderes can't set those,
    not that it fixed them."""
    if destination is not None:
        label = f"{destination.name}, {destination.country}"
        reference = (
            "Reference facts about it - background to draw on only when they help "
            "answer, not a list to recite:\n"
            f"- Trip type: {destination.get_trip_type_display()}\n"
            f"- Cost of living tier: {destination.get_cost_of_living_display()} "
            f"({destination.cost_of_living} on a 1-5 scale, 1 cheapest) - a relative "
            "indication only; we hold no verified prices for flights, hotels or "
            "activities\n"
            f"- Best season: {destination.best_season}\n"
            f"- Worst season: {destination.worst_season}\n"
            f"- Description: {destination.short_description}\n"
            f"- Points of interest: {', '.join(destination.points_of_interest)}\n\n"
        )
    else:
        label = (
            f"{selected['name']}, {selected['country']}"
            if selected.get("country")
            else selected["name"]
        )
        reference = (
            "It isn't in our curated destination dataset, so we hold no verified facts "
            "about it; anything you say about the place comes from general knowledge, "
            "and should be said as such.\n\n"
        )
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f"{label} is already the traveler's chosen destination, so it is background "
                "here, not the subject of this reply.\n"
                f'What they just said: "{message}"\n\n'
                f"{reference}"
                f"{trip_details.fact_block(trip_turn)}"
                "How to reply:\n"
                "1. Answer what they just said, directly and first. If it is a complaint, a "
                "correction, or a question about something you said earlier, deal with that "
                "itself - acknowledge it and answer it - instead of describing the "
                "destination.\n"
                "2. Use the reference facts only if they actually help answer. Don't recite "
                "the description, list attractions, mention the season or the climate, or "
                "suggest a video unless they asked about the destination itself; if they did "
                "('tell me more', 'what is it like', 'what is there to do'), answer that "
                "properly and richly.\n"
                "3. Let the length follow what they asked: a short question gets a short "
                "answer, a thank-you gets a brief, natural acknowledgement. Don't repeat what "
                "you have already told them in this conversation.\n"
                "4. Don't close with a generic question or an offer; ask something only if "
                "you genuinely need it to help them.\n"
                "5. State as fact only what is listed above or was said in this conversation. "
                "Never invent prices, availability, dates, numbers of travelers, bookings, or "
                "what any search link contains. Dates and numbers of travelers exist only as "
                "the trip details listed above, if any: never say one was set, changed or "
                "corrected unless they say so. You can't change a booking page the traveler "
                "already opened - if they say a detail is wrong, say what you hold (or that "
                "you hold none) and ask for the right value, which applies to the next search "
                "link. Without such a list you can't see what a link carried: if asked why it "
                "showed some date or number of travelers, don't explain, defend or deny it - "
                "say you can't see that. For cost, use only the tier above and say you have "
                "no verified prices, nor typical price ranges.\n"
                "Do not mention saving this as a trip or any button or interface element. "
                "Reply in the same language the traveler has been using in this conversation "
                "(check the history above, not just this message)."
            ),
        )
    )
    return messages


def _build_selected_freeform_destination_messages(
    message: str,
    name: str,
    country: str,
    history: list[dict] | None = None,
    trip_turn: trip_details.TripTurn | None = None,
) -> list[AIMessage]:
    """For a traveler who chose a real place our curated catalog doesn't
    have. Same recommendation philosophy as every other "not in the
    catalog" reply: general knowledge, said honestly, no invented
    specifics (prices, hotel names, opening times) and no pretending we hold
    verified data on it."""
    label = f"{name}, {country}" if country else name
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler just said: "{message}" - they have chosen {label} as '
                "where they want to go. It isn't in our curated destination dataset, so "
                "we hold no verified data on it. Treat the destination as already "
                "decided - don't suggest or compare other destinations unless they ask "
                "for alternatives. Respond warmly and usefully from your own general "
                "travel knowledge (what it's known for, when it's good to visit, "
                "something practical), answering what their message actually asks, and "
                "say in passing, without opening with an apology, that this comes from "
                "general knowledge rather than our verified data. Never invent specific "
                "prices, hotel names, or availability. Invite a real follow-up question. "
                "Reply in the same language the traveler has been using in this "
                "conversation (check the history above, not just this message)."
                f"\n\n{trip_details.fact_block(trip_turn)}".rstrip()
            ),
        )
    )
    return messages


def _build_destination_detail_messages(
    message: str,
    destination: Destination,
    *,
    avg_high_c: float | None,
    profile: TravelerProfile | None,
    history: list[dict] | None,
    accommodation_focus: bool = False,
    chosen_destination: bool = False,
    trip_turn: trip_details.TripTurn | None = None,
) -> list[AIMessage]:
    poi = ", ".join(destination.points_of_interest) if destination.points_of_interest else ""
    climate_line = f"\n- Current typical avg high: {avg_high_c}C" if avg_high_c is not None else ""
    # A stays reply is told who is going by the trip facts below alone; the
    # profile's usual group size must not pass as this trip's.
    traveler_note = _traveler_context_note(profile, include_party=not accommodation_focus)
    entry_requirements_note = _entry_requirements_note(profile, [destination])
    video_note = _video_availability_note([destination])
    video_offer = (
        "If a real video is noted as being on file above, you may offer to show it - "
        "only when one was actually noted as available, never speculatively. "
    )

    if accommodation_focus:
        # A where-to-stay answer isn't the place to reopen the weather or pitch a video.
        climate_line = ""
        video_note = ""
        video_offer = ""
        context_line = (
            f"The traveler asked about places to stay in {destination.name}, "
            f"{destination.country}. "
        )
        message_line = f'Their message was: "{message}"\n\n'
        conversation_note = (
            "Focus your reply on what's genuinely useful for choosing where "
            "to stay there - good areas/neighborhoods, what kind of "
            "accommodation fits this destination's character, practical "
            "tips - grounded only in the real facts listed below, never a "
            "specific hotel name, price, or availability claim you can't "
            "verify. Still ground it in a real, detailed sense of the place "
            "(the description and points of interest below), the way a "
        )
    elif chosen_destination:
        context_line = (
            f"The traveler has chosen {destination.name}, {destination.country} as "
            "where they want to go. "
        )
        message_line = f'Their message was: "{message}"\n\n'
        conversation_note = (
            "Treat the destination as already decided - don't suggest or compare "
            "other destinations unless they ask for alternatives. Have a "
            "genuine, detailed conversation about this one place - answer what "
            "their message actually asks, bring the description and points of "
            "interest to life, and invite a real follow-up question, the way a "
        )
    else:
        context_line = (
            f"The traveler chose to hear more about {destination.name}, "
            f'{destination.country} (they clicked "Choose this trip" on it). '
        )
        message_line = f'Their message alongside choosing it was: "{message}"\n\n'
        conversation_note = (
            "Have a genuine, detailed conversation about this one place - "
            "bring the description and points of interest to life, answer "
            "naturally, and invite a real follow-up question, the way a "
        )

    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f"{context_line}"
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
                f"{trip_details.fact_block(trip_turn, always=accommodation_focus)}"
                f"{message_line}"
                f"{conversation_note}"
                "thoughtful travel consultant would once a client has settled "
                f"on somewhere to talk through in depth. {video_offer}"
                "Do not mention saving this as a trip or any "
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
                "instead of a reminder that it was already there). This is "
                "NOT an invitation to have a normal back-and-forth about "
                "their trip - do not ask a follow-up question, do not just "
                "react with excitement, and do not let your reply become a "
                "paraphrase of what the traveler themselves said instead of "
                "the fact below (2026-09-15 QA finding: for an anonymous "
                "traveler, this produced replies like 'You want to go to "
                "Iceland to see the northern lights! When are you thinking "
                "of going?' - conversational and plausible-sounding, but it "
                "never actually told them they needed to log in to save "
                "it, which was the entire point of this call). If a "
                "condition or requirement (like needing to log in) is part "
                "of the fact, it must be clearly present in your reply - a "
                "reply that reads naturally but omits it has failed this "
                "task - this applies just as much to English as to any "
                "other language: "
                f"{fact}"
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
    conversation_key: str | None = None,
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

    destination = _resolve_destination(
        destination_name, ai_provider=ai_provider, conversation_key=conversation_key
    )
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
    conversation_key: str | None = None,
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

    destination = _resolve_destination(
        destination_name, ai_provider=ai_provider, conversation_key=conversation_key
    )
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


def _best_name_match(candidates, name: str) -> Destination | None:
    """Pick the destination a traveler most plausibly meant out of the loose
    substring matches. find_destination_slugs_by_name() matches name OR
    country anywhere inside the text, so a short name pulls in unrelated
    places ("Pai" matches every Spanish destination through "Spain", "Nice"
    matches Venice, "Lima" matches Kilimanjaro) and "first row wins" meant
    the database's row order decided the answer. Preference order: exact
    name, name starting with the text, the text as a whole word inside the
    name, then any other substring; within a tier, the lowest id."""
    wanted = name.strip().lower()
    if not wanted:
        return None
    ordered = list(candidates.order_by("id"))
    whole_word = re.compile(rf"\b{re.escape(wanted)}\b")
    for matches in (
        [d for d in ordered if d.name.lower() == wanted],
        [d for d in ordered if d.name.lower().startswith(wanted)],
        [d for d in ordered if whole_word.search(d.name.lower())],
        ordered,
    ):
        if matches:
            return matches[0]
    return None


def _catalog_name_forms(catalog_name: str) -> set[str]:
    """The names a catalog entry answers to: its own name and each of the
    " / "-separated names a compound entry lists ("Cusco / Machu Picchu"),
    with any parenthetical qualifier ("Hawaii (Maui/Oahu)") left out, all
    compared without case or accents."""
    base = re.sub(r"\([^)]*\)", " ", catalog_name)
    forms = {" ".join(_plain_words(base))}
    forms.update(" ".join(_plain_words(part)) for part in base.split("/"))
    forms.discard("")
    return forms


def _catalog_destination_named(name: str, *, country_hint: str | None = None) -> Destination | None:
    """The catalog destination that IS the place the traveler named: the same
    name, or one of the names a compound entry lists. Nothing fuzzy - no
    substring, prefix, translation or AI step - so a place the catalog does
    not carry comes back as None instead of a related one (a region is not
    its biggest city, "Porto" is not "Porto Seguro"). Two entries with one
    name (there are two Granadas) go to the one in `country_hint`, otherwise
    to the lowest id."""
    wanted = " ".join(_plain_words(name))
    if not wanted:
        return None
    matches = [
        d for d in Destination.objects.order_by("id") if wanted in _catalog_name_forms(d.name)
    ]
    if len(matches) > 1 and country_hint:
        hint = country_hint.strip().lower()
        matches = [d for d in matches if d.country.strip().lower() == hint] or matches
    return matches[0] if matches else None


def _resolve_destination(
    name: str,
    *,
    ai_provider: AIProvider | None = None,
    conversation_key: str | None = None,
) -> Destination | None:
    """Resolve a free-text destination name to a real catalog entry.

    Tries the cheap DB substring match first (find_destination_slugs_by_name,
    narrowed by _best_name_match) - the common case, no AI call needed. Only
    when that finds nothing, and an ai_provider was given, falls back to
    asking the AI to match the raw text against the real catalog (see
    DESTINATION_RESOLUTION_SYSTEM_PROMPT for why this is safe: it can only
    pick a real slug from the actual list, never invent one, and the result
    is re-verified against the database below regardless). Callers that
    can't supply an ai_provider (none currently) simply get the DB-only
    behavior. This is for flows where a nearby match is an acceptable answer
    (offering a stays link); a place the traveler has CHOSEN is looked up
    with _catalog_destination_named instead, which never substitutes."""
    # The raw-name match is added next to find_destination_slugs_by_name()
    # because that one rewrites its terms through the country-alias table
    # first, and "Granada" (the Spanish city) is also the Portuguese name for
    # the country Grenada.
    if not name.strip():
        return None
    slugs = find_destination_slugs_by_name([name])
    candidates = Destination.objects.filter(Q(slug__in=slugs) | Q(name__icontains=name.strip()))
    destination = _best_name_match(candidates, name)
    if destination is not None or ai_provider is None:
        return destination

    catalog = "\n".join(
        f"{d.slug}: {d.name}, {d.country}" for d in Destination.objects.all()
    )
    if not catalog:
        return None

    try:
        with track_llm_call(
            operation="resolve_destination_name", conversation_key=conversation_key
        ):
            response = ai_provider.generate_structured_reply(
                [
                    AIMessage(role="system", content=DESTINATION_RESOLUTION_SYSTEM_PROMPT),
                    AIMessage(
                        role="user",
                        content=(
                            f'The traveler wrote: "{name}"\n\n'
                            f"Real destinations on file:\n{catalog}"
                        ),
                    ),
                ],
                json_schema=DESTINATION_RESOLUTION_SCHEMA,
            )
    except AIProviderError:
        logger.warning(
            "Destination-name AI resolution failed - treating as unresolved. name=%r", name
        )
        return None

    resolved_slug = response.get("slug") if isinstance(response, dict) else None
    if not isinstance(resolved_slug, str) or not resolved_slug:
        return None
    # Never trust the model's slug blindly (09_AI_ORCHESTRATION.md §9) - a
    # hallucinated or malformed value just resolves to None here, same as
    # if the AI had said null in the first place.
    return Destination.objects.filter(slug=resolved_slug).first()


def _resolve_freeform_place(
    name: str, *, ai_provider: AIProvider | None, conversation_key: str | None = None
) -> tuple[str, str] | None:
    """Confirm a place is real enough to hand to Booking.com's own
    free-text search - not a catalog lookup, since a live accommodation
    search doesn't need any of the curated data _resolve_destination
    checks for (BookingComSearchLinkProvider.build_search_url only ever
    needs a name and, optionally, a country string). Only called once
    _resolve_destination has already found nothing in the catalog, so
    this never shadows a real catalog match - and the two are asked
    genuinely different questions (a closed-list lookup vs. "does this
    exist at all"), not the same prompt reused.

    Same "never trust structured output blindly" discipline as
    _resolve_destination: a failed call or an unconfident/malformed
    response just resolves to None, which the caller treats the same as
    "not a real place" - falls back to the existing general-knowledge
    reply with no search link offered, rather than guessing."""
    if ai_provider is None:
        return None
    try:
        with track_llm_call(
            operation="resolve_freeform_place", conversation_key=conversation_key
        ):
            response = ai_provider.generate_structured_reply(
                [
                    AIMessage(role="system", content=FREEFORM_PLACE_SYSTEM_PROMPT),
                    AIMessage(role="user", content=f'The traveler wrote: "{name}"'),
                ],
                json_schema=FREEFORM_PLACE_SCHEMA,
            )
    except AIProviderError:
        logger.warning(
            "Freeform place AI resolution failed - treating as unresolved. name=%r", name
        )
        return None

    if not isinstance(response, dict) or not response.get("is_real_place"):
        return None
    resolved_name = response.get("name")
    if not isinstance(resolved_name, str) or not resolved_name.strip():
        return None
    resolved_country = response.get("country")
    resolved_country = resolved_country.strip() if isinstance(resolved_country, str) else ""
    return resolved_name.strip(), resolved_country


def _resolve_selected_destination(
    name: str | None,
    *,
    country_hint: str | None,
    ai_provider: AIProvider,
    conversation_key: str | None = None,
) -> dict | None:
    """Turn the place the traveler said they're going to into the record the
    accumulated state keeps (see memory._NO_CLIMATE_BUDGET): the catalog
    destination that is that very place, otherwise a real place confirmed by
    _resolve_freeform_place, otherwise None - a name that is neither never
    becomes a selection.

    A chosen place is never swapped for a different one. The catalog lookup
    accepts only the same name (_catalog_destination_named), and the AI
    name-matching step used for suggestion links is deliberately not used: it
    answered "Valência" with Porto and "Toscana" with Florence, which would
    have sent the whole conversation to another city. A place the catalog
    doesn't carry gets the free-form reply under its own name instead. A
    catalog hit costs no model call. A match whose country contradicts the
    country the message implied (`country_hint`) is dropped as well, for two
    entries sharing a name."""
    if not name:
        return None
    destination = _catalog_destination_named(name, country_hint=country_hint)
    if (
        destination is not None
        and country_hint
        and destination.country.strip().lower() != country_hint.strip().lower()
    ):
        logger.info(
            "Dropped a catalog match for the chosen place - its country contradicts the "
            "message. name=%r matched=%r country_hint=%r",
            name,
            destination.slug,
            country_hint,
        )
        destination = None
    if destination is not None:
        return {
            "slug": destination.slug,
            "name": destination.name,
            "country": destination.country,
        }
    freeform_place = _resolve_freeform_place(
        name, ai_provider=ai_provider, conversation_key=conversation_key
    )
    if freeform_place is None:
        return None
    freeform_name, freeform_country = freeform_place
    # The same place under its standard English name (the model wrote
    # "Sevilla", the catalog says "Seville"): an exact lookup on that name,
    # in the same country, is still the same place and gets the catalog reply.
    # A region the catalog merely contains a city of ("Tuscany") has no entry
    # under its own name, so it stays free-form.
    standard = _catalog_destination_named(freeform_name, country_hint=freeform_country)
    if standard is not None and (
        not freeform_country or standard.country.strip().lower() == freeform_country.lower()
    ):
        return {"slug": standard.slug, "name": standard.name, "country": standard.country}
    return {"slug": None, "name": freeform_name, "country": freeform_country or ""}


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


def _sanitized_history_messages(history: list[dict] | None) -> list[AIMessage]:
    """Same as _history_messages, but strips literal temperature/cost-tier
    figures out of assistant turns first (memory.sanitize_reply_for_context)
    - used only by _extract_intent, which is the one caller that needs
    protection from misreading the AI's own stated numbers as something the
    traveler said. Everything else (recall, activity follow-ups, saved-
    conversation titles) needs the real, unedited reply - see that
    function's docstring."""
    return [
        AIMessage(
            role=turn["role"],
            content=(
                memory.sanitize_reply_for_context(turn["content"])
                if turn["role"] == "assistant"
                else turn["content"]
            ),
        )
        for turn in history or []
    ]


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


def _traveler_context_note(
    profile: TravelerProfile | None, *, always_mention: bool = False, include_party: bool = True
) -> str:
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
    if profile.travelers_count and include_party:
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
    messages.extend(_sanitized_history_messages(history))
    messages.append(AIMessage(role="user", content=message))
    # temperature=0 - this feeds straight into deterministic logic (which
    # branch runs, what gets queried), so it needs to be consistent, not
    # creative. Without it, the same message + history could extract a
    # different value from one call to the next - we actually saw an
    # already-established month silently vanish on a later turn.
    data = ai_provider.generate_structured_reply(messages, json_schema=INTENT_SCHEMA, temperature=0)
    return _validate_intent(data)


def _today() -> date:
    return date.today()


def _stored_trip_turn(state_key: str | None) -> trip_details.TripTurn:
    """The trip state as stored, with no model call - for a turn that takes
    the trip as it already is (the "Choose this trip" button)."""
    today = _today()
    record = memory.get_climate_budget(state_key)["trip_details"] if state_key else None
    return trip_details.TripTurn(trip=trip_details.resolve(record, today), today=today)


def _should_read_trip_details(message: str, intent: dict, stored: dict | None) -> bool:
    """Whether this turn is worth the trip-details call. Decided without a
    model: the message has date, length or party cues, or a stays request is
    waiting on exactly this (nobody has said how many adults yet). A chosen
    destination alone is not a reason, so "o que fazer lá?" and "obrigado"
    cost nothing extra. Past-trip feedback, wishes with no plan and the
    video/activity questions aren't about this trip's details."""
    if (
        intent["message_type"] in ("feedback", "future_intent")
        or intent["is_video_request"]
        or intent["is_activity_question"]
    ):
        return False
    if trip_details.has_trip_detail_cues(message):
        return True
    return intent["is_accommodation_request"] and trip_details.needs_occupancy(stored)


def _extract_trip_details_signal(
    message: str,
    *,
    ai_provider: AIProvider,
    history: list[dict] | None,
    conversation_key: str | None = None,
) -> dict:
    """The components of trip detail the traveler gave in this message - never
    a computed date. It sees the message and, for a short reply that needs it
    ("5 anos" answering a question), the assistant's last message with every
    digit masked; it never sees the rest of the history, so a number the
    assistant said earlier can't come back as something the traveler said. A
    failed call reads as "nothing stated"."""
    question = trip_details.previous_question_for_extraction(history, message)
    content = (
        message
        if question is None
        else f"The assistant's previous question (context only):\n{question}\n\n"
        f"The traveler's latest message:\n{message}"
    )
    messages = [
        AIMessage(role="system", content=trip_details.TRIP_DETAILS_SYSTEM_PROMPT),
        AIMessage(role="user", content=content),
    ]
    try:
        with track_llm_call(operation="extract_trip_details", conversation_key=conversation_key):
            data = ai_provider.generate_structured_reply(
                messages, json_schema=trip_details.TRIP_DETAILS_SCHEMA, temperature=0
            )
    except AIProviderError:
        logger.warning("Could not extract trip details - AI provider failure. message=%r", message)
        data = {}
    return trip_details.restrict_clears(trip_details.validate_components(data), message)


def _read_trip_details(
    message: str,
    intent: dict,
    *,
    history: list[dict] | None,
    ai_provider: AIProvider,
    state_write_key,
    thread_id: int | str | None,
    conversation_key: str | None,
) -> trip_details.TripTurn:
    """This turn's trip state: what's stored, updated by what the traveler
    just said (when the gate lets the call run), resolved against today's
    date. A turn that can't write the state (a saved conversation that
    doesn't own it) still resolves what it read from this message, and just
    leaves the stored record alone. The ownership check is repeated right
    before the write, after the model call, like every other state write."""
    today = _today()
    read_key = state_write_key()
    stored = memory.get_climate_budget(read_key)["trip_details"] if read_key else None
    record, issues, ask = stored, (), False
    before = trip_details.resolve(stored, today)
    if _should_read_trip_details(message, intent, stored):
        components = _extract_trip_details_signal(
            message, ai_provider=ai_provider, history=history, conversation_key=conversation_key
        )
        applied = trip_details.apply_components(stored, components, today)
        record, issues, ask = applied.record, applied.issues, applied.ask_child_ages
        write_key = state_write_key()
        if applied.changed and write_key is not None:
            if record is None:
                memory.update_climate_budget(write_key, trip_details_cleared=True, owner=thread_id)
            else:
                memory.update_climate_budget(write_key, trip_details=record, owner=thread_id)
    trip = trip_details.resolve(record, today)
    return trip_details.TripTurn(
        trip=trip,
        issues=issues,
        ask_child_ages=ask,
        today=today,
        changed=trip.booking_kwargs() != before.booking_kwargs(),
    )


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


def _extract_state_clear_signal(
    message: str, *, ai_provider: AIProvider, conversation_key: str | None = None
) -> dict:
    """Derive this turn's explicit-clear signal (see STATE_CLEAR_SCHEMA)
    from this message alone - a wholly separate call from
    _extract_climate_budget_signal above, sharing no schema or prompt
    text with it. See CLIMATE_BUDGET_SYSTEM_PROMPT's comment for why that
    separation is load-bearing, not just tidiness."""
    messages = [
        AIMessage(role="system", content=STATE_CLEAR_SYSTEM_PROMPT),
        AIMessage(role="user", content=message),
    ]
    try:
        with track_llm_call(
            operation="extract_state_clear_signal", conversation_key=conversation_key
        ):
            data = ai_provider.generate_structured_reply(
                messages, json_schema=STATE_CLEAR_SCHEMA, temperature=0
            )
    except AIProviderError:
        logger.warning(
            "Could not extract an isolated state-clear signal - AI provider failure. message=%r",
            message,
        )
        data = {}
    return _validate_state_clear(data)


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


def _validate_state_clear(data: dict) -> dict:
    """Validates STATE_CLEAR_SCHEMA's output - eight booleans/one list,
    nothing that needs enum or catalog checking (unlike _validate_intent's
    trip_type/country, which pick a VALUE; this only ever answers yes/no).
    Missing keys (an older/simpler AIProvider stub, or a provider failure
    degrading to {}) all read as "no clear this turn" - every lookup here
    goes through .get() on purpose."""
    return {
        "min_temp_c_cleared": bool(data.get("min_temp_c_cleared")),
        "max_temp_c_cleared": bool(data.get("max_temp_c_cleared")),
        "max_cost_of_living_cleared": bool(data.get("max_cost_of_living_cleared")),
        "trip_type_cleared": bool(data.get("trip_type_cleared")),
        "continent_cleared": bool(data.get("continent_cleared")),
        "country_cleared": bool(data.get("country_cleared")),
        "excluded_place_names_remove": _clean_string_list(data.get("excluded_place_names_remove")),
        "excluded_place_names_cleared": bool(data.get("excluded_place_names_cleared")),
        "selected_destination_cleared": bool(data.get("selected_destination_cleared")),
    }


# Words that make a short message a statement of choice rather than a bare
# place name ("quero Bali", "I want Bali", "vou Bali").
_FILLER_WORDS = frozenset("o a os as um uma the el la le il por favor please pls pfv porfa".split())
_CHOICE_WORDS = frozenset(
    "quero queria vou vamos bora escolho prefiro quiero voy voglio vado want wanna "
    "going go take choose pick veux vais".split()
)
_BARE_REPLY_MAX_WORDS = 2


def _plain_words(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", folded)


def _options_just_presented(history: list[dict] | None, *place_names: str) -> bool:
    """Whether the assistant's latest reply mentions one of these places - the
    only context a bare place name can be answering."""
    last_reply = next(
        (turn["content"] for turn in reversed(history or []) if turn["role"] == "assistant"), None
    )
    if not last_reply:
        return False
    text = f" {' '.join(_plain_words(last_reply))} "
    return any(
        f" {' '.join(words)} " in text for words in map(_plain_words, place_names) if words
    )


def _drop_unoffered_bare_selection(message: str, intent: dict, history: list[dict] | None) -> None:
    """A bare place name ("Bali") picks a destination only as the answer to
    options the assistant has just presented. With no such options in sight
    - nothing said yet, or a place that reply never mentioned - it is just a
    mention, and the selection the model made from it is dropped. The model
    can't be relied on for this (it selects any bare name), but the context
    is plain in the history, so it is checked here instead. A message with a
    choice word in it ("quero Bali") or more than two words ("outra cidade:
    Madrid") is a statement, never bare - the cost of calling a statement
    bare is a lost selection, so doubt goes the other way."""
    name = intent.get("selected_destination_name")
    if not name:
        return
    words = [w for w in _plain_words(message) if w not in _FILLER_WORDS]
    if not 1 <= len(words) <= _BARE_REPLY_MAX_WORDS or any(w in _CHOICE_WORDS for w in words):
        return
    if _options_just_presented(history, " ".join(words), name):
        return
    logger.info(
        "Dropped a bare place name as a selection - no options naming it were just presented. "
        "message=%r selected=%r",
        message,
        name,
    )
    intent["selected_destination_name"] = None


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
    country = country.strip() if isinstance(country, str) and country.strip() else None
    # The extraction prompt now captures any place narrower than a
    # continent into `country`, multi-country regions included, rather
    # than deciding in the prompt itself whether a name is "a real single
    # country." Check that here against the actual catalog: a value that
    # isn't a real country never becomes a doomed exact-match filter -
    # it's nulled out and kept as unmatched_region_name so the caller can
    # fall back to a general-knowledge answer and log the term.
    #
    # Canonicalized before the catalog check (2026-09-25 evaluation
    # baseline finding): the AI reasonably extracts "United States", but
    # this catalog stores "USA" - is_known_country() alone would say
    # True (it canonicalizes internally too), but the RecommendationRequest
    # built downstream needs the CATALOG's own value, not the traveler's
    # phrasing, or country__icontains="United States" would still match
    # nothing. travel.geography_aliases is a small, explicit table (not a
    # general region/synonym dictionary) - an unrecognized name just
    # passes through unchanged for the same catalog check as before.
    if country is not None:
        country = canonicalize_country_name(country)
    if country is not None and not is_known_country(country):
        data["unmatched_region_name"] = country
        country = None
    else:
        data["unmatched_region_name"] = None
    data["country"] = country

    # A chosen destination is one specific place, and only a recommendation
    # request can carry one. A name that is a country as written, or that the
    # model also gave as the country/region of the same message, is still a
    # discovery constraint and never becomes a selection. The alias table is
    # deliberately not used to decide this from the name alone: it rewrites
    # "Granada" to the country Grenada, and a selected city must survive that.
    selected = data.get("selected_destination_name")
    selected = selected.strip() if isinstance(selected, str) and selected.strip() else None
    if selected is not None:
        region = country or data["unmatched_region_name"] or ""
        names_the_region = bool(region) and (
            canonicalize_country_name(selected).lower() == canonicalize_country_name(region).lower()
        )
        if (
            data.get("message_type") != "recommendation"
            or is_catalog_country_name(selected)
            or names_the_region
        ):
            selected = None
    data["selected_destination_name"] = selected

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

    data["is_accommodation_request"] = bool(data.get("is_accommodation_request"))
    accommodation_place_name = data.get("accommodation_place_name")
    data["accommodation_place_name"] = (
        accommodation_place_name
        if isinstance(accommodation_place_name, str) and accommodation_place_name.strip()
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
    # Numbered by deterministic rank (#1 = the real winner), not a bare
    # bullet list - the explicit rank label is what the ranking-fidelity
    # instruction below refers back to. A plain unordered list left the
    # model free to feature whichever candidates it personally judged
    # most relevant, silently dropping the actual #1 (2026-09-25
    # evaluation baseline: ~26 scenarios where the presented "top pick"
    # wasn't deterministic rank #1 at all).
    candidates_summary = "\n".join(
        f"{i}. {r.destination.name}, {r.destination.country}: avg high {r.avg_high_c}C, "
        f"cost tier {r.destination.cost_of_living}/5, trip type {r.destination.trip_type}"
        for i, r in enumerate(top_results, start=1)
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
                "ranked by the application in this exact order - #1 is the "
                "real winner, not a suggestion you're free to reorder. Do "
                "not invent any other destinations or facts beyond what is "
                "listed here:\n"
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
                "\n\nPresent the top 1-3 options from the numbered list above "
                "as a compact Markdown table (standard pipe syntax) comparing "
                "them side by side, IN THE SAME ORDER as the numbered list - "
                "the destination you present first/as the primary "
                "recommendation must be #1 from that list. Never silently "
                "swap in a lower-ranked candidate as if it were the top "
                "pick just because it seems like a better conversational "
                "fit - the application already decided the ranking, your "
                "job is to explain it, not to re-run it. If #1 has a real "
                "downside worth flagging (e.g. it doesn't perfectly match "
                "something the traveler asked for), say so honestly IN "
                "ADDITION to presenting it first - explaining a trade-off "
                "is not the same as dropping the destination for a "
                "different one you like better. Pick table columns that "
                "actually matter here (e.g. destination, climate, cost, a "
                "standout pro, a real downside or trade-off to weigh) "
                "rather than a fixed template every time. A short sentence "
                "or two of context before or after the table is fine, but "
                "the comparison itself belongs in the table, not "
                "paragraphs of prose. After the table, "
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
                "confident about - an exact current price or a typical price "
                "range, a specific company or airline name and route, live "
                "availability or a schedule - "
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


def _build_unrecognized_accommodation_destination_messages(
    message: str, destination_name: str, history: list[dict] | None = None
) -> list[AIMessage]:
    """Built when an accommodation request names a real place our curated
    catalog doesn't have - same "use AI general knowledge instead of a
    canned dead-end" pattern as the future_intent/feedback cases above,
    for the identical underlying situation. No real "Search stays" link
    can be built for this either (integrations.accommodations needs a
    real Destination for its country field) - the reply says so honestly
    in passing, without dwelling on it as an apology."""
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler just said: "{message}" - asking about places to stay in '
                f"{destination_name}. This destination isn't in our curated catalog, so "
                "there's no real accommodation search link to offer for it the way a "
                "catalog destination would get. Respond helpfully using your own general "
                "travel knowledge about the place (what areas are good to stay in, what "
                "to expect) the way a knowledgeable travel consultant would, rather than "
                "just acknowledging the message. Mention in passing, without opening with "
                "an apology, that you can't pull up a live accommodation search for it "
                "specifically. Never invent a specific hotel name, price, or booking link "
                "- keep suggestions general (neighborhoods, types of stay) rather than "
                "naming a property that may not exist. Reply in the same language the "
                "traveler has been using in this conversation (check the history above, "
                "not just this message) - this applies just as much to English as to any "
                "other language."
            ),
        )
    )
    return messages


def _build_accommodation_party_size_question_messages(
    message: str,
    destination_label: str,
    history: list[dict] | None = None,
    trip_turn: trip_details.TripTurn | None = None,
) -> list[AIMessage]:
    """Built when is_accommodation_request resolves to a real destination
    (catalog or freeform) but nobody has said how many adults are going
    yet - asked once, up front, before any "Search stays" link is generated
    (2026-09-24, direct user report: asked for 3 people, got a link built
    for Booking.com's own default of 2, because the search omitted a count
    entirely). It also asks about children and their ages. The traveler's
    next reply, even a bare number, is read by the trip-details call
    (ai.trip_details), which the stays-request-waiting-on-adults case wakes
    up on purpose.

    Takes a plain "name, country" label rather than a Destination object
    so the same builder covers a freeform (non-catalog) place too - this
    question doesn't need any curated data, just something to name back
    to the traveler."""
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler just said: "{message}" - asking about places to stay '
                f"in {destination_label}, but hasn't said how "
                "many people it's for. Ask them, briefly and naturally, before "
                "suggesting anything specific - how many adults, and whether any "
                "children are coming (and if so, how old each is, since Booking needs "
                "the ages). Keep it short and conversational, not a formal form, and "
                "don't repeat information you already gave them earlier in this "
                "conversation. Reply in the same language the traveler has been using "
                "in this conversation (check the history above, not just this "
                f"message).\n\n{trip_details.fact_block(trip_turn)}".rstrip()
            ),
        )
    )
    return messages


def _build_freeform_accommodation_messages(
    message: str,
    place_name: str,
    place_country: str,
    *,
    trip_turn: trip_details.TripTurn | None,
    profile: TravelerProfile | None,
    history: list[dict] | None = None,
) -> list[AIMessage]:
    """Built when is_accommodation_request names a place _resolve_destination
    can't match in the curated catalog, but _resolve_freeform_place
    confirmed is real - e.g. Wuhan, which Wanderes has never scored or
    written a description for, but is still a real city Booking.com can
    search directly (2026-09-25, direct user report: asked about Wuhan,
    got a canned "can't search" reply with no party-size question at all,
    even though a live accommodation search never actually depended on
    the curated catalog).

    No description/points_of_interest/climate/entry-requirements
    grounding here, unlike _build_destination_detail_messages - none of
    that exists for a non-catalog place, and inventing it would break
    "never invent travel data." ai/views.py attaches the real "Search
    stays" link from place_name/place_country directly - the reply just
    needs to know one is coming so it doesn't claim it can't help."""
    location_label = f"{place_name}, {place_country}" if place_country else place_name
    traveler_note = _traveler_context_note(profile, include_party=False)
    messages = [AIMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(_history_messages(history))
    messages.append(
        AIMessage(
            role="user",
            content=(
                f'The traveler just said: "{message}" - asking about places to '
                f"stay in {location_label}. This isn't one of our "
                "curated destinations, so there's no researched description or "
                "climate data on file for it - but it's a real place, so a live "
                "accommodation search link IS being shown to them separately "
                "right after your reply (don't say you can't help with a "
                "search, and don't paste a URL yourself - just don't dwell on "
                "the lack of one). Using your own general travel knowledge, say "
                "something genuinely useful about staying there - good "
                "areas/neighborhoods, what to expect - the way a knowledgeable "
                "consultant would. Never invent a specific hotel name, price, "
                "or rating. Do not mention saving this as a trip. Reply in the "
                "same language the traveler has been using in this "
                "conversation (check the history above, not just this "
                f"message).{traveler_note}\n\n"
                f"{trip_details.fact_block(trip_turn, always=True)}".rstrip()
            ),
        )
    )
    return messages
