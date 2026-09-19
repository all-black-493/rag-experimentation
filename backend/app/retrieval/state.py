from typing import Literal, NotRequired, TypedDict

from langchain_core.documents import Document

from app.retrieval.filters import LegalFilters
from app.retrieval.plan import QueryPlan

Mode = Literal["search", "ask"]


class SubQueryResult(TypedDict):
    """How one sub-query fared, for the trace and the API's plan summary."""

    query: str
    collection: str
    filters: dict
    retrieved: int
    # True when the planner's filters returned too little and the sub-query was
    # re-run without them.
    relaxed: bool


class GraphState(TypedDict):
    question: str
    # search: ranked passages for review. ask: a grounded answer on top of them.
    mode: Mode
    # The user's own restrictions, from the request. Hard constraints.
    user_filters: LegalFilters
    plan: NotRequired[QueryPlan]
    retrieval: NotRequired[list[SubQueryResult]]
    documents: list[Document]
    answer: str
    grounded: bool
