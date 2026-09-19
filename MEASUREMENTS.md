# Measurements

Every number this project has produced, in the order it was produced, with what changed
between one and the next. The README carries the current numbers; this file is the record
of how they got there. Nothing is removed from it.

Unless stated otherwise: full local corpus (1,533 documents, 84,429 chunks), the API in
Docker on one CPU (4 torch threads), `retrieval_benchmark.py` in search mode at k=5,
scoring document-level recall on the `source` URL of each golden question.

---

## 2026-09-19 · Pivot to Wakili (PR #9, `legal-rag`)

### Corpus reconstruction

| what | value |
|---|---|
| rows in `corpus/all_chunks.json` | 800-char windows, fixed 150-char overlap |
| windows found verbatim in their reconstructed document | 63,603 / 63,603 |
| fallback joins (overlap not found) | 0 |
| documents | 1,533 (543 Acts, 990 judgments, 7 courts) |
| chunks after re-splitting (200-token children, parent windows) | 84,429 |

### Ingest throughput (CPU-bound embedding, bge-small)

| what | value |
|---|---|
| chunks/s | 7–18 (varies with chunk length) |
| 8 torch threads vs 4 | slower with 8 |
| legislation, full | 72 min |
| case law, full | 19 min |
| re-run with warm embedding cache | minutes |

### Retrieval benchmark, 36-question golden set

| retrieval | recall@5 | MRR | nDCG@5 |
|---|---|---|---|
| original question only (`PLANNER_ENABLED=false`) | 100.0% | 0.968 | 0.976 |
| planner's sub-queries only | 97.2% | 0.954 | 0.958 |
| planner + original question (shipped) | 100.0% | 0.981 | 0.986 |

**What changed the result:** the planner's rewrites alone lost one question — a
paraphrase drops the exact wording BM25 matches on. Adding the verbatim question as a
sub-query per collection restored recall and improved ranking over both.

### Faithfulness eval (`run_eval.py`, ragas, Sonnet judge), full corpus

| what | value |
|---|---|
| faithfulness | 0.924 |
| answer rate | 100% |
| invalid citations | 0 |
| citation coverage | 0.740 (gate 0.8 — **failed**) |
| judge overruns at `JUDGE_MAX_TOKENS=4096` | 5 of 36 samples; `legislation-12` scored 0.00 on a correct verbatim answer |

(For reference, the pre-pivot upload-and-chat app scored faithfulness 0.983 on its own
golden set. Different corpus, different questions; not comparable.)

### Latency, one uncached ask (Sonnet planner, sequential retrieval)

| point | seconds |
|---|---|
| plan | 7.1 |
| retrieve + rerank | 2.3 |
| first token | 10.6 |
| last token | 20.8 |
| verified | 23.4 |

---

## 2026-09-19 · Step 0, close the gate (commit `53ceff1`)

Changes: `JUDGE_MAX_TOKENS` 4096 → 16384; generation prompt v5 cites every list item.

| what | before | after |
|---|---|---|
| citation coverage | 0.740 | 0.806 (**partial run** — the Anthropic credit balance ran out mid-eval; the rest of the gate is unmeasured) |

**What changed the result:** coverage losses were six-item lists cited once at the end;
the prompt now puts a marker on each item. The judge overruns were the max-token cap, not
the answers.

**Blocked:** the replacement API key returns `401 authentication_error – invalid`. The full
gate on PR #9, the latency numbers for PR #10 and any planner-on measurement wait on it.

---

## 2026-09-19 · Step 1, latency (PR #10, `latency`)

Changes: Haiku planner (`PLANNER_MODEL`), plan cache, parallel retrieval, `verdict` event
after `done`, catalog TTL refresh. Targets: plan 7.1 s → ≤ 1.5 s, retrieve 2.3 s → ~1 s,
perceived completion 23.4 s → ~21 s.

**Unmeasured** — needs a working Anthropic key. Retrieval benchmark with the planner on
must still hold 100% / 0.981 / 0.986 before merge.

---

## 2026-09-19 · Step 2, citation graph (PR #11, `citation-graph`)

### Graph build (`python -m app.graph.build`, no model calls)

| what | value |
|---|---|
| wall clock | 57 s |
| documents / chunks read | 1,533 / 84,429 |
| edges (deduplicated per source, target, provision) | 6,537 |
| resolved to an indexed document | 3,180 |
| `cites` (case) / `applies` (statute) | 2,825 / 3,712 |
| case → case edges resolving inside the corpus | 13 (judgments cite classic precedents the corpus doesn't hold) |
| most cited (by distinct citing documents) | Constitution of Kenya 331 (1,360 edges); then Civil Procedure Act, Penal Code, Criminal Procedure Code, Employment Act, Evidence Act, Sexual Offences Act, Law of Succession Act |
| most citations in one judgment | 62 |
| titles with the scrape's breadcrumb arrow | 1 (`Constitution of Kenya →`, 610 chunks patched in place) |

Lookup checks: `Kaingu Elias Kasono v Republic` → 5 citing passages; `[1988] KLR 380` →
40 (10 added to the pool); `section 8(1) of the Sexual Offences Act` → 9 (7 added).

### Relationship benchmark, `golden_relationships.jsonl`

10 questions generated from the graph — five "Which judgments cite …", five "Which
judgments have applied …" — each with 30–43 correct documents. Planner off throughout, so
the graph is the only variable. P@5 = share of the top five that are correct.

| run | recall@5 | MRR | nDCG@5 | P@5 | golden-set MRR |
|---|---|---|---|---|---|
| hybrid search only (`GRAPH_EXPANSION_ENABLED=false`) | 80.0% | 0.750 | 0.763 | 72.0% | 0.968 |
| + expansion, first version | 100.0% | 0.950 | 0.963 | 92.0% | **0.963** |
| + expansion, relational heuristic tightened | 100.0% | 0.950 | 0.963 | 92.0% | 0.968 |
| + graph rebuilt with URL fields | 100.0% | 0.950 | 0.963 | **90.0%** | 0.968 |
| + citing-passage order made deterministic (cap 12) | 100.0% | 0.950 | 0.963 | 90.0% | 0.968 |
| lookup cap 24 (side container, not shipped) | 100.0% | 0.950 | 0.963 | 92.0% | — |
| lookup cap 40 (side container, not shipped) | 100.0% | 0.950 | 0.963 | 94.0% | 0.968 |
| + reranker candidate budget (40), cap 12 | 100.0% | 0.950 | 0.963 | 90.0% | 0.968 |
| + leaders collapsed before scoring — **shipped** | 100.0% | 0.950 | 0.963 | 90.0% | 0.968 |
| hybrid only, re-measured on the shipped code | 80.0% | 0.750 | 0.763 | 72.0% | 0.968 |

**What changed each result:**

- *Golden MRR 0.968 → 0.963 in the first version.* The no-model fallback for "is this a
  relational question" matched any relational verb. `case_law-05` ("In *Republic v Oundo*
  … what did counsel argue, **citing** *Republic v Danson Mgunya*…") tripped it, seven
  one-hop neighbours were added, and the reranker put two above Oundo (rank 1 → 3). The
  heuristic now requires the interrogative form ("which/what cases/judgments/…"), and the
  planner's own flag wins whenever it planned. Back to 0.968.
- *P@5 92% → 90% after the graph rebuild.* Not the URL fields: the citing passages for a
  key were returned in whatever order the edges loaded from Weaviate, and the cap of 12
  took the first 12 of 30–44. A rebuild reordered them. The order is now fixed — each
  document's first citing passage before any document's second, then by (doc, chunk) —
  which lands on 90% for good. The single slot is the reranker preferring a passage that
  discusses the provision to one that cites it.
- *Caps 24 / 40 reach 92% / 94%* but cost 12–28 more cross-encoder passes per lookup.
  Not shipped; see latency.
- *Budget and leader-collapsing change no rank on either set.* They change time only.

### Latency of expansion

Search mode, same question three times, wall clock of `POST /query`:

| stage | relational question¹ | plain question² |
|---|---|---|
| expansion off | 2.35 – 2.69 s | 2.07 – 2.44 s |
| expansion on, first version | 6.06 – 7.40 s | 1.90 – 2.34 s |
| + reranker candidate budget (pool held at 40) | 5.13 – 5.74 s | 1.89 – 1.95 s |
| + leaders collapsed before scoring — shipped | **2.09 – 2.31 s** | 2.09 – 2.38 s |

¹ "Which judgments have applied section 26 of the Civil Procedure Act?" ² "What is the
penalty for defilement of a child aged eleven or less?"

Where the time went, from timing each graph node in-process (absolute numbers inflated by
the running server sharing the CPU; the ratio is the point):

| node | relational | plain |
|---|---|---|
| plan (fallback) | 0.01 s | 0.00 s |
| retrieve (40 candidates) | 0.06 – 0.13 s | 0.13 – 0.15 s |
| expand (pool still 40) | 0.00 – 0.15 s | 0.00 s |
| rerank (40 → 10) | **8.25 – 8.38 s** | 3.54 s |

Cross-encoder cost by candidate count (200-token passages, one warm call each): 40 → 2.7 s,
60 → 4.4 s, 80 → 5.0 s — about 70 ms per pair. But 12 graph-added passages cost 3.54 s
against 0.66 s for 12 hybrid ones of the same character length. Their BERT token counts:
hybrid 112–220; graph-added 212–**525**. The citing passages for a costs provision are award
tables with dotted leaders (`damages...........Ksh. 120,000/=`), one token per dot, and
the whole batch pads to the longest sequence. 973 corpus windows in 251 documents carry
such leaders. Collapsing runs of `.`/`-`/`_`/`=`/`*` to three characters *for scoring only*
(the reader's text is untouched) brought the relational question level with a plain one.

Weaviate's share is negligible: `fetch_chunk` ×12 = 11 ms; hybrid search filtered to one
document = 6 ms; unfiltered = 15 ms; loading the whole graph = 0.8 s at startup.

### Known gap recorded for Step 6

"What is the punishment for defilement under section 8 of the Sexual Offences Act?" returns
ten judgments and not the Act, although the Act's own s.8 passages are candidates 1–8 of
the legislation sub-query (chunk 13 is the exact punishment). The cross-encoder scores the
200-token child alone, which says "liable upon conviction to imprisonment…" without the
Act's name or "section 8"; judgments quoting the section carry all three. Candidate fix:
score title + child. Not measured yet.

---

## 2026-09-20 · Step 3, matters (PR #12, `matters`)

### The matter set

Three fixture documents — a lease (2 pages), a demand letter (1), a witness statement (2);
23 chunks in all — uploaded to a fresh matter and searched with the **whole corpus in
scope** (`--scope all`: the user's document competes with 84,429 chunks of law) and with
**the matter alone** (`--scope matter`). 20 questions; each names its document and the page
its answer sits on. `page@5` = the right document *and* page among the top five passages.
Planner off throughout (no working key), so the fallback plan searches every collection.

| run | scope | recall@5 | MRR | nDCG@5 | page@5 |
|---|---|---|---|---|---|
| first version | all | 75.0% | 0.700 | 0.713 | 70.0% |
| + title scored with the passage | all | 85.0% | 0.792 | 0.807 | 85.0% |
| + title scored with the passage | matter | 85.0% | 0.825 | 0.832 | 85.0% |
| relevance threshold removed (side container, not shipped) | matter | 100.0% | 0.900 | 0.926 | 100.0% |
| relevance threshold removed (side container, not shipped) | all | 100.0% | 0.827 | 0.869 | 90.0% |
| + matter documents exempt from the threshold | all | 100.0% | 0.846 | 0.885 | 95.0% |
| + matter documents exempt from the threshold | matter | 100.0% | 0.900 | 0.926 | 100.0% |
| + PDF line wraps joined within a block — **shipped** | all | **100.0%** | **0.871** | **0.903** | **95.0%** |
| + PDF line wraps joined within a block — **shipped** | matter | **100.0%** | **0.900** | **0.926** | **100.0%** |

**What changed each result:**

- *75% → 85%: the title now goes in front of the passage the cross-encoder scores.* "What
  is the monthly rent under the lease?" scored the lease's own clause 3.1 at −0.60 and a
  letter that *mentions* the lease at 4.89: a 200-token child never says which document it
  is from. This was the gap recorded under Step 2 for the Sexual Offences Act, and it closes
  there too — the Act's s.8 passages now rank 3–4 for "what is the punishment for
  defilement under section 8", where before they were absent from the top ten. Golden set
  unchanged; relationship set P@5 **90% → 94%**. Cost: ~+0.4 s per search (titles are
  10–40 tokens per pair), 2.3–2.8 s against 2.1–2.3 s.
- *85% → 100%: the relevance floor.* The three remaining misses — late-rent interest, the
  yearly rent review, what the demand letter threatens — were in the pool and ranked
  correctly among the matter's chunks, but every one scored below `0.2`
  (`RERANK_RELEVANCE_THRESHOLD`) and was dropped; one question returned nothing at all.
  The cross-encoder's absolute scores for a contract's clauses run low even when its
  ordering is right. Removing the floor entirely fixes the matter set without touching the
  golden set, but the floor is what keeps an off-corpus question from being answered from
  passages that merely look relevant — so it now applies to the corpus only. The user's own
  documents are in scope because the user put them there.
- *MRR 0.846 → 0.871: PDF line wraps.* PyMuPDF returns a block's lines separated by `\n`;
  they are layout, not content, and were breaking phrases ("3rd February\n2024") for BM25
  and the embedder alike. Joined at extraction.

### Indexing

Three PDFs, 5 pages, 23 chunks: **12 s** from upload to `indexed`, including one profile
call per document. The profile calls themselves failed — the replacement Anthropic key now
authenticates but the account has **no credits** (`400 credit balance is too low`), so
every document records `profile_error` and stays searchable, which is the designed
behaviour.

### Known gap, for Step 6

`cross-encoder/ms-marco-MiniLM-L-6-v2` scores legal paraphrase poorly in absolute terms: the
demand letter's "our client will … exercise her right of re-entry, levy distress …" scores
−3.6 against "what steps does the landlord threaten if the tenant does not comply". The
ranking survives; the calibration doesn't. A stronger reranker (MiniLM-L-12, bge-reranker-
base) is the obvious candidate, at 2–10× the per-pair cost — to be measured against the
three sets and the latency budget, not assumed.
