"use client";

import type { Phase } from "@/lib/useResearch";
import type { Citation, QueryResponse } from "@/lib/types";
import { AuthorityList } from "./AuthorityList";
import { Prose } from "./Prose";

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
 * Ask and research. Streams the draft as it arrives, then swaps in the authoritative
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

  return (
    <div>
      <Prose
        text={text}
        sourceCount={citations.length}
        activeIndex={activeIndex}
        onOpen={onOpen}
        registerChip={registerChip}
        streaming={streaming}
      />

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
