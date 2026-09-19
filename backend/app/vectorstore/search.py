"""Hybrid search over one corpus collection."""

from langchain_core.documents import Document
from weaviate.classes.query import Filter, HybridFusion, MetadataQuery
from weaviate.client import WeaviateClient

from app.metadata import CLASS_NAMES, Collection
from app.vectorstore.schema import RETURN_PROPERTIES

# Where BM25 looks. The title carries the Act's name and the parties to a case,
# which is often exactly what a question names.
_QUERY_PROPERTIES = ["text", "title"]


def hybrid_search(
    client: WeaviateClient,
    collection: Collection,
    query: str,
    vector: list[float],
    *,
    alpha: float,
    fusion: HybridFusion,
    limit: int,
    filters: Filter | None = None,
) -> list[Document]:
    """BM25 + vector search, fused by Weaviate, filtered before ranking.

    The vector is supplied rather than computed here so the caller controls the
    embedder - and so one embedding of a sub-query serves every collection it is
    sent to. Filters are pushed into the query: applied before ranking, a narrow
    filter still fills the whole candidate pool instead of leaving three survivors.
    """
    handle = client.collections.use(CLASS_NAMES[collection])
    response = handle.query.hybrid(
        query,
        vector=vector,
        alpha=alpha,
        fusion_type=fusion,
        query_properties=_QUERY_PROPERTIES,
        filters=filters,
        limit=limit,
        return_properties=RETURN_PROPERTIES[collection],
        return_metadata=MetadataQuery(score=True),
    )

    documents = []
    for obj in response.objects:
        properties = dict(obj.properties)
        text = properties.pop("text")
        documents.append(
            Document(
                page_content=text,
                metadata={
                    **properties,
                    "collection": collection,
                    "hybrid_score": obj.metadata.score,
                },
            )
        )
    return documents
