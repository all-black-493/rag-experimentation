"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { followAnalysis, startCaseAnalysis } from "./api";
import type { CaseAnalysis, StepStatus } from "./types";

export type AnalysisPhase = "idle" | "running" | "done";

export interface AnalysisState {
  phase: AnalysisPhase;
  matterId: string | null;
  steps: Record<string, StepStatus>;
  analysis: CaseAnalysis | null;
  error: string | null;
}

const INITIAL: AnalysisState = { phase: "idle", matterId: null, steps: {}, analysis: null, error: null };

function empty(matterId: string): CaseAnalysis {
  return {
    matter_id: matterId,
    created_at: new Date().toISOString(),
    parties: [],
    issues: [],
    facts: [],
    chronology: [],
    authorities: [],
    contradictions: [],
    research_questions: [],
    report: null,
    warnings: [],
    sources: [],
  };
}

/**
 * A case analysis as it lands, section by section, or one already on the
 * matter. Sections fill in as their step finishes; `done` replaces the lot
 * with the analysis as stored.
 */
export function useAnalysis() {
  const [state, setState] = useState<AnalysisState>(INITIAL);
  const controller = useRef<AbortController | null>(null);

  const cancel = useCallback(() => {
    controller.current?.abort();
    controller.current = null;
  }, []);

  useEffect(() => cancel, [cancel]);

  const show = useCallback((analysis: CaseAnalysis) => {
    cancel();
    setState({ phase: "done", matterId: analysis.matter_id, steps: {}, analysis, error: null });
  }, [cancel]);

  const start = useCallback(
    async (matterId: string) => {
      cancel();
      const current = new AbortController();
      controller.current = current;
      setState({ phase: "running", matterId, steps: {}, analysis: empty(matterId), error: null });
      try {
        const { job_id } = await startCaseAnalysis(matterId);
        for await (const event of followAnalysis(job_id, current.signal)) {
          if (current.signal.aborted) return;
          setState((s) => {
            const analysis = s.analysis ?? empty(matterId);
            switch (event.event) {
              case "step":
                return { ...s, steps: { ...s.steps, [event.data.name]: event.data.status } };
              case "authorities":
              case "parties":
              case "facts":
              case "chronology":
              case "issues":
              case "contradictions":
                return { ...s, analysis: { ...analysis, ...event.data } };
              case "questions":
                return { ...s, analysis: { ...analysis, research_questions: event.data.questions } };
              case "report":
                return { ...s, analysis: { ...analysis, report: event.data.report } };
              case "done":
                return { ...s, phase: "done", analysis: event.data };
              case "error":
                return { ...s, phase: "done", error: event.data.detail };
            }
          });
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

  const close = useCallback(() => {
    cancel();
    setState(INITIAL);
  }, [cancel]);

  return { state, start, show, close };
}
