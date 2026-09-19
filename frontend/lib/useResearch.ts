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
 * verifying  tokens stopped, the groundedness check hasn't returned
 * done       the authoritative result is in
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
  error: null,
};

// Tokens that stop arriving for this long, before `done`, mean the model has
// finished and the verifier is running.
const VERIFYING_AFTER_MS = 700;

export function useResearch() {
  const [state, setState] = useState<ResearchState>(INITIAL);
  const controller = useRef<AbortController | null>(null);
  const lull = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancel = useCallback(() => {
    controller.current?.abort();
    controller.current = null;
    if (lull.current) clearTimeout(lull.current);
  }, []);

  useEffect(() => cancel, [cancel]);

  const submit = useCallback(
    async (question: string, mode: Mode, filters: QueryFilters) => {
      cancel();
      const current = new AbortController();
      controller.current = current;
      setState({ ...INITIAL, phase: "planning", question, mode });

      const armLull = () => {
        if (lull.current) clearTimeout(lull.current);
        lull.current = setTimeout(() => {
          setState((s) => (s.phase === "answering" ? { ...s, phase: "verifying" } : s));
        }, VERIFYING_AFTER_MS);
      };

      try {
        for await (const event of streamQuery({ question, mode, filters }, current.signal)) {
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
              armLull();
              break;
            case "done":
              if (lull.current) clearTimeout(lull.current);
              setState((s) => ({
                ...s,
                phase: "done",
                result: event.data,
                plan: event.data.plan,
                retrieval: event.data.retrieval,
                citations: event.data.citations,
                draft: event.data.answer ?? s.draft,
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
