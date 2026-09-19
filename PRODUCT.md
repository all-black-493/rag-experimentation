# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Next.js 15 (App Router, TypeScript, Tailwind v4) in `frontend/`, talking to a FastAPI
backend in `backend/` through a same-origin server-side proxy. Decided in the approved
build plan; the user asked for "a very reactive NextJS application".

## Users

Practising Kenyan advocates and paralegals doing case preparation and statutory research,
usually under time pressure. They know the terminology (Acts, sections, holdings, courts,
citations) and want the authority, not an explanation of it. They read on a desktop at a
desk and on a phone between hearings — the user tests from a phone over LAN, and it is a
first-class scene, not an afterthought.

## Product Purpose

Wakili answers legal research questions from Kenyan legislation and case law with cited
sources, and lets the reader inspect every passage the answer rests on. Success is an
answer a lawyer can act on because they can verify it: the statute quoted, the case named,
the court and date visible, the source one click away on kenyalaw.org.

## Positioning

Every answer is built from passages the user can see, in two modes: *Search* returns the
ranked passages themselves for review; *Ask* synthesises a grounded answer on top of them.
A planning step routes each question to legislation, case law or both, infers court and
year filters only when the question names them, and shows what it consulted. Answers that
the sources don't support are declined rather than guessed — the pipeline verifies
groundedness before returning, and strips any citation marker that points nowhere.

## Operating Context

- Corpus: 1,533 documents from new.kenyalaw.org — 543 Acts and subsidiary legislation,
  990 judgments across seven courts (Supreme Court, Court of Appeal, High Court,
  Environment and Land Court, Employment and Labour Relations Court, Magistrates' Courts,
  Kadhis' Courts), judgments 2024 onward.
- Self-hosted: Weaviate, local embedding and reranking models, Claude for planning,
  generation and verification. Langfuse traces every query; a CI gate runs a golden set
  of 36 questions and fails the build on faithfulness, answer rate, citation coverage or
  invalid citations.
- Backend API: `GET /catalog` (collections, courts, year bounds, counts), `POST /query`
  (JSON), `POST /query/stream` (SSE: plan → sources → tokens → done).

## Capabilities and Constraints

- Filters the user can set: collection (legislation / case law), courts, year range. They
  are hard constraints; the planner narrows within them and never widens them.
- Citations carry: collection, title, court, decision date, year, matched passage, the
  surrounding parent window, relevance score, kenyalaw.org URL.
- Streaming: tokens arrive before verification finishes; the final `done` event is
  authoritative and may withdraw an ungrounded answer.
- No accounts, no history persistence, no uploads (corpus only, by decision).
- Not legal advice; the generation prompt avoids disclaimers unless asked what to do.
- Undecided: whether to persist query history per browser.

## Brand Commitments

Name: **Wakili** (Swahili: advocate). Chosen by the user. No logo or existing identity.
A fresh visual identity for a legal-research tone was explicitly requested; the previous
generic doc-chat look (dark charcoal, teal accent, Recoleta) is not to be carried over.

## Evidence on Hand

- Real corpus and real measured numbers (see backend/README.md once the benchmark runs).
- No testimonials, customers, or usage figures. Do not fabricate any.

## Product Principles

1. Verifiability over fluency: the source is the product; the answer is a guide to it.
2. Show the mechanism plainly — what was consulted, which filters applied, whether a
   filter was relaxed — without turning the UI into a dashboard.
3. Respect expertise: legal vocabulary as-is, dense where the reader wants density.
4. The phone is a real workplace: the source panel must never require scrolling past
   the answer to reach.
5. Decline honestly; never pad.

## Accessibility & Inclusion

Keyboard-complete: composer → answer → citation chips → source panel → close. Visible
focus. Contrast at 4.5:1 for body text. Streaming updates announced politely, not on
every token.
