from django.http import HttpResponseBadRequest, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .orchestration import stream_travel_recommendation

MAX_MESSAGE_LENGTH = 2000


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

    return StreamingHttpResponse(result.reply_chunks, content_type="text/plain; charset=utf-8")
