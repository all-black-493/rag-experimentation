from typing import TypedDict

from langchain_core.documents import Document


class GraphState(TypedDict):
    question: str
    tenant: str
    documents: list[Document]
    answer: str
    grounded: bool
