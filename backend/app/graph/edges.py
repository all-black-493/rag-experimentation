from dataclasses import asdict, dataclass

from app.graph.refs import Reference, parties_key
from app.graph.resolve import IndexedDocument, Resolver


@dataclass(frozen=True)
class Edge:
    """One citation, with where it was found and what it points at."""

    source_doc_id: str
    source_collection: str
    source_title: str
    source_url: str
    source_chunk_index: int
    # "cites" a case, "applies" a statute.
    kind: str
    # As written.
    target_ref: str
    # What the reference identifies, normalised: a neutral citation, a case
    # number, or an Act title (plus provision for statutes).
    target_key: str
    provision: str | None
    # Case only: the parties as written, and their lookup key.
    parties: str | None
    parties_key: str | None
    # Resolved against the corpus, or None when the target isn't indexed.
    target_doc_id: str | None
    target_collection: str | None
    target_title: str | None
    target_url: str | None

    def properties(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def edges_for_chunk(
    source: IndexedDocument, chunk_index: int, references: list[Reference], resolver: Resolver
) -> list[Edge]:
    edges = []
    for ref in references:
        target_id = resolver.resolve(ref)
        # A document citing itself - its own neutral citation in its header -
        # is not a relationship.
        if target_id == source.doc_id:
            continue
        target = resolver.by_id.get(target_id) if target_id else None
        edges.append(
            Edge(
                source_doc_id=source.doc_id,
                source_collection=source.collection,
                source_title=source.title,
                source_url=source.url,
                source_chunk_index=chunk_index,
                kind="cites" if ref.kind == "case" else "applies",
                target_ref=ref.text,
                target_key=ref.key,
                provision=ref.provision,
                parties=ref.parties,
                parties_key=parties_key(ref.parties) if ref.parties else None,
                target_doc_id=target_id,
                target_collection=target.collection if target else None,
                target_title=target.title if target else None,
                target_url=target.url if target else None,
            )
        )
    return edges
