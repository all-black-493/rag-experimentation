"use client";

import { describeOutcome } from "@/lib/format";
import type { Phase } from "@/lib/useResearch";
import type { Mode, Plan, ReviewEvent, SubQueryOutcome } from "@/lib/types";

interface Props {
  phase: Phase;
  mode: Mode;
  plan: Plan | null;
  retrieval: SubQueryOutcome[];
  reviews?: ReviewEvent[];
  courtNames: Map<string, string>;
  // After the verdict: whether the answer stood.
  grounded?: boolean | null;
}

const STATUS: Record<Exclude<Phase, "idle" | "done">, string> = {
  planning: "Deciding where to look…",
  searching: "Searching and ranking passages…",
  reviewing: "Reading what was found for what is missing…",
  answering: "Writing the answer…",
  verifying: "Checking the answer against its sources…",
};

/**
 * Where the work has got to, and what it searched - one line, only while it
 * has something to say. During a long answer the phase is the only thing a
 * reader wants; once it is done, the collections it consulted are a fact
 * worth keeping and everything else was commentary.
 */
export function PlanStrip({ phase, mode, plan, retrieval, reviews = [], courtNames, grounded }: Props) {
  if (phase === "idle") return null;

  const outcomes = retrieval.length
    ? retrieval.map((o) => describeOutcome(o, courtNames))
    : plan?.sub_queries.map((s) =>
        describeOutcome(
          { query: s.query, collection: s.collection, filters: { courts: s.courts, year_from: s.year_from ?? undefined, year_to: s.year_to ?? undefined }, retrieved: 0, relaxed: false, round: 1 },
          courtNames,
        ),
      ) ?? [];
  const consulted = Array.from(new Set(outcomes));
  const verified = phase === "done" && mode !== "search" && grounded === true;
  const followUps = reviews.flatMap((review) => review.follow_ups.length);

  return (
    <div
      className="flex min-h-6 flex-wrap items-baseline gap-x-3 font-mono text-xs text-ink-3"
      role="status"
      aria-live="polite"
    >
      {phase !== "done" && <span className="text-ink-2">{STATUS[phase]}</span>}
      {consulted.length > 0 && <span>{consulted.join(" · ")}</span>}
      {followUps.length > 0 && (
        <span>{`searched again ${followUps.length === 1 ? "once" : `${followUps.length} times`}`}</span>
      )}
      {verified && <span className="text-ok">verified</span>}
    </div>
  );
}
