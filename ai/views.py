import json

from django.http import HttpResponseBadRequest, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .orchestration import MAX_EXPLAINED_CANDIDATES, stream_travel_recommendation

MAX_MESSAGE_LENGTH = 2000

# Appended after the streamed reply text so the chat page can offer
# "save as trip" links for the recommended destinations (Phase 13 -
# "Save relevant recommendations") without needing a second endpoint or
# server-side session state. Distinctive enough that real reply text is
# very unlikely to contain it by coincidence.
RECOMMENDATIONS_DELIMITER = "\n<<<TRAVELAGENT_RECOMMENDATIONS>>>\n"


def chat_page(request):
    return render(request, "ai/chat.html")


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
    result = stream_travel_recommendation(message, user=user)

    def _chunks_with_recommendations_footer():
        yield from result.reply_chunks
        if result.recommendations:
            payload = [
                {
                    "slug": r.destination.slug,
                    "name": r.destination.name,
                    "country": r.destination.country,
                }
                for r in result.recommendations[:MAX_EXPLAINED_CANDIDATES]
            ]
            yield RECOMMENDATIONS_DELIMITER + json.dumps(payload)

    return StreamingHttpResponse(
        _chunks_with_recommendations_footer(), content_type="text/plain; charset=utf-8"
    )
