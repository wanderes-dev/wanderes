import json

from django.http import HttpResponseBadRequest, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from analytics.services import record_event

from .orchestration import MAX_EXPLAINED_CANDIDATES, stream_travel_recommendation

MAX_MESSAGE_LENGTH = 2000

# Appended after the streamed reply text so the chat page can offer
# "save as trip" links for the recommended destinations (Phase 13 -
# "Save relevant recommendations") without needing a second endpoint or
# server-side session state. Distinctive enough that real reply text is
# very unlikely to contain it by coincidence.
RECOMMENDATIONS_DELIMITER = "\n<<<WANDERES_RECOMMENDATIONS>>>\n"


def chat_page(request):
    return render(request, "ai/chat.html")


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

    result = stream_travel_recommendation(
        message, user=user, session_key=request.session.session_key
    )
    if result.recommendations:
        record_event(
            "recommendation_generated",
            user=user,
            request=request,
            metadata={"result_count": len(result.recommendations)},
        )

    def _chunks_with_recommendations_footer():
        yield from result.reply_chunks
        if result.recommendations:
            payload = [
                _recommendation_card_data(r)
                for r in result.recommendations[:MAX_EXPLAINED_CANDIDATES]
            ]
            yield RECOMMENDATIONS_DELIMITER + json.dumps(payload)

    return StreamingHttpResponse(
        _chunks_with_recommendations_footer(), content_type="text/plain; charset=utf-8"
    )
