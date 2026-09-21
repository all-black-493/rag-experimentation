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


---

## 2026-09-20 · Step 4, research (PR #13, `research`)

**Unmeasured — every step of a research run past retrieval is a model call.** The review
(Haiku) and the memo (Sonnet) both return `400 credit balance is too low`. Built and tested
with fakes; run live only far enough to see it degrade as designed: `plan → sources → review`
(no follow-ups, the review's failure logged) `→ error` (the memo), the error told to the
follower in the provider's own sentence and recorded on the job.

What to measure once credits are back, in this order:

1. **Does the second pass find what the first missed?** A set of 10–15 questions whose
   answer needs both the Act and a case (or a case and its contrary authority), scored on
   document-set recall after pass 1 and after pass 2 — the relationship-set shape. The
   difference is the review's worth.
2. **Memo quality.** `run_eval.py` faithfulness and citation coverage over the memo, against
   the ask-mode numbers on the same questions; and a rubric check that every heading is
   present and *Authorities* names at least one authority against.
3. **Cost and time.** Calls per run (plan, review, memo, verify ×1–2), tokens, wall clock
   from start to `done` and to `verdict`. Budget: the plan's "minutes; progress streamed".

Also in this PR: a stale `matter_id` on `/query` now returns 404 instead of failing inside
retrieval — the check written for Step 3 had not made it into that commit.


---

## 2026-09-20 · Step 5, case analysis (PR #14, `case-analysis`)

### The deterministic core, `authorities_benchmark.py`

Over the three matter fixtures (a lease, a demand letter, a witness statement), the
citations the documents make, per `golden_authorities.jsonl`:

| what | value |
|---|---|
| citations found | 3 / 3 (Companies Act, Distress for Rent Act, Civil Suit E312 of 2025) |
| spurious | 0 |
| resolved against the corpus when it holds the Act | 2 / 2 (Companies Act, Distress for Rent Act) |
| left unresolved when it doesn't | 1 / 1 (the suit itself) |
| anchored to a passage with a page and box | 3 / 3 |
| judgments in the corpus applying each, from the citation graph | Companies Act 18, Distress for Rent Act 1 |
| wall clock, upload to stored analysis | 7.1 s, including three model calls that failed in ~2 s each |

**What made the number:** the graph's extractor took only `section N of the X Act`; a letter
cites "the Distress for Rent Act" and a lease "the Companies Act, 2015" with no section, so
both were missed. A bare-Act pattern now runs *on request only* — in a judgment every
mention of the Penal Code would become an edge, and the Step 2 numbers would move.

### Unmeasured — the model steps

Parties, facts, events, issues, contradictions, research questions and the report are model
calls (`400 credit balance is too low`). The analysis degrades as designed: authorities and
chronology stand, the unread documents are named with the reason, the report is absent.

What to measure once credits are back: on the fixtures, parties recall (there are 6 named
roles), facts anchored to the right page (the golden matter set's 20 answers double as
facts), the chronology's dates (11 dated events across the three documents), and whether the
one genuine contradiction — the letter's "no rent received for May–August" against the
statement's "KSh 513,600 held in escrow since 5 August" — is found and cited to both sides.


---

## 2026-09-20 · Step 6, eval growth — the sets

| set | questions | ground truth | scored on |
|---|---|---|---|
| `golden_dataset.jsonl` | 36 | one document | recall@5, MRR, nDCG |
| `golden_relationships.jsonl` | 10 | 30–43 documents each, from the citation graph | + P@5 |
| `golden_matter.jsonl` | 20 | one document and a page | + page@5 |
| `golden_authorities.jsonl` | 3 documents | the citations each makes, and whether the corpus holds them | found / resolved / anchored |
| `golden_topics.jsonl` | 8 | 7–23 judgments each, every one containing the theme's phrases | recall@5, MRR, P@5 |

77 questions in all. The topic set's baseline, planner off, citation-graph expansion on, no
topic tree yet:

| `--set topics` | recall@5 | MRR | nDCG@5 | P@5 |
|---|---|---|---|---|
| hybrid + graph expansion (no tree) | 87.5% | 0.875 | 0.875 | 70.0% |

Four themes were dropped by their own rule — fewer than five judgments contain the phrases
(defilement + age assessment: 4; distress for rent: 4; dying declaration: 1; trial within a
trial + confession: 1). The bar is deliberate: a set of four is a lookup, not a theme.

`run_eval.py` now records p50/p95 wall clock per `/query` and the provider and models that
answered (from `/health`), in the report and on the console.

---

## 2026-09-20 · Local models (PR #15, `ollama`)

### The machine

No GPU. 8 cores, 15.6 GB RAM, a 2 GB swap file — **already full** before Ollama starts:
Weaviate, the API (torch, two local models), and unrelated containers (a k3d cluster,
MSSQL, Kafka, Postgres) leave ~1 GB available. The host's own Ollama is 0.5.7 (too old for
Qwen3: `412 requires a newer version`), so the compose service (`ollama/ollama`, 0.34.2)
runs it, CPU only. Pulling: the image 5.5 GB, `qwen3:8b` 5.2 GB, at 1.9–2.5 MB/s.

### Raw speed, `qwen3:8b`, thinking off

| call | prompt tokens | prompt eval | generation |
|---|---|---|---|
| "Say ready.", first load | 19 | 13.6 tok/s | 4.8 tok/s (load 11 s) |
| 2,064-token prompt, `num_ctx` 8192 | 2,064 | 9.2 tok/s | 2.4 tok/s |
| 2,064-token prompt, `num_ctx` 16384 | 2,064 | 8.4 tok/s | 2.6 tok/s |
| the planner, cold | 534 | 2.6 tok/s | 2.4 tok/s |
| generation (5 parent windows) | 2,344 | 7.5 tok/s | 1.8 tok/s |
| verify | 2,209 | 7.9 tok/s | 2.0 tok/s |

Context size barely matters; memory does. With swap full, the weights page in and out
under every call.

### One uncached ask, whole pipeline (`latency_probe.py`, planner on)

| point | Sonnet + Haiku (2026-09-19 baseline) | qwen3:8b, this CPU |
|---|---|---|
| plan | 7.1 s | 253.7 s |
| sources | 9.4 s | 256.3 s |
| first token | 10.6 s | 570.9 s |
| last token | 20.8 s | 598.9 s |
| verified | 23.4 s | 933.6 s |

The pipeline is intact end to end on a local model — planner, generation and verifier all
returned, structured output included — and it takes **15.6 minutes**, of which retrieval
and reranking are 2.6 s. On this hardware the local path is for measuring correctness in
the background, not for sitting in front of. A GPU, or a machine that isn't already
swapping, changes the arithmetic by an order of magnitude; the code does not change.

Worth knowing: the planner prompt is 580 tokens (catalog 178, a matter's documents 81);
the generation prompt with five parent windows ~2,300; a memo's twelve would be ~5,500.

### The model-driven steps, run on `qwen3:8b` (the first time they have run at all)

The matter fixtures, uploaded to a fresh matter with the local model answering every call.
Wall clock is on this swapping CPU; the same calls on Haiku/Sonnet are seconds each.

**Profiles (Step 3), 3 of 3 documents.** Types "Demand Letter", "Lease Agreement", a
witness statement; parties with roles (landlord, tenant, the advocates); dates (lease
signed 3 Feb 2024, commencing 1 Mar 2024, expiring 28 Feb 2029; demand 12 Aug 2025). One
profile call: 1,417-token prompt, 364-token output, 5.3 min. (The third profile showed as
missing in the first read of the record: a document is `indexed` before it is profiled,
and the script read it in between. Both writes are now logged.)

**Matter topic tree (Step 4b).** 3 nodes over 23 passages, rebuilt after each upload,
titles the model wrote: *Lease Termination and Rent Arrears Notice* (7 passages, 2
documents), *Lease Terms and Arrears Notice* (6, 2), *Legal Letter Closing and Client CC*
(1). Upload to indexed, profiled and treed: 1,311 s for the three documents.

**Case analysis (Step 5).** Against the measurements planned for it:

| what | planned check | result |
|---|---|---|
| parties | 6 named roles in the fixtures | 6 found, all with roles, all anchored to a passage |
| facts | anchored to the right page | 47 facts, 47 anchored (100%); e.g. rent KSh 120,000 → passage 6, interest 14% → passage 7 |
| chronology | 11 dated events | 24 events, all dated and ordered (3 Feb 2024 → Sept 2025) |
| issues | — | 5 (re-entry for arrears, liability for the leaking roof, the third party in the shop, the changed locks, rent into escrow) |
| contradictions | the one genuine one: "no rent received May–August" vs "KSh 513,600 in escrow" | 2 reported, both cited to both sides: the letter's 12 Aug date vs the 20 Aug receipt (genuine); the rent review as a fixed figure vs as 7% a year (not a conflict). **The escrow contradiction was not found.** |
| research questions | — | 5, each searchable as written ("Under the Distress for Rent Act, what are the procedures and limitations on a landlord's right…") |
| authorities (deterministic) | 3/3 | 3/3, as before |
| report | headings, every fact cited | 13,784 characters under Parties / Facts / Chronology / Issues / Authorities cited / Contradictions / Next steps, `[n]` on every fact |
| warnings | — | none |

Calls: extraction of the three documents 8.1, 30.0 and 25.5 min (the lease's 1,676-token
output at 1.95 tok/s is why local output is now capped per role); synthesis and report
~2 h each as logged, queue time included. A working file worth having, at the price of an
afternoon on this hardware.

**Research run (Step 4).** Started after the analysis; its three calls — review, memo,
verify — logged at 9.9, 12.5 and 45.3 min. The session driving the probe ended before it
could read the memo; the run itself completed inside the API.

**Eval gate with the local judge.** Not run: at ~15 min an ask and ~10 a judgment, the
36-question gate is ~15 hours here. `run_eval.py --judge-model ollama:qwen3:8b` is ready
for a machine that can afford it.

### Topic set, `golden_topics.jsonl` (Step 6)

8 thematic questions whose ground truth is every judgment containing the theme's phrases
(7–23 judgments each). Planner off, graph on, no corpus tree yet:

| retrieval | recall@5 | MRR | nDCG@5 | P@5 |
|---|---|---|---|---|
| hybrid + citation graph, no tree | 87.5% | 0.875 | 0.875 | 70.0% |

This is the baseline the corpus tree will be judged against. The tree needs ~5k summary
calls a level over case law: hours on a paid model, days on this CPU; not built here.

## 2026-09-20 · The gate without a paid model (PR #17, `ollama` → `main`)

Local models are now the default (`LLM_PROVIDER=ollama`, `qwen3:8b`); Anthropic is the
opt-in. CI had gated every PR on the 36-question faithfulness eval, which failed the moment
the Anthropic account ran out of credits (`400 credit balance is too low`), on runs
35446540746 through 35512968574. What CI measures on a PR is now what needs no model:

| check | floor | last measured on the CI slice (run 35512968574) |
|---|---|---|
| golden set recall@5 / MRR | 0.97 / 0.95 | 100.0% / 1.000 (36 fallback plans: no planner) |
| matter set recall@5 / MRR | 0.95 / 0.90 | 100.0% / 0.950 |
| authorities found, spurious | 3/3, 0 | 3/3, 0 |

Floors sit under the measured numbers by about one question, the room the planner's
rewrites took on the full corpus (97.2% / 0.981). `retrieval_benchmark.py` gained
`--min-recall`/`--min-mrr` for this; it had never failed a run.

First run of the new gate (35514750003, 15 min): golden 100.0% / 1.000, matter 100.0% /
0.950, authorities 3/3 found, 0 spurious, 3/3 anchored, 1.0 s. Resolution reads 1/3 there
against 3/3 locally because the slice holds neither the Companies Act nor the Distress for
Rent Act; the benchmark gates on found and spurious, which don't depend on the corpus.

The faithfulness gate itself is a manual run: `run_eval.py --concurrency 1 --timeout 1800
--resume` against the local stack (hours; `--resume` keeps each result in
`report.partial.jsonl`, so a restart continues), or `workflow_dispatch` on CI with a
Claude judge when a key has credits. Its last measured numbers remain the Anthropic ones
above (faithfulness 0.924, coverage 0.74 before prompt v5); the local numbers are not yet
taken.
