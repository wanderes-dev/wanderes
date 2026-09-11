import logging
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction

from .memory import sanitize_reply_for_context
from .models import SavedConversation
from .provider import AIMessage, AIProvider, AIProviderError, get_ai_provider

logger = logging.getLogger(__name__)

SUBJECT_MAX_LENGTH = 60

# record_turn()'s reason codes, surfaced to the chat page for a one-time
# explanatory modal - never blocks the conversation, just says whether
# this particular turn got saved.
REASON_CONVERSATION_LIMIT_REACHED = "conversation_limit_reached"
REASON_SIZE_LIMIT_EXCEEDED = "size_limit_exceeded"


@dataclass(frozen=True)
class SaveResult:
    saved: bool
    conversation_id: int | None
    subject: str | None
    reason: str | None


def record_turn(
    *,
    user,
    conversation: SavedConversation | None,
    save_requested: bool,
    user_message: str,
    assistant_reply: str,
    ai_provider: AIProvider | None = None,
) -> SaveResult:
    """Persist one (user, assistant) turn, enforcing SavedConversation's
    Free-tier limits (those numbers came from the user, not a guess here).

    `conversation` is whichever SavedConversation this turn continues, or
    None for a brand-new one - the caller already resolved it to build the
    AI call's history, so no need to look it up again here.

    `ai_provider` stays unresolved until _append_turn actually needs one
    (only for a new conversation's title) - building a real provider on
    every call would require an API key even for the common case where
    nothing gets saved at all.

    Saving is opt-in (the chat page's checkbox, always off for anonymous
    visitors) and never blocks the conversation - every path below still
    lets the chat continue, this only decides whether the turn gets
    written to Postgres. Never raises either, same as
    analytics.services.record_event(): a failure here just means "not
    saved," not a broken reply that's already been shown to the traveler.
    """
    if not save_requested or user is None or not getattr(user, "is_authenticated", False):
        return SaveResult(saved=False, conversation_id=None, subject=None, reason=None)

    try:
        return _record_turn(
            user=user,
            conversation=conversation,
            user_message=user_message,
            assistant_reply=assistant_reply,
            ai_provider=ai_provider,
        )
    except Exception:
        logger.warning("Failed to save a chat turn to a SavedConversation.", exc_info=True)
        return SaveResult(
            saved=False,
            conversation_id=conversation.pk if conversation is not None else None,
            subject=None,
            reason=None,
        )


def _record_turn(
    *,
    user,
    conversation: SavedConversation | None,
    user_message: str,
    assistant_reply: str,
    ai_provider: AIProvider | None,
) -> SaveResult:
    if conversation is not None:
        if conversation.is_full:
            # We already warned once, on the turn that crossed MAX_CHARS.
            # Stay quiet after that.
            return SaveResult(
                saved=False, conversation_id=conversation.pk, subject=None, reason=None
            )
        return _append_turn(
            conversation, user_message, assistant_reply, ai_provider=ai_provider, is_new=False
        )

    # Starting a new conversation. Locking the user row here stops two
    # near-simultaneous requests (two open tabs, say) from both reading the
    # same count and both squeaking past the cap. Kept narrow - just the
    # count-check-and-create - since _append_turn below can make a real
    # network call (title generation) that shouldn't sit behind a row lock.
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        existing_count = SavedConversation.objects.filter(user=user).count()
        if existing_count >= SavedConversation.MAX_CONVERSATIONS_PER_USER:
            return SaveResult(
                saved=False,
                conversation_id=None,
                subject=None,
                reason=REASON_CONVERSATION_LIMIT_REACHED,
            )
        new_conversation = SavedConversation.objects.create(user=user)

    return _append_turn(
        new_conversation, user_message, assistant_reply, ai_provider=ai_provider, is_new=True
    )


def _append_turn(
    conversation: SavedConversation,
    user_message: str,
    assistant_reply: str,
    *,
    ai_provider: AIProvider | None,
    is_new: bool,
) -> SaveResult:
    conversation.messages.append({"role": "user", "content": user_message})
    conversation.messages.append(
        {"role": "assistant", "content": sanitize_reply_for_context(assistant_reply)}
    )

    # True only on the turn that actually pushes us over MAX_CHARS -
    # record_turn() already bailed early for a conversation that was
    # already full.
    just_crossed_limit = conversation.char_count() > SavedConversation.MAX_CHARS
    if just_crossed_limit:
        conversation.is_full = True

    generated_subject = None
    if is_new:
        # See record_turn's docstring - this is deliberately lazy.
        provider = ai_provider or get_ai_provider()
        generated_subject = _generate_subject(user_message, assistant_reply, ai_provider=provider)
        conversation.subject = generated_subject

    conversation.save(update_fields=["messages", "subject", "is_full", "updated_at"])

    return SaveResult(
        saved=True,
        conversation_id=conversation.pk,
        subject=generated_subject,
        reason=REASON_SIZE_LIMIT_EXCEEDED if just_crossed_limit else None,
    )


def _generate_subject(user_message: str, assistant_reply: str, *, ai_provider: AIProvider) -> str:
    """One small AI call per new saved conversation (not per message) -
    titles the thread from its opening exchange, sidebar-style. Falls back
    to truncating the traveler's own message if the call fails - a bad
    title beats a failed save."""
    messages = [
        AIMessage(
            role="system",
            content=(
                "You write short conversation titles, like a chat app's "
                "thread name in a sidebar. Reply with ONLY the title "
                "itself - no quotes, no punctuation at the end, no "
                "explanation - 3 to 6 words. Write the title in whatever "
                "language the traveler's own message below is written in "
                "- judge this strictly from the traveler's actual "
                "sentence, never from a destination or country name "
                "mentioned in it or in the assistant's reply (a place "
                "name is not a language signal - an English sentence "
                "that mentions 'Thailand' still gets an English title)."
            ),
        ),
        AIMessage(
            role="user",
            content=(
                f'Traveler: "{user_message}"\n'
                f'Assistant: "{assistant_reply[:400]}"\n\n'
                "Title this conversation."
            ),
        ),
    ]
    subject = ""
    try:
        subject = ai_provider.generate_reply(messages, max_tokens=20).content.strip()
    except AIProviderError:
        logger.warning("Could not generate a conversation subject - using a fallback title.")
    if not subject:
        subject = user_message.strip()
    return subject[:SUBJECT_MAX_LENGTH]
