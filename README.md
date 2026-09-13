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
| `POST /ingest/file` | `.pdf`, `.txt`, `.md`. Magic-byte, size, and encoding checks run before any parser touches the bytes; failures return `400` with a reason. |
| `POST /ingest/url` | `{"url": "..."}` — scrapes and indexes a page. |
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

1. **retrieve** — Weaviate hybrid search scoped to the tenant. A tenant that has never
   written anything short-circuits rather than querying a tenant that doesn't exist.
2. **rerank** — Cohere cross-encoder; chunks below `RERANK_RELEVANCE_THRESHOLD` are dropped.
3. **generate** — drafts a cited answer, or routes straight to **decline** if nothing survived.
4. **verify** — structured-output call checks the draft against the numbered context; an
   ungrounded answer is replaced by the decline message.

## Ingestion

```
Document → validation → parsing → structure detection → chunking
         → metadata enrichment → embedding → Weaviate
```

Chunks are token-bounded (`tiktoken` `cl100k_base`) and never cross a PDF page boundary, so
each one maps to exactly one page and one bounding box — what makes "jump to the cited page
and highlight it" possible. Markdown splits on headers first; web pages have
`script`/`style`/`nav`/`footer`/`header` stripped.

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

Gates on mean faithfulness (default `0.8`) and answer rate (default `0.9`, so the pipeline
can't game faithfulness by declining everything). See `eval/README.md`.

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
