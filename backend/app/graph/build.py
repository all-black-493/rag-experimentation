"""Build the citation graph from the indexed corpus.

    uv run python -m app.graph.build

Reads every chunk already in Weaviate, extracts the citations it contains,
resolves them against the corpus's own titles, and replaces the `Citation`
collection. Derived data, rebuilt whole: a few minutes, no model calls.
"""

import argparse
import json
import logging
import sys
from collections import Counter

from weaviate.client import WeaviateClient

from app.config import get_settings
from app.graph.edges import Edge, edges_for_chunk
from app.graph.refs import extract_references
from app.graph.resolve import IndexedDocument, Resolver
from app.graph.store import replace_edges
from app.metadata import CLASS_NAMES, COLLECTIONS
from app.vectorstore.client import weaviate_client

logger = logging.getLogger(__name__)


def index_documents(client: WeaviateClient) -> tuple[list[IndexedDocument], list[dict]]:
    """Every chunk's text and provenance, plus one entry per document."""
    documents: dict[str, IndexedDocument] = {}
    chunks: list[dict] = []
    for collection in COLLECTIONS:
        handle = client.collections.use(CLASS_NAMES[collection])
        for obj in handle.iterator(
            return_properties=["doc_id", "title", "url", "chunk_index", "text"]
        ):
            p = obj.properties
            documents.setdefault(
                p["doc_id"], IndexedDocument(p["doc_id"], collection, p["title"], p["url"])
            )
            chunks.append(
                {"doc_id": p["doc_id"], "chunk_index": p["chunk_index"], "text": p["text"]}
            )
    return list(documents.values()), chunks


def build(client: WeaviateClient) -> dict:
    documents, chunks = index_documents(client)
    resolver = Resolver(documents)

    edges: list[Edge] = []
    for chunk in chunks:
        references = extract_references(chunk["text"])
        if references:
            source = resolver.by_id[chunk["doc_id"]]
            edges.extend(edges_for_chunk(source, chunk["chunk_index"], references, resolver))

    # One edge per (source, target key, provision): a case that cites the same
    # authority in ten passages is one relationship, kept at its first mention.
    unique: dict[tuple, Edge] = {}
    for e in edges:
        unique.setdefault((e.source_doc_id, e.target_key, e.provision), e)
    edges = list(unique.values())

    written = replace_edges(client, edges)
    resolved = [e for e in edges if e.target_doc_id]
    cited = Counter(e.target_title for e in resolved)
    return {
        "documents": len(documents),
        "chunks_scanned": len(chunks),
        "edges": written,
        "resolved": len(resolved),
        "cites": sum(1 for e in edges if e.kind == "cites"),
        "applies": sum(1 for e in edges if e.kind == "applies"),
        "most_cited": cited.most_common(8),
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    with weaviate_client(get_settings()) as client:
        summary = build(client)
    print(json.dumps(summary, indent=2), file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
