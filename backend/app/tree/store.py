"""Summary nodes in Weaviate: one collection, a tenant per tree.

The corpus tree lives under the tenant "corpus"; a matter's tree under the
matter's id, so a query sees the shared topics and its own. Nodes carry
their own vectors and their text is BM25-searchable, so the same hybrid
query that searches passages searches topics. A node never becomes a
citation: it points at leaf passages, and those are what a query gets.
"""

from dataclasses import dataclass, field

from weaviate.classes.config import Configure, DataType, Property, Tokenization
from weaviate.classes.data import DataObject
from weaviate.classes.query import Filter, HybridFusion, MetadataQuery
from weaviate.classes.tenants import Tenant
from weaviate.client import WeaviateClient

CLASS_NAME = "Summary"
CORPUS_TENANT = "corpus"

_KEYWORD = {"tokenization": Tokenization.FIELD, "index_searchable": False}
_PROPERTIES = [
    Property(name="text", data_type=DataType.TEXT),
    Property(name="title", data_type=DataType.TEXT),
    Property(name="level", data_type=DataType.INT),
    # Which passage collection the leaves live in: legislation, case_law, matter.
    Property(name="collection", data_type=DataType.TEXT, **_KEYWORD),
    # "doc_id#chunk_index" of every leaf under this node, transitively.
    Property(name="leaves", data_type=DataType.TEXT_ARRAY, **_KEYWORD),
    Property(name="doc_ids", data_type=DataType.TEXT_ARRAY, **_KEYWORD),
]
_BATCH = 200


@dataclass
class SummaryNode:
    text: str
    title: str
    level: int
    collection: str
    leaves: list[str]
    doc_ids: list[str]
    vector: list[float] = field(default_factory=list)
    score: float | None = None


def leaf_key(doc_id: str, chunk_index: int) -> str:
    return f"{doc_id}#{chunk_index}"


def ensure_summary_collection(client: WeaviateClient) -> bool:
    if client.collections.exists(CLASS_NAME):
        return False
    client.collections.create(
        name=CLASS_NAME,
        vector_config=Configure.Vectors.self_provided(),
        properties=_PROPERTIES,
        multi_tenancy_config=Configure.multi_tenancy(enabled=True, auto_tenant_creation=True),
    )
    return True


def _handle(client: WeaviateClient, tenant: str):
    collection = client.collections.use(CLASS_NAME)
    if not collection.tenants.exists(tenant):
        collection.tenants.create([Tenant(name=tenant)])
    return collection.with_tenant(tenant)


def replace_tree(
    client: WeaviateClient, tenant: str, nodes: list[SummaryNode], collection: str | None = None
) -> int:
    """Write a tree, dropping what the tenant held for that passage collection first."""
    ensure_summary_collection(client)
    handle = _handle(client, tenant)
    if collection is None:
        existing = client.collections.use(CLASS_NAME)
        if existing.tenants.exists(tenant):
            existing.tenants.remove([tenant])
        handle = _handle(client, tenant)
    else:
        handle.data.delete_many(where=Filter.by_property("collection").equal(collection))
    for start in range(0, len(nodes), _BATCH):
        batch = [
            DataObject(
                properties={
                    "text": n.text,
                    "title": n.title,
                    "level": n.level,
                    "collection": n.collection,
                    "leaves": n.leaves,
                    "doc_ids": n.doc_ids,
                },
                vector=n.vector,
            )
            for n in nodes[start : start + _BATCH]
        ]
        result = handle.data.insert_many(batch)
        if result.has_errors:
            first = next(iter(result.errors.values()))
            raise RuntimeError(f"summary insert failed: {first.message}")
    return len(nodes)


def search_summaries(
    client: WeaviateClient,
    tenant: str,
    query: str,
    vector: list[float],
    *,
    alpha: float,
    fusion: HybridFusion,
    limit: int,
) -> list[SummaryNode]:
    collection = client.collections.use(CLASS_NAME)
    if not collection.tenants.exists(tenant):
        return []
    response = collection.with_tenant(tenant).query.hybrid(
        query,
        vector=vector,
        alpha=alpha,
        fusion_type=fusion,
        query_properties=["text", "title"],
        limit=limit,
        return_metadata=MetadataQuery(score=True),
    )
    return [
        SummaryNode(
            text=obj.properties["text"],
            title=obj.properties["title"],
            level=int(obj.properties["level"]),
            collection=obj.properties["collection"],
            leaves=list(obj.properties["leaves"] or []),
            doc_ids=list(obj.properties["doc_ids"] or []),
            score=obj.metadata.score,
        )
        for obj in response.objects
    ]


def count_nodes(client: WeaviateClient, tenant: str) -> int:
    collection = client.collections.use(CLASS_NAME)
    if not collection.tenants.exists(tenant):
        return 0
    return collection.with_tenant(tenant).aggregate.over_all(total_count=True).total_count or 0
