from typing import Annotated

from fastapi import Depends, Request
from langgraph.graph.state import CompiledStateGraph

from app.config import Settings, get_settings
from app.retrieval.catalog import Catalog


def get_graph(request: Request) -> CompiledStateGraph:
    return request.app.state.graph


def get_catalog(request: Request) -> Catalog:
    return request.app.state.catalog.current()


SettingsDep = Annotated[Settings, Depends(get_settings)]
GraphDep = Annotated[CompiledStateGraph, Depends(get_graph)]
CatalogDep = Annotated[Catalog, Depends(get_catalog)]
