// Proxies API requests to the backend so the frontend stays same-origin.
//
// Same-origin is the point: the browser keeps sending relative paths and its
// X-Session-Id header exactly as it does locally, with no CORS and no API URL
// baked into app code. The only thing this adds is the shared secret the
// backend requires (app/proxy_auth.py), which therefore never leaves Cloudflare.
//
// Which paths reach this function is decided by frontend/_routes.json; every
// other path is served as a static asset without running it.

export async function onRequest({ request, env }) {
  if (!env.BACKEND_URL || !env.PROXY_SECRET) {
    return new Response("Backend is not configured for this deployment.", { status: 503 });
  }

  const incoming = new URL(request.url);
  const target = new URL(incoming.pathname + incoming.search, env.BACKEND_URL);

  const headers = new Headers(request.headers);
  headers.set("X-Proxy-Secret", env.PROXY_SECRET);
  // Belongs to the target, not the caller; fetch derives it from the URL.
  headers.delete("Host");

  const hasBody = !["GET", "HEAD"].includes(request.method);
  return fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? request.body : undefined,
    // Pass redirects through untouched rather than following them here.
    redirect: "manual",
  });
}
