"""Retrieval accuracy benchmark: does the right document come back, and how high?

Run from the repo root (uses the app's own environment, not eval/'s):

    uv run python eval/retrieval_benchmark.py --fusion relative
    uv run python eval/retrieval_benchmark.py --fusion ranked
    uv run python eval/retrieval_benchmark.py --compare

Separate from run_eval.py on purpose. That harness scores the *answer* with an
LLM judge, which is slow, costs money, and conflates retrieval quality with
generation quality. This one scores only retrieval, deterministically, against
the `source` recorded for each golden question - so a change to fusion or
filtering can be judged on its own terms in seconds.

Metrics are the standard ones for this job:
  recall@k  did the correct document appear anywhere in the top k
  MRR       1/rank of the first correct document, so rank 1 beats rank 5
  nDCG@k    rank-discounted, the usual tiebreaker when recall is saturated
"""

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.vectorstore.client import weaviate_client
from app.vectorstore.embeddings import build_embeddings
from app.vectorstore.store import build_vector_store, tenant_exists
from weaviate.classes.query import HybridFusion

DATASET = Path(__file__).resolve().parent / "golden_dataset.jsonl"

FUSIONS = {
    "relative": HybridFusion.RELATIVE_SCORE,
    "ranked": HybridFusion.RANKED,  # reciprocal rank fusion
}


@dataclass
class Scores:
    questions: int
    recall_at_k: float
    mrr: float
    ndcg: float

    def render(self, label: str) -> str:
        return (
            f"{label:<28} recall@k {self.recall_at_k:6.1%}   "
            f"MRR {self.mrr:6.3f}   nDCG {self.ndcg:6.3f}   (n={self.questions})"
        )


def load_dataset() -> list[dict]:
    return [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]


def score_run(ranked_sources: list[list[str]], truths: list[str]) -> Scores:
    hits = reciprocal_ranks = ndcg_total = 0.0

    for sources, truth in zip(ranked_sources, truths, strict=True):
        rank = next((i for i, s in enumerate(sources, start=1) if s == truth), None)
        if rank is not None:
            hits += 1
            reciprocal_ranks += 1 / rank
            # Binary relevance, single relevant document: ideal DCG is 1.
            ndcg_total += 1 / math.log2(rank + 1)

    n = len(truths)
    return Scores(n, hits / n, reciprocal_ranks / n, ndcg_total / n)


def run(tenant: str, fusion: str, k: int) -> Scores:
    settings = get_settings()
    rows = load_dataset()

    with weaviate_client(settings) as client:
        if not tenant_exists(client, settings.weaviate_collection, tenant):
            raise SystemExit(
                f"tenant {tenant!r} has no documents - ingest the fixtures first "
                f"(see --help)"
            )
        store = build_vector_store(client, build_embeddings(settings), settings)

        ranked_sources = []
        for row in rows:
            documents = store.similarity_search(
                row["question"],
                k=k,
                alpha=settings.hybrid_alpha,
                tenant=tenant,
                fusion_type=FUSIONS[fusion],
            )
            ranked_sources.append([d.metadata.get("source", "") for d in documents])

    return score_run(ranked_sources, [row["source"] for row in rows])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant",
        default=os.environ.get("BENCH_TENANT", "retrieval-bench"),
        help="session whose documents to search; ingest the fixtures into it first",
    )
    parser.add_argument("--fusion", choices=sorted(FUSIONS), default="relative")
    parser.add_argument("--k", type=int, default=10, help="rank cutoff for the metrics")
    parser.add_argument(
        "--compare", action="store_true", help="run every fusion strategy and diff them"
    )
    args = parser.parse_args()

    if not args.compare:
        print(run(args.tenant, args.fusion, args.k).render(args.fusion))
        return 0

    results = {name: run(args.tenant, name, args.k) for name in sorted(FUSIONS)}
    print(f"Retrieval accuracy over {len(load_dataset())} golden questions, k={args.k}\n")
    for name, scores in results.items():
        label = "relativeScoreFusion" if name == "relative" else "rankedFusion (RRF)"
        print(scores.render(label))

    baseline, rrf = results["relative"], results["ranked"]
    print(
        f"\ndelta (RRF - relative):       recall {rrf.recall_at_k - baseline.recall_at_k:+.1%}   "
        f"MRR {rrf.mrr - baseline.mrr:+.3f}   nDCG {rrf.ndcg - baseline.ndcg:+.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
