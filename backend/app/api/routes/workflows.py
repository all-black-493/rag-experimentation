"""Workflows: work that takes long enough to watch.

A run starts with one request and is followed with another - a stream of the
same events a query sends, replayed from the start for a client that arrives
late. The job is the unit of status; the events are the unit of progress.
"""

from functools import partial

from fastapi import APIRouter, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.api.routes.query import check_matter
from app.api.schemas import QueryRequest, WorkflowAccepted, WorkflowStatus
from app.config import get_settings
from app.dependencies import GraphDep, MatterStoreDep, WorkflowRunsDep
from app.rate_limit import limiter
from app.workflows import research

router = APIRouter(prefix="/workflows", tags=["workflows"])
_research_limit = get_settings().rate_limit_research


@router.post("/research", status_code=202)
@limiter.limit(_research_limit)
async def start_research(
    request: Request,
    payload: QueryRequest,
    graph: GraphDep,
    store: MatterStoreDep,
    runs: WorkflowRunsDep,
) -> WorkflowAccepted:
    """Start a research memo: passes of retrieval, a review between them, a memo at the end."""
    check_matter(payload, store)
    run = runs.start(
        research.NAME,
        payload.question,
        partial(research.run, graph=graph, question=payload.question, filters=payload.to_filters()),
    )
    return WorkflowAccepted(job_id=run.id, workflow=run.workflow, question=run.question)


@router.get("/{job_id}")
async def get_run(job_id: str, runs: WorkflowRunsDep) -> WorkflowStatus:
    run = runs.get(job_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No such run")
    return WorkflowStatus(**run.summary())


@router.get("/{job_id}/events", response_class=EventSourceResponse)
async def follow_run(job_id: str, runs: WorkflowRunsDep):
    """Every event so far, then each new one as it happens; closes when the run ends."""
    run = runs.get(job_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No such run")
    async for item in run.follow():
        yield ServerSentEvent(data=item["data"], event=item["event"])
