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

# Gate on the same citation-coverage code the app scores live with, rather than a
# copy that can drift: a gate measuring something subtly different from the
# dashboard is worse than no gate. app.scoring is stdlib-only, so importing it
# here doesn't drag the app's LangChain pins into this isolated environment.
sys.path.insert(0, str(EVAL_DIR.parent))
from app.scoring import citation_coverage

HEALTH_TIMEOUT_SECONDS = 60
CONCURRENCY = 5
JUDGE_MAX_TOKENS = 4096


@dataclass
class SampleResult:
    id: str
    question: str
    ground_truth: str
    source: str
    answer: str = ""
    answered: bool = False
    faithfulness: float | None = None
    citation_coverage: float | None = None
    invalid_citations: int = 0
    # Kept apart on purpose: `error` means the system under test failed, while
    # `judge_error` means the measuring instrument did. Only the first is a
    # regression; treating them alike blocks merges on judge flakiness.
    error: str | None = None
    judge_error: str | None = None


@dataclass
class Report:
    results: list[SampleResult] = field(default_factory=list)

    @property
    def answered(self) -> list[SampleResult]:
        return [r for r in self.results if r.answered and r.error is None]

    @property
    def errored(self) -> list[SampleResult]:
        """Failures of the RAG API itself — always a gate failure."""
        return [r for r in self.results if r.error is not None]

    @property
    def judge_errored(self) -> list[SampleResult]:
        """Samples the judge couldn't score — unknown quality, not bad quality."""
        return [r for r in self.results if r.judge_error is not None]

    @property
    def answer_rate(self) -> float:
        scored = [r for r in self.results if r.error is None]
        return len([r for r in scored if r.answered]) / len(scored) if scored else 0.0

    @property
    def mean_faithfulness(self) -> float | None:
        scores = [r.faithfulness for r in self.answered if r.faithfulness is not None]
        return sum(scores) / len(scores) if scores else None

    @property
    def mean_citation_coverage(self) -> float | None:
        scores = [r.citation_coverage for r in self.answered if r.citation_coverage is not None]
        return sum(scores) / len(scores) if scores else None

    @property
    def total_invalid_citations(self) -> int:
        return sum(r.invalid_citations for r in self.answered)


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

        coverage = citation_coverage(result.answer, len(payload["citations"]))
        result.citation_coverage = coverage.coverage
        result.invalid_citations = len(coverage.invalid_indices)

        try:
            sample = SingleTurnSample(
                user_input=row["question"], response=result.answer, retrieved_contexts=contexts
            )
            result.faithfulness = await faithfulness.single_turn_ascore(sample)
        except Exception as exc:  # noqa: BLE001 - isolate one sample's failure from the batch
            result.judge_error = f"faithfulness scoring failed: {exc}"

    return result


async def run(args: argparse.Namespace) -> Report:
    dataset = load_dataset(args.dataset)

    # ChatAnthropic defaults to max_tokens=1024, which ragas's faithfulness judge
    # overruns on longer answers — it then reports "The LLM generation was not
    # completed" and the sample goes unscored.
    llm = ChatAnthropic(
        model=args.judge_model,
        anthropic_api_key=args.anthropic_api_key,
        max_tokens=JUDGE_MAX_TOKENS,
    )
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
        "mean_citation_coverage": report.mean_citation_coverage,
        "invalid_citations": report.total_invalid_citations,
        "total": len(report.results),
        "answered": len(report.answered),
        "errored": len(report.errored),
        "judge_errored": len(report.judge_errored),
        "results": [vars(r) for r in report.results],
    }
    path.write_text(json.dumps(payload, indent=2))


def print_summary(report: Report, thresholds: argparse.Namespace) -> bool:
    print(f"\n{len(report.results)} questions, {len(report.answered)} answered, "
          f"{len(report.errored)} errored")
    print(f"answer rate:       {report.answer_rate:.2%} "
          f"(threshold {thresholds.min_answer_rate:.2%})")

    mean_faithfulness = report.mean_faithfulness
    if mean_faithfulness is None:
        print("mean faithfulness: n/a (no answered samples)")
        passed_faithfulness = False
    else:
        print(
            f"mean faithfulness: {mean_faithfulness:.3f} "
            f"(threshold {thresholds.faithfulness_threshold:.3f})"
        )
        passed_faithfulness = mean_faithfulness >= thresholds.faithfulness_threshold

    coverage = report.mean_citation_coverage
    if coverage is None:
        print("citation coverage: n/a (no answered samples)")
        passed_coverage = False
    else:
        print(f"citation coverage: {coverage:.3f} "
              f"(threshold {thresholds.min_citation_coverage:.3f})")
        passed_coverage = coverage >= thresholds.min_citation_coverage

    invalid = report.total_invalid_citations
    print(f"invalid citations: {invalid} (max {thresholds.max_invalid_citations})")
    passed_invalid = invalid <= thresholds.max_invalid_citations

    worst = sorted(
        (r for r in report.answered if r.faithfulness is not None), key=lambda r: r.faithfulness
    )[:5]
    if worst:
        print("\nlowest-scoring answers:")
        for r in worst:
            print(f"  [{r.faithfulness:.2f}] {r.id}: {r.question}")

    for r in report.errored:
        print(f"  ERROR {r.id}: {r.error}")
    for r in report.judge_errored:
        print(f"  JUDGE {r.id}: {r.judge_error}")

    # A judge failure means the sample's quality is unknown, not bad. A couple of
    # those shouldn't block a merge; many of them mean the measurement is broken
    # and the run can't be trusted either way.
    judge_errors = len(report.judge_errored)
    if judge_errors:
        print(f"judge errors:      {judge_errors} (max {thresholds.max_judge_errors})")

    passed_answer_rate = report.answer_rate >= thresholds.min_answer_rate
    checks = {
        "faithfulness": passed_faithfulness,
        "answer rate": passed_answer_rate,
        "citation coverage": passed_coverage,
        "invalid citations": passed_invalid,
        "no api errors": not report.errored,
        "judge reliability": judge_errors <= thresholds.max_judge_errors,
    }
    failed = [name for name, ok in checks.items() if not ok]
    print("\nGATE: " + ("PASS" if not failed else f"FAIL ({', '.join(failed)})"))
    return not failed


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
    parser.add_argument("--min-citation-coverage", type=float, default=0.8)
    parser.add_argument("--max-invalid-citations", type=int, default=0)
    parser.add_argument(
        "--max-judge-errors",
        type=int,
        default=2,
        help="samples the judge may fail to score before the run is untrustworthy",
    )
    parser.add_argument("--skip-ingest", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = asyncio.run(run(args))
    write_report(report, args.report)
    passed = print_summary(report, args)
    print(f"\nreport written to {args.report}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
