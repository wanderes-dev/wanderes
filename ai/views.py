import json

from django.http import (
    HttpResponseBadRequest,
    HttpResponseForbidden,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from analytics.services import record_event

from . import memory
from .conversations import record_turn
from .models import SavedConversation
from .orchestration import FALLBACK_REPLY, MAX_RECOMMENDATIONS, stream_travel_recommendation

MAX_MESSAGE_LENGTH = 2000

# Appended after the streamed reply text so the chat page can offer
# "save as trip" links for the recommended destinations (Phase 13 -
# "Save relevant recommendations") without needing a second endpoint or
# server-side session state. Distinctive enough that real reply text is
# very unlikely to contain it by coincidence.
RECOMMENDATIONS_DELIMITER = "\n<<<WANDERES_RECOMMENDATIONS>>>\n"

# Same approach, same reasoning, for saved-conversation status (2026-09-02):
# whether this turn got persisted, and why not when it didn't - lets the
# chat page show a one-time explanatory modal without a second endpoint or
# server-side session state either. Only ever appended for authenticated
# users - anonymous visitors can't save conversations at all.
CONVERSATION_DELIMITER = "\n<<<WANDERES_CONVERSATION>>>\n"


def chat_page(request):
    return render(
        request,
        "ai/chat.html",
        {"max_saved_conversations": SavedConversation.MAX_CONVERSATIONS_PER_USER},
    )


def _require_authenticated_json(request):
    """Shared guard for the small JSON conversation-management endpoints
    below - a plain 403 rather than login_required's HTML redirect, since
    these are only ever called by the chat page's own JS, which already
    knows (from the template) whether the visitor is signed in."""
    if not request.user.is_authenticated:
        return HttpResponseForbidden("Login required.")
    return None


def _parse_conversation_id(raw: str | None) -> int | None:
    if raw and raw.isdigit():
        return int(raw)
    return None


def _recommendation_card_data(scored_destination):
    """Shape one ScoredDestination into what the chat page's recommendation
    cards need (2026-09-01 UI/UX pass - `05_AI_DESIGN.md` §7 "never invent
    travel data" applies to the frontend too, so this only ever exposes
    real fields already computed by recommendations.scoring, never new
    facts). `fit_reasons` translates the scoring factors that are already
    used to rank destinations into safe, user-facing explanations - never
    exposes the AI's own reasoning or raw scores, matching the existing
    "no internal chain-of-thought in the UI" boundary."""
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
    }


@require_POST
def recommendations_stream(request):
    # Request Validation (09_AI_ORCHESTRATION.md §3, step 1): reject empty
    # or absurdly long input before spending an AI call on it.
    message = request.POST.get("message", "").strip()
    if not message:
        return HttpResponseBadRequest("Message must not be empty.")
    if len(message) > MAX_MESSAGE_LENGTH:
        return HttpResponseBadRequest("Message is too long.")

    user = request.user if request.user.is_authenticated else None
    # Any chat interaction counts, regardless of what it turns out to be
    # (recommendation, feedback, future intent, or off-topic) - Phase 17
    # decision, 2026-08-30.
    record_event("travel_question_submitted", user=user, request=request)

    # Anonymous conversation memory (ai.memory) is keyed by the Django
    # session, which is otherwise unused for anonymous visitors - force it
    # to exist now rather than waiting for some other write to create it,
    # so the very first message already has a stable key.
    if not request.session.session_key:
        request.session.save()

    # Saved conversations (2026-09-02, direct request) - registered users
    # only; the checkbox itself isn't even rendered for anonymous visitors,
    # but this is enforced server-side too, not just hidden in the UI.
    save_requested = user is not None and request.POST.get("save") == "true"
    conversation_id = _parse_conversation_id(request.POST.get("conversation_id"))
    conversation = None
    history_override = None
    if conversation_id is not None and user is not None:
        conversation = SavedConversation.objects.filter(pk=conversation_id, user=user).first()
        if conversation is None:
            # Stale/foreign id (e.g. deleted from another tab) - fall back
            # to treating this exactly like a fresh, not-yet-saved thread.
            conversation_id = None
        else:
            history_override = conversation.messages[-memory.MAX_HISTORY_MESSAGES :]

    # No explicit ai_provider passed - stream_travel_recommendation resolves
    # its own default lazily, same as before this feature (2026-09-02:
    # record_turn below does the same, for the same reason - constructing
    # a real AIProvider isn't free and isn't always needed, e.g. whenever
    # save_requested is False).
    result = stream_travel_recommendation(
        message,
        user=user,
        session_key=request.session.session_key,
        history_override=history_override,
    )
    if result.recommendations:
        record_event(
            "recommendation_generated",
            user=user,
            request=request,
            metadata={"result_count": len(result.recommendations)},
        )

    def _chunks_with_footers():
        collected = []
        for chunk in result.reply_chunks:
            collected.append(chunk)
            yield chunk
        full_reply = "".join(collected)

        if result.recommendations:
            # result.recommendations is already capped to MAX_RECOMMENDATIONS
            # by ai.orchestration before it ever reaches this view - this
            # slice is a defensive no-op for the current caller, kept so a
            # future caller that doesn't pre-cap still can't flood the UI
            # with cards.
            payload = [
                _recommendation_card_data(r) for r in result.recommendations[:MAX_RECOMMENDATIONS]
            ]
            yield RECOMMENDATIONS_DELIMITER + json.dumps(payload)

        if user is not None:
            # A degraded reply (the AI provider was unreachable, or failed
            # mid-stream) shouldn't be permanently written into the
            # traveler's saved conversation as if it were a real answer -
            # 2026-09-02 review: previously it was, counting toward the
            # conversation's char limit and staying visible on reload.
            # FALLBACK_REPLY appears verbatim (a full failure) or as a
            # suffix (a partial reply before a mid-stream failure); either
            # way, skip saving this turn - the conversation itself already
            # continued normally, this only affects persistence.
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
    exists under this visitor's key - called when they click "New
    conversation" so a genuinely fresh thread doesn't silently inherit
    context from whatever was last discussed under the same key. Works for
    anonymous visitors too (keyed by session), not just registered users -
    conversation *saving* is registered-only, but starting fresh isn't."""
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
    # Structural authorization, same pattern as every trips/users view:
    # only ever fetches the caller's own conversation.
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
