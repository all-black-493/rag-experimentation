import { readEvents } from "./stream";
import type {
  AnalysisEvent,
  Catalog,
  GraphNeighbourhood,
  Matter,
  MatterEvent,
  QueryRequest,
  StreamEvent,
  WorkflowAccepted,
} from "./types";

/**
 * What went wrong, in words a reader can act on.
 *
 * A 4xx is the reader's to fix and the server says why - the file is too
 * large, the matter is gone - so that sentence is passed through. A 5xx is
 * ours, and a status code tells the reader nothing they can do anything
 * about, so it never reaches the page.
 */
async function failure(response: Response): Promise<Error> {
  if (response.status === 429) {
    return new Error("Too many requests just now. Wait a moment and try again.");
  }
  if (response.status < 500) {
    try {
      const body = await response.json();
      if (typeof body.detail === "string" && body.detail) return new Error(body.detail);
    } catch {
      // No JSON body: fall through to the general sentence.
    }
  }
  return new Error("Something went wrong at our end. Try again in a moment.");
}

export async function fetchCatalog(): Promise<Catalog> {
  const response = await fetch("/api/catalog");
  if (!response.ok) throw await failure(response);
  return response.json();
}

/** What a document cites and what cites it; null when nothing is recorded. */
export async function fetchNeighbourhood(docId: string): Promise<GraphNeighbourhood | null> {
  const response = await fetch(`/api/graph/${encodeURIComponent(docId)}`);
  if (response.status === 404) return null;
  if (!response.ok) throw await failure(response);
  return response.json();
}

export async function listMatters(): Promise<Matter[]> {
  const response = await fetch("/api/matters");
  if (!response.ok) throw await failure(response);
  return response.json();
}

export async function createMatter(name: string): Promise<Matter> {
  const response = await fetch("/api/matters", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!response.ok) throw await failure(response);
  return response.json();
}

export async function fetchMatter(id: string): Promise<Matter> {
  const response = await fetch(`/api/matters/${id}`, { cache: "no-store" });
  if (!response.ok) throw await failure(response);
  return response.json();
}

/** Accepted, not indexed: the document's status on the matter says when it is. */
export async function uploadDocument(matterId: string, file: File): Promise<void> {
  const body = new FormData();
  body.append("file", file, file.name);
  const response = await fetch(`/api/matters/${matterId}/documents`, { method: "POST", body });
  if (!response.ok) throw await failure(response);
}

export async function deleteDocument(matterId: string, docId: string): Promise<void> {
  const response = await fetch(`/api/matters/${matterId}/documents/${docId}`, { method: "DELETE" });
  if (!response.ok) throw await failure(response);
}

/** Where the original is served from, same-origin, for the viewer and for a link out. */
export function documentUrl(matterId: string, docId: string): string {
  return `/api/matters/${matterId}/files/${docId}`;
}

/** Start a research run; its events are followed separately, so a reload can pick it up. */
export async function startResearch(request: QueryRequest): Promise<WorkflowAccepted> {
  const response = await fetch("/api/workflows/research", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) throw await failure(response);
  return response.json();
}

/** Every event of a run so far, then each new one until it ends. */
export async function* followRun(jobId: string, signal: AbortSignal): AsyncGenerator<StreamEvent> {
  const response = await fetch(`/api/workflows/${jobId}/events`, {
    headers: { accept: "text/event-stream" },
    signal,
  });
  if (!response.ok) throw await failure(response);
  yield* readEvents(response, signal);
}

/**
 * A matter's state now, then again on every change, until nothing is indexing.
 *
 * The server closes the stream when the last document is in, which is the
 * signal to stop watching - there is nothing further to hear.
 */
export async function* followMatter(
  matterId: string,
  signal: AbortSignal,
): AsyncGenerator<Matter> {
  const response = await fetch(`/api/matters/${matterId}/events`, {
    headers: { accept: "text/event-stream" },
    signal,
  });
  if (!response.ok) throw await failure(response);
  for await (const event of readEvents<MatterEvent>(response, signal)) {
    yield event.data;
  }
}

/** Read a matter's documents into a working file; followed like any run. */
export async function startCaseAnalysis(matterId: string): Promise<WorkflowAccepted> {
  const response = await fetch("/api/workflows/case-analysis", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ matter_id: matterId }),
  });
  if (!response.ok) throw await failure(response);
  return response.json();
}

export async function* followAnalysis(
  jobId: string,
  signal: AbortSignal,
): AsyncGenerator<AnalysisEvent> {
  for await (const event of followRun(jobId, signal)) {
    yield event as unknown as AnalysisEvent;
  }
}

export async function* streamQuery(
  request: QueryRequest,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await fetch("/api/query/stream", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream" },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) throw await failure(response);
  yield* readEvents(response, signal);
}
