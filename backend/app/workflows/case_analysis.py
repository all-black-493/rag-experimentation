"""The case analysis workflow: a matter's documents read into a working file."""

import logging
from functools import partial

from langchain_core.language_models import BaseChatModel
from weaviate.client import WeaviateClient

from app.analysis.run import analyse
from app.graph.store import Graph
from app.matters.store import MatterStore
from app.retrieval.run import failure_detail
from app.workflows.runs import WorkflowRun

logger = logging.getLogger(__name__)

NAME = "case-analysis"


def run(
    run: WorkflowRun,
    *,
    store: MatterStore,
    client: WeaviateClient,
    graph: Graph,
    llm: BaseChatModel | None,
    matter_id: str,
) -> None:
    try:
        analysis = analyse(store, client, graph, llm, matter_id, emit=partial(_emit, run))
        run.emit("done", analysis.model_dump(mode="json"))
    except Exception as exc:
        run.emit("error", {"detail": failure_detail(exc)})
        raise
    finally:
        run.finish()


def _emit(run: WorkflowRun, event: str, data: dict) -> None:
    run.emit(event, data)
