"""Resolve a citation found in a matter's document against the corpus.

The graph build resolves against every title at once; here a handful of
references arrive at a time, so each is looked up by its title or number
with a keyword query and matched exactly by the same rules the graph uses.
"""

from weaviate.client import WeaviateClient

from app.graph.refs import Reference
from app.graph.resolve import IndexedDocument, Resolver
from app.metadata import CLASS_NAMES

_CANDIDATES = 20


class CorpusResolver:
    def __init__(self, client: WeaviateClient):
        self._client = client

    def resolve(self, reference: Reference) -> IndexedDocument | None:
        collection = "case_law" if reference.kind == "case" else "legislation"
        query = reference.parties or reference.text if reference.kind == "case" else reference.key
        handle = self._client.collections.use(CLASS_NAMES[collection])
        response = handle.query.bm25(
            query,
            query_properties=["title"],
            limit=_CANDIDATES,
            return_properties=["doc_id", "title", "url"],
        )
        candidates: dict[str, IndexedDocument] = {}
        for obj in response.objects:
            p = obj.properties
            candidates.setdefault(
                p["doc_id"], IndexedDocument(p["doc_id"], collection, p["title"], p["url"])
            )
        if not candidates:
            return None
        resolver = Resolver(list(candidates.values()))
        doc_id = resolver.resolve(reference)
        return resolver.by_id.get(doc_id) if doc_id else None
