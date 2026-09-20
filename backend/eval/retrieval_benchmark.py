"""Retrieval accuracy benchmark: does the right document come back, and how high?

    uv run python eval/retrieval_benchmark.py                    # against a running API
    uv run python eval/retrieval_benchmark.py --k 5 --label planner
    uv run python eval/retrieval_benchmark.py --set matter       # uploads the fixtures first
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
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

EVAL_DIR = Path(__file__).resolve().parent
DATASET = EVAL_DIR / "golden_dataset.jsonl"
RELATIONSHIPS = EVAL_DIR / "golden_relationships.jsonl"
TOPICS = EVAL_DIR / "golden_topics.jsonl"
MATTER = EVAL_DIR / "golden_matter.jsonl"
MATTER_FIXTURES = EVAL_DIR / "fixtures" / "matter"


@dataclass
class Scores:
    questions: int
    recall_at_k: float
    mrr: float
    ndcg: float
    # Multi-answer questions only: share of the top k that are correct.
    precision_at_k: float | None
    # Matter questions only: the right document *and* the right page in the top k.
    page_recall_at_k: float | None
    relaxed: int
    fallback_plans: int

    def render(self, label: str, k: int) -> str:
        precision = (
            f"   P@{k} {self.precision_at_k:6.1%}" if self.precision_at_k is not None else ""
        )
        page = (
            f"   page@{k} {self.page_recall_at_k:6.1%}" if self.page_recall_at_k is not None else ""
        )
        return (
            f"{label:<14} recall@{k} {self.recall_at_k:6.1%}   MRR {self.mrr:6.3f}   "
            f"nDCG {self.ndcg:6.3f}{precision}{page}   relaxed {self.relaxed}   fallback plans "
            f"{self.fallback_plans}   (n={self.questions})"
        )


def load_dataset(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def truths_of(row: dict) -> set[str]:
    """One correct document, or several for a relationship question."""
    return set(row["sources"]) if "sources" in row else {row["source"]}


def score_run(
    ranked_sources: list[list[str]],
    truths: list[set[str]],
    k: int,
    ranked_pages: list[list[tuple[str, int | None]]] | None = None,
    truth_pages: list[int | None] | None = None,
) -> tuple:
    hits = reciprocal = ndcg = 0.0
    precisions: list[float] = []
    page_hits: list[float] = []
    for i, (ranked, truth) in enumerate(zip(ranked_sources, truths, strict=True)):
        # Document-level: several passages from one document count once, at
        # the best rank any of them reached.
        seen: list[str] = []
        for source in ranked:
            if source not in seen:
                seen.append(source)
        top = seen[:k]
        correct = [j for j, source in enumerate(top) if source in truth]
        if correct:
            rank = correct[0] + 1
            hits += 1
            reciprocal += 1 / rank
            ndcg += 1 / math.log2(rank + 1)
        if len(truth) > 1:
            precisions.append(len(correct) / k)
        if truth_pages is not None and truth_pages[i] is not None and ranked_pages is not None:
            # Passage-level: the top k passages, not documents.
            page_hits.append(
                float(any(s in truth and p == truth_pages[i] for s, p in ranked_pages[i][:k]))
            )
    n = len(truths)
    precision = sum(precisions) / len(precisions) if precisions else None
    page_recall = sum(page_hits) / len(page_hits) if page_hits else None
    return hits / n, reciprocal / n, ndcg / n, precision, page_recall


def run(
    api_url: str,
    k: int,
    dataset: list[dict],
    matter_id: str | None = None,
    collections: list[str] | None = None,
) -> Scores:
    ranked, pages, relaxed, fallbacks = [], [], 0, 0
    with httpx.Client(base_url=api_url, timeout=180.0) as client:
        for row in dataset:
            body = {
                "question": row["question"],
                "mode": "search",
                "matter_id": matter_id,
                "filters": {"collections": collections or []},
            }
            response = client.post("/query", json=body)
            response.raise_for_status()
            payload = response.json()
            # Corpus documents are known by URL; matter documents by name.
            ranked.append(
                [c["title"] if c["collection"] == "matter" else c["url"] for c in payload["citations"]]
            )
            pages.append([(c["title"], c.get("page")) for c in payload["citations"]])
            relaxed += sum(1 for r in payload["retrieval"] if r["relaxed"])
            fallbacks += payload["plan"]["origin"] == "fallback"

    recall, mrr, ndcg, precision, page_recall = score_run(
        ranked, [truths_of(row) for row in dataset], k, pages, [row.get("page") for row in dataset]
    )
    return Scores(len(dataset), recall, mrr, ndcg, precision, page_recall, relaxed, fallbacks)


def prepare_matter(api_url: str) -> str:
    """Create a matter holding the fixture documents; wait until every one is indexed."""
    with httpx.Client(base_url=api_url, timeout=180.0) as client:
        matter = client.post("/matters", json={"name": "Karanja v Otieno & Sons (benchmark)"})
        matter.raise_for_status()
        matter_id = matter.json()["id"]
        for path in sorted(MATTER_FIXTURES.glob("*.pdf")):
            with path.open("rb") as handle:
                accepted = client.post(
                    f"/matters/{matter_id}/documents",
                    files={"file": (path.name, handle, "application/pdf")},
                )
            accepted.raise_for_status()
        deadline = time.time() + 300
        while time.time() < deadline:
            documents = client.get(f"/matters/{matter_id}").json()["documents"]
            if all(d["status"] in ("indexed", "failed") for d in documents):
                failed = [d for d in documents if d["status"] == "failed"]
                if failed:
                    raise RuntimeError(f"fixture failed to index: {failed[0]['error']}")
                return matter_id
            time.sleep(1)
    raise TimeoutError("matter fixtures did not index in time")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8010")
    parser.add_argument("--k", type=int, default=5, help="rank cutoff for the metrics")
    parser.add_argument("--label", default="search", help="name for this run in the output")
    parser.add_argument(
        "--set",
        choices=["golden", "relationships", "topics", "both", "matter"],
        default="golden",
        help="golden: single-document questions; relationships: graph-derived multi-document "
        "ones; topics: thematic questions with phrase-defined document sets; matter: the "
        "fixture documents, uploaded to a fresh matter first",
    )
    parser.add_argument(
        "--scope",
        choices=["all", "matter"],
        default="all",
        help="matter set only: search the whole corpus too (all) or the matter alone",
    )
    args = parser.parse_args()

    if args.set == "matter":
        matter_id = prepare_matter(args.api_url)
        try:
            scores = run(
                args.api_url,
                args.k,
                load_dataset(MATTER),
                matter_id=matter_id,
                collections=["matter"] if args.scope == "matter" else None,
            )
        finally:
            # The benchmark's matter is scaffolding, not something to keep.
            httpx.delete(f"{args.api_url}/matters/{matter_id}", timeout=60.0)
    else:
        sets = {
            "golden": [DATASET],
            "relationships": [RELATIONSHIPS],
            "topics": [TOPICS],
            "both": [DATASET, RELATIONSHIPS],
        }
        dataset = [row for path in sets[args.set] for row in load_dataset(path)]
        scores = run(args.api_url, args.k, dataset)
    suffix = f"/{args.scope}" if args.set == "matter" else ""
    print(scores.render(f"{args.label}/{args.set}{suffix}", args.k))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
