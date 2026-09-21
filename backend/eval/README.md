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

`golden_dataset.jsonl` — 36 questions over the corpus (19 legislation, 17 case law), one
JSON object per line:

```json
{"id": "case_law-03", "question": "...", "ground_truth": "...",
 "source": "https://new.kenyalaw.org/akn/ke/judgment/kemc/2025/174/eng@2025-08-01",
 "collection": "case_law", "title": "Republic v Oundo ..."}
```

Drafted by `build_golden.py` from a passage of each sampled document, then read and pruned
by hand: header-lookup questions ("which judge, which station") and vague "which Acts were
cited" ones were cut. `source` is the document URL the retrieval benchmark scores against.
`ground_truth` isn't used by the faithfulness gate (which judges the answer against the
retrieved passages, not a reference) — it's there for review and future correctness metrics.

## Running

The corpus must be indexed first. Locally that's the full corpus; in CI it's
`fixtures/corpus_slice.json` (the golden documents plus 80 distractors), loaded
with the same ingest CLI:

```bash
docker compose cp backend/eval/fixtures/corpus_slice.json app:/tmp/corpus_slice.json
docker compose exec app python -m app.corpus.ingest /tmp/corpus_slice.json
docker compose restart app          # the catalog is inspected at startup

cd backend/eval
uv run python retrieval_benchmark.py --label planner   # seconds, no judge
uv run python run_eval.py --anthropic-api-key ...       # the gate
```

## Regenerating the golden set

```bash
uv run python build_golden.py ../../corpus/all_chunks.json --anthropic-api-key ...
uv run python corpus_slice.py ../../corpus/all_chunks.json
```

`build_golden.py` drafts questions from reconstructed passages; the output is a draft to
be read and pruned by hand before it's committed. `corpus_slice.py` re-cuts the CI slice
around whatever the golden set references.
