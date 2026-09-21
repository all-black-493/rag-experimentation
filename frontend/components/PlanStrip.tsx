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
 * What was consulted, in one line. The mechanism made visible without a
 * dashboard: collections, any court or year restriction, and whether the
 * planner's own restriction had to be relaxed.
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
  const relaxed = retrieval.filter((o) => o.relaxed).length;

  return (
    <div className="flex min-h-6 flex-wrap items-baseline gap-x-3 gap-y-1 font-mono text-xs text-ink-2" role="status" aria-live="polite">
      {phase !== "done" && (
        <span className="text-red">{STATUS[phase]}</span>
      )}
      {consulted.length > 0 && (
        <span>
          <span className="text-ink-3">Consulted</span> {consulted.join(" — ")}
          {plan && plan.sub_queries.length > 1 && (
            <span className="text-ink-3"> · {plan.sub_queries.length} queries</span>
          )}
        </span>
      )}
      {relaxed > 0 && (
        <span className="text-ink-3">
          · {relaxed === 1 ? "a restriction was" : `${relaxed} restrictions were`} widened to find enough
        </span>
      )}
      {reviews
        .filter((review) => review.follow_ups.length > 0)
        .map((review) => (
          <span key={review.round}>
            <span className="text-ink-3">· Pass {review.round + 1}</span>{" "}
            {review.follow_ups.map((f) => f.reason).join(", ")}
          </span>
        ))}
      {phase === "done" && mode !== "search" && grounded === true && (
        <span className="text-ok">· verified against its sources</span>
      )}
      {plan?.origin === "fallback" && phase === "done" && (
        <span className="text-ink-3">· planner unavailable, searched everything in scope</span>
      )}
      {phase === "done" && mode !== "search" && consulted.length === 0 && (
        <span className="text-ink-3">Nothing consulted.</span>
      )}
    </div>
  );
}
