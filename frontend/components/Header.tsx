import type { ReactNode } from "react";

/** The wordmark, and whatever the page needs beside it. */
export function Header({ children }: { children?: ReactNode }) {
  return (
    <header className="flex h-14 items-center justify-between border-b border-rule px-4 md:px-6">
      <span className="font-serif text-[1.35rem] leading-none tracking-[-0.02em] text-ink">
        Wakili
      </span>
      {children}
    </header>
  );
}
