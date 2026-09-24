from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph
from weaviate.client import WeaviateClient

from app.caching import TTLCache
from app.config import Settings, get_settings
from app.graph.store import Graph
from app.jobs import JobRegistry
from app.matters.events import MatterEvents
from app.matters.store import MatterStore
from app.retrieval.catalog import Catalog
from app.workflows.runs import WorkflowRuns


def get_graph(request: Request) -> CompiledStateGraph:
    return request.app.state.graph


def get_catalog(request: Request) -> Catalog:
    return request.app.state.catalog.current()


def get_citation_graph(request: Request) -> Graph:
    return request.app.state.citation_graph


def get_client(request: Request) -> WeaviateClient:
    return request.app.state.client


def get_matter_store(request: Request) -> MatterStore:
    return request.app.state.matters


def get_jobs(request: Request) -> JobRegistry:
    return request.app.state.jobs


def get_matter_events(request: Request) -> MatterEvents:
    return request.app.state.matter_events


def get_ingest(request: Request) -> Callable[[str, str], int]:
    """The ingest job for one document: (matter_id, doc_id) -> chunks indexed."""
    return request.app.state.ingest


def get_retrieval_cache(request: Request) -> TTLCache:
    return request.app.state.retrieval_cache


def get_workflow_runs(request: Request) -> WorkflowRuns:
    return request.app.state.workflows


def get_analyst(request: Request) -> BaseChatModel | None:
    """The model that reads a matter's documents; None means the deterministic steps only."""
    return getattr(request.app.state, "analyst", None)


SettingsDep = Annotated[Settings, Depends(get_settings)]
GraphDep = Annotated[CompiledStateGraph, Depends(get_graph)]
CatalogDep = Annotated[Catalog, Depends(get_catalog)]
CitationGraphDep = Annotated[Graph, Depends(get_citation_graph)]
ClientDep = Annotated[WeaviateClient, Depends(get_client)]
MatterStoreDep = Annotated[MatterStore, Depends(get_matter_store)]
MatterEventsDep = Annotated[MatterEvents, Depends(get_matter_events)]
JobsDep = Annotated[JobRegistry, Depends(get_jobs)]
IngestDep = Annotated[Callable[[str, str], int], Depends(get_ingest)]
RetrievalCacheDep = Annotated[TTLCache, Depends(get_retrieval_cache)]
WorkflowRunsDep = Annotated[WorkflowRuns, Depends(get_workflow_runs)]
AnalystDep = Annotated[BaseChatModel | None, Depends(get_analyst)]
