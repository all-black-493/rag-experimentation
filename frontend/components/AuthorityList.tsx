"use client";

import { COLLECTION_LABEL, provenance } from "@/lib/format";
import type { Citation } from "@/lib/types";

interface Props {
  citations: Citation[];
  activeIndex: number | null;
  onOpen: (index: number) => void;
  registerChip?: (index: number, el: HTMLButtonElement | null) => void;
  /** Search mode shows the passage itself; ask mode lists the authorities under the answer. */
  showPassage?: boolean;
  heading?: string;
}

/**
 * The bundle's index: every authority, numbered to match the [n] markers.
 * Rows, not cards. Each is one control that opens the authority.
 */
export function AuthorityList({ citations, activeIndex, onOpen, registerChip, showPassage = false, heading = "Authorities" }: Props) {
  return (
    <section className="mt-8" aria-label={heading}>
      <h2 className="mb-2 font-mono text-xs uppercase tracking-[0.08em] text-ink-3">
        {heading}
      </h2>
      <ol className="divide-y divide-rule border-y border-rule">
        {citations.map((citation) => {
          const active = activeIndex === citation.index;
          return (
            <li key={citation.index}>
              <button
                type="button"
                ref={registerChip ? (el) => registerChip(citation.index, el) : undefined}
                onClick={() => onOpen(citation.index)}
                aria-pressed={active}
                className={[
                  "group grid w-full grid-cols-[2rem_1fr] gap-x-3 py-3 pr-2 text-left transition-colors duration-150 hover:bg-sheet",
                  active ? "bg-sheet" : "",
                ].join(" ")}
              >
                <span
                  className={[
                    "font-mono text-sm tabular",
                    active ? "text-red" : "text-ink-3 group-hover:text-red",
                  ].join(" ")}
                >
                  {citation.index}
                </span>
                <span className="min-w-0">
                  <span className="block font-serif text-base leading-snug text-ink">
                    {citation.title}
                  </span>
                  <span className="mt-0.5 block font-mono text-xs text-ink-3">
                    {COLLECTION_LABEL[citation.collection]} · {provenance(citation)}
                  </span>
                  {citation.via && (
                    <span className="mt-0.5 block truncate font-mono text-xs text-ink-2">{citation.via}</span>
                  )}
                  {showPassage && (
                    <span className="mt-2 line-clamp-3 font-serif text-[0.95rem] leading-relaxed text-ink-2">
                      {citation.text}
                    </span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
