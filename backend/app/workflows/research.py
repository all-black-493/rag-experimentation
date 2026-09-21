"""The research memo workflow: the retrieval graph in research mode, as a run.

It owns no retrieval logic. It runs the same graph a query does - plan,
retrieve, expand, rerank, then review → retrieve again while a review asks for
more, then the memo and its verification - and relays each event into the
run's log, where a client follows it. The events are the ones `/query/stream`
sends, plus `review` after each pass.
"""

import logging

from langgraph.graph.state import CompiledStateGraph

from app.api.schemas import QueryResponse
from app.retrieval.filters import LegalFilters
from app.retrieval.run import stream_query
from app.workflows.runs import WorkflowRun

logger = logging.getLogger(__name__)

NAME = "research"


def run(run: WorkflowRun, graph: CompiledStateGraph, question: str, filters: LegalFilters) -> None:
    try:
        for event in stream_query(graph, question, "research", filters):
            data = event.data
            if event.event == "done":
                data = QueryResponse.from_outcome(data).model_dump(mode="json")
            run.emit(event.event, data)
            if event.event == "error":
                # The stream reports the failure to its followers; the job records it.
                raise RuntimeError(data["detail"])
    finally:
        run.finish()
