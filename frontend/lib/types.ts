// Mirrors backend/app/api/schemas.py. Change both or neither.

export type Collection = "legislation" | "case_law" | "matter";
// search: ranked passages. ask: one pass, a cited answer. research: the pass
// is reviewed for what it missed, searched again, and written up as a memo.
export type Mode = "search" | "ask" | "research";

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
  // The user's own documents to search alongside the corpus.
  matter_id: string | null;
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
  // Which pass ran it: 1 for the plan, 2 for a review's follow-ups.
  round: number;
}

export interface FollowUp {
  query: string;
  collection: Collection;
  reason: string;
}

// What a research pass's review found missing, and what it searched for next.
export interface ReviewOutcome {
  round: number;
  missing: string;
  follow_ups: FollowUp[];
}

export interface ReviewEvent {
  round: number;
  missing: string | null;
  follow_ups: FollowUp[];
  another_pass: boolean;
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
  // Matter documents only: the page and the box on it the passage sits in.
  matter_id: string | null;
  page: number | null;
  bbox: [number, number, number, number] | null;
  page_width: number | null;
  page_height: number | null;
  text: string;
  parent_text: string;
  relevance_score: number | null;
  // Why the citation graph added this passage: "cites X", "applies section N of Y".
  via: string | null;
}

export type DocumentKind = "pdf" | "docx" | "text";
export type DocumentStatus = "queued" | "running" | "indexed" | "failed";

export interface DocumentProfile {
  summary: string;
  document_type: string;
  parties: string[];
  dates: string[];
}

export interface MatterDocument {
  doc_id: string;
  name: string;
  kind: DocumentKind;
  bytes: number;
  status: DocumentStatus;
  pages: number | null;
  chunks: number | null;
  error: string | null;
  profile: DocumentProfile | null;
  profile_error: string | null;
  added_at: string;
}

export interface WorkflowAccepted {
  job_id: string;
  workflow: string;
  question: string;
}

export interface Matter {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  documents: MatterDocument[];
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
  reviews: ReviewOutcome[];
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
  | { event: "review"; data: ReviewEvent }
  | { event: "token"; data: { text: string } }
  | { event: "done"; data: QueryResponse }
  | { event: "verdict"; data: Verdict }
  | { event: "error"; data: { detail: string } };
