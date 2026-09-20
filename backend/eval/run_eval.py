"""Offline faithfulness evaluation: runs the golden dataset against a live API and
scores whether each answer's claims are actually supported by the passages it cites.

The corpus must already be indexed - in CI, `eval/fixtures/corpus_slice.json` is
ingested through the CLI before this runs (see .github/workflows/eval.yml).

Runs in its own isolated environment (see README.md) because ragas 0.4.x's dependency
metadata conflicts with the main app's LangChain 1.x pins.

A local model answers one question at a time and takes minutes over each, so a run
is hours: `--concurrency 1 --timeout 1800 --resume` writes every result to
`<report>.partial.jsonl` as it lands and a restarted run picks up from there.
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
DEFAULT_REPORT = EVAL_DIR / "report.json"

# Gate on the same citation-coverage code the app scores live with, rather than a
# copy that can drift: a gate measuring something subtly different from the
# dashboard is worse than no gate. app.scoring is stdlib-only, so importing it
# here doesn't drag the app's LangChain pins into this isolated environment.
sys.path.insert(0, str(EVAL_DIR.parent))
from app.scoring import citation_coverage

HEALTH_TIMEOUT_SECONDS = 60
# Legal answers decompose into many claims; at 4096 the judge overran on 5 of 36
# and scored a correct verbatim answer 0.00.
JUDGE_MAX_TOKENS = 16384


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
    # Wall clock of the /query call, as the user would experience it.
    seconds: float | None = None


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(p * (len(ordered) - 1))))
    return ordered[index]


@dataclass
class Report:
    results: list[SampleResult] = field(default_factory=list)
    # How the run was configured, so numbers are never read without their setup.
    setup: dict = field(default_factory=dict)

    @property
    def latencies(self) -> list[float]:
        return [r.seconds for r in self.results if r.seconds is not None and r.error is None]

    @property
    def p50_seconds(self) -> float | None:
        return percentile(self.latencies, 0.5)

    @property
    def p95_seconds(self) -> float | None:
        return percentile(self.latencies, 0.95)

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
        started = time.monotonic()
        try:
            response = await client.post(
                "/query", json={"question": row["question"], "mode": "ask"}
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            result.error = f"query failed: {exc}"
            return result
        result.seconds = time.monotonic() - started

        result.answer = payload["answer"] or ""
        # The parent window, because that is what the generator actually read;
        # judging against the shorter matched child would penalise claims the
        # model correctly drew from the surrounding lines.
        contexts = [c["parent_text"] for c in payload["citations"]]
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


def build_judge(args: argparse.Namespace):
    """The faithfulness judge: a local Ollama model by default, or Claude.

    The same judge must be used across the runs being compared, since a
    judge is part of the instrument.
    """
    if args.judge_model.startswith("ollama:"):
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=args.judge_model.removeprefix("ollama:"),
            base_url=args.ollama_base_url,
            num_ctx=16384,
            num_predict=JUDGE_MAX_TOKENS,
            reasoning=False,
        )
    if not args.anthropic_api_key:
        raise SystemExit("--anthropic-api-key is required for a Claude judge")
    # ChatAnthropic defaults to max_tokens=1024, which ragas's faithfulness judge
    # overruns on longer answers — it then reports "The LLM generation was not
    # completed" and the sample goes unscored.
    return ChatAnthropic(
        model=args.judge_model,
        anthropic_api_key=args.anthropic_api_key,
        max_tokens=JUDGE_MAX_TOKENS,
    )


def partial_path(report: Path) -> Path:
    return report.with_name(report.stem + ".partial.jsonl")


def load_partial(path: Path) -> dict[str, SampleResult]:
    """Results a previous run finished: scored, or unanswered on purpose. A failed
    query or a judge that couldn't score is retried, not carried over."""
    done: dict[str, SampleResult] = {}
    if not path.exists():
        return done
    for line in path.read_text().splitlines():
        if line.strip():
            result = SampleResult(**json.loads(line))
            if result.error is None and result.judge_error is None:
                done[result.id] = result
    return done


async def run(args: argparse.Namespace) -> Report:
    dataset = load_dataset(args.dataset)

    judge = LangchainLLMWrapper(build_judge(args), bypass_temperature=True)
    faithfulness = Faithfulness(llm=judge)

    partial = partial_path(args.report)
    done = load_partial(partial) if args.resume else {}
    if done:
        print(f"resuming: {len(done)} of {len(dataset)} already scored in {partial}")

    async def score_and_keep(row: dict, semaphore: asyncio.Semaphore) -> SampleResult:
        if row["id"] in done:
            return done[row["id"]]
        result = await score_sample(client, faithfulness, row, semaphore)
        if args.resume:
            with partial.open("a") as handle:
                handle.write(json.dumps(vars(result)) + "\n")
        return result

    async with httpx.AsyncClient(base_url=args.api_url, timeout=args.timeout) as client:
        await wait_for_health(client, HEALTH_TIMEOUT_SECONDS)
        semaphore = asyncio.Semaphore(args.concurrency)
        results = await asyncio.gather(*[score_and_keep(row, semaphore) for row in dataset])

    setup = {"judge_model": args.judge_model, "api_url": args.api_url, "dataset": str(args.dataset)}
    try:
        health = await httpx.AsyncClient(base_url=args.api_url, timeout=10.0).get("/health")
        setup.update(health.json())
    except httpx.HTTPError:
        pass
    return Report(results=list(results), setup=setup)


def write_report(report: Report, path: Path) -> None:
    payload = {
        "setup": report.setup,
        "p50_seconds": report.p50_seconds,
        "p95_seconds": report.p95_seconds,
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
    if report.p50_seconds is not None:
        print(f"latency:           p50 {report.p50_seconds:.1f}s   p95 {report.p95_seconds:.1f}s "
              f"(wall clock per /query, {report.setup.get('provider', 'provider unknown')})")
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
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--judge-model",
        default="ollama:qwen3:8b",
        help="ollama:<model> for a local judge, or a Claude model id",
    )
    parser.add_argument("--anthropic-api-key", default="")
    parser.add_argument("--ollama-base-url", default="http://localhost:11435")
    parser.add_argument("--concurrency", type=int, default=5, help="1 for a local model")
    parser.add_argument("--timeout", type=float, default=180.0, help="seconds per /query")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="keep each result in <report>.partial.jsonl and skip those on the next run",
    )
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
