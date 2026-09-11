import time
from contextlib import contextmanager

from .services import record_event

# Latency + success/failure instrumentation for AI-provider and external-
# provider calls. Lives here rather than in ai/ so integrations.climate can
# use it too without pulling in the whole ai app - both already depend on
# analytics.services.record_event directly, so this is no riskier a shared
# dependency.
#
# Deliberately thin: records latency + success/failure + a coarse
# error_type (exception class name only, never a message/stack - see
# _track_call below). Nothing about tokens/model/cost, because neither
# AIProvider.generate_structured_reply (plain dict) nor stream_reply (raw
# text chunks) exposes that today - there's nothing to capture at the three
# call sites this is actually used from
# (ai.orchestration._extract_intent/_extract_climate_budget_signal/
# _stream_ai_reply). See documentation/16_ANALYTICS_ARCHITECTURE.md for the
# path to real token/cost metrics later.


@contextmanager
def _track_call(event_type: str, *, operation: str, conversation_key: str | None = None):
    """Never swallows the wrapped call's exception - always re-raises after
    recording, so callers still see the exact AIProviderError/
    ClimateProviderError they always did. record_event itself never raises
    (see analytics.services), so recording this telemetry can't mask or
    replace the real error."""
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        record_event(
            event_type,
            metadata={
                "operation": operation,
                "success": False,
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                "error_type": type(exc).__name__,
            },
            conversation_key=conversation_key,
        )
        raise
    else:
        record_event(
            event_type,
            metadata={
                "operation": operation,
                "success": True,
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            },
            conversation_key=conversation_key,
        )


def track_llm_call(*, operation: str, conversation_key: str | None = None):
    """Wrap one synchronous AI-provider call - e.g.
    ``with track_llm_call(operation="extract_intent", conversation_key=key): ...``"""
    return _track_call(
        "llm_request_completed", operation=operation, conversation_key=conversation_key
    )


def track_provider_call(*, operation: str, conversation_key: str | None = None):
    """Wrap one external (non-AI) provider call, e.g. a climate lookup."""
    return _track_call(
        "provider_request_completed", operation=operation, conversation_key=conversation_key
    )
