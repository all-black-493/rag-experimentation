import type { StreamEvent } from "./types";

/**
 * Consume a POST server-sent-event stream.
 *
 * `EventSource` can't POST, so this reads the response body directly and
 * parses the SSE wire format: events separated by a blank line, each with
 * `event:` and one or more `data:` lines. Yields typed events; stops when the
 * body ends or the signal aborts.
 */
export async function* readEvents(
  response: Response,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (signal?.aborted) return;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseEvent(raw);
        if (parsed) yield parsed;
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function parseEvent(raw: string): StreamEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) } as StreamEvent;
  } catch {
    return null;
  }
}
