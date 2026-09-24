"use client";

import type { Mode } from "@/lib/types";

const EXAMPLES: Record<Mode, string[]> = {
  ask: [
    "What is the penalty for illegally manufacturing or possessing tea under the Tea Act?",
    "How have Kenyan courts treated the burden of proving compelling reasons to deny bail?",
    "Does a licensed auctioneer need a separate licence to sell seized liquor?",
  ],
  research: [
    "Is a probationary employee entitled to notice on termination?",
    "Can a landlord levy distress for rent while the tenant disputes the arrears?",
    "When may a court deny bail for a pending charge of robbery with violence?",
  ],
  search: [
    "robbery with violence section 296(2) Penal Code",
    "gratuity versus severance pay Employment Act",
    "judicial notice Evidence Act section 60",
  ],
};

/**
 * First run. Questions the corpus can actually answer, ready to send - which
 * teaches more about what this does than a paragraph describing it would.
 */
export function EmptyState({ mode, onPick }: { mode: Mode; onPick: (q: string) => void }) {
  return (
    <div className="grid gap-2 sm:grid-cols-3">
      {EXAMPLES[mode].map((example) => (
        <button
          key={example}
          type="button"
          onClick={() => onPick(example)}
          className="rounded-panel border border-rule bg-paper-2 p-3.5 text-left font-serif text-base leading-snug text-ink-2 transition-colors duration-150 hover:border-rule-2 hover:bg-sheet hover:text-ink"
        >
          {example}
        </button>
      ))}
    </div>
  );
}
