# Design

<!-- impeccable:design-schema 1 -->

Wakili's visual world, recorded from `frontend/` as built. Tokens live in
`frontend/app/globals.css` (`@theme`); this file explains them.

## World

Paper, ink, one red. The materials are the practitioner's own: the law-report
page, the bound statute, the bundle of authorities with numbered tabs. Light
throughout — the use scene is daylight at a desk or a phone in a court corridor.
No cards, no gradients, no decorative shadows; hairline rules separate, and the
only elevation is the bundle lifting off the page.

## Color

| token | value | role |
|---|---|---|
| `paper` | `#f6f2ea` | page ground |
| `paper-2` | `#ede7db` | second neutral: filter rail, panel headers |
| `sheet` | `#fdfbf6` | working surfaces: query slip, bundle, active row |
| `ink` / `ink-2` / `ink-3` | `#1b1916` / `#4d4740` / `#6c655c` | text, secondary, faint (all ≥4.5:1 on every ground) |
| `rule` / `rule-2` | `#d8d0c1` / `#c6bcaa` | hairlines, control borders |
| `red` / `red-2` / `red-tint` | `#7a1f1f` / `#5c1717` / `#f2e3df` | the one accent: primary action, active mode, citation chips, live status |
| `marker` | `#f1e0a5` | the highlighter drawn across a matched passage |

Red is never decorative. It marks what is actionable or currently active and
nothing else; inactive controls stay in ink and rule tones.

## Type

IBM Plex in three cuts, self-hosted via `next/font`:

- **Serif** — anything read as law: the question, answers, passages, titles,
  empty-state copy. `.prose-law`: 1.0625rem / 1.6, measure 68ch.
- **Sans** — anything operated: buttons, labels, filters, status.
- **Mono** — identifiers and data: neutral citations, courts and dates,
  document counts, the plan strip. Tabular numerals on counts.

Scale is fixed rem at ~1.2 steps (`text-xs` 0.75 → `text-2xl` 1.75). No
tracking below −0.01em. Headings do not carry kickers.

## Layout

A research desk: wordmark header (56px), filter rail (260px), working page
(max 76ch, composer at the top), bundle.

| width | rail | bundle |
|---|---|---|
| < 1024 | sheet from the left, opened from the header's Filters button | sheet rising from the bottom, 85dvh |
| 1024–1279 | column | drawer over the right of the page, 420px |
| ≥ 1280 | column | third column, 360–420px |

The source is never below the answer: on every width the bundle appears over
or beside the page, never at the end of it.

## Components

- **Query slip** (`QueryComposer`): serif textarea, mode toggle, one red
  action. Enter submits; Shift+Enter breaks a line; Stop replaces the action
  while a query runs.
- **Mode toggle** (`ModeToggle`): a radiogroup; the active option sits on
  `sheet` in red.
- **Filter rail** (`FilterRail`): checkboxes with mono counts, year inputs in
  mono, help lines in `ink-3`. Built from `/catalog`; never hardcoded.
- **Plan strip** (`PlanStrip`): one mono line — live status in red while
  running, then what was consulted, query count, and any widened restriction.
- **Citation chip** (`CitationChip`): `[n]` as a small mono tab in red-tint;
  red fill when its authority is open; inert text when it points nowhere.
- **Authority list** (`AuthorityList`): rows on hairlines, mono index, serif
  title, mono provenance. Search mode adds a three-line passage preview.
- **Bundle** (`SourcePanel`): "Authority n of N" with prev/next, serif title,
  mono provenance, link out, the parent window with the matched child under
  the marker. Escape closes; arrows navigate; focus returns to the chip.
- **Empty state**: a sentence of purpose and three real questions as rows.
- **Skeletons** shimmer in paper tones; no spinners in content.

## Motion

One authored moment: the highlighter sweep (`.marker--sweep`, 520ms,
exponential ease-out) when an authority opens. Panels enter with a short rise
or slide (≤320ms). Everything else is a 150ms color transition. All of it is
disabled under `prefers-reduced-motion`.

## Browser surfaces

Selection is `marker` on ink; the caret is red; focus rings are 2px red with
2px offset; scrollbars are thin in `rule-2`; underline offset 0.18em.
