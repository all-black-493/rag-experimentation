"""Circuit breaker for outbound provider calls.

Retries handle a blip. They make a sustained outage worse: every request pays the
full retry budget before failing, so workers pile up waiting on a provider that
is already known to be down. The breaker short-circuits that - after enough
consecutive failures it fails immediately for a cooldown, then lets a single
request through to test recovery.

Applied to reranking, where failing fast is genuinely better than waiting: the
pipeline can fall back to the retriever's own ordering and still answer. It is
deliberately *not* applied to generation, where there is no meaningful degraded
answer to serve.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)


class CircuitOpenError(RuntimeError):
    """Raised instead of calling a provider that is currently considered down."""


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int, reset_seconds: float):
        self._name = name
        self._threshold = failure_threshold
        self._reset = reset_seconds
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._opened_at is not None and not self._cooldown_elapsed()

    def _cooldown_elapsed(self) -> bool:
        return self._opened_at is not None and time.monotonic() - self._opened_at >= self._reset

    def before_call(self) -> None:
        with self._lock:
            if self._opened_at is None:
                return
            if self._cooldown_elapsed():
                # Half-open: allow this one through. A success closes the
                # breaker, a failure re-opens it for another cooldown.
                logger.info("circuit %s half-open, probing", self._name)
                self._opened_at = None
                self._failures = self._threshold - 1
                return
            raise CircuitOpenError(f"{self._name} circuit is open")

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold and self._opened_at is None:
                self._opened_at = time.monotonic()
                logger.warning(
                    "circuit %s opened after %d consecutive failures", self._name, self._failures
                )
