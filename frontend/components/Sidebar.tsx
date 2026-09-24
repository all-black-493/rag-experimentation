"use client";

import { X } from "lucide-react";
import type { ReactNode } from "react";

interface Props {
  /** Desktop: the column is folded away to the left. */
  collapsed: boolean;
  /** Below lg: the column is a sheet over the page. */
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}

/**
 * The left column: fixed, so it keeps its place while the answer scrolls,
 * and foldable, so the reading can have the whole window when it needs it.
 *
 * It does not animate its own width. A width transition on a fixed column
 * re-lays-out everything beside it on every frame; the page reserves the
 * space instead and the column slides behind its own edge, which costs one
 * compositor transform and nothing else.
 */
export function Sidebar({ collapsed, open, onClose, children }: Props) {
  return (
    <>
      <aside
        id="sidebar"
        inert={collapsed || undefined}
        className={[
          "fixed bottom-0 left-0 top-14 z-40 w-[280px] overflow-y-auto overscroll-contain border-r bg-paper-2",
          "transition-transform duration-300 ease-out-expo motion-reduce:transition-none",
          collapsed ? "lg:-translate-x-full lg:border-transparent" : "lg:translate-x-0 lg:border-rule",
          open ? "translate-x-0 border-rule-2 shadow-drawer" : "-translate-x-full border-transparent",
        ].join(" ")}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="press absolute right-2 top-2 grid size-9 place-items-center rounded-control text-ink-2 hover:bg-paper hover:text-ink lg:hidden"
        >
          <X size={18} aria-hidden="true" />
        </button>
        <div className="flex flex-col gap-7 px-4 py-5">{children}</div>
      </aside>

      {open && (
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="fade-in fixed inset-0 z-30 bg-black/60 lg:hidden"
        />
      )}
    </>
  );
}

/** A titled block inside the column. The title names it and says no more. */
export function SidebarSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="px-2 pb-2 font-mono text-[0.6875rem] uppercase tracking-[0.1em] text-ink-3">
        {title}
      </h2>
      {children}
    </section>
  );
}
