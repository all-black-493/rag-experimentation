from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from app.api.schemas import GraphNeighbourhood
from app.dependencies import CitationGraphDep
from app.graph.store import group_by_document

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/{doc_id}")
async def neighbourhood(doc_id: str, graph: CitationGraphDep) -> GraphNeighbourhood:
    """What a document cites and what cites it, one row per document.

    Unresolved targets - authorities the corpus doesn't hold - are listed too,
    with `doc_id` null: a lawyer wants to know what was cited either way.
    """
    cites = graph.cites.get(doc_id, [])
    cited_by = graph.cited_by.get(doc_id, [])
    if not cites and not cited_by:
        raise HTTPException(status_code=404, detail="No citations recorded for this document")
    # Judgments before Acts in both directions: what was cited, in the order
    # the document reached it; who cited it, by name.
    cites_links = sorted(group_by_document(cites), key=lambda link: link.kind != "cites")
    cited_by_links = sorted(
        group_by_document(cited_by),
        key=lambda link: (link.collection != "case_law", link.title or ""),
    )
    return GraphNeighbourhood(
        doc_id=doc_id,
        cites=[asdict(link) for link in cites_links],
        cited_by=[asdict(link) for link in cited_by_links],
    )
