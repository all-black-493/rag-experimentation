"use client";

import type { Mode } from "@/lib/types";

const OPTIONS: Array<{ value: Mode; label: string; hint: string }> = [
  { value: "ask", label: "Ask", hint: "A cited answer" },
  { value: "search", label: "Search", hint: "Ranked passages to review" },
];

export function ModeToggle({ value, onChange }: { value: Mode; onChange: (mode: Mode) => void }) {
  return (
    <div
      role="radiogroup"
      aria-label="Mode"
      className="inline-flex rounded-control border border-rule-2 bg-paper-2 p-0.5"
    >
      {OPTIONS.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            title={option.hint}
            onClick={() => onChange(option.value)}
            className={[
              "min-h-9 rounded-[4px] px-3 text-sm font-medium transition-colors duration-150",
              active
                ? "bg-sheet text-red shadow-[0_1px_2px_rgb(27_25_22_/_0.12)]"
                : "text-ink-2 hover:text-ink",
            ].join(" ")}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
