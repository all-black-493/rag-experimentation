"""Offline faithfulness evaluation: runs the golden dataset against a live RAG API
and scores whether each answer's claims are actually supported by the chunks it cites.

Runs in its own isolated environment (see README.md) because ragas 0.4.x's dependency
metadata conflicts with the main app's LangChain 1.x pins.
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from langchain_anthropic import ChatAnthropic
from ragas.dataset_schema import SingleTurnSample
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import Faithfulness

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = EVAL_DIR / "golden_dataset.jsonl"
DEFAULT_FIXTURES_DIR = EVAL_DIR / "fixtures"
DEFAULT_REPORT = EVAL_DIR / "report.json"

HEALTH_TIMEOUT_SECONDS = 60
CONCURRENCY = 5


@dataclass
class SampleResult:
    id: str
    question: str
    ground_truth: str
    source: str
    answer: str = ""
    answered: bool = False
    faithfulness: float | None = None
    error: str | None = None


@dataclass
class Report:
    results: list[SampleResult] = field(default_factory=list)

    @property
    def answered(self) -> list[SampleResult]:
        return [r for r in self.results if r.answered and r.error is None]

    @property
    def errored(self) -> list[SampleResult]:
        return [r for r in self.results if r.error is not None]

    @property
    def answer_rate(self) -> float:
        scored = [r for r in self.results if r.error is None]
        return len([r for r in scored if r.answered]) / len(scored) if scored else 0.0

    @property
    def mean_faithfulness(self) -> float | None:
        scores = [r.faithfulness for r in self.answered if r.faithfulness is not None]
        return sum(scores) / len(scores) if scores else None


def load_dataset(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"No QA pairs found in {path}")
    return rows


async def wait_for_health(client: httpx.AsyncClient, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = await client.get("/health")
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(2)
    raise RuntimeError(f"API did not become healthy within {timeout}s")


async def ingest_fixtures(client: httpx.AsyncClient, fixtures_dir: Path) -> None:
    for path in sorted(fixtures_dir.glob("*.md")):
        with path.open("rb") as f:
            response = await client.post("/ingest/file", files={"file": (path.name, f)})
        response.raise_for_status()
        print(f"ingested {path.name}: {response.json()['chunks_indexed']} chunks")


async def score_sample(
    client: httpx.AsyncClient,
    faithfulness: Faithfulness,
    row: dict,
    semaphore: asyncio.Semaphore,
) -> SampleResult:
    result = SampleResult(
        id=row["id"],
        question=row["question"],
        ground_truth=row["ground_truth"],
        source=row["source"],
    )
    async with semaphore:
        try:
            response = await client.post("/query", json={"question": row["question"]})
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            result.error = f"query failed: {exc}"
            return result

        result.answer = payload["answer"]
        contexts = [c["text"] for c in payload["citations"]]
        result.answered = bool(contexts)

        if not result.answered:
            return result

        try:
            sample = SingleTurnSample(
                user_input=row["question"], response=result.answer, retrieved_contexts=contexts
            )
            result.faithfulness = await faithfulness.single_turn_ascore(sample)
        except Exception as exc:  # noqa: BLE001 - isolate one sample's failure from the batch
            result.error = f"faithfulness scoring failed: {exc}"

    return result


async def run(args: argparse.Namespace) -> Report:
    dataset = load_dataset(args.dataset)

    llm = ChatAnthropic(model=args.judge_model, anthropic_api_key=args.anthropic_api_key)
    judge = LangchainLLMWrapper(llm, bypass_temperature=True)
    faithfulness = Faithfulness(llm=judge)

    headers = {"X-Session-Id": args.session_id}
    async with httpx.AsyncClient(base_url=args.api_url, timeout=120.0, headers=headers) as client:
        await wait_for_health(client, HEALTH_TIMEOUT_SECONDS)

        if not args.skip_ingest:
            await ingest_fixtures(client, args.fixtures_dir)

        semaphore = asyncio.Semaphore(CONCURRENCY)
        tasks = [score_sample(client, faithfulness, row, semaphore) for row in dataset]
        results = await asyncio.gather(*tasks)

    return Report(results=list(results))


def write_report(report: Report, path: Path) -> None:
    payload = {
        "answer_rate": report.answer_rate,
        "mean_faithfulness": report.mean_faithfulness,
        "total": len(report.results),
        "answered": len(report.answered),
        "errored": len(report.errored),
        "results": [vars(r) for r in report.results],
    }
    path.write_text(json.dumps(payload, indent=2))


def print_summary(report: Report, faithfulness_threshold: float, min_answer_rate: float) -> bool:
    print(f"\n{len(report.results)} questions, {len(report.answered)} answered, "
          f"{len(report.errored)} errored")
    print(f"answer rate:       {report.answer_rate:.2%} (threshold {min_answer_rate:.2%})")

    mean_faithfulness = report.mean_faithfulness
    if mean_faithfulness is None:
        print("mean faithfulness: n/a (no answered samples)")
        passed_faithfulness = False
    else:
        print(
            f"mean faithfulness: {mean_faithfulness:.3f} "
            f"(threshold {faithfulness_threshold:.3f})"
        )
        passed_faithfulness = mean_faithfulness >= faithfulness_threshold

    worst = sorted(
        (r for r in report.answered if r.faithfulness is not None), key=lambda r: r.faithfulness
    )[:5]
    if worst:
        print("\nlowest-scoring answers:")
        for r in worst:
            print(f"  [{r.faithfulness:.2f}] {r.id}: {r.question}")

    for r in report.errored:
        print(f"  ERROR {r.id}: {r.error}")

    passed_answer_rate = report.answer_rate >= min_answer_rate
    return passed_faithfulness and passed_answer_rate and not report.errored


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8010")
    parser.add_argument(
        "--session-id",
        default="eval",
        help="X-Session-Id sent with every request, isolating the eval corpus from other sessions",
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--fixtures-dir", type=Path, default=DEFAULT_FIXTURES_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--judge-model", default="claude-sonnet-5")
    parser.add_argument("--anthropic-api-key", required=True)
    parser.add_argument("--faithfulness-threshold", type=float, default=0.8)
    parser.add_argument("--min-answer-rate", type=float, default=0.9)
    parser.add_argument("--skip-ingest", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = asyncio.run(run(args))
    write_report(report, args.report)
    passed = print_summary(report, args.faithfulness_threshold, args.min_answer_rate)
    print(f"\nreport written to {args.report}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
