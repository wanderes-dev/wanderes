import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """Django resets the database between tests (transaction rollback) but
    never touches the cache - tests run against the real Redis-backed cache
    (config/settings/test.py doesn't override CACHES, deliberately, to test
    against real infra rather than a substitute). Without this, cache-based
    state (ai.memory conversation history, integrations.climate's caching)
    can leak between tests through key reuse - most visibly for anonymous
    conversation history, which falls back to a fixed key when no session
    exists. Distinct from - and unrelated to - the conftest.py fixture
    attempted and removed during the Phase 15 investigation; that one
    targeted Celery eager-mode config and didn't work. This one has a
    different, narrower job and does work.
    """
    cache.clear()
    yield
    cache.clear()
