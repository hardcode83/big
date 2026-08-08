import { isIP } from "node:net";

import type { NextRequest } from "next/server";

import { getServerConfig } from "@/lib/config/server";

/**
 * The same-origin path from the browser to the API (change `api-ingress-routing`,
 * design D1). Everything under `/api/` on the public origin is forwarded to the
 * backend over the compose-internal network; nothing else is.
 *
 * Why a Route Handler and not a `rewrites` entry in `next.config.ts`: rewrite
 * destinations are baked into `.next/routes-manifest.json` at BUILD time —
 * `config.rewrites()` runs once during `next build` and production never calls it
 * again — so `process.env.BACKEND_INTERNAL_URL` would capture whatever the CI build
 * job had, which is nothing. `next dev` does reload it on every start, so that route
 * would have worked locally and failed only once deployed.
 */

// Node, not edge: `BACKEND_INTERNAL_URL` is a runtime value and the backend is reachable
// only by its compose service name, neither of which an edge runtime gets.
export const runtime = "nodejs";
// Explicit, so a future Next default cannot make a proxied response cacheable.
export const dynamic = "force-dynamic";

/** Only this prefix is proxied. Anything else is a 404 from the Next app (R2.1). */
const PROXIED_PREFIX = "/api/";

/**
 * The widest client address worth forwarding. Mirrors `MAX_CLIENT_IP_LENGTH` in
 * `backend/app/auth/api/dependencies.py`, which exists because `audit_logs.actor_ip` is
 * VARCHAR(45) and its factory raises past that.
 */
const MAX_CLIENT_IP_LENGTH = 45;

/**
 * Forwarding headers a caller can set themselves. They are dropped from the outbound
 * copy and the one we care about is then re-written from a value WE derive (R4.2).
 *
 * This is the whole bypass if omitted: the documented proxy pattern
 * (`new Request(proxyURL, request)`) copies incoming headers verbatim, so a client's
 * own `CF-Connecting-IP` would reach a backend that trusts this container's address
 * and be believed.
 */
const CLIENT_CONTROLLED_FORWARDING_HEADERS = [
  "x-forwarded-for",
  "x-forwarded-host",
  "x-forwarded-proto",
  "x-forwarded-port",
  "forwarded",
  "cf-connecting-ip",
  "true-client-ip",
  "x-real-ip",
];

/** Per-connection headers that must never be forwarded across a hop (RFC 9110 §7.6.1). */
const HOP_BY_HOP_HEADERS = [
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "te",
  "trailer",
  // `host` is deliberately dropped rather than rewritten: undici sets it from the
  // target URL, so the backend sees `backend:8000` without us fighting the runtime
  // over a header the fetch spec treats as its own.
  "host",
];

/** Response headers the runtime must recompute rather than inherit from upstream. */
const RESPONSE_HEADERS_TO_DROP = [
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  // undici has already decoded the body, so passing these through would describe a
  // compression and a length the bytes we forward no longer have.
  "content-encoding",
  "content-length",
  // Names the internal server. Harmless on its own, but it is internal detail about a
  // service R1.3 keeps off the internet, and there is no reason for it to travel.
  "server",
];

class ProxyUnavailableError extends Error {}

/**
 * The outbound URL, built so the caller cannot steer it outside `/api/` (R2.1).
 *
 * **The path is rebuilt from the router's decoded segments, never copied from the
 * incoming pathname.** An earlier version did copy the pathname — on the theory that it
 * preserved percent escapes byte for byte — and that was a real, reproduced bypass: the
 * traversal check ran against `params.path` (split on LITERAL `/`, so `..%2f..%2fx` is
 * one segment and never equals `".."`) while the outbound request line came from the
 * still-encoded pathname, which undici decodes when it serialises. So
 * `GET /api/..%2f..%2fopenapi.json` left as `GET /api/../openapi.json` and reached the
 * backend, outside the `/api/` scope R2.1 declares. It only failed to disclose anything
 * because Starlette matches routes literally and never collapses `..` — a property of a
 * service this proxy has no contract with, not a protection this change owns.
 *
 * So: decode, validate, re-encode. A segment that decodes to something containing a path
 * separator is **rejected rather than transported**, because there is no way to carry it
 * faithfully — whatever we emit, undici turns `%2F` back into `/` on the wire.
 */
function buildTargetUrl(request: NextRequest, segments: string[]): URL {
  const { backendInternalUrl } = getServerConfig();
  if (!backendInternalUrl) {
    throw new ProxyUnavailableError("BACKEND_INTERNAL_URL is not configured");
  }

  for (const segment of segments) {
    if (segment === "." || segment === "..") {
      throw new ProxyUnavailableError("path traversal rejected");
    }
    // Catches the decoded form of `%2f` and `%5c`, which is what made the traversal
    // reachable: a separator smuggled INSIDE what the router treated as one segment.
    if (segment.includes("/") || segment.includes("\\")) {
      throw new ProxyUnavailableError("path separator inside a segment rejected");
    }
  }

  const incoming = new URL(request.url);
  if (!incoming.pathname.startsWith(PROXIED_PREFIX)) {
    throw new ProxyUnavailableError(`refusing to proxy ${incoming.pathname}`);
  }

  const base = new URL(backendInternalUrl);
  const target = new URL(base);
  // Preserve any path prefix the base URL carries, so a `BACKEND_INTERNAL_URL` with a
  // sub-path keeps it instead of having it replaced by an absolute pathname.
  const prefix = base.pathname.replace(/\/+$/, "");
  const rebuilt = segments.map(encodeURIComponent).join("/");
  target.pathname = `${prefix}${PROXIED_PREFIX}${rebuilt}`;
  target.search = incoming.search;

  if (!target.pathname.startsWith(`${prefix}${PROXIED_PREFIX}`)) {
    throw new ProxyUnavailableError(`refusing to proxy ${target.pathname}`);
  }
  return target;
}

/**
 * The client address to report downstream, or `undefined` when we cannot vouch for one.
 *
 * `CF-Connecting-IP` is written by the Cloudflare edge, which overwrites whatever the
 * client sent, so through the tunnel it is trustworthy. Validated before use so a junk
 * value can never become a rate-limit key or an `audit_logs.actor_ip` (which is
 * VARCHAR(45) and whose domain guard raises past that length). Omitting the header is
 * the safe failure: the backend then falls back to this container's address, which
 * under-counts rather than letting a caller pick their own bucket.
 *
 * Residual accepted in design D2: a request arriving at the VM's `127.0.0.1:3000`
 * (kept for `ssh -L` debugging) did not come from the edge, so its header is whatever
 * the caller sent. Reaching it requires SSH on the VM — a position from which
 * `127.0.0.1:8000` is directly reachable anyway.
 */
function edgeClientIp(request: NextRequest): string | undefined {
  const candidate = request.headers.get("cf-connecting-ip")?.trim();
  if (!candidate || isIP(candidate) === 0) {
    return undefined;
  }
  // `isIP` is NOT sufficient, measured rather than assumed: Node accepts a zone
  // identifier, so `isIP("fe80::1%" + "z".repeat(100))` returns 6 and a 108-character
  // value would be written into `X-Forwarded-For`. The backend rejects scoped addresses
  // at its own boundary, so this is defence in depth rather than the only guard — but
  // emitting a value we know the far end must throw away is not something to leave in.
  // A zone is link-local scoping for one host and can never describe a remote client.
  if (candidate.includes("%") || candidate.length > MAX_CLIENT_IP_LENGTH) {
    return undefined;
  }
  return candidate;
}

function outboundHeaders(request: NextRequest): Headers {
  const headers = new Headers(request.headers);
  for (const name of [
    ...CLIENT_CONTROLLED_FORWARDING_HEADERS,
    ...HOP_BY_HOP_HEADERS,
  ]) {
    headers.delete(name);
  }
  for (const name of [...headers.keys()]) {
    if (name.startsWith("proxy-")) {
      headers.delete(name);
    }
  }

  const clientIp = edgeClientIp(request);
  if (clientIp) {
    headers.set("x-forwarded-for", clientIp);
  }
  return headers;
}

/**
 * Strip the internal origin out of a redirect the backend issued (R1.5).
 *
 * Starlette's `redirect_slashes` answers `307` with an ABSOLUTE `Location`, built from the
 * authority it was addressed by — which is `backend:8000`, since `host` is left for undici
 * to set. Passing that through told any anonymous caller the internal service name and port
 * of a service R1.3 keeps off the internet, and pointed a real browser at a host it cannot
 * resolve. Measured before this: `GET /api/v1/users/` came back with
 * `location: http://backend:8000/api/v1/users`.
 *
 * A redirect to the internal origin is rewritten to the equivalent same-origin path, which
 * is where the client should go. Anything pointing elsewhere is left alone: the backend does
 * not issue those today, and inventing a rewrite for a case that does not exist would be
 * guessing at its intent.
 */
function rewriteUpstreamLocation(headers: Headers, target: URL): void {
  const location = headers.get("location");
  if (!location) {
    return;
  }

  // DEFAULT-DENY, and it took two review rounds to get the shape right. The first attempt
  // rewrote same-origin values and passed everything else through; the second added a
  // deny-list for the scheme-relative shape. Both were wrong in the same way: a deny-list
  // has to enumerate every spelling a URL parser folds into an authority, and it missed
  // the backslash-leading forms — `\\evil.example/x` does not start with `/`, so the
  // pattern skipped it, and `new URL("\\\\evil.example/x", base).href` is
  // `http://evil.example/x`. A browser on the public origin would have followed it
  // off-site: an open redirect handed over by the code whose job is stripping internal
  // detail out.
  //
  // So the header is now emitted ONLY when the proxy can construct it itself from a value
  // that resolves to the backend origin. Everything else is dropped. The backend issues no
  // cross-origin redirect today (Starlette's `redirect_slashes` is the only emitter), so
  // nothing legitimate is lost — and the day one is added, it fails visibly rather than
  // becoming an open redirect silently.
  headers.delete("location");

  let resolved: URL;
  try {
    resolved = new URL(location, target);
  } catch {
    return;
  }
  if (resolved.origin !== target.origin) {
    return;
  }
  const rewritten = `${resolved.pathname}${resolved.search}${resolved.hash}`;
  // Same origin is necessary and NOT sufficient, and this is the bit that bit me while
  // inverting the check: `http://backend:8000//evil.example/x` has the backend's origin and
  // a pathname of `//evil.example/x`, so origin-matching alone re-emitted a scheme-relative
  // path — the very open redirect being closed, smuggled through the allowed branch. The
  // value must be a single-slash path or nothing.
  if (!rewritten.startsWith("/") || rewritten.startsWith("//")) {
    return;
  }
  headers.set("location", rewritten);
}

/**
 * The PRD §23 envelope for a failure of the hop itself (R1.5, design D6).
 *
 * `INTERNAL_ERROR` rather than a code of the proxy's own: `backend/app/core/
 * error_codes.py` is the single source of these values and `api-contract-export`
 * publishes them as an OpenAPI enum, so a code invented here would make the frontend's
 * exhaustive switch exhaustive over the wrong set. The distinction between "backend
 * bug" and "proxy could not reach the backend" is for the operator, and goes to the
 * server log below — not to a client for whom both mean "5xx, retry".
 */
function upstreamFailure(): Response {
  return Response.json(
    {
      error: {
        code: "INTERNAL_ERROR",
        message: "The API is temporarily unavailable.",
        details: {},
      },
    },
    { status: 502 },
  );
}

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await context.params;

  let target: URL;
  try {
    target = buildTargetUrl(request, path ?? []);
  } catch (reason) {
    // Server-side only: the internal service name, the internal URL and the reason
    // never reach the client (R1.5).
    console.error("[api-proxy] refusing request:", reason);
    return upstreamFailure();
  }

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers: outboundHeaders(request),
      body: hasBody ? request.body : null,
      // Required by undici to stream a body instead of buffering it first.
      ...(hasBody ? { duplex: "half" } : {}),
      // A redirect from the backend is the browser's to follow, on the public origin.
      // Chasing it here would resolve it against the internal URL.
      redirect: "manual",
    } as RequestInit);

    const headers = new Headers(upstream.headers);
    for (const name of RESPONSE_HEADERS_TO_DROP) {
      headers.delete(name);
    }
    rewriteUpstreamLocation(headers, target);
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers,
    });
  } catch (reason) {
    console.error("[api-proxy] upstream request failed:", reason);
    return upstreamFailure();
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
export const OPTIONS = proxy;
