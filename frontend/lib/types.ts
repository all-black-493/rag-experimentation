// Mirrors backend/app/api/schemas.py. Change both or neither.

export type Collection = "legislation" | "case_law";
export type Mode = "search" | "ask";

export interface QueryFilters {
  collections: Collection[];
  courts: string[];
  year_from: number | null;
  year_to: number | null;
}

export interface QueryRequest {
  question: string;
  mode: Mode;
  filters: QueryFilters;
}

export interface SubQuery {
  query: string;
  collection: Collection;
  courts: string[];
  year_from: number | null;
  year_to: number | null;
}

export interface Plan {
  sub_queries: SubQuery[];
  rationale: string;
  origin: "planner" | "fallback";
}

export interface SubQueryOutcome {
  query: string;
  collection: Collection;
  filters: { courts?: string[]; year_from?: number; year_to?: number };
  retrieved: number;
  relaxed: boolean;
}

export interface Citation {
  index: number;
  collection: Collection;
  title: string;
  url: string;
  court: string | null;
  court_code: string | null;
  decision_date: string | null;
  year: number | null;
  chunk_index: number | null;
  text: string;
  parent_text: string;
  relevance_score: number | null;
}

export interface QueryResponse {
  mode: Mode;
  question: string;
  plan: Plan | null;
  retrieval: SubQueryOutcome[];
  citations: Citation[];
  answer: string | null;
  grounded: boolean | null;
}

export interface CourtInfo {
  code: string;
  name: string;
  rank: number;
  documents: number;
}

export interface CollectionInfo {
  key: Collection;
  label: string;
  description: string;
  documents: number;
  passages: number;
  year_min: number | null;
  year_max: number | null;
  courts: CourtInfo[];
}

export interface Catalog {
  collections: CollectionInfo[];
}

export interface Verdict {
  grounded: boolean;
  withdrawn: boolean;
  // What replaces the answer when it's withdrawn.
  answer: string | null;
}

// Server-sent events from POST /query/stream, in the order they arrive.
// `done` carries the final answer; in ask mode `verdict` follows it.
export type StreamEvent =
  | { event: "plan"; data: { plan: Plan | null } }
  | { event: "sources"; data: { citations: Citation[] } }
  | { event: "token"; data: { text: string } }
  | { event: "done"; data: QueryResponse }
  | { event: "verdict"; data: Verdict }
  | { event: "error"; data: { detail: string } };
