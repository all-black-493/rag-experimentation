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
  ask: "Ask a question and get an answer built only from Kenyan legislation and judgments, each claim cited to the passage it rests on.",
  research:
    "Research reads what the first search found, searches again for what it missed and for the other side, and writes a memo: issue, law, authorities, analysis, conclusion.",
  search: "Search returns the passages themselves, ranked by relevance, for you to read and cite.",
};

/**
 * First run. Teaches what the tool does in the space where the answer will
 * appear, with questions the corpus can actually answer.
 */
export function EmptyState({ mode, catalog, onPick }: { mode: Mode; catalog: Catalog | null; onPick: (q: string) => void }) {
  const acts = catalog?.collections.find((c) => c.key === "legislation")?.documents;
  const cases = catalog?.collections.find((c) => c.key === "case_law")?.documents;

  return (
    <div className="max-w-[60ch]">
      <p className="prose-law text-ink-2">
        {PURPOSE[mode]}
        {acts && cases && (
          <span className="text-ink-3">
            {" "}
            {acts.toLocaleString()} Acts and {cases.toLocaleString()} judgments indexed.
          </span>
        )}
      </p>
      <ul className="mt-5 divide-y divide-rule border-y border-rule">
        {EXAMPLES[mode].map((example) => (
          <li key={example}>
            <button
              type="button"
              onClick={() => onPick(example)}
              className="block w-full py-2.5 text-left font-serif text-base text-ink transition-colors duration-150 hover:text-red"
            >
              {example}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
