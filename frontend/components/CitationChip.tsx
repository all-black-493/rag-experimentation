"use client";

import { forwardRef } from "react";

interface Props {
  index: number;
  active: boolean;
  onOpen: (index: number) => void;
  /** Whether a citation with this index exists; a dangling marker renders inert. */
  exists: boolean;
}

/** An inline [n] marker, rendered as the tab of the authority it points to. */
export const CitationChip = forwardRef<HTMLButtonElement, Props>(function CitationChip(
  { index, active, onOpen, exists },
  ref,
) {
  if (!exists) {
    return (
      <span className="font-mono text-[0.72em] text-ink-3" aria-label={`citation ${index}, not available`}>
        [{index}]
      </span>
    );
  }
  return (
    <button
      ref={ref}
      type="button"
      onClick={() => onOpen(index)}
      aria-label={`Open authority ${index}`}
      aria-pressed={active}
      className={[
        "mx-0.5 inline-flex min-h-5 min-w-5 -translate-y-px items-center justify-center rounded-[3px] border px-1 align-baseline font-mono text-[0.72em] leading-none transition-colors duration-150",
        active
          ? "border-red bg-red text-sheet"
          : "border-red/40 bg-red-tint text-red hover:border-red",
      ].join(" ")}
    >
      {index}
    </button>
  );
});
