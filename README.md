# Wakili

Legal research over Kenyan legislation and case law. Every answer is built from passages the
reader can open, and the system says what it consulted to build it.

Three modes. **Search** returns the ranked passages themselves for review. **Ask** synthesises a
grounded answer on top of them, cites each claim to a passage, verifies the answer against its
sources, and declines rather than guesses. **Research** reads what the first pass found,
searches again for what it missed and for the other side, and writes a memo. A planning step
routes each question to legislation, case law, the user's own documents or all three, and
infers court and year restrictions only when the question names them.

Modelled on Weaviate's legal-RAG reference architecture — collections by document type, an
agent that inspects the schema → routes → builds filtered queries → reranks → answers — but
self-hosted: the agent is our own LangGraph, not Weaviate Cloud's Query Agent.

## Stack

| | |
|---|---|
| `backend/` | FastAPI · LangGraph · Weaviate (self-hosted) · local embeddings + cross-encoder · PyMuPDF · Claude · Langfuse |
| `frontend/` | Next.js 16 · TypeScript · Tailwind v4 · a server-side proxy to the backend |
| `corpus/` | 1,533 documents from new.kenyalaw.org: 543 Acts, 990 judgments across 7 courts (not committed, see `corpus/README.md`) |

## Run

```bash
cp backend/.env.example backend/.env       # ANTHROPIC_API_KEY, optional Langfuse keys
docker compose up -d --build               # Weaviate + API on :8010
docker compose exec app python -m app.corpus.ingest /corpus/all_chunks.json
docker compose exec app python -m app.graph.build    # citation graph, ~1 min, no model calls
docker compose restart app                 # catalog and graph are loaded at startup

cd frontend && cp .env.example .env.local && npm install && npm run dev   # :3000
```

### Local models

Every model call can go to Ollama instead of Anthropic, so measuring costs nothing:

```bash
LLM_PROVIDER=ollama docker compose --profile ollama up -d      # adds the ollama service
docker compose exec ollama ollama pull qwen3:8b                 # ~5 GB, once
```

`OLLAMA_MODEL` (answers, memos, reports, the verifier) and `OLLAMA_FAST_MODEL` (planner,
review, profiles, extraction) default to `qwen3:8b`; a machine with the memory can run
`qwen3:14b` or `qwen3:30b` for the first. Thinking is off (`OLLAMA_REASONING`) — every
structured call is JSON, not reasoning, and on a CPU thinking doubles the time. The context
window is 16k (`OLLAMA_NUM_CTX`): a memo prompt carries twelve parent windows. An NVIDIA GPU
needs the device reservation commented in `docker-compose.yml`; a host install instead of
the service is `OLLAMA_BASE_URL=http://host.docker.internal:11434`. The eval harness's judge
can be local too: `run_eval.py --judge-model ollama:qwen3:8b`.

One factory, `app/llm.py`, builds both roles for either provider; nothing downstream knows
which it has.

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
decision date). No multi-tenancy — the corpus is shared. A third, `MatterDocument`, holds the
user's own documents, one tenant per matter (below).

## Matters

A matter is the user's own file: the lease, the demand letter, the witness statement. Its
documents are indexed beside the corpus and searched with it, so "what does the law say"
and "what does my contract say" are one question.

`POST /matters {name}` · `POST /matters/{id}/documents` (PDF, Word, text; validated on the
request, indexed in the background, status on the matter) · `DELETE …/documents/{doc_id}` ·
`GET …/files/{doc_id}` (the original, with range requests for the viewer). `POST /query`
takes `matter_id`; the matter is then a third collection the planner can route to, told
what each document is by a profile (summary, type, parties, dates) one model call reads off
it after indexing. A PDF chunk never spans a page and carries the union box of its blocks,
so a citation opens the page with the passage highlighted. Deletion removes chunks first,
then the file and the record. Originals live under `data/matters/<id>/`.

## Retrieval

```
plan → retrieve → expand → topics → rerank → [search]   END
                                           → [ask]      generate → verify → END / decline
                                           → [research] review → (follow-ups) retrieve …
                                                               → generate → verify → END / decline
```

- **plan** (`retrieval/planner.py`) — one structured call to a small fast model
  (`PLANNER_MODEL`, Haiku), cached per question + filters. Sees the catalog (built from the
  live database: collections, courts and their counts, year bounds; refreshed on a TTL) and
  returns 1–4 sub-queries, each aimed at one collection, with court/year filters only when
  the question names them, plus a `relationships` flag for questions about how authorities
  relate. Validated by Pydantic; bounded by the user's own filters, which it can narrow but
  never widen; unknown court codes dropped. Falls back to one unfiltered query per
  collection if the call fails. `PLANNER_ENABLED=false` forces the fallback.
- **retrieve** (`retrieval/retrieve.py`) — hybrid BM25 + vector search per sub-query, in
  parallel, filters pushed into Weaviate. The original question is always searched too,
  once per collection the plan touches (see the numbers below). A sub-query whose planner
  filter returns fewer than `MIN_CANDIDATES_PER_SUBQUERY` is re-run without it and marked
  *relaxed*; the user's filters are never relaxed. Results are pooled and de-duplicated.
- **expand** (`retrieval/expand.py`) — the citation graph widens the pool, in memory, in
  milliseconds. An authority the question names (`Kaingu Elias Kasono v Republic`,
  `section 8(1) of the Sexual Offences Act`) brings in the exact passages that cite it; a
  relational question also brings in the best passage of each document one hop from the
  top candidates. Bounded, filtered by the user's restrictions, and every added passage is
  tagged with why it is there (`via: "applies section 8(1) of the Sexual Offences Act"`).
  The reranker still decides, over a pool no larger than before.
  `GRAPH_EXPANSION_ENABLED=false` switches it off.
- **topics** (`retrieval/topics.py`, off until a tree exists) — RAPTOR's collapsed-tree
  search over summary nodes (`app/tree/`): the question is searched against topic summaries
  of the corpus and of the matter; a node that matches contributes the leaf passages beneath
  it, tagged `topic: …`, under the same candidate budget. A summary is never a citation.
- **topics** (`retrieval/topics.py`) — a summary tree (RAPTOR, below) widens the pool by
  theme: the question is searched against the tree's nodes, and each node that matches hands
  over the passages beneath it, tagged `topic: …`. A summary is never a citation; the leaves
  are what a query gets, under the same candidate budget as the graph. Off until a tree has
  been built (`TOPICS_ENABLED`).
- **rerank** — a local cross-encoder scores every candidate (title + passage) against the
  *original* question; a threshold, which the user's own documents are exempt from, and a
  per-mode cut (5 for ask, 10 for search).
- **review** (`retrieval/review.py`, research only) — one structured call over the reranked
  passages: what do they not yet cover, and what would cut the other way? It returns up to
  `RESEARCH_MAX_FOLLOW_UPS` follow-up searches, never one already run, within the user's
  scope; those run as a second pass that adds to the pool rather than replacing it, and the
  reranker judges old and new together. Bounded by `RESEARCH_MAX_ROUNDS` (2). A review that
  fails costs the pass, not the memo.
- **generate / verify** — a cited answer (or, in research, a memo under *Issue, Law,
  Authorities, Analysis, Conclusion*), streamed, then a groundedness judgment delivered
  after it as a separate verdict. The judge is a sampled model call and disagrees with
  itself a few percent of the time, so a single "not grounded" gets one independent second
  opinion; the answer is withdrawn only if both say so. The verifier is deliberately
  uncached — a cached verdict pinned one unlucky judgment on a good answer for the life of
  the process. Invalid `[n]` markers are stripped before the answer leaves; bracketed years
  in neutral citations (`[2010] eKLR`) are not markers.

### Citation graph

`app/graph/` reads every chunk once and extracts what it cites with regular expressions —
neutral citations (`[2025] KEMC 94 (KLR)`), case numbers (`Criminal Appeal No. 54 of 2010`),
party names, `section N of the X Act`, Articles of the Constitution — and resolves each
against the corpus's own titles. Every edge keeps its provenance (the chunk it sits in).
Over the full corpus: 6,537 edges from 1,533 documents in under a minute, 3,180 resolved
to an indexed document, zero model calls. Most cited cases are classic precedents the
corpus doesn't hold; they are recorded anyway, unresolved, because "which judgments applied
*Kasono*" is answered by the citing passages, not by the cited document. Edges live in a
`Citation` collection and are loaded into memory at startup; `GET /graph/{doc_id}` returns
what a document cites and what cites it. LLM entity extraction (LightRAG-style) was
rejected for the corpus: one call per chunk is ~85k calls for relationships that are
written in a recognisable form anyway.

### Topic tree

`app/tree/` builds a RAPTOR tree (arXiv 2401.18059) kept to what the corpus needs: the
indexed passages and their stored vectors are clustered (a Gaussian mixture on the 384-d
embeddings, the number of clusters by BIC around a target size of ten), each cluster is
summarised in one model call, the summaries are embedded, and a second level clusters the
first. Every node points at the leaf passages beneath it, so a hit hands retrieval real
passages; the summary text is navigation, never evidence. `python -m app.tree.build --matter
<id>` builds a matter's tree — also rebuilt after every upload, a few calls — and
`--collection case_law --docs N --levels 2` the corpus's, which at ~5k calls per level is
work for a paid model or a GPU, not a CPU. `TOPICS_ENABLED=true` turns the node on.

### Topic tree

`app/tree/` is RAPTOR (arXiv 2401.18059) kept to what this corpus needs: passages are
clustered by their stored embeddings (Gaussian mixtures, the count chosen by BIC around a
target cluster size — no UMAP, the vectors are already small), each cluster is summarised by
one model call, the summaries are embedded and clustered again for the next level. Nodes live
in a `Summary` collection, one tenant per tree: the corpus's, and each matter's, rebuilt
after every upload (a 25-passage matter is two or three calls). `python -m app.tree.build
--collection case_law --docs N --levels 2` builds the corpus's, which at ~5k clusters a level
is a job for a paid model or a GPU. Summaries are navigation, never evidence.

### Measured

Every number ever produced, with what changed between one and the next, is in
`MEASUREMENTS.md`. The current ones:

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

`golden_relationships.jsonl` holds 10 questions the graph exists for — "which judgments
have applied section 26 of the Civil Procedure Act?" — with every correct document derived
from the graph itself (30–43 each). Planner off, so the graph is the only variable:

| retrieval (`--set relationships`) | recall@5 | MRR | P@5 |
|---|---|---|---|
| hybrid search only | 80.0% | 0.750 | 72.0% |
| **+ citation-graph expansion** (shipped) | **100.0%** | **0.950** | **94.0%** |

`golden_matter.jsonl` holds 20 questions over three fixture documents (a lease, a demand
letter, a witness statement, `eval/fixtures/matter/`) uploaded to a fresh matter. `--set
matter` scores the document and the page:

| `--set matter`, planner off | recall@5 | MRR | page@5 |
|---|---|---|---|
| whole corpus in scope (the document competes with 84k chunks of law) | 100.0% | 0.871 | 95.0% |
| the matter alone | 100.0% | 0.900 | 100.0% |

Two things the set changed. The cross-encoder now scores the document's **title with each
passage** — a 200-token child seldom names its own document, and "what does the lease say"
ranked a letter mentioning the lease above the lease itself; the same fix lifted the
relationship set's P@5 from 90% to 94% and put the Sexual Offences Act back in the top five
for a question about its section 8. And the **relevance floor no longer applies to the
user's own documents**: the cross-encoder's absolute scores for a contract's clauses run
low even when its ranking of them is right, and three questions were returning nothing.

On the single-document golden set the expansion changes nothing (100% / 0.968 / 0.976
either way): it only widens the pool, and the reranker keeps what was already right.

Latency: the graph itself is free, the cross-encoder is not (~70 ms per candidate on this
CPU). Two things keep a relational search at the same ~2.1 s as any other. The pool handed
to the reranker never grows — graph passages displace the weakest hybrid candidates
(`GRAPH_CANDIDATE_BUDGET`). And dotted leaders in award tables
(`damages...........Ksh. 120,000`) tokenise one dot per token, padding a whole batch to
512; they are collapsed for scoring only. Before both, the same question took 5–7 s.

## API

`POST /query` `{question, mode: "search" | "ask", filters?: {collections, courts,
year_from, year_to}, matter_id?}` → `{plan, retrieval, citations, answer?, grounded?}`.
`POST /query/stream` — the same as server-sent events: `plan` → `sources` → `token`… →
`done` (the final answer) → `verdict` (grounded, or withdrawn). `GET /catalog` — what the
corpus contains, for the UI's filters. `GET /graph/{doc_id}` — what a document cites and
what cites it.

Two workflows run as jobs, because they take long enough to watch. Research: `POST /workflows/research`
(the same body as a query) returns a job at once; `GET /workflows/{job_id}/events` streams the
same events a query does, plus `review` after each pass, replayed from the start for a client
that connects late; `GET /workflows/{job_id}` is the job's status. Case analysis:
`POST /workflows/case-analysis {matter_id}` reads a matter's documents into a working file
(below), section by section. `app/workflows/` owns no retrieval or analysis logic: a workflow
composes the graph, or `app/analysis/`. Rate-limited per client; `PROXY_SECRET` gates
everything but `/health` when set.

## Case analysis

What a matter's documents say, before any law is researched: the parties, the facts each
document asserts, the events in date order, the Acts and cases the documents cite, where the
documents contradict each other, and what to look up next — every item pointing at the
passage it was read from, so a click opens the page with the words highlighted.

The order is deliberate. The deterministic steps run first: the **authorities** are found by
the citation graph's own extractor (plus an Act named without a section, which a letter does
and a judgment does too often), resolved against the corpus by the same rules the graph uses,
and each carries how many judgments in the corpus have applied it. The **chronology** is
parsed from dates as documents write them. Only then do the model steps run — one call per
document for parties, facts, events and issues (the model gives page numbers; the passage is
found by word overlap on that page, so anchors are real chunks with real boxes), one call
across the documents for issues, contradictions and research questions, one for the report.
A model step that fails is recorded on the analysis in its own words and the rest stands. The
result is stored on the matter; a research question in it is one click from a research run.


## Frontend

A research desk, not a chat: the query slip at the top of the page with its three modes, the
answer (or memo) as a cited argument, each `[n]` opening the authority in a bundle beside the page — a bottom sheet on a
phone, a drawer at laptop width, a column from 1280px. The source is never below the answer.
An authority the graph added says why it is there; the bundle lists what each authority
cites and what cites it, each row opening the document. The rail holds the matter in use:
its documents, their status, and the way to add more; a citation to one of them renders the
page in the bundle with the passage highlighted (PDF.js, loaded on first use). Filters come
from `/catalog`. The design world is recorded in `DESIGN.md`; product truth in `PRODUCT.md`.

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
  citation coverage ≥ 0.8, zero invalid citations, no API errors; reports p50/p95 latency
  per `/query` and the provider and models that answered, so a number is never read without
  its setup. The judge can be Claude or a local model.
- `retrieval_benchmark.py` — the tables above, in seconds, no judge; `--set golden |
  relationships | both | matter`.
- `golden_relationships.jsonl` — 10 multi-document questions, generated from the citation
  graph by `build_relationship_questions.py`.
- `golden_topics.jsonl` — 8 thematic questions ("how have courts treated …") whose ground
  truth is every judgment containing the phrases that name the theme, from
  `build_topic_questions.py`; what the topic tree is for.
- `golden_topics.jsonl` — 8 thematic questions ("how have courts treated…") whose document
  sets are defined by phrases every judgment in the set contains, by
  `build_topic_questions.py`; what the topic tree exists for.
- `golden_matter.jsonl` + `fixtures/matter/` — 20 questions over one matter's three
  documents, authored as Markdown and rendered to PDF by `build_matter_fixtures.py`.
- `authorities_benchmark.py` + `golden_authorities.jsonl` — the case analysis's
  deterministic step over the same fixtures: every citation found, resolved when the corpus
  holds it, anchored to a passage.

`.github/workflows/eval.yml` runs unit tests, ingests the slice, runs both, on every PR.

## Layout

```
backend/app/
  corpus/       documents (reconstruction), courts, chunking, splitting, parenting, ingest CLI
  vectorstore/  client, schema (explicit collections), search (hybrid), embeddings
  graph/        refs (extraction), resolve, edges, store (Weaviate + in-memory), build CLI
  tree/         cluster (GMM by BIC), summarise, store (Summary collection), build CLI
  matters/      models, store (disk), pdf (blocks → page + box), loaders, chunking,
                ingest (the job), enrich (profile), delete, catalog (for the planner)
  analysis/     models, chunks, sources (anchors), authorities, resolve, chronology,
                extract (per document), synthesise (across them, and the report), run
  retrieval/    catalog, plan (schema), planner (node), filters, retrieve, expand, topics,
                rerank, review, answer, grounding, citations, run (one query, one trace), graph
  workflows/    runs (a job with followable events), research, case_analysis
  api/          schemas, routes/{query,catalog,graph,matters,workflows}, streaming
  config, main, dependencies, jobs, proxy_auth, rate_limit, caching, resilience, scoring,
  tracing, metrics, prompts, prompt_sync
backend/prompts/   planner, generation, review, memo, grounding, profile, extract, analysis,
                   report, summary, responses
backend/eval/      the harness above
frontend/          app/ (layout, page, api proxy), components/, lib/ (types, api, stream, hook)
```

## Tests

```bash
cd backend && uv run ruff check app tests eval && uv run pytest
cd frontend && npx tsc --noEmit && npm run lint && npm run build
```
