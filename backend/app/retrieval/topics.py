"""Widen the pool by topic: a summary tree's hit hands over its passages.

RAPTOR's "collapsed tree" search, with one rule kept strict: a summary is
never a citation. The question is searched against the summary nodes (the
corpus's, and the matter's when one is in scope); each node that matches
contributes the leaf passages beneath it that hybrid search did not already
find, tagged with the topic they came in under. The reranker judges them
with everything else, under the same candidate budget as the citation graph,
so a topic can add a passage but never the cost of one.
"""

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from weaviate.classes.query import Filter, HybridFusion
from weaviate.client import WeaviateClient

from app.metadata import CLASS_NAMES, MATTER
from app.retrieval.expand import _identity, _within_budget
from app.retrieval.state import GraphState
from app.retrieval.tracing import traceable
from app.tracing import observation
from app.tree.store import CORPUS_TENANT, SummaryNode, search_summaries
from app.vectorstore.schema import RETURN_PROPERTIES


def topics(
    state: GraphState,
    client: WeaviateClient,
    embeddings: Embeddings,
    *,
    alpha: float,
    fusion: HybridFusion,
    max_nodes: int,
    max_leaves: int,
    budget: int,
    enabled: bool = True,
) -> dict:
    if not enabled:
        return {"topics": None}
    question = state["question"]
    user = state["user_filters"]
    pooled: dict[tuple, Document] = {_identity(d): d for d in state["documents"]}
    summary = {"nodes": [], "added": 0}

    with observation(
        as_type="retriever", name="topic-tree-expand", input={"question": question}
    ) as span:
        vector = embeddings.embed_query(question)
        tenants = [CORPUS_TENANT] + ([user.matter_id] if user.matter_id else [])
        hits: list[SummaryNode] = []
        for tenant in tenants:
            hits.extend(
                search_summaries(
                    client, tenant, question, vector, alpha=alpha, fusion=fusion, limit=max_nodes
                )
            )
        hits = [h for h in hits if user.allows(h.collection)]
        hits.sort(key=lambda h: -(h.score or 0.0))

        for node in hits[:max_nodes]:
            added = 0
            for doc in _leaves(client, node, user.matter_id, max_leaves):
                if _identity(doc) in pooled:
                    continue
                doc.metadata["via"] = f"topic: {node.title}"
                pooled[_identity(doc)] = doc
                added += 1
            summary["nodes"].append({"title": node.title, "level": node.level, "added": added})
            summary["added"] += added

        documents = _within_budget(list(pooled.values()), len(state["documents"]), budget)
        span.update(
            output=[traceable(d) for d in documents if d.metadata.get("via")], metadata=summary
        )
    return {"documents": documents, "topics": summary}


def _leaves(
    client: WeaviateClient, node: SummaryNode, matter_id: str | None, limit: int
) -> list[Document]:
    """The first `limit` passages beneath a node, fetched by their keys."""
    handle = client.collections.use(CLASS_NAMES[node.collection])
    if node.collection == MATTER:
        if not matter_id:
            return []
        handle = handle.with_tenant(matter_id)
    documents = []
    for key in node.leaves[:limit]:
        doc_id, _, index = key.rpartition("#")
        response = handle.query.fetch_objects(
            filters=Filter.by_property("doc_id").equal(doc_id)
            & Filter.by_property("chunk_index").equal(int(index)),
            limit=1,
            return_properties=RETURN_PROPERTIES[node.collection],
        )
        for obj in response.objects:
            properties = dict(obj.properties)
            text = properties.pop("text")
            documents.append(
                Document(page_content=text, metadata={**properties, "collection": node.collection})
            )
    return documents
