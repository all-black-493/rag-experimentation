"""Retrieval accuracy benchmark: does the right document come back, and how high?

    uv run python eval/retrieval_benchmark.py                    # against a running API
    uv run python eval/retrieval_benchmark.py --k 5 --label planner
    PLANNER_ENABLED=false docker compose up -d app && uv run python eval/retrieval_benchmark.py --label plain

Separate from run_eval.py on purpose. That harness scores the *answer* with an
LLM judge, which is slow, costs money, and conflates retrieval quality with
generation quality. This one scores only what search mode returns - the
planned, filtered, reranked passages - against the `source` recorded for each
golden question, deterministically, in seconds. Run it with the planner on and
off to measure what the agentic layer is worth.

Metrics are the standard ones for this job:
  recall@k  did the correct document appear anywhere in the top k
  MRR       1/rank of the first correct document, so rank 1 beats rank 5
  nDCG@k    rank-discounted, the usual tiebreaker when recall is saturated
"""

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import httpx

EVAL_DIR = Path(__file__).resolve().parent
DATASET = EVAL_DIR / "golden_dataset.jsonl"
RELATIONSHIPS = EVAL_DIR / "golden_relationships.jsonl"


@dataclass
class Scores:
    questions: int
    recall_at_k: float
    mrr: float
    ndcg: float
    # Multi-answer questions only: share of the top k that are correct.
    precision_at_k: float | None
    relaxed: int
    fallback_plans: int

    def render(self, label: str, k: int) -> str:
        precision = (
            f"   P@{k} {self.precision_at_k:6.1%}" if self.precision_at_k is not None else ""
        )
        return (
            f"{label:<14} recall@{k} {self.recall_at_k:6.1%}   MRR {self.mrr:6.3f}   "
            f"nDCG {self.ndcg:6.3f}{precision}   relaxed {self.relaxed}   fallback plans "
            f"{self.fallback_plans}   (n={self.questions})"
        )


def load_dataset(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def truths_of(row: dict) -> set[str]:
    """One correct document, or several for a relationship question."""
    return set(row["sources"]) if "sources" in row else {row["source"]}


def score_run(ranked_sources: list[list[str]], truths: list[set[str]], k: int) -> tuple:
    hits = reciprocal = ndcg = 0.0
    precisions: list[float] = []
    for ranked, truth in zip(ranked_sources, truths, strict=True):
        # Document-level: several passages from one document count once, at
        # the best rank any of them reached.
        seen: list[str] = []
        for source in ranked:
            if source not in seen:
                seen.append(source)
        top = seen[:k]
        correct = [i for i, source in enumerate(top) if source in truth]
        if correct:
            rank = correct[0] + 1
            hits += 1
            reciprocal += 1 / rank
            ndcg += 1 / math.log2(rank + 1)
        if len(truth) > 1:
            precisions.append(len(correct) / k)
    n = len(truths)
    precision = sum(precisions) / len(precisions) if precisions else None
    return hits / n, reciprocal / n, ndcg / n, precision


def run(api_url: str, k: int, dataset: list[dict]) -> Scores:
    ranked, relaxed, fallbacks = [], 0, 0
    with httpx.Client(base_url=api_url, timeout=180.0) as client:
        for row in dataset:
            response = client.post("/query", json={"question": row["question"], "mode": "search"})
            response.raise_for_status()
            payload = response.json()
            ranked.append([c["url"] for c in payload["citations"]])
            relaxed += sum(1 for r in payload["retrieval"] if r["relaxed"])
            fallbacks += payload["plan"]["origin"] == "fallback"

    recall, mrr, ndcg, precision = score_run(ranked, [truths_of(row) for row in dataset], k)
    return Scores(len(dataset), recall, mrr, ndcg, precision, relaxed, fallbacks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8010")
    parser.add_argument("--k", type=int, default=5, help="rank cutoff for the metrics")
    parser.add_argument("--label", default="search", help="name for this run in the output")
    parser.add_argument(
        "--set",
        choices=["golden", "relationships", "both"],
        default="golden",
        help="golden: single-document questions; relationships: graph-derived multi-document ones",
    )
    args = parser.parse_args()

    sets = {"golden": [DATASET], "relationships": [RELATIONSHIPS], "both": [DATASET, RELATIONSHIPS]}
    dataset = [row for path in sets[args.set] for row in load_dataset(path)]
    print(run(args.api_url, args.k, dataset).render(f"{args.label}/{args.set}", args.k))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
