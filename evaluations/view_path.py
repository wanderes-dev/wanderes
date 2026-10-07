"""Drives a conversation through the real /api/v1/recommendations/ view, the
way the chat page does for a signed-in traveler with "Save this
conversation" left on: every turn a POST, the saved conversation's id
picked up from the response footer and sent back from turn 2 on.

That is the path where ai.views hands the orchestration a history_override
and a thread_id, so it's the only way to exercise the saved-conversation
state-ownership logic - ai.orchestration.stream_travel_recommendation()
called directly (what evaluations.conversation_runner's default path does)
never sees any of it.

Nothing here replaces production behavior. The view is called for real; the
only things patched are (a) its call into the orchestration, wrapped so the
evaluation can hand in its own providers and read intent_sink/state_sink
back out, and (b) the provider that writes a new conversation's title, so a
run doesn't pay for a title call it doesn't otherwise make.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest import mock

from django.conf import settings
from django.test import Client
from django.urls import reverse

from ai import orchestration
from ai.provider.base import AIResponse
from ai.views import CONVERSATION_DELIMITER, RECOMMENDATIONS_DELIMITER

_UNSET = object()


class _TitleProvider:
    """Stands in for the provider ai.conversations uses to title a new
    saved conversation."""

    def generate_reply(self, messages, *, max_tokens=None):
        return AIResponse(
            content="Evaluation conversation", model="stub", prompt_tokens=0, completion_tokens=0
        )


@dataclass
class ViewTurn:
    reply: str
    recommendations: list
    intent: dict
    state: dict
    saved: bool
    conversation_id: int | None
    # What the view actually passed to stream_travel_recommendation() -
    # history_override, thread_id and the rest.
    view_kwargs: dict = field(default_factory=dict)
    # The cards the page would render, as the view sent them (including the
    # "Search stays" URL and its caption).
    cards: list = field(default_factory=list)


def _allowed_host() -> str:
    for host in settings.ALLOWED_HOSTS:
        if host and host != "*" and not host.startswith("."):
            return host
    return "localhost"


class ViewSession:
    """One browser tab's conversation, as the chat page's JS drives it."""

    def __init__(self, user, *, ai_provider, climate_provider, save: bool = True):
        self.user = user
        self.ai_provider = ai_provider
        self.climate_provider = climate_provider
        self.save = save
        self.client = Client(HTTP_HOST=_allowed_host())
        if user is not None:  # None = an anonymous visitor, who has no saved conversations
            self.client.force_login(user)
        # The page's currentConversationId: None until a turn has been saved.
        self.conversation_id: int | None = None

    def post(self, message: str, *, conversation_id=_UNSET, save: bool | None = None) -> ViewTurn:
        sent_id = self.conversation_id if conversation_id is _UNSET else conversation_id
        intent_sink: dict = {}
        state_sink: dict = {}
        captured: dict = {}

        def _through_the_orchestration(message, **kwargs):
            captured["kwargs"] = dict(kwargs)
            result = orchestration.stream_travel_recommendation(
                message,
                ai_provider=self.ai_provider,
                climate_provider=self.climate_provider,
                intent_sink=intent_sink,
                state_sink=state_sink,
                **kwargs,
            )
            captured["result"] = result
            return result

        with (
            mock.patch("ai.views.stream_travel_recommendation", _through_the_orchestration),
            mock.patch("ai.conversations.get_ai_provider", return_value=_TitleProvider()),
        ):
            response = self.client.post(
                reverse("ai:recommendations-api"),
                {
                    "message": message,
                    "save": "true" if (self.save if save is None else save) else "false",
                    "conversation_id": "" if sent_id is None else str(sent_id),
                },
            )
            body = b"".join(response.streaming_content).decode()

        footer = {}
        if CONVERSATION_DELIMITER in body:
            footer = json.loads(body.split(CONVERSATION_DELIMITER, 1)[1])
        reply = body.split(RECOMMENDATIONS_DELIMITER, 1)[0].split(CONVERSATION_DELIMITER, 1)[0]

        if footer.get("saved") and footer.get("conversation_id"):
            self.conversation_id = footer["conversation_id"]

        cards = []
        if RECOMMENDATIONS_DELIMITER in body:
            tail = body.split(RECOMMENDATIONS_DELIMITER, 1)[1]
            cards = json.loads(tail.split(CONVERSATION_DELIMITER, 1)[0])

        return ViewTurn(
            reply=reply,
            recommendations=list(captured["result"].recommendations),
            intent=dict(intent_sink),
            state=dict(state_sink),
            saved=bool(footer.get("saved")),
            conversation_id=footer.get("conversation_id"),
            view_kwargs=captured["kwargs"],
            cards=cards,
        )

    def new_conversation(self) -> None:
        """The "New conversation" button: the page forgets its id and calls
        the reset endpoint."""
        self.conversation_id = None
        self.client.post(reverse("ai:conversation-reset"))

    def delete_conversation(self, conversation_id: int) -> None:
        self.client.post(reverse("ai:conversation-delete", args=[conversation_id]))
        if conversation_id == self.conversation_id:
            self.new_conversation()
