from typing import Literal, NotRequired, TypedDict

from langchain_core.documents import Document

from app.retrieval.filters import LegalFilters
from app.retrieval.plan import QueryPlan, SubQuery

# search: ranked passages. ask: one pass, a cited answer. research: the pass
# is reviewed for what it missed, searched again, and written up as a memo.
Mode = Literal["search", "ask", "research"]


class SubQueryResult(TypedDict):
    """How one sub-query fared, for the trace and the API's plan summary."""

    query: str
    collection: str
    filters: dict
    retrieved: int
    # True when the planner's filters returned too little and the sub-query was
    # re-run without them.
    relaxed: bool
    # Which pass of retrieval ran it: 1 for the plan, 2+ for a review's follow-ups.
    round: int


class GraphState(TypedDict):
    question: str
    # search: ranked passages for review. ask: a grounded answer on top of them.
    mode: Mode
    # The user's own restrictions, from the request. Hard constraints.
    user_filters: LegalFilters
    plan: NotRequired[QueryPlan]
    retrieval: NotRequired[list[SubQueryResult]]
    # What the citation graph and the topic tree contributed, for the trace and the API.
    expansion: NotRequired[dict]
    topics: NotRequired[dict]
    # Research mode: passes of retrieval completed, what the last review found
    # wanting, and the follow-up searches it asked for (consumed by the next pass).
    rounds: NotRequired[int]
    reviews: NotRequired[list[dict]]
    follow_ups: NotRequired[list[SubQuery]]
    documents: list[Document]
    answer: str
    # None until the verifier has judged the answer.
    grounded: bool | None
