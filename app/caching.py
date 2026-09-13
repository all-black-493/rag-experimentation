"""The three caches on the hot paths: embeddings, retrieval, and LLM calls.

Written here rather than pulled from langchain-community (`CacheBackedEmbeddings`,
`LocalFileStore`), which this project deliberately avoids - see the note in
loaders.py about it being sunset upstream.

Tenant scoping is a correctness boundary, not an optimisation. The retrieval
cache keys on the tenant, so one session can never be served another's documents
out of cache. The embedding and LLM caches key on content alone, which is safe:
identical input means identical output regardless of who asked, and neither
stores anything that identifies a session.
"""

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings

logger = logging.getLogger(__name__)

EMBEDDING_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "embeddings"


class CachedEmbeddings(Embeddings):
    """Disk-backed embedding cache keyed by model + exact text.

    Documents are cached on write and queries on read, so re-ingesting a file
    that shares chunks with one already indexed costs nothing, and a repeated
    question skips the query embedding too.

    Keyed on the model name as well as the text: embeddings from different models
    aren't interchangeable, and without it a model change would silently serve
    vectors from the old one.
    """

    def __init__(self, inner: Embeddings, model: str, cache_dir: Path = EMBEDDING_CACHE_DIR):
        self._inner = inner
        self._model = model
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, text: str) -> Path:
        digest = hashlib.sha256(f"{self._model}\x00{text}".encode()).hexdigest()
        # One level of fan-out: a flat directory of a million files is slow to
        # stat on most filesystems.
        bucket = self._dir / digest[:2]
        bucket.mkdir(parents=True, exist_ok=True)
        return bucket / f"{digest}.json"

    def _read(self, text: str) -> list[float] | None:
        path = self._path(text)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _write(self, text: str, vector: list[float]) -> None:
        try:
            self._path(text).write_text(json.dumps(vector))
        except OSError:
            # A cache that can't write is still a working embedder.
            logger.debug("could not cache embedding", exc_info=True)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        cached = [self._read(text) for text in texts]
        missing = [i for i, vector in enumerate(cached) if vector is None]
        if missing:
            fresh = self._inner.embed_documents([texts[i] for i in missing])
            for i, vector in zip(missing, fresh, strict=True):
                cached[i] = vector
                self._write(texts[i], vector)
        logger.info("embedded %d chunk(s), %d from cache", len(texts), len(texts) - len(missing))
        return cached  # type: ignore[return-value]

    def embed_query(self, text: str) -> list[float]:
        vector = self._read(text)
        if vector is not None:
            return vector
        vector = self._inner.embed_query(text)
        self._write(text, vector)
        return vector


class TTLCache:
    """Small thread-safe TTL cache for retrieval results.

    In-memory on purpose: retrieval results are cheap to recompute and go stale
    the moment a tenant ingests anything, so persisting them across restarts
    would mostly serve answers that ignore newly added documents.
    """

    def __init__(self, ttl_seconds: float, max_entries: int = 512):
        self._ttl = ttl_seconds
        self._max = max_entries
        self._entries: dict[str, tuple[float, Any]] = {}
        # Which keys belong to which tenant, so ingesting a document can drop
        # exactly that tenant's stale results.
        self._namespaces: dict[str, set[str]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def key(*parts: Any) -> str:
        return hashlib.sha256("\x00".join(str(p) for p in parts).encode()).hexdigest()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at < time.monotonic():
                del self._entries[key]
                return None
            return value

    def set(self, key: str, value: Any, namespace: str | None = None) -> None:
        with self._lock:
            if len(self._entries) >= self._max:
                # Oldest-expiry first: cheaper than tracking access order, and
                # close enough for a cache this size.
                oldest = min(self._entries, key=lambda k: self._entries[k][0])
                self._forget(oldest)
            self._entries[key] = (time.monotonic() + self._ttl, value)
            if namespace is not None:
                self._namespaces.setdefault(namespace, set()).add(key)

    def _forget(self, key: str) -> None:
        self._entries.pop(key, None)
        for keys in self._namespaces.values():
            keys.discard(key)

    def invalidate_namespace(self, namespace: str) -> None:
        """Drop one tenant's entries.

        Called after that tenant ingests anything: otherwise a question asked
        moments after an upload would be answered from results computed before
        the document existed, and the user is told their own file isn't there.
        """
        with self._lock:
            for key in self._namespaces.pop(namespace, set()):
                self._entries.pop(key, None)

    def invalidate_all(self) -> None:
        with self._lock:
            self._entries.clear()
            self._namespaces.clear()


def enable_llm_cache() -> None:
    """Cache identical prompt -> completion pairs for the process lifetime.

    Keyed on the full prompt, which for this pipeline includes the retrieved
    context, so a hit means the model was asked exactly the same question over
    exactly the same passages.
    """
    from langchain_core.caches import InMemoryCache
    from langchain_core.globals import set_llm_cache

    set_llm_cache(InMemoryCache())
    logger.info("llm cache enabled")
