import re
from typing import Annotated

from fastapi import Depends, Header, Request
from langchain_weaviate import WeaviateVectorStore
from langgraph.graph.state import CompiledStateGraph

from app.caching import TTLCache
from app.config import Settings, get_settings
from app.jobs import JobRegistry

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_DEFAULT_TENANT = "default"


def get_vector_store(request: Request) -> WeaviateVectorStore:
    return request.app.state.vector_store


def get_graph(request: Request) -> CompiledStateGraph:
    return request.app.state.graph


def get_retrieval_cache(request: Request) -> TTLCache:
    return request.app.state.retrieval_cache


def get_jobs(request: Request) -> JobRegistry:
    return request.app.state.jobs


def get_tenant(x_session_id: Annotated[str | None, Header()] = None) -> str:
    """Isolates each browser session's documents from every other session's.

    There's no auth - anonymous use is intentional - so this is a client-supplied
    partition key, not a security boundary. A caller that sends someone else's
    session id sees that session's documents; the guarantee is only that two
    sessions that don't share an id never see each other's data by accident.
    """
    if x_session_id and SESSION_ID_PATTERN.match(x_session_id):
        return x_session_id
    return _DEFAULT_TENANT


SettingsDep = Annotated[Settings, Depends(get_settings)]
VectorStoreDep = Annotated[WeaviateVectorStore, Depends(get_vector_store)]
GraphDep = Annotated[CompiledStateGraph, Depends(get_graph)]
RetrievalCacheDep = Annotated[TTLCache, Depends(get_retrieval_cache)]
JobsDep = Annotated[JobRegistry, Depends(get_jobs)]
TenantDep = Annotated[str, Depends(get_tenant)]
