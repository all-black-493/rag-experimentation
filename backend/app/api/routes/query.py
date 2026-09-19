from collections.abc import AsyncIterable

from asyncer import asyncify
from fastapi import APIRouter
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.api.schemas import QueryRequest, QueryResponse
from app.api.streaming import sse_events
from app.dependencies import GraphDep
from app.retrieval.run import QueryOutcome, run_query, stream_query

router = APIRouter(prefix="/query", tags=["query"])


def to_response(outcome: QueryOutcome) -> QueryResponse:
    return QueryResponse(
        mode=outcome.mode,
        question=outcome.question,
        plan=outcome.plan.model_dump() if outcome.plan else None,
        retrieval=outcome.retrieval,
        expansion=outcome.expansion,
        citations=outcome.citations,
        answer=outcome.answer,
        grounded=outcome.grounded,
    )


@router.post("")
async def answer_question(payload: QueryRequest, graph: GraphDep) -> QueryResponse:
    outcome = await asyncify(run_query)(graph, payload.question, payload.mode, payload.to_filters())
    return to_response(outcome)


@router.post("/stream", response_class=EventSourceResponse)
async def stream_answer(payload: QueryRequest, graph: GraphDep) -> AsyncIterable[ServerSentEvent]:
    """The same query as server-sent events: plan, sources, tokens, then done.

    `done` carries the full QueryResponse; everything before it is a preview
    the client may render immediately and must replace when `done` lands.
    """
    events = stream_query(graph, payload.question, payload.mode, payload.to_filters())
    async for event in sse_events(events, finalize=to_response):
        yield event
