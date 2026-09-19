/**
 * Same-origin proxy to the backend.
 *
 * The browser only ever talks to this app, so there is no CORS, no API URL in
 * client code, and the shared secret the backend requires (its proxy gate)
 * never leaves the server. The real client address is forwarded so the
 * backend's rate limiter can tell users apart. Streaming responses are passed
 * through as-is, body untouched, so SSE reaches the browser event by event.
 */

import type { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL;
const PROXY_SECRET = process.env.PROXY_SECRET;

// Everything else is served by this app itself.
const ALLOWED = ["query", "query/stream", "catalog", "health"];
// Routes with an id after the prefix.
const ALLOWED_PREFIXES = ["graph/", "matters", "workflows"];

function allowed(target: string): boolean {
  return ALLOWED.includes(target) || ALLOWED_PREFIXES.some((prefix) => target.startsWith(prefix));
}

async function proxy(request: NextRequest, ctx: RouteContext<"/api/[...path]">) {
  const { path } = await ctx.params;
  const target = path.join("/");
  if (!allowed(target)) {
    return Response.json({ detail: "Not found" }, { status: 404 });
  }
  if (!BACKEND_URL) {
    return Response.json({ detail: "Backend is not configured." }, { status: 503 });
  }

  const headers = new Headers();
  for (const name of ["content-type", "content-length", "range", "if-range"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("accept", request.headers.get("accept") ?? "application/json");
  if (PROXY_SECRET) headers.set("x-proxy-secret", PROXY_SECRET);
  const client =
    request.headers.get("x-forwarded-for") ?? request.headers.get("x-real-ip") ?? "";
  if (client) headers.set("x-forwarded-for", client);

  const upstream = await fetch(`${BACKEND_URL}/${target}${request.nextUrl.search}`, {
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
    // Required by the fetch spec to stream a request body.
    // @ts-expect-error - duplex is not in the lib types yet
    duplex: "half",
    cache: "no-store",
  });

  const passthrough = new Headers();
  // The range headers let a PDF viewer fetch one page of a long document.
  for (const name of [
    "content-type",
    "cache-control",
    "content-length",
    "content-range",
    "accept-ranges",
    "content-disposition",
  ]) {
    const value = upstream.headers.get(name);
    if (value) passthrough.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers: passthrough });
}

export const GET = proxy;
export const POST = proxy;
export const DELETE = proxy;
