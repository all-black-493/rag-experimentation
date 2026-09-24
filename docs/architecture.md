# Architecture

How Wakili is put together, and why. The [README](../README.md) is what you need to run it;
this is what you need to change it. Numbers live in [MEASUREMENTS.md](../MEASUREMENTS.md).

Modelled on Weaviate's legal-RAG reference architecture — collections by document type, an
agent that inspects the schema, routes, builds filtered queries, reranks and answers — but
self-hosted: the agent is our own LangGraph, not Weaviate Cloud's Query Agent.

## Corpus

The rows arrive as 800-character windows with a fixed 150-character overlap, cut mid-word
four times out of five. Because the overlap is fixed, `app/corpus/documents.py` reconstructs
every document losslessly — verified: all 63,603 windows found verbatim in their document,
zero fallback joins — and re-chunks it with a sentence-aware, small-to-big splitter.
200-token children are what get embedded, matched and quoted; the window of neighbours
around a child is what the model reads. Court, decision date, year enacted and
point-in-time version are parsed from Kenya Law's URLs.

Two Weaviate collections with explicit schemas (`app/vectorstore/schema.py`), not
autoschema: `Legislation` and `CaseLaw`. No multi-tenancy — the corpus is shared. A third,
`MatterDocument`, holds the user's own documents, one tenant per matter.

## Retrieval

```
plan → retrieve → expand → topics → rerank → [search]   END
                                           → [ask]      generate → verify → END / decline
                                           → [research] review → (follow-ups) retrieve …
                                                               → generate → verify → END / decline
```

**plan** (`retrieval/planner.py`) — one structured call to the fast model, cached per
question and filters. It sees the catalog, built from the live database (collections,
courts and their counts, year bounds, refreshed on a TTL), and returns 1–4 sub-queries,
each aimed at one collection, with court and year filters only when the question names
them, plus a `relationships` flag for questions about how authorities relate. Validated by
Pydantic and bounded by the user's own filters, which it may narrow but never widen;
unknown court codes are dropped. A failed call falls back to one unfiltered query per
collection, which `PLANNER_ENABLED=false` also forces.

**retrieve** (`retrieval/retrieve.py`) — hybrid BM25 and vector search per sub-query, in
parallel, filters pushed into Weaviate. The original question is always searched too, once
per collection the plan touches. A sub-query whose planner filter returns fewer than
`MIN_CANDIDATES_PER_SUBQUERY` is re-run without it and marked *relaxed*; the user's filters
are never relaxed. Results are pooled and de-duplicated.

**expand** (`retrieval/expand.py`) — the citation graph widens the pool, in memory, in
milliseconds. An authority the question names brings in the exact passages that cite it; a
relational question also brings in the best passage of each document one hop from the top
candidates. Bounded, filtered by the user's restrictions, and every added passage is tagged
with why it is there (`via: "applies section 8(1) of the Sexual Offences Act"`). The
reranker still decides, over a pool no larger than before.
`GRAPH_EXPANSION_ENABLED=false` switches it off.

**topics** (`retrieval/topics.py`) — a summary tree widens the pool by theme: the question
is searched against the tree's nodes, and each node that matches hands over the passages
beneath it, tagged `topic: …`. A summary is never a citation; the leaves are what a query
gets, under the same candidate budget as the graph. Off until a tree has been built
(`TOPICS_ENABLED`).

**rerank** — a local cross-encoder scores every candidate (title with passage) against the
*original* question; then a relevance threshold, which the user's own documents are exempt
from, and a per-mode cut: 5 for ask, 10 for search.

**review** (`retrieval/review.py`, research only) — one structured call over the reranked
passages: what do they not yet cover, and what would cut the other way? It returns up to
`RESEARCH_MAX_FOLLOW_UPS` follow-up searches, never one already run, within the user's
scope. Those run as a second pass that adds to the pool rather than replacing it, and the
reranker judges old and new together. Bounded by `RESEARCH_MAX_ROUNDS`. A review that fails
costs the pass, not the memo.

**generate / verify** — a cited answer, or in research a memo under *Issue, Law,
Authorities, Analysis, Conclusion*, streamed; then a groundedness judgment delivered after
it as a separate verdict. The judge is a sampled model call and disagrees with itself a few
percent of the time, so a single "not grounded" gets one independent second opinion and the
answer is withdrawn only if both say so. The verifier is deliberately uncached — a cached
verdict once pinned one unlucky judgment on a good answer for the life of the process.
Invalid `[n]` markers are stripped before the answer leaves; bracketed years in neutral
citations (`[2010] eKLR`) are not markers.

### Why the reranker stays fast

The graph itself is free; the cross-encoder is not, at ~70 ms per candidate on CPU. Two
things keep a relational search at the same ~2.1 s as any other. The pool handed to the
reranker never grows — graph passages displace the weakest hybrid candidates
(`GRAPH_CANDIDATE_BUDGET`). And dotted leaders in award tables
(`damages...........Ksh. 120,000`) tokenise one dot per token, padding a whole batch to
512, so they are collapsed for scoring only. Before both, the same question took 5–7 s.

## Citation graph

`app/graph/` reads every chunk once and extracts what it cites with regular expressions —
neutral citations (`[2025] KEMC 94 (KLR)`), case numbers (`Criminal Appeal No. 54 of
2010`), party names, `section N of the X Act`, Articles of the Constitution — and resolves
each against the corpus's own titles. Every edge keeps its provenance: the chunk it sits in.

Over the full corpus: 6,537 edges from 1,533 documents in under a minute, 3,180 resolved to
an indexed document, zero model calls. Most cited cases are classic precedents the corpus
doesn't hold; they are recorded anyway, unresolved, because "which judgments applied
*Kasono*" is answered by the citing passages, not by the cited document.

LLM entity extraction (LightRAG-style) was rejected for the corpus: one call per chunk is
~85k calls for relationships that are written in a recognisable form anyway.

## Topic tree

`app/tree/` is RAPTOR (arXiv 2401.18059) kept to what this corpus needs. Passages are
clustered by their stored embeddings — Gaussian mixtures, the count chosen by BIC around a
target cluster size; no UMAP, the vectors are already small — each cluster is summarised by
one model call, and the summaries are embedded and clustered again for the next level.
Every node points at the leaf passages beneath it, so a hit hands retrieval real passages.

Nodes live in a `Summary` collection, one tenant per tree: the corpus's, and each matter's,
rebuilt after every upload (a 25-passage matter is two or three calls).
`python -m app.tree.build --collection case_law --docs N --levels 2` builds the corpus's,
which at ~5k clusters a level is a job for a paid model or a GPU.

## Matters

A matter is the user's own file. `POST /matters/{id}/documents` validates on the request —
so a bad file is refused while the user is looking at it — and indexes in the background:
parse, chunk, embed, index, then one model call for a profile (summary, type, parties,
dates) that tells the planner what the document is.

A PDF chunk never spans a page and carries the union box of its blocks, so a citation opens
the page with the passage highlighted. Deletion removes chunks first, then the file and the
record. Originals live under `data/matters/<id>/`.

Every write to a matter passes through `MatterStore._write`, which is where
`app/matters/events.py` publishes it. `GET /matters/{id}/events` turns that into SSE: the
matter as it stands, then each change, closing when nothing is indexing, with a keep-alive
comment in between. The client opens it on upload instead of polling.

## Case analysis

What a matter's documents say, before any law is researched: the parties, the facts each
document asserts, the events in date order, the Acts and cases the documents cite, where
the documents contradict each other, and what to look up next — every item pointing at the
passage it was read from.

The order is deliberate. The deterministic steps run first: **authorities** are found by the
citation graph's own extractor (plus an Act named without a section, which a letter does and
a judgment does too often), resolved against the corpus by the same rules the graph uses,
and each carries how many judgments in the corpus have applied it. The **chronology** is
parsed from dates as documents write them.

Only then do the model steps run: one call per document for parties, facts, events and
issues — the model gives page numbers, and the passage is found by word overlap on that
page, so anchors are real chunks with real boxes — one call across the documents for
issues, contradictions and research questions, and one for the report. A model step that
fails is recorded on the analysis in its own words and the rest stands. The result is stored
on the matter, and a research question in it is one click from a research run.

## Workflows

Research and case analysis take long enough to watch, so they run as jobs.
`app/workflows/runs.py` is a job plus an event log: events are kept, so a client that
connects late — or reconnects — sees everything from the start. `app/workflows/` owns no
retrieval or analysis logic; a workflow composes the retrieval graph, or `app/analysis/`.

## Frontend

A research desk, not a chat. The query slip sits at the top with its three modes, the
answer or memo reads as a cited argument, and each `[n]` opens the authority in a bundle
beside the page — a bottom sheet on a phone, a drawer at laptop width, a column from
1280px. The source is never below the answer.

An authority the graph added says why it is there; the bundle lists what each authority
cites and what cites it. The rail holds the matter in use: its documents, their status and
the way to add more. A citation to one of them renders the page in the bundle with the
passage highlighted (PDF.js, loaded on first use). Filters come from `/catalog`.

`frontend/app/api/[...path]/route.ts` proxies to `BACKEND_URL`, attaching `PROXY_SECRET`
server-side, so the browser stays same-origin and the secret never ships.

## Tracing

Set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` to enable; blank keys emit nothing. One
trace per query: `plan-query` (chain) → one `weaviate-hybrid-search` (retriever) per
sub-query, with its filters and whether it was relaxed → `rerank-cross-encoder` with each
survivor's prior position → `generate` (prompt version, tokens, cost) → `verify-groundedness`
(evaluator, both verdicts). Scores on the root: `answered`, `grounded`, `failed`,
`citation_coverage`, `invalid_citations`.

```bash
uv run python -m app.metrics --since 7d    # p50/p95 latency, cost, coverage, failures
uv run python -m app.prompt_sync           # mirror prompts/*.yaml into Langfuse
```

Prompts live in `backend/prompts/*.yaml`, versioned in git; Langfuse mirrors them so
generations link to the version that produced them.

## Layout

```
backend/app/
  corpus/       documents (reconstruction), courts, chunking, splitting, parenting, ingest CLI
  vectorstore/  client, schema (explicit collections), search (hybrid), embeddings
  graph/        refs (extraction), resolve, edges, store (Weaviate + in-memory), build CLI
  tree/         cluster (GMM by BIC), summarise, store (Summary collection), build CLI
  matters/      models, store (disk), events (the change feed), pdf (blocks → page + box),
                loaders, chunking, ingest (the job), enrich (profile), delete, catalog
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
backend/eval/      golden sets, benchmarks, the faithfulness harness, gate.sh
frontend/          app/ (layout, page, api proxy), components/, lib/ (types, api, stream, hooks)
```
