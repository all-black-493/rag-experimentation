"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { followRun, startResearch, streamQuery } from "./api";
import type {
  Citation,
  Mode,
  Plan,
  QueryFilters,
  QueryRequest,
  QueryResponse,
  ReviewEvent,
  StreamEvent,
  SubQueryOutcome,
} from "./types";

/**
 * What the screen is doing, in the words the status line uses.
 *
 * planning   the question is with the planner
 * searching  the plan is known, passages are being retrieved and reranked
 * reviewing  research: the pass is being read for what it missed
 * answering  tokens are arriving
 * verifying  the answer is final; the groundedness check hasn't returned
 * done       the verdict is in (or search results are)
 */
export type Phase = "idle" | "planning" | "searching" | "reviewing" | "answering" | "verifying" | "done";

export interface ResearchState {
  phase: Phase;
  question: string;
  mode: Mode;
  plan: Plan | null;
  retrieval: SubQueryOutcome[];
  // Research: one entry per pass reviewed.
  reviews: ReviewEvent[];
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
  reviews: [],
  citations: [],
  draft: "",
  result: null,
  withdrawn: false,
  error: null,
};


export function useResearch(onFinished?: (state: ResearchState) => void) {
  const [state, setState] = useState<ResearchState>(INITIAL);
  const controller = useRef<AbortController | null>(null);
  // Held in a ref so a run that finishes after a re-render still calls the
  // callback the page has now, not the one it had when the run started.
  const finished = useRef(onFinished);
  finished.current = onFinished;

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
      // Mirrors what the page is showing, so the finished run can be handed
      // over whole without reading state through a stale closure.
      let latest: ResearchState = { ...INITIAL, phase: "planning", question, mode };
      // The accumulator is authoritative and React mirrors it, not the other
      // way round: an updater runs when React chooses to, so reading the
      // finished run out of one would read whatever had been applied so far.
      const update = (next: (s: ResearchState) => ResearchState) => {
        latest = next(latest);
        setState(latest);
      };
      setState(latest);

      try {
        const request: QueryRequest = { question, mode, filters, matter_id: matterId };
        for await (const event of events(request, current.signal)) {
          if (current.signal.aborted) return;
          switch (event.event) {
            case "plan":
              update((s) => ({ ...s, phase: "searching", plan: event.data.plan }));
              break;
            case "sources":
              update((s) => ({
                ...s,
                citations: event.data.citations,
                phase: mode === "search" ? s.phase : mode === "research" ? "reviewing" : "answering",
              }));
              break;
            case "review":
              update((s) => ({
                ...s,
                reviews: [...s.reviews, event.data],
                phase: event.data.another_pass ? "searching" : "answering",
              }));
              break;
            case "token":
              update((s) => ({ ...s, phase: "answering", draft: s.draft + event.data.text }));
              break;
            case "done":
              // The answer is final. In ask mode the verifier is still running;
              // the reader can start now rather than wait for its verdict.
              update((s) => ({
                ...s,
                phase: mode !== "search" && event.data.citations.length ? "verifying" : "done",
                result: event.data,
                plan: event.data.plan,
                retrieval: event.data.retrieval,
                citations: event.data.citations,
                draft: event.data.answer ?? s.draft,
              }));
              break;
            case "verdict":
              update((s) => ({
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
        if (!current.signal.aborted) finished.current?.(latest);
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

  /** Put a finished conversation back on the page, without asking again. */
  const restore = useCallback(
    (previous: ResearchState) => {
      cancel();
      setState(previous);
    },
    [cancel],
  );

  /** Back to an empty desk. */
  const reset = useCallback(() => {
    cancel();
    setState(INITIAL);
  }, [cancel]);

  return { state, submit, cancel, restore, reset };
}

/** A query streams from one request; a research run is started, then followed. */
async function* events(request: QueryRequest, signal: AbortSignal): AsyncGenerator<StreamEvent> {
  if (request.mode === "research") {
    const { job_id } = await startResearch(request);
    yield* followRun(job_id, signal);
    return;
  }
  yield* streamQuery(request, signal);
}
