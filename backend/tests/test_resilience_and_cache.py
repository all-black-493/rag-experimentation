import time

import pytest

from app.caching import CachedEmbeddings, TTLCache
from app.resilience import CircuitBreaker, CircuitOpenError


class CountingEmbeddings:
    """Records how often the real provider was actually asked."""

    def __init__(self):
        self.document_calls = 0
        self.query_calls = 0

    def embed_documents(self, texts):
        self.document_calls += 1
        return [[float(len(t))] for t in texts]

    def embed_query(self, text):
        self.query_calls += 1
        return [float(len(text))]


def test_identical_content_is_not_re_embedded(tmp_path):
    inner = CountingEmbeddings()
    cached = CachedEmbeddings(inner, model="m", cache_dir=tmp_path)

    first = cached.embed_documents(["alpha", "beta"])
    second = cached.embed_documents(["alpha", "beta"])

    assert first == second
    assert inner.document_calls == 1, "second pass should have been served from cache"


def test_only_uncached_texts_reach_the_provider(tmp_path):
    inner = CountingEmbeddings()
    cached = CachedEmbeddings(inner, model="m", cache_dir=tmp_path)

    cached.embed_documents(["alpha"])
    cached.embed_documents(["alpha", "gamma"])

    # Second call embeds only "gamma", but the vectors must still line up
    # positionally with the input texts.
    assert cached.embed_documents(["alpha", "gamma"]) == [[5.0], [5.0]]
    assert inner.document_calls == 2


def test_a_different_model_does_not_reuse_vectors(tmp_path):
    """Vectors from different models aren't interchangeable."""
    inner = CountingEmbeddings()
    CachedEmbeddings(inner, model="old", cache_dir=tmp_path).embed_query("q")
    CachedEmbeddings(inner, model="new", cache_dir=tmp_path).embed_query("q")

    assert inner.query_calls == 2


def test_ttl_cache_expires_entries():
    cache = TTLCache(ttl_seconds=0.05)
    cache.set("k", "v")
    assert cache.get("k") == "v"
    time.sleep(0.08)
    assert cache.get("k") is None


def test_ttl_cache_key_separates_tenants():
    """The tenant is part of the key, so sessions can't read each other's hits."""
    assert TTLCache.key("tenant-a", "q") != TTLCache.key("tenant-b", "q")


def test_ttl_cache_evicts_when_full():
    cache = TTLCache(ttl_seconds=60, max_entries=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.get("c") == 3
    assert sum(cache.get(k) is not None for k in "abc") == 2


def test_breaker_opens_after_threshold_and_fails_fast():
    breaker = CircuitBreaker("x", failure_threshold=2, reset_seconds=60)

    breaker.before_call()
    breaker.record_failure()
    breaker.record_failure()

    assert breaker.is_open
    with pytest.raises(CircuitOpenError):
        breaker.before_call()


def test_success_resets_the_failure_count():
    breaker = CircuitBreaker("x", failure_threshold=2, reset_seconds=60)
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()

    assert not breaker.is_open


def test_breaker_probes_once_after_cooldown():
    breaker = CircuitBreaker("x", failure_threshold=1, reset_seconds=0.05)
    breaker.record_failure()
    assert breaker.is_open

    time.sleep(0.08)
    breaker.before_call()  # half-open probe is allowed through
    breaker.record_success()

    assert not breaker.is_open


def test_ingesting_invalidates_only_that_tenants_entries():
    """Otherwise a question asked right after an upload is answered from results
    computed before the document existed."""
    cache = TTLCache(ttl_seconds=60)
    a_key, b_key = TTLCache.key("a", "q"), TTLCache.key("b", "q")
    cache.set(a_key, ["a-docs"], namespace="a")
    cache.set(b_key, ["b-docs"], namespace="b")

    cache.invalidate_namespace("a")

    assert cache.get(a_key) is None
    assert cache.get(b_key) == ["b-docs"]
