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

const api = {
  ingestFile(file) {
    const body = new FormData();
    body.append("file", file);
    return request("/ingest/file", { method: "POST", body });
  },

  ingestUrl(url) {
    return request("/ingest/url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
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
