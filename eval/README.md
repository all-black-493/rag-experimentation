# Faithfulness evaluation

Offline check that answers are actually grounded in the chunks retrieved for them, using
[ragas](https://docs.ragas.io)'s Faithfulness metric: it decomposes the answer into
individual claims and verifies each one against the retrieved context, independently of
the golden `ground_truth` answer.

## Why this lives in its own environment

`ragas==0.4.3` hard-imports `langchain_community` and `langchain_openai` at package-import
time no matter which provider you use, and its unpinned requirements on those resolve to
versions that don't import together (see the comments in `pyproject.toml`). Rather than
fight that inside the main app's LangChain 1.x environment, this directory is a separate
`uv` project with its own lockfile, pinned to the LangChain 0.3.x line ragas actually needs.
It talks to the running API over HTTP, so it never needs to import the app's own
LangGraph/Weaviate stack at all.

## Golden dataset

`golden_dataset.jsonl` — 49 question/answer pairs, one JSON object per line:

```json
{"id": "travel-01", "question": "...", "ground_truth": "...", "source": "travel_and_expenses.md"}
```

Every pair is derived from, and hand-verified word-for-word against, the fixture documents
in `fixtures/`. This is a **starter set**, not a substitute for real production curation —
swap in QA pairs from your actual corpus, verified by someone who knows that content, once
you have one. Keep the same schema so `run_eval.py` doesn't need to change.

`ground_truth` isn't used by the faithfulness gate itself (faithfulness only checks the
answer against retrieved context, not against a reference answer) — it's there for manual
review and for future correctness-style metrics.

## Running locally

```bash
cd eval
uv sync
docker compose -f ../docker-compose.yml up -d --build   # from repo root, or reuse a running stack
uv run python run_eval.py --anthropic-api-key "$ANTHROPIC_API_KEY"
```

Useful flags:

- `--api-url` — defaults to `http://localhost:8010`
- `--skip-ingest` — reuse an already-populated index instead of re-ingesting the fixtures
- `--faithfulness-threshold` (default `0.8`) / `--min-answer-rate` (default `0.9`) — gate thresholds
- `--report` — where to write the JSON results (default `eval/report.json`)

Exit code is `0` only if the mean faithfulness score and the answer rate both clear their
thresholds and no sample errored — that's what CI checks.

### Why gate on answer rate too

Faithfulness alone can't catch a system that has started declining everything: a decline
carries no claims, so it can't be unfaithful either. Gating on `--min-answer-rate` as well
catches that failure mode — a good pipeline should actually answer nearly all of these
golden questions, not just avoid being wrong about the ones it attempts.

### Measured baseline

Last clean run against the bundled fixtures: **49/49 answered, mean faithfulness 0.983**.
The two lowest-scoring answers (0.50, 0.67) were, on inspection, fully correct and
verbatim-grounded — the judge's claim-by-claim decomposition scored one sub-claim of a
multi-clause answer conservatively. That's expected LLM-judge noise, not a pipeline defect;
worth knowing so a future dip in the 0.6-0.8 range isn't automatically read as regression
without checking the actual answer text in `report.json` first.

## CI

`.github/workflows/eval.yml` runs this on every pull request: brings up `docker compose`,
waits for health, runs `run_eval.py` against it, uploads `report.json` as an artifact, and
fails the build if the gate fails.
