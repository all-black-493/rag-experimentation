"""The law a matter's documents cite: deterministic, and the first thing a lawyer wants.

Every Act and case named in the documents, where it was named, whether the
corpus holds it, and - through the citation graph - how many judgments in the
corpus have applied it. No model call: the citations are written in a form
the graph's extractor already reads, and a bare Act name is taken too, since
a letter cites "the Distress for Rent Act" without a section.
"""

from langchain_core.documents import Document

from app.analysis.models import Authority
from app.analysis.resolve import CorpusResolver
from app.analysis.sources import SourceBook
from app.graph.refs import Reference, extract_references
from app.graph.store import Graph


def find_authorities(
    chunks_by_document: dict[str, list[Document]],
    resolver: CorpusResolver,
    graph: Graph,
    book: SourceBook,
) -> list[Authority]:
    found: dict[tuple, tuple[Reference, list[Document]]] = {}
    for chunks in chunks_by_document.values():
        for chunk in chunks:
            for ref in extract_references(chunk.page_content, bare_acts=True):
                signature = (ref.kind, ref.key.lower(), ref.provision)
                entry = found.setdefault(signature, (ref, []))
                entry[1].append(chunk)

    authorities = []
    for ref, passages in found.values():
        resolved = resolver.resolve(ref)
        authorities.append(
            Authority(
                ref=ref.text,
                kind=ref.kind,
                key=ref.key,
                provision=ref.provision,
                doc_id=resolved.doc_id if resolved else None,
                title=resolved.title if resolved else None,
                url=resolved.url if resolved else None,
                applied_by=_applied_by(graph, ref, resolved.doc_id if resolved else None),
                sources=[book.index_of(p) for p in passages],
            )
        )
    # Statutes first, then cases; each by how much the corpus has to say about it.
    return sorted(authorities, key=lambda a: (a.kind != "statute", -a.applied_by, a.ref))


def _applied_by(graph: Graph, ref: Reference, doc_id: str | None) -> int:
    citing = {n.via_doc_id for n in graph.citing_passages(ref.key, ref.provision)}
    if doc_id:
        citing |= {n.doc_id for n in graph.cited_by.get(doc_id, []) if n.doc_id}
    return len(citing)
