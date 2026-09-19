import { readEvents } from "./stream";
import type { Catalog, GraphNeighbourhood, QueryRequest, StreamEvent } from "./types";

async function failure(response: Response): Promise<Error> {
  try {
    const body = await response.json();
    return new Error(body.detail ?? `Request failed (${response.status})`);
  } catch {
    return new Error(`Request failed (${response.status})`);
  }
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
