"use client";

import { Fragment, type ReactNode } from "react";
import { splitMarkers } from "@/lib/format";
import { blocks, type Inline } from "@/lib/markdown";
import type { Phase } from "@/lib/useResearch";
import type { Citation, QueryResponse } from "@/lib/types";
import { CitationChip } from "./CitationChip";
import { AuthorityList } from "./AuthorityList";

interface Props {
  phase: Phase;
  draft: string;
  result: QueryResponse | null;
  citations: Citation[];
  activeIndex: number | null;
  onOpen: (index: number) => void;
  registerChip: (index: number, el: HTMLButtonElement | null) => void;
}

/**
 * Ask mode. Streams the draft as it arrives, then swaps in the authoritative
 * answer from `done` - which may have withdrawn the draft if it wasn't
 * grounded, or removed a marker that pointed nowhere.
 */
export function AnswerView({ phase, draft, result, citations, activeIndex, onOpen, registerChip }: Props) {
  // A result with no citations is a decline - for lack of passages, or because
  // the verdict withdrew the answer.
  const declined = result !== null && result.citations.length === 0 && phase === "done";
  // Once `done` lands the answer is final, whatever the verifier says later.
  const text = result?.answer ?? draft;
  const streaming = phase === "answering";

  if (phase === "planning" || (phase === "searching" && !draft)) {
    return <AnswerSkeleton />;
  }

  if (declined) {
    return (
      <div className="prose-law border-l border-rule-2 pl-4 text-ink-2">
        <p>{result?.answer}</p>
      </div>
    );
  }

  const renderInline = (inline: Inline, key: number): ReactNode => {
    const parts = splitMarkers(inline.text).map((part, i) =>
      "marker" in part ? (
        <CitationChip
          key={`${key}-${i}`}
          ref={(el) => registerChip(part.marker, el)}
          index={part.marker}
          exists={part.marker >= 1 && part.marker <= citations.length}
          active={activeIndex === part.marker}
          onOpen={onOpen}
        />
      ) : (
        <Fragment key={`${key}-${i}`}>{part.text}</Fragment>
      ),
    );
    if (inline.kind === "strong") return <strong key={key} className="font-semibold">{parts}</strong>;
    if (inline.kind === "em") return <em key={key}>{parts}</em>;
    return <Fragment key={key}>{parts}</Fragment>;
  };

  return (
    <div>
      <div className="prose-law" aria-busy={streaming}>
        {blocks(text).map((block, i) =>
          block.kind === "paragraph" ? (
            <p key={i}>{block.inlines.map(renderInline)}</p>
          ) : block.ordered ? (
            <ol key={i} className="mt-3 list-decimal space-y-1.5 pl-6 marker:font-mono marker:text-sm marker:text-ink-3">
              {block.items.map((item, j) => (
                <li key={j}>{item.map(renderInline)}</li>
              ))}
            </ol>
          ) : (
            <ul key={i} className="mt-3 list-disc space-y-1.5 pl-6 marker:text-ink-3">
              {block.items.map((item, j) => (
                <li key={j}>{item.map(renderInline)}</li>
              ))}
            </ul>
          ),
        )}
        {streaming && (
          <span className="ml-0.5 inline-block h-[1.1em] w-[2px] translate-y-[0.2em] bg-red motion-safe:animate-pulse" aria-hidden="true" />
        )}
      </div>

      {citations.length > 0 && (
        <AuthorityList citations={citations} activeIndex={activeIndex} onOpen={onOpen} registerChip={registerChip} />
      )}
    </div>
  );
}

function AnswerSkeleton() {
  return (
    <div className="max-w-[68ch] space-y-3" aria-hidden="true">
      <div className="skeleton h-4 w-[92%]" />
      <div className="skeleton h-4 w-[88%]" />
      <div className="skeleton h-4 w-[60%]" />
    </div>
  );
}
