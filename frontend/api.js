// crypto.randomUUID() only exists in secure contexts (HTTPS or localhost) - a
// phone hitting this app over plain http://<lan-ip> doesn't get it, so this
// falls back to crypto.getRandomValues() (not secure-context-restricted), and
// as a last resort Math.random(). Session ids don't need to be
// cryptographically unguessable, only unique per browser.
function generateId() {
  if (typeof crypto?.randomUUID === "function") {
    return crypto.randomUUID();
  }
  if (typeof crypto?.getRandomValues === "function") {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

// Isolates this browser's documents from everyone else's: the backend partitions
// storage by this id. Persisted in localStorage so it survives a reload; falls
// back to an in-memory id for the page's lifetime if storage is unavailable
// (private browsing, blocked site data).
let sessionIdFallback = null;

function getSessionId() {
  try {
    let id = localStorage.getItem("rag-session-id");
    if (!id) {
      id = generateId();
      localStorage.setItem("rag-session-id", id);
    }
    return id;
  } catch {
    sessionIdFallback ??= generateId();
    return sessionIdFallback;
  }
}

async function extractError(response) {
  try {
    const body = await response.json();
    return body.detail ?? `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

async function request(path, options = {}) {
  const headers = { ...options.headers, "X-Session-Id": getSessionId() };
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    throw new Error(await extractError(response));
  }
  return response.json();
}

// Ingestion returns a job immediately and indexes in the background, so the
// client polls until the job settles. Backs off from a snappy first check to a
// slower cadence, since a large document can take minutes and there's no point
// asking twice a second for all of it.
const POLL_INTERVAL_MS = 700;
const POLL_MAX_INTERVAL_MS = 4000;

async function awaitJob(job) {
  let job_state = job;
  let interval = POLL_INTERVAL_MS;

  while (job_state.status === "queued" || job_state.status === "running") {
    await new Promise((resolve) => setTimeout(resolve, interval));
    interval = Math.min(interval * 1.5, POLL_MAX_INTERVAL_MS);
    job_state = await request(`/ingest/jobs/${job_state.job_id}`);
  }

  if (job_state.status === "failed") {
    throw new Error(job_state.error || "Indexing failed.");
  }
  return job_state;
}

const api = {
  async ingestFile(file) {
    const body = new FormData();
    body.append("file", file);
    return awaitJob(await request("/ingest/file", { method: "POST", body }));
  },

  async ingestUrl(url) {
    return awaitJob(
      await request("/ingest/url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      }),
    );
  },

  query(question) {
    return request("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
  },

  pdfUrl(docId) {
    return `/files/${docId}`;
  },

  // Session-scoped images can't be loaded by pointing <img src> at them: the
  // browser won't attach X-Session-Id to an image request, so the server sees an
  // unscoped caller and 404s. Fetch the bytes with the header, hand back a blob
  // URL instead.
  async imageObjectUrl(path) {
    const response = await fetch(path, { headers: { "X-Session-Id": getSessionId() } });
    if (!response.ok) {
      throw new Error(await extractError(response));
    }
    return URL.createObjectURL(await response.blob());
  },
};
