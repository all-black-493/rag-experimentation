"use client";

import { ChevronLeft, ChevronRight, ExternalLink, X } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import { COLLECTION_LABEL, provenance } from "@/lib/format";
import type { Citation } from "@/lib/types";
import { Neighbourhood } from "./Neighbourhood";

interface Props {
  citations: Citation[];
  index: number;
  onNavigate: (index: number) => void;
  onClose: () => void;
}

/**
 * The bundle of authorities, opened at one tab.
 *
 * Desktop: a column beside the working page, sliding in from the right.
 * Phone: a sheet rising from the bottom over the answer - the source is never
 * something you scroll down to find. The matched passage is shown inside its
 * parent window, and the highlighter is drawn across it on open.
 */
export function SourcePanel({ citations, index, onNavigate, onClose }: Props) {
  const citation = citations.find((c) => c.index === index);
  const heading = useRef<HTMLHeadingElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const first = citations[0]?.index ?? 1;
  const last = citations[citations.length - 1]?.index ?? 1;

  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
    body.current?.querySelector(".marker")?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [index]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowLeft" && index > first) onNavigate(index - 1);
      if (event.key === "ArrowRight" && index < last) onNavigate(index + 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, first, last, onClose, onNavigate]);

  const segments = useMemo(() => (citation ? highlight(citation.parent_text, citation.text) : null), [citation]);

  if (!citation) return null;

  return (
    <aside
      role="dialog"
      aria-modal="false"
      aria-labelledby="authority-title"
      className={[
        "flex flex-col bg-sheet",
        // Phone: a sheet rising over the page.
        "fixed inset-x-0 bottom-0 z-30 h-[85dvh] rounded-t-panel border-t border-rule-2 shadow-sheet sheet-enter",
        // Laptop: a drawer over the right of the page.
        "lg:inset-y-0 lg:left-auto lg:right-0 lg:h-auto lg:w-[420px] lg:rounded-none lg:border-t-0 lg:border-l lg:shadow-drawer lg:drawer-enter",
        // Wide: its own column beside the page, staying put while the page scrolls.
        "xl:sticky xl:top-0 xl:h-dvh xl:w-auto xl:self-start xl:shadow-none",
      ].join(" ")}
    >
      <div className="flex items-center justify-between gap-2 border-b border-rule px-4 py-2.5 lg:px-5">
        <div className="flex items-center gap-1 font-mono text-xs text-ink-2">
          <button
            type="button"
            onClick={() => onNavigate(index - 1)}
            disabled={index <= first}
            aria-label="Previous authority"
            className="grid size-8 place-items-center rounded-control text-ink-2 transition-colors duration-150 hover:bg-paper-2 hover:text-ink disabled:cursor-not-allowed disabled:text-rule-2"
          >
            <ChevronLeft size={16} aria-hidden="true" />
          </button>
          <span className="tabular">
            Authority <span className="text-red">{index}</span> of {last}
          </span>
          <button
            type="button"
            onClick={() => onNavigate(index + 1)}
            disabled={index >= last}
            aria-label="Next authority"
            className="grid size-8 place-items-center rounded-control text-ink-2 transition-colors duration-150 hover:bg-paper-2 hover:text-ink disabled:cursor-not-allowed disabled:text-rule-2"
          >
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close authority"
          className="grid size-9 place-items-center rounded-control text-ink-2 transition-colors duration-150 hover:bg-paper-2 hover:text-ink"
        >
          <X size={18} aria-hidden="true" />
        </button>
      </div>

      <div ref={body} className="min-h-0 flex-1 overflow-y-auto px-4 py-5 lg:px-6">
        <h2
          id="authority-title"
          ref={heading}
          tabIndex={-1}
          className="font-serif text-lg font-medium leading-snug outline-none"
        >
          {citation.title}
        </h2>
        <p className="mt-1.5 font-mono text-xs text-ink-2">
          {COLLECTION_LABEL[citation.collection]} · {provenance(citation)}
          {citation.chunk_index !== null && (
            <span className="text-ink-3"> · passage {citation.chunk_index + 1}</span>
          )}
        </p>
        {citation.via && <p className="mt-0.5 font-mono text-xs text-ink-2">{citation.via}</p>}
        <a
          href={citation.url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-flex items-center gap-1.5 text-sm text-red underline-offset-2 hover:underline"
        >
          Open on kenyalaw.org
          <ExternalLink size={13} aria-hidden="true" />
        </a>

        <div className="prose-law mt-5 whitespace-pre-line text-[1rem]">
          {segments ? (
            <p>
              {segments.before}
              <mark key={citation.index} className="marker marker--sweep text-ink">
                {segments.match}
              </mark>
              {segments.after}
            </p>
          ) : (
            <>
              <p>
                <mark key={citation.index} className="marker marker--sweep text-ink">
                  {citation.text}
                </mark>
              </p>
              <p className="mt-4 text-ink-2">{citation.parent_text}</p>
            </>
          )}
        </div>

        <Neighbourhood docId={citation.doc_id} />
      </div>
    </aside>
  );
}

/** Locate the matched child inside its parent window, tolerating whitespace differences. */
function highlight(parent: string, child: string): { before: string; match: string; after: string } | null {
  const direct = parent.indexOf(child);
  if (direct !== -1) {
    return { before: parent.slice(0, direct), match: child, after: parent.slice(direct + child.length) };
  }
  const collapse = (s: string) => s.replace(/\s+/g, " ").trim();
  const p = collapse(parent);
  const c = collapse(child);
  const at = p.indexOf(c);
  if (at === -1) return null;
  return { before: p.slice(0, at), match: c, after: p.slice(at + c.length) };
}
