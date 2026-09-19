"""One query, end to end, under one trace.

Both API routes - the JSON one and the streaming one - run the same graph, apply
the same citation enforcement, and record the same scores on the trace. This
module is that shared path, so the two can never drift apart on what an answer
means.

Everything here is synchronous and self-contained on purpose: the routes hand
it to a worker thread, and the active-observation context is thread-local, so
the root span has to be opened on the same thread the graph nodes run on.
"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from app.retrieval.citations import Citation, build_citations
from app.retrieval.filters import LegalFilters
from app.retrieval.plan import QueryPlan
from app.retrieval.state import GraphState, Mode, SubQueryResult
from app.scoring import citation_coverage, strip_invalid_citations
from app.tracing import build_callback_handler, trace

logger = logging.getLogger(__name__)


@dataclass
class QueryOutcome:
    mode: Mode
    question: str
    plan: QueryPlan | None = None
    retrieval: list[SubQueryResult] = field(default_factory=list)
    expansion: dict | None = None
    topics: dict | None = None
    reviews: list[dict] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    # Ask and research only.
    answer: str | None = None
    grounded: bool | None = None


@dataclass(frozen=True)
class StreamEvent:
    """One server-sent event: `plan`, `sources`, `token`, `done`, `verdict` or `error`.

    `done` carries the answer once it is final; `verdict` follows with the
    groundedness judgment, and withdraws the answer if it failed. Splitting
    them lets the reader start on the answer while the verifier runs, instead
    of staring at a finished answer for three more seconds.
    """

    event: str
    data: Any


def initial_state(question: str, mode: Mode, filters: LegalFilters) -> GraphState:
    return {
        "question": question,
        "mode": mode,
        "user_filters": filters,
        "documents": [],
        "answer": "",
        "grounded": None,
    }


def _finalize(state: GraphState, mode: Mode, question: str, root) -> QueryOutcome:
    """Enforce the citation contract and score the trace.

    A marker pointing past the context is a reference the reader can't check, so
    it is removed before the answer leaves the server - not just measured.
    """
    documents = state["documents"]
    outcome = QueryOutcome(
        mode=mode,
        question=question,
        plan=state.get("plan"),
        retrieval=state.get("retrieval", []),
        expansion=state.get("expansion"),
        topics=state.get("topics"),
        reviews=state.get("reviews", []),
        citations=build_citations(documents),
    )
    metadata: dict = {
        "mode": mode,
        "plan_origin": outcome.plan.origin if outcome.plan else None,
        "sub_queries": len(outcome.plan.sub_queries) if outcome.plan else 0,
        "relaxed": sum(1 for r in outcome.retrieval if r["relaxed"]),
    }

    if mode == "search":
        root.update(output={"passages": len(documents)}, metadata=metadata)
        root.score_trace(name="answered", value=bool(documents), data_type="BOOLEAN")
        return outcome

    answered = bool(documents)
    cleaned, stripped = strip_invalid_citations(state["answer"], len(documents))
    if stripped:
        logger.warning("stripped invalid citation markers %s", stripped)
    outcome.answer = cleaned
    report = citation_coverage(cleaned, len(documents))

    root.update(
        output={"answer": cleaned, "citations": len(documents)},
        metadata={
            **metadata,
            "declined": not answered,
            "cited_indices": report.cited_indices,
            "unused_citations": report.unused_citations,
            "invalid_indices": stripped,
        },
    )
    # Scores rather than metadata: these are the series tracked over time, and
    # Langfuse aggregates scores, not metadata.
    root.score_trace(name="answered", value=answered, data_type="BOOLEAN")
    if answered:
        root.score_trace(name="citation_coverage", value=report.coverage, data_type="NUMERIC")
        # A marker pointing at a citation that doesn't exist is the model
        # inventing a reference, which coverage alone would score as a hit.
        root.score_trace(name="invalid_citations", value=float(len(stripped)), data_type="NUMERIC")
    return outcome


def _score_verdict(state: GraphState, root) -> dict:
    """Record the groundedness verdict on the trace; the event for the client."""
    grounded = bool(state.get("grounded"))
    withdrawn = not grounded
    root.update(metadata={"grounded": grounded})
    root.score_trace(name="grounded", value=grounded, data_type="BOOLEAN")
    return {
        "grounded": grounded,
        "withdrawn": withdrawn,
        # What replaces the answer when it's withdrawn.
        "answer": state["answer"] if withdrawn else None,
    }


def run_query(
    graph: CompiledStateGraph, question: str, mode: Mode, filters: LegalFilters
) -> QueryOutcome:
    with trace(name="rag-query", session_id=mode, input={"question": question}) as root:
        handler = build_callback_handler()
        config = {"callbacks": [handler]} if handler else {}
        try:
            state = graph.invoke(initial_state(question, mode, filters), config=config)
        except Exception:
            # An errored request would otherwise leave a trace with no scores at
            # all, which reads the same as a trace that was never sent.
            root.score_trace(name="failed", value=True, data_type="BOOLEAN")
            raise
        root.score_trace(name="failed", value=False, data_type="BOOLEAN")
        outcome = _finalize(state, mode, question, root)
        # The verifier only runs after an answer was generated; a decline for
        # lack of passages never reaches it and has no verdict to report.
        if state.get("grounded") is not None:
            outcome.grounded = _score_verdict(state, root)["grounded"]
        return outcome


def stream_query(
    graph: CompiledStateGraph, question: str, mode: Mode, filters: LegalFilters
) -> Iterator[StreamEvent]:
    """The same run, surfaced as it happens.

    Node outputs arrive as `updates`; generation tokens as `messages`, filtered
    to the generate node so the planner's and verifier's own model calls don't
    leak into the answer. `done` fires as soon as the answer is final - the
    streamed tokens were a preview, this is authoritative - and `verdict`
    follows once the verifier has judged it.
    """
    with trace(name="rag-query", session_id=mode, input={"question": question}) as root:
        handler = build_callback_handler()
        config = {"callbacks": [handler]} if handler else {}
        state = initial_state(question, mode, filters)
        answered = False
        try:
            for kind, payload in graph.stream(
                state, config=config, stream_mode=["updates", "messages"]
            ):
                if kind == "updates":
                    for node, update in payload.items():
                        state.update(update)
                        if node == "plan":
                            yield StreamEvent("plan", _plan_payload(state))
                        elif node == "rerank":
                            yield StreamEvent(
                                "sources", {"citations": build_citations(state["documents"])}
                            )
                        elif node == "review":
                            yield StreamEvent("review", _review_payload(state))
                        elif node == "generate":
                            answered = True
                            yield StreamEvent("done", _finalize(state, mode, question, root))
                elif kind == "messages":
                    chunk, metadata = payload
                    if metadata.get("langgraph_node") == "generate" and chunk.text:
                        yield StreamEvent("token", {"text": chunk.text})
        except Exception as exc:
            root.score_trace(name="failed", value=True, data_type="BOOLEAN")
            logger.exception("query stream failed")
            yield StreamEvent("error", {"detail": failure_detail(exc)})
            return
        root.score_trace(name="failed", value=False, data_type="BOOLEAN")
        if answered and state.get("grounded") is not None:
            yield StreamEvent("verdict", _score_verdict(state, root))
        elif not answered:
            # Search mode, or a decline before any answer was generated.
            yield StreamEvent("done", _finalize(state, mode, question, root))


def failure_detail(exc: Exception) -> str:
    """What the reader is told. A provider's error carries its own sentence
    inside a JSON body; the sentence is the useful part."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        message = (
            (body.get("error") or {}).get("message")
            if isinstance(body.get("error"), dict)
            else None
        )
        if message:
            return f"The model provider refused the request: {message}"
    return str(exc)


def _plan_payload(state: GraphState) -> dict:
    plan = state.get("plan")
    return {"plan": plan.model_dump() if plan else None}


def _review_payload(state: GraphState) -> dict:
    """The review that just closed a pass: what it found missing, and whether it asked for more."""
    reviews = state.get("reviews", [])
    latest = reviews[-1] if reviews and reviews[-1]["round"] == state.get("rounds") else None
    return {
        "round": state.get("rounds", 1),
        "missing": latest["missing"] if latest else None,
        "follow_ups": latest["follow_ups"] if latest else [],
        "another_pass": bool(state.get("follow_ups")),
    }
