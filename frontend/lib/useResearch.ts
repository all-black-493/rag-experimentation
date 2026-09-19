"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { streamQuery } from "./api";
import type { Citation, Mode, Plan, QueryFilters, QueryResponse, SubQueryOutcome } from "./types";

/**
 * What the screen is doing, in the words the status line uses.
 *
 * planning   the question is with the planner
 * searching  the plan is known, passages are being retrieved and reranked
 * answering  tokens are arriving
 * verifying  the answer is final; the groundedness check hasn't returned
 * done       the verdict is in (or search results are)
 */
export type Phase = "idle" | "planning" | "searching" | "answering" | "verifying" | "done";

export interface ResearchState {
  phase: Phase;
  question: string;
  mode: Mode;
  plan: Plan | null;
  retrieval: SubQueryOutcome[];
  citations: Citation[];
  // The streamed preview; replaced by the final answer on `done`.
  draft: string;
  result: QueryResponse | null;
  // Ask mode, after `verdict`: true if the answer was withdrawn as ungrounded.
  withdrawn: boolean;
  error: string | null;
}

const INITIAL: ResearchState = {
  phase: "idle",
  question: "",
  mode: "ask",
  plan: null,
  retrieval: [],
  citations: [],
  draft: "",
  result: null,
  withdrawn: false,
  error: null,
};


export function useResearch() {
  const [state, setState] = useState<ResearchState>(INITIAL);
  const controller = useRef<AbortController | null>(null);

  const cancel = useCallback(() => {
    controller.current?.abort();
    controller.current = null;
  }, []);

  useEffect(() => cancel, [cancel]);

  const submit = useCallback(
    async (question: string, mode: Mode, filters: QueryFilters, matterId: string | null = null) => {
      cancel();
      const current = new AbortController();
      controller.current = current;
      setState({ ...INITIAL, phase: "planning", question, mode });

      try {
        for await (const event of streamQuery(
          { question, mode, filters, matter_id: matterId },
          current.signal,
        )) {
          if (current.signal.aborted) return;
          switch (event.event) {
            case "plan":
              setState((s) => ({ ...s, phase: "searching", plan: event.data.plan }));
              break;
            case "sources":
              setState((s) => ({
                ...s,
                citations: event.data.citations,
                phase: mode === "search" ? s.phase : "answering",
              }));
              break;
            case "token":
              setState((s) => ({ ...s, phase: "answering", draft: s.draft + event.data.text }));
              break;
            case "done":
              // The answer is final. In ask mode the verifier is still running;
              // the reader can start now rather than wait for its verdict.
              setState((s) => ({
                ...s,
                phase: mode === "ask" && event.data.citations.length ? "verifying" : "done",
                result: event.data,
                plan: event.data.plan,
                retrieval: event.data.retrieval,
                citations: event.data.citations,
                draft: event.data.answer ?? s.draft,
              }));
              break;
            case "verdict":
              setState((s) => ({
                ...s,
                phase: "done",
                withdrawn: event.data.withdrawn,
                result: s.result
                  ? {
                      ...s.result,
                      grounded: event.data.grounded,
                      answer: event.data.withdrawn ? event.data.answer : s.result.answer,
                      citations: event.data.withdrawn ? [] : s.result.citations,
                    }
                  : s.result,
                citations: event.data.withdrawn ? [] : s.citations,
              }));
              break;
            case "error":
              throw new Error(event.data.detail);
          }
        }
      } catch (error) {
        if (current.signal.aborted) return;
        setState((s) => ({
          ...s,
          phase: "done",
          error: error instanceof Error ? error.message : "Something went wrong.",
        }));
      }
    },
    [cancel],
  );

  const reset = useCallback(() => {
    cancel();
    setState(INITIAL);
  }, [cancel]);

  return { state, submit, cancel, reset };
}
