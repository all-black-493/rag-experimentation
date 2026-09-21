"""Build a summary tree over passages: cluster, summarise, embed, recurse.

    python -m app.tree.build --matter <id>                 # a matter's documents
    python -m app.tree.build --collection case_law --docs 200 --levels 2

RAPTOR (arXiv 2401.18059), kept to what this corpus needs: leaves are the
indexed passages with their stored vectors; each level clusters the level
below and writes one summary per cluster; a summary's `leaves` are every
passage under it, so a hit on any node hands retrieval real passages.
Summaries are navigation, never evidence.

One model call per cluster, so the cost is the number of clusters: a matter
of 25 passages is 2 or 3 calls; case law at 47k passages is ~5k calls per
level, which is a job for a paid model or a GPU, not a CPU.
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass

import numpy as np
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from weaviate.client import WeaviateClient

from app.config import get_settings
from app.llm import build_chat_model
from app.metadata import CLASS_NAMES, MATTER, Collection
from app.tree.cluster import cluster
from app.tree.store import CORPUS_TENANT, SummaryNode, leaf_key, replace_tree
from app.tree.summarise import summarise
from app.vectorstore.client import weaviate_client
from app.vectorstore.embeddings import build_embeddings

logger = logging.getLogger(__name__)


@dataclass
class Leaf:
    key: str
    doc_id: str
    text: str
    vector: list[float]


def load_leaves(
    client: WeaviateClient,
    collection: Collection,
    *,
    tenant: str | None = None,
    docs: int | None = None,
) -> list[Leaf]:
    """Passages with their stored vectors; `docs` caps the number of documents read."""
    handle = client.collections.use(CLASS_NAMES[collection])
    if tenant is not None:
        if not handle.tenants.exists(tenant):
            return []
        handle = handle.with_tenant(tenant)
    leaves: list[Leaf] = []
    seen_docs: list[str] = []
    for obj in handle.iterator(
        include_vector=True, return_properties=["doc_id", "chunk_index", "text"]
    ):
        p = obj.properties
        if p["doc_id"] not in seen_docs:
            if docs is not None and len(seen_docs) >= docs:
                continue
            seen_docs.append(p["doc_id"])
        vector = obj.vector["default"] if isinstance(obj.vector, dict) else obj.vector
        leaves.append(
            Leaf(leaf_key(p["doc_id"], int(p["chunk_index"])), p["doc_id"], p["text"], list(vector))
        )
    return leaves


def build_tree(
    leaves: list[Leaf],
    llm: BaseChatModel,
    embeddings: Embeddings,
    *,
    collection: Collection,
    levels: int = 1,
    target_size: int = 10,
    progress=None,
) -> list[SummaryNode]:
    """Summary nodes for every level, each pointing at the leaves beneath it."""
    nodes: list[SummaryNode] = []
    # What this level clusters: (text, vector, leaf keys beneath, doc ids beneath).
    layer = [(leaf.text, leaf.vector, [leaf.key], [leaf.doc_id]) for leaf in leaves]
    for level in range(1, levels + 1):
        if len(layer) < 2:
            break
        groups = cluster(np.array([item[1] for item in layer]), target_size=target_size)
        if len(groups) == 1 and level > 1:
            break
        next_layer = []
        for i, group in enumerate(groups):
            members = [layer[j] for j in group]
            summary, title = summarise(llm, [m[0] for m in members])
            vector = embeddings.embed_documents([summary])[0]
            keys = sorted({k for m in members for k in m[2]})
            doc_ids = sorted({d for m in members for d in m[3]})
            nodes.append(
                SummaryNode(
                    text=summary,
                    title=title,
                    level=level,
                    collection=collection,
                    leaves=keys,
                    doc_ids=doc_ids,
                    vector=vector,
                )
            )
            next_layer.append((summary, vector, keys, doc_ids))
            if progress:
                progress(level, i + 1, len(groups))
        layer = next_layer
    return nodes


def build_matter_tree(
    client: WeaviateClient,
    embeddings: Embeddings,
    llm: BaseChatModel,
    matter_id: str,
    target_size: int = 8,
) -> int:
    """A matter's tree, level 1 only: a few summaries across its documents."""
    leaves = load_leaves(client, MATTER, tenant=matter_id)
    nodes = build_tree(
        leaves, llm, embeddings, collection=MATTER, levels=1, target_size=target_size
    )
    return replace_tree(client, matter_id, nodes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--matter", help="build a matter's tree instead of the corpus's")
    parser.add_argument("--collection", choices=["legislation", "case_law"], default="case_law")
    parser.add_argument("--docs", type=int, help="corpus: only the first N documents")
    parser.add_argument("--levels", type=int, default=1)
    parser.add_argument("--target-size", type=int, default=10)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    settings = get_settings()
    embeddings = build_embeddings(settings)
    llm = build_chat_model(settings, "fast")
    started = time.time()
    with weaviate_client(settings) as client:
        if args.matter:
            count = build_matter_tree(client, embeddings, llm, args.matter, args.target_size)
            summary = {"tenant": args.matter, "nodes": count}
        else:
            leaves = load_leaves(client, args.collection, docs=args.docs)
            logger.info("%d passages from %s", len(leaves), args.collection)
            calls = {"n": 0}

            def progress(level, i, total):
                calls["n"] += 1
                if i % 10 == 0 or i == total:
                    logger.info(
                        "level %d: %d/%d clusters, %.0fs", level, i, total, time.time() - started
                    )

            nodes = build_tree(
                leaves,
                llm,
                embeddings,
                collection=args.collection,
                levels=args.levels,
                target_size=args.target_size,
                progress=progress,
            )
            count = replace_tree(client, CORPUS_TENANT, nodes, collection=args.collection)
            summary = {
                "tenant": CORPUS_TENANT,
                "collection": args.collection,
                "leaves": len(leaves),
                "nodes": count,
                "calls": calls["n"],
            }
    summary["seconds"] = round(time.time() - started, 1)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
