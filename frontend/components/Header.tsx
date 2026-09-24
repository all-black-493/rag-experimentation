import type { ReactNode } from "react";

/**
 * The wordmark, with whatever controls the shell needs beside it. The fold
 * sits to the left of the name, over the column it folds.
 */
export function Header({ children }: { children?: ReactNode }) {
  return (
    <header className="sticky top-0 z-50 flex h-14 items-center gap-2 border-b border-rule bg-paper px-2 md:px-3">
      {children}
      <span className="font-serif text-[1.35rem] leading-none tracking-[-0.02em] text-ink">
        Wakili
      </span>
    </header>
  );
}
