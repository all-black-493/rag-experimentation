import type { ReactNode } from "react";

export function Header({ children }: { children?: ReactNode }) {
  return (
    <header className="flex h-14 items-center justify-between border-b border-rule px-4 md:px-6">
      <span className="font-serif text-xl font-medium tracking-[-0.01em]">Wakili</span>
      {children}
    </header>
  );
}
