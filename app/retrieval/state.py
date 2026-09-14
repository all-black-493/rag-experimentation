from typing import NotRequired, TypedDict

from langchain_core.documents import Document

from app.retrieval.filters import RetrievalFilters


class GraphState(TypedDict):
    question: str
    tenant: str
    # Optional metadata restriction, applied inside the Weaviate query.
    filters: NotRequired[RetrievalFilters]
    documents: list[Document]
    answer: str
    grounded: bool
