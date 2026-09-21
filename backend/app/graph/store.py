"""Edges in Weaviate, and the in-memory graph the request path reads.

Weaviate holds the edges so they survive restarts and can be rebuilt in one
place; the adjacency the retrieval graph consults is loaded from there at
startup. Tens of thousands of edges fit in memory comfortably, and a lookup
during a request must cost microseconds, not a round trip.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from weaviate.classes.config import Configure, DataType, Property, Tokenization
from weaviate.classes.data import DataObject
from weaviate.client import WeaviateClient

from app.graph.edges import Edge

CLASS_NAME = "Citation"

_KEYWORD = {"tokenization": Tokenization.FIELD, "index_searchable": False}

_PROPERTIES = [
    Property(name="source_doc_id", data_type=DataType.TEXT, **_KEYWORD),
    Property(name="source_collection", data_type=DataType.TEXT, **_KEYWORD),
    Property(name="source_title", data_type=DataType.TEXT, index_searchable=False),
    Property(name="source_url", data_type=DataType.TEXT, **_KEYWORD),
    Property(name="source_chunk_index", data_type=DataType.INT),
    Property(name="kind", data_type=DataType.TEXT, **_KEYWORD),
    Property(name="target_ref", data_type=DataType.TEXT, index_searchable=False),
    Property(name="target_key", data_type=DataType.TEXT, **_KEYWORD),
    Property(name="provision", data_type=DataType.TEXT, **_KEYWORD),
    Property(name="parties", data_type=DataType.TEXT, index_searchable=False),
    Property(name="parties_key", data_type=DataType.TEXT, **_KEYWORD),
    Property(name="target_doc_id", data_type=DataType.TEXT, **_KEYWORD),
    Property(name="target_collection", data_type=DataType.TEXT, **_KEYWORD),
    Property(name="target_title", data_type=DataType.TEXT, index_searchable=False),
    Property(name="target_url", data_type=DataType.TEXT, **_KEYWORD),
]

_BATCH = 500


def ensure_citation_collection(client: WeaviateClient) -> bool:
    """Create the edge collection if missing. Returns whether it was created."""
    if client.collections.exists(CLASS_NAME):
        return False
    # No vectors: edges are looked up by key, never searched semantically.
    client.collections.create(
        name=CLASS_NAME, vector_config=Configure.Vectors.self_provided(), properties=_PROPERTIES
    )
    return True


def replace_edges(client: WeaviateClient, edges: list[Edge]) -> int:
    """Rebuild the collection from scratch. Derived data: cheap to redo, hard to patch."""
    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)
    ensure_citation_collection(client)
    handle = client.collections.use(CLASS_NAME)
    for start in range(0, len(edges), _BATCH):
        result = handle.data.insert_many(
            [DataObject(properties=e.properties()) for e in edges[start : start + _BATCH]]
        )
        if result.has_errors:
            first = next(iter(result.errors.values()))
            raise RuntimeError(f"citation insert failed: {first.message}")
    return len(edges)


@dataclass(frozen=True)
class Neighbour:
    """One document at the far end of an edge, with the passage that made the link."""

    doc_id: str | None
    collection: str | None
    title: str | None
    url: str | None
    # What the citing passage wrote, and where it is.
    ref: str
    kind: str
    provision: str | None
    parties: str | None
    via_doc_id: str
    via_chunk_index: int


@dataclass
class Graph:
    """Adjacency by document, and citing passages by what they cite.

    The second index is the one relationship questions use. Most authorities
    judgments cite are not themselves in the corpus, so `cited_by` by doc_id
    would be nearly empty - but the citing passages are indexed, and "which
    cases have applied X" is answered by looking X up as a key.
    """

    cites: dict[str, list[Neighbour]] = field(default_factory=lambda: defaultdict(list))
    cited_by: dict[str, list[Neighbour]] = field(default_factory=lambda: defaultdict(list))
    # Citing passages by normalised target: a neutral citation, a case number,
    # party names, or an Act title (with the provision under a second key).
    citing: dict[str, list[Neighbour]] = field(default_factory=lambda: defaultdict(list))
    edges: int = 0

    def add(self, e: dict) -> None:
        self.edges += 1
        source = Neighbour(
            doc_id=e["source_doc_id"],
            collection=e["source_collection"],
            title=e["source_title"],
            url=e.get("source_url"),
            ref=e["target_ref"],
            kind=e["kind"],
            provision=e.get("provision"),
            parties=e.get("parties"),
            via_doc_id=e["source_doc_id"],
            via_chunk_index=int(e["source_chunk_index"]),
        )
        self.cites[e["source_doc_id"]].append(
            Neighbour(
                doc_id=e.get("target_doc_id"),
                collection=e.get("target_collection"),
                title=e.get("target_title"),
                url=e.get("target_url"),
                ref=e["target_ref"],
                kind=e["kind"],
                provision=e.get("provision"),
                parties=e.get("parties"),
                via_doc_id=e["source_doc_id"],
                via_chunk_index=int(e["source_chunk_index"]),
            )
        )
        if target := e.get("target_doc_id"):
            self.cited_by[target].append(source)
        self.citing[e["target_key"].lower()].append(source)
        if e.get("parties_key"):
            self.citing[e["parties_key"]].append(source)
        if e.get("provision"):
            self.citing[f"{e['target_key'].lower()} § {e['provision'].lower()}"].append(source)

    def neighbours(self, doc_id: str) -> list[Neighbour]:
        """Every indexed document one hop away, in either direction, de-duplicated."""
        seen: set[str] = set()
        out = []
        for n in [*self.cites.get(doc_id, []), *self.cited_by.get(doc_id, [])]:
            if n.doc_id and n.doc_id not in seen:
                seen.add(n.doc_id)
                out.append(n)
        return out

    def citing_passages(self, key: str, provision: str | None = None) -> list[Neighbour]:
        """Passages that cite `key` - a citation, party names, or an Act.

        Each document's first citing passage comes before any document's
        second, so a capped read covers as many documents as it can; within
        that the order is fixed, not the order edges happened to load in.
        """
        lookup = f"{key.lower()} § {provision.lower()}" if provision else key.lower()
        by_document: dict[str, list[Neighbour]] = defaultdict(list)
        seen: set[tuple] = set()
        for n in sorted(self.citing.get(lookup, []), key=lambda n: (n.via_doc_id, n.via_chunk_index)):
            identity = (n.via_doc_id, n.via_chunk_index)
            if identity not in seen:
                seen.add(identity)
                by_document[n.via_doc_id].append(n)
        rounds = max((len(v) for v in by_document.values()), default=0)
        return [
            passages[i]
            for i in range(rounds)
            for passages in by_document.values()
            if i < len(passages)
        ]


@dataclass
class Link:
    """A neighbouring document, with every way the link was written."""

    doc_id: str | None
    collection: str | None
    title: str | None
    url: str | None
    kind: str
    parties: str | None
    refs: list[str]
    via_doc_id: str
    via_chunk_index: int


def group_by_document(neighbours: list[Neighbour]) -> list[Link]:
    """One row per document: a judgment applying five sections of one Act is one link.

    Unresolved targets group by the citation as written. Order follows the
    first passage each link was found in.
    """
    links: dict[str, Link] = {}
    for n in sorted(neighbours, key=lambda n: n.via_chunk_index):
        key = n.doc_id or n.ref.lower()
        link = links.get(key)
        if link is None:
            links[key] = Link(
                doc_id=n.doc_id,
                collection=n.collection,
                title=n.title,
                url=n.url,
                kind=n.kind,
                parties=n.parties,
                refs=[n.ref],
                via_doc_id=n.via_doc_id,
                via_chunk_index=n.via_chunk_index,
            )
        elif n.ref not in link.refs:
            link.refs.append(n.ref)
    return list(links.values())


def load_graph(client: WeaviateClient) -> Graph:
    graph = Graph()
    if not client.collections.exists(CLASS_NAME):
        return graph
    for obj in client.collections.use(CLASS_NAME).iterator():
        graph.add(obj.properties)
    return graph
