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
  relationships: boolean;
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
  doc_id: string;
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
  // Why the citation graph added this passage: "cites X", "applies section N of Y".
  via: string | null;
}

export interface Expansion {
  lookups: { cited: string; passages: number; added: number }[];
  neighbours: number;
  added: number;
}

export interface QueryResponse {
  mode: Mode;
  question: string;
  plan: Plan | null;
  retrieval: SubQueryOutcome[];
  expansion: Expansion | null;
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

// A document one citation away from an authority, with every way the link was written.
export interface GraphLink {
  doc_id: string | null;
  collection: Collection | null;
  title: string | null;
  url: string | null;
  kind: "cites" | "applies";
  parties: string | null;
  refs: string[];
  via_doc_id: string;
  via_chunk_index: number;
}

export interface GraphNeighbourhood {
  doc_id: string;
  cites: GraphLink[];
  cited_by: GraphLink[];
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
