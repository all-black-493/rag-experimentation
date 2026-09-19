from collections.abc import AsyncIterable

from asyncer import asyncify
from fastapi import APIRouter, HTTPException
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.api.schemas import QueryRequest, QueryResponse
from app.api.streaming import sse_events
from app.dependencies import GraphDep, MatterStoreDep
from app.matters.store import MatterStore
from app.retrieval.run import run_query, stream_query

router = APIRouter(prefix="/query", tags=["query"])


def check_matter(payload: QueryRequest, store: MatterStore) -> None:
    """A matter named in a query must exist: a stale id is a client mistake, not a 500."""
    if payload.matter_id is not None and store.get(payload.matter_id) is None:
        raise HTTPException(status_code=404, detail="No such matter")


@router.post("")
async def answer_question(
    payload: QueryRequest, graph: GraphDep, store: MatterStoreDep
) -> QueryResponse:
    check_matter(payload, store)
    outcome = await asyncify(run_query)(graph, payload.question, payload.mode, payload.to_filters())
    return QueryResponse.from_outcome(outcome)


@router.post("/stream", response_class=EventSourceResponse)
async def stream_answer(
    payload: QueryRequest, graph: GraphDep, store: MatterStoreDep
) -> AsyncIterable[ServerSentEvent]:
    """The same query as server-sent events: plan, sources, tokens, then done.

    `done` carries the full QueryResponse; everything before it is a preview
    the client may render immediately and must replace when `done` lands.
    """
    check_matter(payload, store)
    events = stream_query(graph, payload.question, payload.mode, payload.to_filters())
    async for event in sse_events(events, finalize=QueryResponse.from_outcome):
        yield event
