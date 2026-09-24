"use client";

import type { Catalog, Mode } from "@/lib/types";

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

const PURPOSE: Record<Mode, string> = {
  ask: "An answer built only from Kenyan legislation and judgments, each claim cited to the passage it rests on.",
  research:
    "Reads what the first search found, searches again for what it missed and for the other side, and writes a memo.",
  search: "The passages themselves, ranked, for you to read and cite.",
};

/**
 * First run. Says what this mode does, and offers questions the corpus can
 * actually answer - a question you can send is worth more than a description
 * of the kind of question you could send.
 */
export function EmptyState({
  mode,
  catalog,
  onPick,
}: {
  mode: Mode;
  catalog: Catalog | null;
  onPick: (q: string) => void;
}) {
  const acts = catalog?.collections.find((c) => c.key === "legislation")?.documents;
  const cases = catalog?.collections.find((c) => c.key === "case_law")?.documents;

  return (
    <div>
      <p className="max-w-[58ch] text-ink-2">
        {PURPOSE[mode]}
        {acts && cases && (
          <span className="text-ink-3">
            {" "}
            {acts.toLocaleString()} Acts and {cases.toLocaleString()} judgments indexed.
          </span>
        )}
      </p>
      <div className="mt-5 grid gap-2 sm:grid-cols-3">
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
    </div>
  );
}
