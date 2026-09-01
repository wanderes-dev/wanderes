import logging
from dataclasses import dataclass

from .models import SavedConversation
from .provider import AIMessage, AIProvider, AIProviderError, get_ai_provider

logger = logging.getLogger(__name__)

SUBJECT_MAX_LENGTH = 60

# Reasons record_turn() reports to the caller so the chat page can show a
# one-time explanatory modal - never anything that blocks the conversation
# itself, only whether *this* turn got persisted.
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
    """Persist one (user, assistant) turn, enforcing the two Free-tier
    limits on SavedConversation - decided directly by the user, 2026-09-02,
    not guessed by Claude Code (CLAUDE.md rule 2 reserves the actual
    pricing/plan boundaries for the human; only these specific numbers were
    supplied directly in that request).

    `conversation` is the already-resolved SavedConversation this turn
    should continue (or None for a not-yet-saved/brand-new conversation) -
    resolved by the caller (the view), which also needs it to build the
    conversation's history for the AI call before this function ever runs,
    so there is no reason to look it up a second time here.

    `ai_provider` defaults to None and is only ever actually resolved (via
    get_ai_provider()) deep inside _append_turn, and only when a NEW
    conversation needs a subject generated - i.e. never for the very
    common case of an unsaved/bypassed turn (save_requested=False, the
    overwhelming majority of calls into this function). Constructing a
    real AIProvider eagerly here, on every call regardless of whether it's
    needed, would require OPENAI_API_KEY to be configured just to run a
    request that never touches the AI provider at all - true today of
    CI/most tests, and needlessly wasteful even outside them.

    Saving is entirely opt-in (`save_requested`, from the chat page's
    checkbox - always unchecked here for anonymous users, since this whole
    feature is registered-users-only) and never blocks the conversation
    itself - every branch below still lets the chat continue; it only ever
    decides whether *this* turn gets written to Postgres.
    """
    if not save_requested or user is None or not getattr(user, "is_authenticated", False):
        return SaveResult(saved=False, conversation_id=None, subject=None, reason=None)

    if conversation is not None:
        if conversation.is_full:
            # Already warned once, the turn this crossed MAX_CHARS on -
            # stay quiet from here on, exactly like the checkbox being off.
            return SaveResult(
                saved=False, conversation_id=conversation.pk, subject=None, reason=None
            )
        return _append_turn(
            conversation, user_message, assistant_reply, ai_provider=ai_provider, is_new=False
        )

    # No conversation to continue - this turn is starting a new one.
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
    conversation.messages.append({"role": "assistant", "content": assistant_reply})

    # Only ever True on the exact turn that pushes the total over MAX_CHARS
    # - record_turn() already returned early above for a conversation that
    # was already full, so this is genuinely the first time it happens.
    just_crossed_limit = conversation.char_count() > SavedConversation.MAX_CHARS
    if just_crossed_limit:
        conversation.is_full = True

    generated_subject = None
    if is_new:
        # Lazily resolved - see record_turn's docstring for why this isn't
        # constructed any earlier than strictly necessary.
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
    """One small, non-streaming AI call per NEW saved conversation (never
    per message) - names the thread from its opening exchange, the way a
    ChatGPT-style sidebar entry gets its title. Falls back to a plain
    truncation of the traveler's own first message if the call fails, so
    saving a conversation never hard-fails just because titling did."""
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
