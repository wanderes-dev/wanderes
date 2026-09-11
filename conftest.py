import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """Django resets the database between tests (transaction rollback) but
    never touches the cache - tests run against the real Redis-backed
    cache (config/settings/test.py doesn't override CACHES on purpose, to
    exercise real infra rather than a substitute). Without this,
    cache-based state (ai.memory conversation history,
    integrations.climate's caching) can leak between tests through key
    reuse - most visibly for anonymous conversation history, which falls
    back to a fixed key when no session exists.
    """
    cache.clear()
    yield
    cache.clear()
