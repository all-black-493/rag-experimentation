from typing import Annotated

from fastapi import Depends, Request
from langgraph.graph.state import CompiledStateGraph

from app.config import Settings, get_settings
from app.graph.store import Graph
from app.retrieval.catalog import Catalog


def get_graph(request: Request) -> CompiledStateGraph:
    return request.app.state.graph


def get_catalog(request: Request) -> Catalog:
    return request.app.state.catalog.current()


def get_citation_graph(request: Request) -> Graph:
    return request.app.state.citation_graph


SettingsDep = Annotated[Settings, Depends(get_settings)]
GraphDep = Annotated[CompiledStateGraph, Depends(get_graph)]
CatalogDep = Annotated[Catalog, Depends(get_catalog)]
CitationGraphDep = Annotated[Graph, Depends(get_citation_graph)]
