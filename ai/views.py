import json

from django.http import (
    HttpResponseBadRequest,
    HttpResponseForbidden,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from analytics.services import record_event

from . import memory
from .conversations import record_turn
from .models import SavedConversation
from .orchestration import FALLBACK_REPLY, MAX_RECOMMENDATIONS, stream_travel_recommendation

MAX_MESSAGE_LENGTH = 2000

# Appended after the streamed reply so the chat page can build "save as
# trip" links without a second endpoint or server-side session state.
# Distinctive enough real reply text won't collide with it by accident.
RECOMMENDATIONS_DELIMITER = "\n<<<WANDERES_RECOMMENDATIONS>>>\n"

# Same trick for saved-conversation status - whether this turn got
# persisted, and why not if it didn't - so the chat page can show its
# explanatory modal without another endpoint. Only appended for
# authenticated users; anonymous visitors can't save conversations.
CONVERSATION_DELIMITER = "\n<<<WANDERES_CONVERSATION>>>\n"


def _chat_i18n_json() -> str:
    """Translated strings the chat page's JS needs at runtime - loading
    messages, dynamically built recommendation cards, error bubbles -
    none of which a template-level {% trans %} tag can reach.

    Serialized with json.dumps rather than hand-quoted into JS string
    literals: some of these strings contain an apostrophe (e.g. "Couldn't
    load that conversation."), which breaks a naive single-quoted JS
    literal once translated. Same <>&-escaping as
    core.context_processors.site_meta's JSON-LD, for the same reason -
    safe to embed in a <script> tag."""
    data = json.dumps(
        {
            "loadingMessages": [
                _("Finding destinations that fit your preferences..."),
                _("Thinking about the best options for your trip..."),
                _("Comparing possibilities..."),
                _("Looking at climate and costs for you..."),
            ],
            "whyThisFitsYou": _("Why this fits you"),
            "avgTempSuffix": _("avg"),
            "saveThisTrip": _("Save this trip"),
            "chooseThisTrip": _("Choose this trip"),
            # {name} is substituted client-side (JS .replace()), not by
            # Django - translators must keep the literal "{name}" token.
            "tellMeMoreAbout": _("Tell me more about {name}"),
            "notSaving": _("(not saving)"),
            "deleteConversation": _("Delete conversation"),
            "noSavedConversationsYet": _("No saved conversations yet."),
            "couldntLoadConversation": _("Couldn't load that conversation."),
            "newConversation": _("New conversation"),
            "couldntReachServer": _(
                "Couldn't reach the server. Check your connection and try again."
            ),
            "somethingWentWrong": _("Something went wrong on our end. Please try again."),
        }
    )
    return data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def chat_page(request):
    return render(
        request,
        "ai/chat.html",
        {
            "max_saved_conversations": SavedConversation.MAX_CONVERSATIONS_PER_USER,
            "chat_i18n_json": _chat_i18n_json(),
        },
    )


def _require_authenticated_json(request):
    """Guard for the small JSON conversation-management endpoints below.
    Returns a plain 403 instead of login_required's HTML redirect, since
    these are only ever called by the chat page's own JS, which already
    knows from the template whether the visitor is signed in."""
    if not request.user.is_authenticated:
        return HttpResponseForbidden("Login required.")
    return None


def _parse_conversation_id(raw: str | None) -> int | None:
    if raw and raw.isdigit():
        return int(raw)
    return None


def _recommendation_card_data(scored_destination, *, detail_shown=False):
    """Shape one ScoredDestination into what the chat page's recommendation
    cards need. `05_AI_DESIGN.md` §7's "never invent travel data" applies
    to the frontend too - only real fields already computed by
    recommendations.scoring get exposed here, never new facts.
    `fit_reasons` turns the scoring factors already used to rank
    destinations into safe, user-facing explanations - never the AI's own
    reasoning or raw scores.

    `detail_shown` tells the frontend whether this card came from
    ai.orchestration's single-destination detail path. If so it renders
    the real "Save this trip" link; otherwise "Choose this trip", which
    sends the traveler back into that detail path instead of saving
    immediately."""
    destination = scored_destination.destination
    fit_reasons = []
    if scored_destination.preference_fit > 0:
        fit_reasons.append("Matches your travel style")
    if scored_destination.budget_fit > 0:
        fit_reasons.append("Within your budget")
    if scored_destination.temperature_fit > 0:
        fit_reasons.append("Great climate match")

    return {
        "slug": destination.slug,
        "name": destination.name,
        "country": destination.country,
        "trip_type": destination.get_trip_type_display(),
        "cost_of_living": destination.get_cost_of_living_display(),
        "avg_high_c": scored_destination.avg_high_c,
        "fit_reasons": fit_reasons,
        "detail_shown": detail_shown,
    }


@require_POST
def recommendations_stream(request):
    # Reject empty or absurdly long input before spending an AI call on it
    # (09_AI_ORCHESTRATION.md §3, step 1).
    message = request.POST.get("message", "").strip()
    if not message:
        return HttpResponseBadRequest("Message must not be empty.")
    if len(message) > MAX_MESSAGE_LENGTH:
        return HttpResponseBadRequest("Message is too long.")

    user = request.user if request.user.is_authenticated else None

    # ai.memory keys anonymous conversations by the Django session, which
    # is otherwise unused for anonymous visitors - force it to exist now
    # instead of waiting for some other write to create it later, so even
    # the first message gets a stable key. Has to happen before the
    # analytics call below so conversation_key is resolvable from the
    # very first event, not just from the second message onward.
    if not request.session.session_key:
        request.session.save()
    conversation_key = memory.conversation_key(user=user, session_key=request.session.session_key)
    locale = request.LANGUAGE_CODE

    # Any chat interaction counts here, regardless of what it turns out to
    # be - recommendation, feedback, future intent, or off-topic.
    record_event(
        "travel_question_submitted",
        user=user,
        request=request,
        conversation_key=conversation_key,
        locale=locale,
    )

    # Saving is for registered users only - the checkbox isn't even
    # rendered for anonymous visitors, but enforce it server-side too,
    # not just hide it in the UI.
    save_requested = user is not None and request.POST.get("save") == "true"
    conversation_id = _parse_conversation_id(request.POST.get("conversation_id"))
    conversation = None
    history_override = None
    if conversation_id is not None and user is not None:
        conversation = SavedConversation.objects.filter(pk=conversation_id, user=user).first()
        if conversation is None:
            # Stale or foreign id (e.g. deleted from another tab) - treat
            # this like a fresh, not-yet-saved thread.
            conversation_id = None
        else:
            history_override = conversation.messages[-memory.MAX_HISTORY_MESSAGES :]

    # Sent only by the chat page's own "Choose this trip" button, which
    # already knows the destination - no validation here,
    # stream_travel_recommendation's own Destination lookup is the source
    # of truth, and a bogus/stale slug just falls through to normal
    # message handling there.
    focus_destination_slug = request.POST.get("focus_destination_slug", "").strip() or None

    # No explicit ai_provider - stream_travel_recommendation resolves its
    # own default lazily. record_turn below does the same, for the same
    # reason: constructing a real AIProvider isn't free and isn't always
    # needed (e.g. whenever save_requested is False).
    result = stream_travel_recommendation(
        message,
        user=user,
        session_key=request.session.session_key,
        history_override=history_override,
        focus_destination_slug=focus_destination_slug,
    )
    if result.recommendations:
        if result.is_destination_detail:
            # The "Choose this trip" detail reply is a deliberate user
            # action, distinct from a normal browse-stage
            # recommendation_generated. Its single ScoredDestination isn't
            # a fresh recommendation_generated event - it grew out of one
            # already recorded on an earlier turn.
            record_event(
                "destination_selected",
                user=user,
                request=request,
                metadata={"destination_slug": result.recommendations[0].destination.slug},
                conversation_key=conversation_key,
                locale=locale,
            )
        else:
            record_event(
                "recommendation_generated",
                user=user,
                request=request,
                metadata={
                    "result_count": len(result.recommendations),
                    "destination_slugs": [
                        r.destination.slug for r in result.recommendations[:MAX_RECOMMENDATIONS]
                    ],
                    "constraints": result.recommendation_constraints,
                },
                conversation_key=conversation_key,
                locale=locale,
            )

    def _chunks_with_footers():
        collected = []
        for chunk in result.reply_chunks:
            collected.append(chunk)
            yield chunk
        full_reply = "".join(collected)

        if result.recommendations:
            # Already capped to MAX_RECOMMENDATIONS by ai.orchestration
            # before it reaches this view - this slice is a no-op today,
            # kept so a future caller that doesn't pre-cap can't flood the
            # UI with cards.
            payload = [
                _recommendation_card_data(r, detail_shown=result.is_destination_detail)
                for r in result.recommendations[:MAX_RECOMMENDATIONS]
            ]
            yield RECOMMENDATIONS_DELIMITER + json.dumps(payload)

        if user is not None:
            # A degraded reply (provider unreachable, or failed
            # mid-stream) shouldn't get permanently written into the
            # traveler's saved conversation as if it were a real answer -
            # it would count toward the char limit and stay visible on
            # reload. FALLBACK_REPLY shows up verbatim (a full failure) or
            # as a suffix (partial reply before a mid-stream failure);
            # either way, skip saving this turn. The conversation itself
            # already continued normally - this only affects persistence.
            save_result = record_turn(
                user=user,
                conversation=conversation,
                save_requested=save_requested and FALLBACK_REPLY not in full_reply,
                user_message=message,
                assistant_reply=full_reply,
            )
            yield CONVERSATION_DELIMITER + json.dumps(
                {
                    "saved": save_result.saved,
                    "conversation_id": save_result.conversation_id,
                    "subject": save_result.subject,
                    "reason": save_result.reason,
                }
            )

    return StreamingHttpResponse(_chunks_with_footers(), content_type="text/plain; charset=utf-8")


@require_POST
def conversation_reset(request):
    """Clear whatever short-term AI context (ai.memory, Redis-backed)
    exists under this visitor's key. Called on "New conversation" so a
    genuinely fresh thread doesn't silently inherit context from whatever
    was last discussed under the same key. Works for anonymous visitors
    too, keyed by session - saving a conversation is registered-only, but
    starting fresh isn't."""
    user = request.user if request.user.is_authenticated else None
    if not request.session.session_key:
        request.session.save()
    key = memory.conversation_key(user=user, session_key=request.session.session_key)
    memory.clear_history(key)
    return JsonResponse({"reset": True})


@require_GET
def conversation_list(request):
    forbidden = _require_authenticated_json(request)
    if forbidden:
        return forbidden
    conversations = SavedConversation.objects.filter(user=request.user)
    return JsonResponse(
        {
            "conversations": [
                {
                    "id": c.pk,
                    "subject": c.subject or "New conversation",
                    "updated_at": c.updated_at.isoformat(),
                }
                for c in conversations
            ],
            "max_conversations": SavedConversation.MAX_CONVERSATIONS_PER_USER,
        }
    )


@require_GET
def conversation_detail(request, pk):
    forbidden = _require_authenticated_json(request)
    if forbidden:
        return forbidden
    # Same pattern as every trips/users view - only ever fetches the
    # caller's own conversation.
    conversation = get_object_or_404(SavedConversation, pk=pk, user=request.user)
    return JsonResponse(
        {
            "id": conversation.pk,
            "subject": conversation.subject,
            "messages": conversation.messages,
            "is_full": conversation.is_full,
        }
    )


@require_POST
def conversation_delete(request, pk):
    forbidden = _require_authenticated_json(request)
    if forbidden:
        return forbidden
    conversation = get_object_or_404(SavedConversation, pk=pk, user=request.user)
    conversation.delete()
    return JsonResponse({"deleted": True})
