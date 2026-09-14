# RAG

Ingestion, hybrid Weaviate retrieval with reranking, citation-enforced generation, Langfuse
tracing, and an offline faithfulness eval gate. Documents are isolated per browser session.

## Stack

| | |
|---|---|
| **LangChain / LangGraph** | document loading; the retrieve → rerank → generate → verify graph |
| **FastAPI** | HTTP API, also serves the UI |
| **Weaviate** | vector store, multi-tenant, native hybrid (BM25 + vector) search |
| **Cohere** | embeddings (`embed-v4.0`), reranking (`rerank-v3.5`) |
| **Anthropic Claude** | answer generation, groundedness check |
| **PyMuPDF** | bbox-aware PDF extraction, page thumbnails |
| **Langfuse** | tracing and quality metrics |
| **ragas** | offline faithfulness eval, gates CI (`eval/`) |

## Setup

```bash
cp .env.example .env   # fill in COHERE_API_KEY and ANTHROPIC_API_KEY
docker compose up -d --build
```

Weaviate on `:8080`/`:50051`, API and UI on `:8010`, API docs at `/docs`.

Local iteration without rebuilding:

```bash
uv sync
docker compose up -d weaviate
fastapi dev app/main.py
```

All configuration is environment-driven — see `.env.example` for the full list.

## API

| Endpoint | Notes |
|---|---|
| `POST /ingest/file` | Returns `202` with a job id and indexes in the background. Validation and the malware scan run first, synchronously, so a bad file still gets an immediate `400`. |
| `POST /ingest/url` | `{"url": "..."}` — same, `202` plus a job id. |
| `GET /ingest/jobs/{job_id}` | Job status: `queued`, `running`, `succeeded`, `failed`. Scoped to the session that created it; another session gets `404`. |
| `POST /query` | `{"question": "..."}` → `{answer, citations}`. Inline `[1]`, `[2]` markers match `citations[i].index`. Returns a fixed decline message with no citations if nothing relevant is retrieved or the answer fails the groundedness check. |
| `GET /files/{doc_id}` | The original PDF, session-scoped. Supports range requests. 404s (not 403) on a wrong session, so existence never leaks. |
| `GET /files/{doc_id}/thumbnail/{page}` | Rendered page image for the hover preview, session-scoped. |
| `GET /favicons/{domain}` | Cached favicon bytes. Public. |
| `GET /thumbnails/{key}` | Cached `og:image` for a web citation. Public, opaque key. |

Every request carries `X-Session-Id`; it selects the Weaviate tenant. Absent or malformed,
it falls back to a shared `default` tenant.

## Retrieval pipeline

```
retrieve --(candidates)--> rerank --(any survive threshold?)--> generate -> verify -> END
                                  \--(none survive)--> decline -> END
                                                          ^
                                          (verify says ungrounded)
```

1. **retrieve** — Weaviate hybrid search (BM25 + vector) scoped to the tenant, with optional
   metadata filters pushed into the query. A tenant that has never written anything
   short-circuits rather than querying a tenant that doesn't exist.
2. **rerank** — Cohere cross-encoder over 60 candidates, keeping 5 above
   `RERANK_RELEVANCE_THRESHOLD`. Behind a circuit breaker: if it's unavailable, retrieval
   order is used instead of failing the query.
3. **generate** — drafts a cited answer, or routes straight to **decline** if nothing survived.
4. **verify** — structured-output call checks the draft against the numbered context; an
   ungrounded answer is replaced by the decline message.

### Metadata filtering

`POST /query` takes an optional `filters` object — `source_types`, `sources`, `doc_ids`,
`page_from`/`page_to`, ANDed. They become Weaviate `Filter` objects pushed into the hybrid
query, so filtering happens **before** ranking. Post-filtering a fixed candidate pool is the
tempting shortcut and it silently destroys recall: ask for 60 and filter after, and a narrow
filter can leave three.

Filters only ever narrow. Tenancy, not filters, is what bounds visibility.

### Hybrid fusion: measured, not assumed

`HYBRID_FUSION` selects how BM25 and vector rankings combine — `relative`
(relativeScoreFusion, Weaviate's default) or `ranked` (reciprocal rank fusion).

`eval/retrieval_benchmark.py` scores retrieval on its own, deterministically, against the
`source` recorded for each golden question — no LLM judge, so it runs in seconds:

```bash
uv run python eval/retrieval_benchmark.py --compare --k 1 --tenant <tenant>
```

On a 142-chunk corpus (the 6 fixtures plus topic-adjacent Wikipedia distractors):

| fusion | recall@1 | MRR@5 | nDCG@5 |
|---|---|---|---|
| relativeScoreFusion | **95.9%** | **0.973** | **0.980** |
| rankedFusion (RRF) | 91.8% | 0.949 | 0.957 |

RRF lost at every cutoff, so the default stays `relative`. The instinct behind RRF — use
ranks, ignore incomparable score scales — is sound when fusing genuinely independent
retrievers, but here BM25 is the noisier signal and RRF gives its ranking equal standing
with the vector ranking's.

Two caveats worth keeping in mind: the gap is ~2 questions out of 49, which is not
statistically strong, and against the *original* 6-chunk fixture corpus the two strategies
scored **identically** (every query returned the whole corpus, so recall was 100% by
construction). That is why the distractors exist — a benchmark that can't fail can't choose.

## Ingestion

```
upload → validate → malware scan → parse → extract structure → normalize
       → chunk → attach provenance → embed → index
```

Accepts `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.csv`, `.tsv`, `.json`, `.html`, `.md`, `.rst`,
`.txt`, `.log`, plus URLs.

- **Validate** — extension, size, magic bytes, UTF-8 decodability, before any parser runs.
- **Malware scan** — clamd over TCP, **off by default** (`MALWARE_SCAN_ENABLED`); the
  service is behind a compose profile because its signature database is slow to load:
  `docker compose --profile scanning up -d`. When enabled and the scanner is unreachable the
  upload is **refused**, not waved through.
- **Normalize** — NFKC folding, invisible characters, NBSP, PDF line-break hyphenation.
  Conservative by design: it never lowercases or restructures, because chunking and bbox
  highlighting depend on the text still matching the source.
- **Chunk** — token-bounded (`tiktoken` `cl100k_base`), never crossing a PDF page boundary,
  so each chunk maps to one page and one bounding box.

Ingestion is **content-addressed**: the doc id is a hash of the bytes, so re-uploading the
same file is idempotent — it skips parsing, chunking and embedding entirely rather than
indexing a second copy. Identical content is never re-embedded.

It's also **asynchronous**. The request returns a job id in ~50ms instead of holding the
connection open for the whole index (~2s for a small text file, minutes for a large PDF);
the client polls `/ingest/jobs/{id}`. Concurrency is bounded (`INGEST_CONCURRENCY`, default
2) because the embedding provider is rate-limited — more parallelism buys 429s and retry
backoff, not throughput.

Jobs live in the app process: a restart loses in-flight work, and status is only known to
the instance that accepted it. That's fine for one container, and `JobRegistry` is the seam
to swap for Redis/Celery when there's more than one.

## Citations

Citations are built entirely from each chunk's own metadata (`build_citations()` in
`app/retrieval/citations.py`). The LLM sees numbered context and writes `[n]` markers; it
never supplies the citation metadata. `source_type` (`"pdf" | "web" | "text"`) is set at
ingestion and immutable thereafter — the frontend uses it to decide whether a citation opens
the PDF viewer, opens a link, or scrolls to itself.

PDF citations carry `doc_id`/`page`/`bbox`; web citations carry `favicon_url`. Both carry a
`thumbnail_url` for the hover preview, pre-rendered at ingestion.

## Tracing and quality metrics

Set `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` to enable. Blank keys disable tracing
entirely — the pipeline is unchanged, it just emits nothing. One trace per `/query`:

```
rag-query                              root; session_id = tenant
└── LangGraph
    ├── retrieve → weaviate-hybrid-search   (retriever) candidate chunks, full text
    ├── rerank   → cohere-rerank            (retriever) survivors + relevance_score, moved_from
    ├── generate → ChatAnthropic            (generation) prompt, answer, model, tokens, cost
    └── verify   → verify-groundedness      (evaluator) groundedness verdict
```

The LangChain callback handler covers the LLM calls; retrieval and reranking get explicit
observations via `app/tracing.py` since they aren't LangChain components.

Traces carry the full text of retrieved chunks, so the Langfuse project holds the same
content as the documents themselves.

Each request also carries scores, which is what makes quality trackable over time:
`answered`, `grounded`, `failed`, `citation_coverage` (share of answer sentences carrying a
`[n]` marker) and `invalid_citations` (markers pointing at citations that don't exist).
Computed in `app/scoring.py` — deterministic, no second LLM call.

```bash
uv run python -m app.metrics --follow            # live, one line per query as it lands
uv run python -m app.metrics --since 7d          # p50/p95 latency, cost, coverage, failures
uv run python -m app.metrics --since 14d --daily # one row per day, to spot the bad day
uv run python -m app.metrics --day 2026-09-08    # that day, plus its slowest traces
```

`--follow` polls (the Langfuse API is REST — there's no subscription endpoint), so a query
shows up within one interval, default 3s.

Gotcha: the root span must be opened on the thread the graph runs on — OTel context is
thread-local and the route dispatches via `asyncify`.

## Layout

```
prompts/                  Versioned prompts (generation, grounding, decline message)
frontend/                 Plain HTML/CSS/JS, no build step; served by app.frontend()
app/
  config.py               Settings (env-driven)
  metadata.py             SourceType literal, shared vocabulary
  prompts.py              Loads prompts/*.yaml into versioned templates
  dependencies.py         FastAPI deps: settings, vector store, graph, tenant
  rate_limit.py           slowapi limiter, keyed by session id
  storage.py              Uploaded PDFs + page thumbnails, scoped by tenant
  favicons.py             Domain-keyed favicon cache
  thumbnails.py           og:image extraction + cache
  tracing.py              Langfuse setup; no-ops without keys
  metrics.py              Quality metrics CLI over the Langfuse API
  scoring.py              Citation coverage, computed per answer
  main.py                 App factory + lifespan
  api/                    Schemas, one router per resource
  ingestion/              validation, loaders, pdf, splitting, pipeline
  retrieval/              state, graph, prompts, grounding, citations, reranker
  vectorstore/            client, store, embeddings
eval/                     Offline faithfulness harness, isolated uv project
.github/workflows/        eval.yml — runs the eval on every PR
```

## Faithfulness evaluation

`eval/` is a self-contained offline harness in its own `uv` project. It ingests a fixture
corpus, runs 49 hand-verified golden questions against the live `/query` API, and scores
answers with ragas's Faithfulness metric.

```bash
cd eval && uv sync
uv run python run_eval.py --anthropic-api-key "$ANTHROPIC_API_KEY"
```

It gates on four thresholds, and the build fails if any of them slips:

| Check | Default | Flag |
|---|---|---|
| mean faithfulness | `0.8` | `--faithfulness-threshold` |
| answer rate | `0.9` | `--min-answer-rate` |
| citation coverage | `0.8` | `--min-citation-coverage` |
| invalid citations | `0` | `--max-invalid-citations` |

Answer rate is there so the pipeline can't game faithfulness by declining everything.
Coverage is computed with the same `app/scoring.py` the app scores live with, rather than a
copy, so the gate and the dashboard can't drift apart. See `eval/README.md`.

`main` is protected: the eval must pass before a pull request can merge, so work happens on
a branch.

## Prompt management

Prompts live in `prompts/*.yaml` and are versioned in git — that's the source of truth.
Langfuse mirrors them:

```bash
uv run python -m app.prompt_sync --dry-run
uv run python -m app.prompt_sync        # after merging a prompt change
```

The direction matters. Authoring prompts in the Langfuse UI would let a prompt change alter
production behaviour with no pull request and no eval — the exact path the gate above
exists to close. Keeping them in the repo makes a prompt change a code change.

What Langfuse adds is the version history, the Playground, and the link from each
generation back to the prompt version that produced it, so latency, cost and scores can be
grouped by prompt version when something regresses.

## Notes

- `WEAVIATE_HOST` is `localhost` for host-side runs; docker-compose overrides it to
  `weaviate` for the container, so both work unmodified.
- Uploaded PDFs live in the `pdf_uploads` volume at `/app/data/uploads`. Enabling
  multi-tenancy on an existing collection requires recreating it — drop `Chunk` once.
- Session ids fall back to `crypto.getRandomValues()` when `crypto.randomUUID()` is absent
  (it needs a secure context, which `http://<lan-ip>` isn't).
- `frontend/recoleta/Recoleta-RegularDEMO.otf` is a demo weight — check Latinotype's license
  before shipping.

## Tests

```bash
pytest
```
