# RAG

Ingestion, hybrid Weaviate retrieval with reranking, citation-enforced generation, an
offline faithfulness eval gate, and per-session document isolation.

## Stack

- **LangChain** — document loading glue, prompt templates
- **LangGraph** — the retrieve → rerank → generate → verify pipeline
- **FastAPI** — HTTP API, serving the UI too
- **Weaviate** — vector store, multi-tenant, running native hybrid (BM25 + vector) search
- **Cohere** — embeddings (`embed-v4.0`) and cross-encoder reranking (`rerank-v3.5`)
- **Anthropic Claude** — answer generation and groundedness verification
- **PyMuPDF** — bounding-box-aware PDF extraction, for citations that highlight the exact
  quoted region
- **ragas** — offline faithfulness evaluation, gating CI (see `eval/`)

## Setup

```bash
cp .env.example .env   # fill in COHERE_API_KEY and ANTHROPIC_API_KEY
docker compose up -d --build
```

This builds and runs the whole stack: Weaviate on `:8080`/`:50051`, the API on
`:8010`. Visit `http://localhost:8010` for the UI, or `/docs` for interactive
API docs.

For local iteration without rebuilding the image each time:

```bash
uv sync
docker compose up -d weaviate
fastapi dev app/main.py   # WEAVIATE_HOST=localhost from .env applies here
```

## UI

A static single-page console at `/` — add sources (file upload or URL) in the sidebar,
ask questions in the main panel, which reads as a running transcript (most recent turn on
top). A declined answer renders as a distinct callout instead of a normal answer. Dark
theme only, by design.

Ingestion accepts up to 5 files and up to 3 URLs (one per line) per batch. Items are
indexed sequentially, not in parallel, with an indeterminate progress bar and a live
`"Indexing N of M: <name>…"` status so the user is never left wondering whether anything
is happening in the background. Each item's success or failure is independent — a batch
ends with a summary like `Indexed 4, 1 failed - report.pdf: <reason>` rather than an
all-or-nothing result.

Answers render as sanitized markdown (`marked` + `DOMPurify`, vendored locally — no CDN
at runtime). Inline `[n]` citation markers are real buttons, and the entire citation
(including its favicon, for web sources) is clickable: for a PDF citation, clicking one
opens the source PDF at the cited page with the exact quoted region highlighted (PDF.js,
lazy-loaded); for a web citation, it opens the source URL in a new tab; for any other
source, it jumps to the citation's entry in the list below the answer instead.

Hovering a citation on a pointer device shows a preview of what it points at: the
rendered image of the cited PDF page, or the site's own `og:image` for a web source. Both
are generated once at ingestion, never on hover. The card is suppressed entirely on touch
screens (`(hover: hover) and (pointer: fine)`), where there's no hover to reveal it and a
tap opens the source outright, and on windows too narrow for the gutter it sits in.

The PDF viewer is a collapsible panel beside the thread rather than a modal — reading the
cited page doesn't block the conversation behind it, and collapsing it hands the width
back to the chat. On phones it becomes a bottom sheet pinned to the viewport instead of a
section appended below the thread, so a citation tap shows the page immediately rather
than after scrolling past the whole conversation.

Typography follows a deliberate split: Recoleta (serif) for the wordmark and in-answer
headings, Inter for body copy and labels, monospace (IBM Plex Mono) for buttons, small
UI labels, filenames, and citation source labels — a technical/editorial contrast rather
than one uniform UI font.

It's plain HTML/CSS/JS served directly by FastAPI's `app.frontend()` — no build step or
dev server; it calls the same-origin API below, sending `X-Session-Id` (a UUID generated
once per browser and kept in `localStorage`) on every request.

> Note: `frontend/recoleta/Recoleta-RegularDEMO.otf` is a demo weight — check Latinotype's
> license before shipping this to real users; swap in a licensed weight for production.

Session ids are generated with `crypto.randomUUID()` where available, falling back to
`crypto.getRandomValues()` (and finally `Math.random()`) otherwise — `randomUUID` requires
a secure context (HTTPS or `localhost`), which a phone hitting the app over plain
`http://<lan-ip>:8010` doesn't satisfy. See `generateId()` in `frontend/api.js`.

## Citations are structured, not LLM-authored

Every citation the UI renders is built entirely from the retrieved chunk's own metadata —
`build_citations()` in `app/retrieval/citations.py` reads `source`, `title`, `source_type`,
`page`, `doc_id`, `bbox`, `page_width`, `page_height`, and `favicon_url` off each
`Document.metadata` dict and nothing else. The LLM only ever sees numbered context and
writes `[n]` markers pointing at it; it never generates, sees, or has a chance to
hallucinate the underlying citation metadata. `source_type` (`SourceType` in
`app/metadata.py`, one of `"pdf" | "web" | "text"`) is set once at ingestion and carried
immutably through chunking, embedding, and retrieval — it's what the frontend uses to
decide whether a citation opens the PDF viewer, opens a link, or just scrolls to itself.

Web citations carry a `favicon_url` (`/favicons/{domain}`, domain derived from the
ingested URL via `urlparse`, at ingestion time — never asked of the LLM). Favicons
themselves are fetched at most once per domain: `app/favicons.py` tries `https://
{domain}/favicon.ico` first, falls back to Google's public favicon service, and caches
the bytes + content-type to disk (`data/favicons/`) so a repeat request for the same
domain — from any session — never triggers a new outbound request.

## Sessions and isolation

There's no auth — anonymous use is intentional — but each browser session's documents
are isolated from every other session's via Weaviate multi-tenancy, keyed by the
`X-Session-Id` header. A request without that header (or with a malformed one) falls back
to a shared `default` tenant rather than erroring. This is isolation by convention, not a
security boundary: a client that sends someone else's session id sees that session's
documents, the same way knowing someone's URL would. See `get_tenant` in
`app/dependencies.py`.

`/ingest/*` and `/query` are rate-limited per session (falling back to per-IP when no
session header is present) via `slowapi` — see `RATE_LIMIT_INGEST`/`RATE_LIMIT_QUERY` in
`.env.example`. This is the abuse guard anonymous access needs in place of auth.

## API

- `POST /ingest/file` — multipart file upload (`.pdf`, `.txt`, `.md`). Validated before
  parsing ever begins: magic-byte check for PDFs (`%PDF-`), UTF-8 decodability for text
  files, and a size cap (`MAX_UPLOAD_SIZE_MB`, default 20) — a file that fails any of
  these gets a `400` with a specific reason instead of being handed to a parser.
- `POST /ingest/url` — `{"url": "https://..."}`, scrapes and indexes a web page
- `POST /query` — `{"question": "..."}`, returns `{answer, citations}` where `answer`
  cites passages inline as `[1]`, `[2]`, ... matching `citations[i].index`. Each citation
  carries `source_type` (`"pdf" | "web" | "text"`) and the chunk's `text`; PDF citations
  also carry `doc_id`, `bbox`, `page_width`, `page_height` for the viewer, and web
  citations carry `favicon_url`. If retrieval turns up nothing relevant, or the drafted
  answer doesn't hold up under a groundedness check, `answer` is a fixed decline message
  and `citations` is empty rather than a plausible-sounding guess.
- `GET /files/{doc_id}` — the original uploaded PDF, scoped to the requesting session;
  404s (not 403) for a wrong session or a malformed id, so existence never leaks.
- `GET /favicons/{domain}` — cached favicon bytes for a web citation's domain; serves from
  disk cache after the first request, `Cache-Control: public, max-age=86400`.
- `GET /files/{doc_id}/thumbnail/{page}` — the rendered image of one PDF page, for the
  hover preview. Session-scoped like the PDF itself, so the frontend fetches it with the
  session header and uses a blob URL: a plain `<img src>` can't send custom headers and
  would just 404.
- `GET /thumbnails/{key}` — a cached web page preview image (`og:image`), keyed by a hash
  of the image URL. Not session-scoped, since it's public content under an opaque key.

## Layout

```
prompts/
  generation.yaml       Answer-generation prompt (versioned)
  grounding.yaml         Groundedness-check prompt (versioned)
  responses.yaml          Canned decline message (versioned)
frontend/
  index.html            Structure, incl. the PDF viewer <dialog>
  styles.css              Design tokens + component styles
  api.js                    Fetch wrappers; attaches X-Session-Id to every request
  pdf-viewer.js             Lazy-loads PDF.js, renders a page, draws the highlight
  app.js                    DOM wiring, markdown rendering, citation interaction
  vendor/                 marked, DOMPurify, PDF.js - fetched pinned, not CDN-loaded
  recoleta/               Headline serif font file
app/
  config.py             Settings (env-driven)
  metadata.py            SourceType literal ("pdf" | "web" | "text"), shared vocabulary
  prompts.py             Loads prompts/*.yaml into versioned ChatPromptTemplates
  dependencies.py        FastAPI dependencies: settings, vector store, graph, tenant
  rate_limit.py           slowapi Limiter, keyed by session id (falls back to IP)
  storage.py              Persists/serves uploaded PDFs + page thumbnails, by tenant
  favicons.py              Domain-keyed favicon fetch + disk cache
  thumbnails.py             og:image extraction + disk cache for web previews
  tracing.py                 Langfuse setup; no-ops when keys are absent
  main.py                  App factory + lifespan (wires client/store/graph/limiter)
  api/
    schemas.py            Request/response models
    routes/               One router per resource (ingestion, query, files, favicons)
  ingestion/
    validation.py          Magic-byte/size/encoding checks, run before any parsing
    loaders.py            Text/markdown/web -> Document
    pdf.py                  Bounding-box-aware PDF extraction + chunking
    splitting.py            Token-bounded chunking for non-PDF sources
    pipeline.py              load -> chunk -> index (PDFs take the pdf.py path)
  retrieval/
    state.py                LangGraph state schema (includes tenant)
    graph.py                 retrieve -> rerank -> generate -> verify -> decline
    prompts.py                Loads the generation prompt from the registry
    grounding.py               Loads the grounding prompt + decline message
    citations.py                Numbered context + citation extraction
    reranker.py                  Cohere cross-encoder reranker factory
  vectorstore/
    client.py                Weaviate connection lifecycle (retries on startup)
    store.py                  WeaviateVectorStore wiring (multi-tenant) + tenant_exists
    embeddings.py              Cohere embeddings factory
eval/
  golden_dataset.jsonl   49 hand-verified QA pairs (see eval/README.md)
  fixtures/               Source documents the golden set is derived from
  run_eval.py              Faithfulness eval CLI, isolated uv project
.github/workflows/
  eval.yml                Runs the eval on every PR, fails the build below threshold
```

## Retrieval pipeline

```
retrieve --(candidates)--> rerank --(any survive threshold?)--> generate -> verify -> END
                                  \--(none survive)--> decline -> END
                                                          ^
                                          (verify says ungrounded)
```

1. **retrieve** — Weaviate hybrid search, scoped to the request's tenant (`HYBRID_ALPHA`
   blends BM25 and vector similarity server-side), pulls `RETRIEVAL_CANDIDATES`
   candidates. A tenant that has never written anything short-circuits to no documents
   rather than querying a Weaviate tenant that doesn't exist yet.
2. **rerank** — Cohere's cross-encoder scores each (query, chunk) pair; chunks below
   `RERANK_RELEVANCE_THRESHOLD` are dropped, the rest kept to `RERANK_TOP_N`.
3. **generate** — drafts a cited answer from the surviving chunks, or the graph routes
   straight to **decline** if none survived reranking.
4. **verify** — a structured-output LLM call checks every claim in the draft against the
   numbered context; an ungrounded answer is replaced by the same decline message instead
   of being returned.

## Ingestion defense layers

Every document — file or URL — passes through the same sequence before it's queryable:

```
Document -> File Validation -> Parsing -> Structure detection -> Chunking
         -> Metadata enrichment -> Embedding -> Vector DB
```

- **File validation** (`app/ingestion/validation.py`) — magic bytes, size cap, encoding;
  runs on raw bytes before any parser touches the file. See the `/ingest/file` entry above.
- **Parsing** (`app/ingestion/loaders.py`, `app/ingestion/pdf.py`) — format-specific
  extraction: PyMuPDF for PDFs, `httpx`+`bs4` for URLs, plain read for text/markdown.
- **Structure detection** — PDFs keep PyMuPDF's block-level layout (paragraph boundaries,
  per-block bounding boxes); Markdown splits on headers before falling back to a token
  budget; web pages have `script`/`style`/`nav`/`footer`/`header` tags stripped first.
- **Chunking** (`app/ingestion/splitting.py`, `app/ingestion/pdf.py`) — token-bounded
  (`tiktoken` `cl100k_base`), never crossing a PDF page boundary.
- **Metadata enrichment** — every chunk gets `source`, `title`, `source_type`, and
  format-specific fields (`page`/`bbox`/`page_width`/`page_height` for PDFs,
  `favicon_url` for web) attached to `Document.metadata` before embedding. This is the
  metadata `build_citations()` later reads verbatim — see "Citations are structured, not
  LLM-authored" above.
- **Embedding** (`app/vectorstore/embeddings.py`) — Cohere `embed-v4.0`.
- **Vector DB** (`app/vectorstore/store.py`) — written to Weaviate, tenant-scoped, with
  `CITATION_ATTRIBUTES` as the fixed set of metadata fields Weaviate is allowed to return
  alongside a chunk.

Once written, chunk metadata is immutable — nothing downstream of ingestion (retrieval,
reranking, generation) ever edits a `Document`'s metadata; it's only ever read.

## PDF citations with page + highlight

PDFs skip the generic text-splitter path. `app/ingestion/pdf.py` extracts PyMuPDF's
paragraph-level text blocks with their page-space bounding boxes, then packs them into
token-budgeted chunks that never cross a page boundary — each chunk ends up with exactly
one page number and one bounding box (the union of the blocks it's made of). The original
PDF is saved via `app/storage.py`, keyed by a generated `doc_id` plus the uploading
session's tenant.

When a citation with a `doc_id` is clicked, `pdf-viewer.js` hands PDF.js the *URL* of that
PDF (session-scoped, `GET /files/{doc_id}`) rather than a pre-fetched buffer, renders the
cited page, and draws the highlight by scaling the stored bbox by the same factor used to
render the page — PyMuPDF's coordinate space is already top-left/y-down, the same
convention `<canvas>` uses, so no axis flip is needed.

Passing a URL is what makes large PDFs open quickly: PDF.js drives its own ranged fetches
against it, and Starlette's `FileResponse` already answers `Range` with `206 Partial
Content`, so a citation deep in a large document pulls the cross-reference table plus that
one page instead of the whole file. `disableAutoFetch` stops PDF.js from backfilling the
remaining pages in the background — this viewer only ever renders the single cited page.
(Handing it an `ArrayBuffer` instead, as an earlier version did, forces the entire file to
download before anything can render, however few of its pages you actually want.)

## Tracing with Langfuse

Every `/query` emits one trace, so a bad answer can be read back step by step rather than
guessed at. Set `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` to turn it on; leave them blank
and the pipeline runs unchanged without emitting spans, which is what CI and local runs do.

```
rag-query                     (span, root - session_id = the tenant, so one browser
│                              session's questions group together)
└── LangGraph
    ├── retrieve
    │   └── weaviate-hybrid-search   (retriever) every candidate chunk, full text
    │                                 plus source/page/doc_id
    ├── rerank
    │   └── cohere-rerank            (retriever) survivors with relevance_score and
    │                                 moved_from, so the reordering is legible
    ├── generate
    │   └── ChatAnthropic            (generation) rendered prompt, answer, model,
    │                                 token usage, cost, prompt version
    └── verify
        └── verify-groundedness      (evaluator) the groundedness verdict
            └── ChatAnthropic        (generation)
```

The LangChain callback handler covers the two LLM calls automatically - that's where model
name, token counts, and Langfuse's cost calculation come from. Retrieval and reranking
aren't LangChain components (they call Weaviate and Cohere directly), so `app/retrieval/graph.py`
wraps them in explicit observations via `app/tracing.py`. Observation types are deliberate:
`retriever` for the two lookup steps and `evaluator` for the groundedness check, since those
drive filtering and the agent graph.

Two things worth knowing if you extend this:

- **The root span must be opened on the thread the graph runs on.** The active observation
  lives in OpenTelemetry's context, which is thread-local, and the route hands the graph to
  a worker thread via `asyncify`. That's why `_run_graph` in `app/api/routes/query.py` is a
  plain sync function rather than the root being opened in the async handler.
- **Traces are buffered and flushed on shutdown** (`shutdown_tracing` in the lifespan).
  Without that, a short-lived process exits with its spans still in the buffer.

Traces carry the full text of retrieved chunks - that's the point, since "which chunks did
it actually see" is the question a trace has to answer - so treat the Langfuse project as
holding the same content as the documents themselves.

## Prompts are versioned config, not code

Every prompt sent to an LLM — and the canned decline message — lives in `prompts/*.yaml`
as `{version, system, human}` (or `{version, <field>}` for plain text), not as a Python
string literal. `app/prompts.py` loads them into `VersionedPrompt`/`VersionedText` objects
and logs the name + version in use. Changing a prompt's wording is a config diff in
`prompts/`, not a code change in `app/retrieval/`; bumping its `version` field is how you
track which prompt revision produced a given answer.

## Faithfulness evaluation (Phase 3)

`eval/` is a self-contained offline harness, in its own `uv` project (see
`eval/README.md` for why it's isolated from the app's dependencies). It ingests a small
bundled fixture corpus, runs 49 hand-verified golden questions against the live `/query`
API, and scores each answer with ragas's Faithfulness metric — do the answer's claims
actually hold up against the chunks it cited, independent of whether the wording matches
a reference answer.

```bash
cd eval
uv sync
uv run python run_eval.py --anthropic-api-key "$ANTHROPIC_API_KEY"
```

The gate checks two thresholds: mean faithfulness (default `0.8`) and answer rate
(default `0.9`, so a pipeline can't game faithfulness by declining everything). Last
clean run: 49/49 answered, mean faithfulness 0.983. See `eval/README.md` for the full
design, including why it uses ragas's legacy `LangchainLLMWrapper(bypass_temperature=True)`
path instead of the new collections API.

`.github/workflows/eval.yml` runs this on every pull request and fails the build if either
threshold isn't met. It expects `COHERE_API_KEY` and `ANTHROPIC_API_KEY` as repo secrets.

## Design notes

- Chunking targets `CHUNK_SIZE_TOKENS`/`CHUNK_OVERLAP_TOKENS` (default 650/100) measured
  with `tiktoken`'s `cl100k_base` encoding, used purely as a size proxy independent of the
  generation model. PDFs use the same budget but pack whole text blocks rather than
  splitting arbitrarily, to keep each chunk's bounding box meaningful.
- Markdown files split on headers first (`RecursiveCharacterTextSplitter` with
  `Language.MARKDOWN` separators) before falling back to the same token budget.
- Web loading uses `httpx`+`bs4` directly rather than `langchain-community`, which is
  being sunset upstream.
- No LangSmith/tracing wiring by design.
- `WEAVIATE_HOST` is `localhost` in `.env` for host-side runs; docker-compose overrides it
  to `weaviate` for the containerized app so both work unmodified.
- Uploaded PDFs persist in the `pdf_uploads` docker volume, mounted at
  `/app/data/uploads`; enabling Weaviate multi-tenancy on an existing collection requires
  recreating it (drop `Chunk` via Weaviate's schema API once after upgrading).

## Tests

```bash
pytest
```
