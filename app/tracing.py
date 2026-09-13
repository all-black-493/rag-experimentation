"""Langfuse tracing for the retrieval pipeline.

Every helper degrades to a no-op when Langfuse credentials are absent, so local
runs and the test suite never need a Langfuse project - `observation()` still
yields something with `.update()`, callers never branch on whether tracing is on.

The LangChain callback handler covers the two LLM calls (prompt, response, model,
token usage) automatically. Retrieval and reranking aren't LangChain components -
they call Weaviate and Cohere directly - so those get explicit observations in
`app/retrieval/graph.py`.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)

_client: Any = None


class _NoopObservation:
    """Stand-in so tracing-off callers can still call .update() unconditionally."""

    def update(self, **kwargs: Any) -> None:
        return None

    def score_trace(self, **kwargs: Any) -> None:
        return None


def configure_tracing(settings: Settings) -> None:
    """Initialise the Langfuse client, or leave tracing off if keys are missing."""
    global _client

    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        logger.info("langfuse keys absent - tracing disabled")
        return

    from langfuse import Langfuse

    _client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_base_url,
        # Without an environment, dev and prod traffic pile into one undifferentiated
        # trace list with no way to filter between them.
        environment=settings.langfuse_environment,
    )
    logger.info(
        "langfuse tracing enabled (%s, env=%s)",
        settings.langfuse_base_url,
        settings.langfuse_environment,
    )


def shutdown_tracing() -> None:
    """Flush buffered spans. Without this, a short-lived process loses its traces."""
    if _client is not None:
        _client.flush()


def tracing_enabled() -> bool:
    return _client is not None


def get_client() -> Any:
    return _client


@contextmanager
def linked_prompt(name: str) -> Iterator[None]:
    """Attach the Langfuse prompt version to generations created in this block.

    This is what lets Langfuse group latency, cost and scores by prompt version,
    so a quality regression can be pinned to the prompt that shipped it. The
    prompt is fetched by label rather than version - the SDK caches it, and
    `app/prompt_sync.py` keeps the `production` label pointing at whatever is in
    prompts/*.yaml on main.

    A failure here must never break a query: an unreachable Langfuse, or a prompt
    that was never synced, degrades to an unlinked (but still traced) generation.
    """
    if _client is None:
        yield
        return

    try:
        from langfuse import propagate_attributes

        prompt = _client.get_prompt(name, label="production")
    except Exception:  # tracing is never worth failing a request for
        logger.debug("no langfuse prompt to link for %s", name, exc_info=True)
        yield
        return

    with propagate_attributes(prompt=prompt):
        yield


def build_callback_handler() -> Any | None:
    """A LangChain callback handler bound to the current trace, or None when off.

    Passed to `graph.invoke(config={"callbacks": [...]})`; LangGraph hands it down
    to every nested LLM call, which is where model name and token usage come from.
    """
    if _client is None:
        return None

    from langfuse.langchain import CallbackHandler

    return CallbackHandler()


@contextmanager
def observation(*, as_type: str, name: str, **kwargs: Any) -> Iterator[Any]:
    """Nest one observation under the currently active trace."""
    if _client is None:
        yield _NoopObservation()
        return

    with _client.start_as_current_observation(as_type=as_type, name=name, **kwargs) as obs:
        yield obs


@contextmanager
def trace(*, name: str, session_id: str, **kwargs: Any) -> Iterator[Any]:
    """Root span for one request, grouped into a Langfuse session by tenant.

    Must be entered on the same thread the graph runs on: the active observation
    lives in OpenTelemetry's context, which is thread-local, so a root opened on
    the event loop wouldn't be found by nodes running in the worker thread.
    """
    if _client is None:
        yield _NoopObservation()
        return

    from langfuse import propagate_attributes

    with (
        _client.start_as_current_observation(as_type="span", name=name, **kwargs) as root,
        propagate_attributes(session_id=session_id),
    ):
        yield root
