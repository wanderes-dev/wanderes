from django.conf import settings
from django.db import models


class SavedConversation(models.Model):
    """A registered user's saved chat conversation - genuinely new,
    permanent, user-owned storage for the `ai` app, unlike the rest of
    this app's modules (provider/orchestration/memory.py), which stay
    model-free per 09_AI_ORCHESTRATION.md §7's "conversation context vs
    persistent memory" split. This is the persistent half of that split,
    for travelers who opt in via the chat page's "save this conversation"
    checkbox - distinct from ai.memory's Redis-backed short-term context,
    which keeps serving every conversation whether or not it's ever saved
    here.

    Free-tier limits (01_PRODUCT_REQUIREMENTS.md §6.2, "Store travel
    history within Free plan limits") - the numbers themselves are a human
    decision, not guessed:
    - at most MAX_CONVERSATIONS_PER_USER saved conversations per user.
    - at most MAX_CHARS characters (summed across every stored message)
      per conversation.
    Enforcement lives in ai.conversations, not here - this model just
    stores the data and the `is_full` flag marking a conversation that
    already crossed MAX_CHARS once, so the one-time "no longer saving"
    notice isn't repeated every turn.

    `messages` mirrors ai.memory's turn shape ({"role", "content"} dicts)
    as a plain JSONField list - consistent with this project's precedent
    for structured-but-not-money/rated list data (Feedback.tags,
    TravelerProfile.preferred_trip_types), not the relational-model
    precedent reserved for money-bearing/ratable data
    (TripFlight/TripAccommodation, per CLAUDE.md). Individual messages are
    never queried, filtered, or rated on their own.
    """

    MAX_CONVERSATIONS_PER_USER = 5
    MAX_CHARS = 50_000

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_conversations"
    )
    subject = models.CharField(max_length=200, blank=True, default="")
    messages = models.JSONField(default=list, blank=True)
    is_full = models.BooleanField(
        default=False,
        help_text=(
            "True once a turn pushed this conversation past MAX_CHARS - further turns "
            "stop being persisted, but the conversation itself keeps working, unsaved."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.subject or f"Conversation {self.pk}"

    def char_count(self) -> int:
        return sum(len(turn.get("content", "")) for turn in self.messages)
