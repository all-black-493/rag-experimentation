# Wakili

Legal research over Kenyan legislation and case law. Every answer is built from passages the
reader can open, and the system says what it consulted to build it.

Two modes. **Search** returns the ranked passages themselves for review. **Ask** synthesises a
grounded answer on top of them, cites each claim to a passage, verifies the answer against its
sources, and declines rather than guesses. A planning step routes each question to
legislation, case law or both, and infers court and year restrictions only when the question
names them.

Modelled on Weaviate's legal-RAG reference architecture — collections by document type, an
agent that inspects the schema → routes → builds filtered queries → reranks → answers — but
self-hosted: the agent is our own LangGraph, not Weaviate Cloud's Query Agent.

## Stack

| | |
|---|---|
| `backend/` | FastAPI · LangGraph · Weaviate (self-hosted) · local embeddings + cross-encoder · Claude · Langfuse |
| `frontend/` | Next.js 16 · TypeScript · Tailwind v4 · a server-side proxy to the backend |
| `corpus/` | 1,533 documents from new.kenyalaw.org: 543 Acts, 990 judgments across 7 courts (not committed, see `corpus/README.md`) |

## Run

```bash
cp backend/.env.example backend/.env       # ANTHROPIC_API_KEY, optional Langfuse keys
docker compose up -d --build               # Weaviate + API on :8010
docker compose exec app python -m app.corpus.ingest /corpus/all_chunks.json
docker compose restart app                 # the catalog is inspected at startup

cd frontend && cp .env.example .env.local && npm install && npm run dev   # :3000
```

Ingest is idempotent per document and resumable; a document left half-indexed by an
interrupted run is redone. Embedding is CPU-bound (~8 chunks/s here): the full corpus is
~85k chunks, so the first ingest takes a couple of hours; re-runs come from the embedding
cache.

## Corpus

The rows arrive as 800-character windows with a fixed 150-character overlap, cut mid-word
four times out of five. Because the overlap is fixed, `app/corpus/documents.py` reconstructs
every document losslessly (verified: all 63,603 windows found verbatim in their document,
0 fallback joins) and re-chunks it with a sentence-aware, small-to-big splitter: 200-token
children are what get embedded, matched and quoted; the window of neighbours around a child
is what the model reads. Court, decision date, year enacted and point-in-time version are
parsed from Kenya Law's URLs.

Two Weaviate collections with explicit schemas (`app/vectorstore/schema.py`), not autoschema:
`Legislation` (title, url, year enacted, version date) and `CaseLaw` (plus court code, court,
decision date). No multi-tenancy — the corpus is shared.

## Retrieval

```
plan → retrieve → rerank → [search] END
                         → [ask]    generate → verify → END / decline
```

- **plan** (`retrieval/planner.py`) — one structured Claude call. Sees the catalog (built
  from the live database: collections, courts and their counts, year bounds) and returns
  1–4 sub-queries, each aimed at one collection, with court/year filters only when the
  question names them. Validated by Pydantic; bounded by the user's own filters, which it
  can narrow but never widen; unknown court codes dropped. Falls back to one unfiltered
  query per collection if the call fails. `PLANNER_ENABLED=false` forces the fallback.
- **retrieve** (`retrieval/retrieve.py`) — hybrid BM25 + vector search per sub-query, filters
  pushed into Weaviate. The original question is always searched too, once per collection
  the plan touches (see the numbers below). A sub-query whose planner filter returns fewer
  than `MIN_CANDIDATES_PER_SUBQUERY` is re-run without it and marked *relaxed*; the user's
  filters are never relaxed. Results are pooled and de-duplicated.
- **rerank** — a local cross-encoder scores every candidate against the *original*
  question; a threshold and a per-mode cut (5 for ask, 10 for search).
- **generate / verify** — a cited answer, then a groundedness judgment. The judge is a
  sampled model call and disagrees with itself a few percent of the time, so a single
  "not grounded" gets one independent second opinion; the answer is withdrawn only if both
  say so. The verifier is deliberately uncached — a cached verdict pinned one unlucky
  judgment on a good answer for the life of the process. Invalid `[n]` markers are
  stripped before the answer leaves; bracketed years in neutral citations (`[2010] eKLR`)
  are not markers.

### Measured

`backend/eval/retrieval_benchmark.py` scores document-level recall of what search mode
returns against the 36-question golden set, over the full corpus (84,429 chunks):

| retrieval | recall@5 | MRR | nDCG@5 |
|---|---|---|---|
| original question only (`PLANNER_ENABLED=false`) | 100.0% | 0.968 | 0.976 |
| planner's sub-queries only | 97.2% | 0.954 | 0.958 |
| **planner + original question** (shipped) | **100.0%** | **0.981** | **0.986** |

The planner's rewrites alone *lost* recall: a paraphrase drops the exact wording keyword
search matches on. Kept as pure expansion — the original always searched, the plan adding
to it — the layer improves ranking rather than costing recall. The golden set has no
court- or year-constrained questions, so the planner's filtering isn't measured by it.

## API

`POST /query` `{question, mode: "search" | "ask", filters?: {collections, courts,
year_from, year_to}}` → `{plan, retrieval, citations, answer?, grounded?}`.
`POST /query/stream` — the same as server-sent events: `plan` → `sources` → `token`… →
`done` (authoritative; may withdraw the streamed preview). `GET /catalog` — what the corpus
contains, for the UI's filters. Rate-limited per client; `PROXY_SECRET` gates everything but
`/health` when set.

## Frontend

A research desk, not a chat: the query slip at the top of the page, the answer as a cited
argument, each `[n]` opening the authority in a bundle beside the page — a bottom sheet on a
phone, a drawer at laptop width, a column from 1280px. The source is never below the answer.
Filters come from `/catalog`. The design world is recorded in `DESIGN.md`; product truth in
`PRODUCT.md`.

`frontend/app/api/[...path]/route.ts` proxies to `BACKEND_URL`, attaching `PROXY_SECRET`
server-side, so the browser stays same-origin and the secret never ships.

## Tracing and quality metrics

Set `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` to enable; blank keys emit nothing. One trace
per query: `plan-query` (chain) → one `weaviate-hybrid-search` (retriever) per sub-query,
with its filters and whether it was relaxed → `rerank-cross-encoder` with each survivor's
prior position → `generate` (prompt version, tokens, cost) → `verify-groundedness`
(evaluator, both verdicts). Scores on the root: `answered`, `grounded`, `failed`,
`citation_coverage`, `invalid_citations`.

```bash
uv run python -m app.metrics --since 7d           # p50/p95 latency, cost, coverage, failures
uv run python -m app.prompt_sync                   # mirror prompts/*.yaml into Langfuse
```

Prompts live in `backend/prompts/*.yaml`, versioned in git; Langfuse mirrors them so
generations link to the version that produced them.

## Evaluation

`backend/eval/` is its own uv project (ragas pins conflict with LangChain 1.x).

- `golden_dataset.jsonl` — 36 questions over the corpus, drafted by `build_golden.py` from
  reconstructed passages and pruned by hand.
- `fixtures/corpus_slice.json` — the golden documents plus 80 distractors (3.9 MB), what CI
  indexes; distractors are what let retrieval fail.
- `run_eval.py` — the faithfulness gate: ragas faithfulness ≥ 0.8, answer rate ≥ 0.9,
  citation coverage ≥ 0.8, zero invalid citations, no API errors.
- `retrieval_benchmark.py` — the table above, in seconds, no judge.

`.github/workflows/eval.yml` runs unit tests, ingests the slice, runs both, on every PR.

## Layout

```
backend/app/
  corpus/       documents (reconstruction), courts, chunking, splitting, parenting, ingest CLI
  vectorstore/  client, schema (explicit collections), search (hybrid), embeddings
  retrieval/    catalog, plan (schema), planner (node), filters, retrieve, rerank,
                answer, grounding, citations, run (one query under one trace), graph (wiring)
  api/          schemas, routes/{query,catalog}, streaming (thread → SSE bridge)
  config, main, dependencies, proxy_auth, rate_limit, caching, resilience, scoring,
  tracing, metrics, prompts, prompt_sync
backend/prompts/   planner, generation, grounding, responses
backend/eval/      the harness above
frontend/          app/ (layout, page, api proxy), components/, lib/ (types, api, stream, hook)
```

## Tests

```bash
cd backend && uv run ruff check app tests eval && uv run pytest
cd frontend && npx tsc --noEmit && npm run lint && npm run build
```
