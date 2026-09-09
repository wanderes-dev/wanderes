import time
from contextlib import contextmanager

from .services import record_event

# 2026-09-09, analytics/data-engineering pass: latency + success/failure
# instrumentation for AI-provider and external-provider calls. Lives here
# (not in ai/) specifically so integrations.climate can use it too without
# that low-level, dependency-free app having to import the ai app - both
# already depend on analytics.services.record_event directly, so this is
# just as safe a shared dependency.
#
# Deliberately thin: records ONLY latency + success/failure + a coarse
# error_type (exception class name, never a message/stack - see
# _track_call below), never tokens/model/cost. AIProvider.generate_structured_reply
# returns a plain dict (not AIResponse), and AIProvider.stream_reply yields
# raw text chunks - neither exposes token/model data today, so there is
# nothing to capture for the three call sites this module is actually used
# from (ai.orchestration._extract_intent/_extract_climate_budget_signal/
# _stream_ai_reply). See documentation/16_ANALYTICS_ARCHITECTURE.md for the
# documented future path to real token/cost metrics (extending
# AIProvider.stream_reply's contract, and/or instrumenting the one call
# site - ai.conversations._generate_subject - that already gets free
# token data via generate_reply/AIResponse but is deliberately left
# uninstrumented here: low volume, low value).


@contextmanager
def _track_call(event_type: str, *, operation: str, conversation_key: str | None = None):
    """Never suppresses the wrapped call's own exception - always
    re-raises after recording, so callers see exactly the same
    AIProviderError/ClimateProviderError they always did. record_event
    itself never raises (see analytics.services), so a failure recording
    this telemetry can never mask or replace the real error."""
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
