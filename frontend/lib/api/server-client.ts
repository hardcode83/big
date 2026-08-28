import "server-only";

import { cookies } from "next/headers";

import { getServerConfig } from "@/lib/config/server";
import { parseApiError } from "@/lib/api/errors";
import type { paths } from "@/lib/api/generated/openapi";

/**
 * Server-side HTTP client for Server Components (design D4, R4). The browser
 * runs all its API traffic through `lib/api/client.ts` (relative URLs that the
 * `/api/[...path]` proxy route forwards to the backend over the compose-internal
 * network). Server Components cannot reach the same-origin `/api/...` URLs the
 * way the browser does — they would re-enter the same Next.js server instead
 * of talking to the backend — so this module calls the backend directly via
 * `BACKEND_INTERNAL_URL`.
 *
 * **Cookie forwarding** (`forwardCookies: true` by default): the inbound
 * request's cookies are re-sent as a `Cookie` header on the outbound fetch.
 * `RootPage` uses this to validate the session-presence cookie against
 * `/auth/me`, but the JWT lives in browser memory and is never visible to the
 * Server Component — so this forward is best-effort: it sends what the
 * browser sent (the non-sensitive presence cookie), not what the browser held
 * (the JWT). The behavioural consequence of that gap is recorded as OQ1 in
 * the change's `design.md` "Decisiones del gate".
 *
 * **Why `import "server-only"`**: this module reads `BACKEND_INTERNAL_URL`,
 * which the steering reserves for `app/api/[...path]/route.ts` under `app/`.
 * `lib/` is allowed to read it, but a Client Component that accidentally
 * imported this module would leak the internal URL into the browser bundle.
 * `server-only` turns that import into a build error.
 */
export interface ServerFetchOptions<Body> {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: Body;
  query?: Record<string, string | number | boolean | null | undefined>;
  headers?: HeadersInit;
  /**
   * Forward the inbound request's cookies to the backend as a `Cookie` header.
   * Default `true` — `RootPage` relies on it to read the session-presence
   * cookie. Pass `false` for endpoints that should be unauthenticated.
   */
  forwardCookies?: boolean;
  /**
   * Per-request timeout in milliseconds. Default `2000` (R4 #6).
   */
  timeoutMs?: number;
  signal?: AbortSignal;
}

function joinUrl(baseUrl: string, path: string): string {
  const trimmedBase = baseUrl.replace(/\/+$/, "");
  const trimmedPath = path.replace(/^\/+/, "");
  return `${trimmedBase}/${trimmedPath}`;
}

function appendQuery(
  path: string,
  query: Record<string, string | number | boolean | null | undefined> = {},
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) {
      params.set(key, String(value));
    }
  }
  const encoded = params.toString();
  return encoded ? `${path}?${encoded}` : path;
}

type SuccessfulStatus = 200 | 201 | 202 | 203 | 204 | 205 | 206 | 207 | 208 | 226;

type MethodForPath<Path extends keyof paths> = Extract<
  keyof paths[Path],
  "get" | "post" | "put" | "patch" | "delete"
>;

type ResponseFor<Path extends keyof paths, Method extends MethodForPath<Path>> =
  paths[Path][Method] extends { responses: infer Responses }
    ? Responses extends Record<infer Status, { content?: { "application/json"?: infer Body } }>
      ? Status extends SuccessfulStatus
        ? Body
        : never
      : never
    : never;

/**
 * Server-only fetch with the same envelope shape as `lib/api/client.ts`.
 *
 * Returns the parsed JSON body on 2xx, throws `ApiError` on non-2xx, and
 * applies a default `AbortSignal.timeout(2000)` so a hanging backend never
 * strands a Server Component render.
 */
export async function serverFetch<
  Path extends keyof paths,
  Method extends MethodForPath<Path> = MethodForPath<Path>,
>(
  path: Path,
  options: ServerFetchOptions<unknown> = {},
): Promise<ResponseFor<Path, Method>> {
  const { backendInternalUrl } = getServerConfig();
  if (!backendInternalUrl) {
    throw new Error("serverFetch: BACKEND_INTERNAL_URL is not configured");
  }

  const headers = new Headers(options.headers ?? {});
  if (options.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (options.forwardCookies !== false) {
    const store = await cookies();
    const cookieValue = store.toString();
    if (cookieValue) {
      headers.set("Cookie", cookieValue);
    }
  }

  const url = appendQuery(
    joinUrl(backendInternalUrl, String(path)),
    options.query,
  );

  const timeoutSignal = AbortSignal.timeout(options.timeoutMs ?? 2000);
  const signal =
    options.signal !== undefined
      ? AbortSignal.any([timeoutSignal, options.signal])
      : timeoutSignal;

  const response = await fetch(url, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal,
  });

  if (!response.ok) {
    throw await parseApiError(response);
  }

  if (response.status === 204) {
    return undefined as ResponseFor<Path, Method>;
  }

  return (await response.json()) as ResponseFor<Path, Method>;
}