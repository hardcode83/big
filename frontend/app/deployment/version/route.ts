import { buildPublicRuntimeConfig } from "@/lib/config/public";
import { getServerConfig } from "@/lib/config/server";

/**
 * Version comparison for the provenance panel (change app-version-visibility, R5.1-R5.6).
 *
 * WHY A ROUTE HANDLER AND NOT A READ DURING RENDER (design D9):
 * `sdd/specs/frontend-foundation.md` requires `BACKEND_INTERNAL_URL` to stay "server-only
 * and unread at shell render", and the shell to render completely without a backend. This
 * handler keeps that literally true — the shell never touches the backend, the badge makes
 * no request at all, and this only runs when an operator opens the panel.
 *
 * WHY NOT UNDER `/api/` (R5.6): the roadmap entry `api-ingress-routing` leans towards a
 * Next `rewrite` of `/api/*` to the backend. A handler under that prefix would collide
 * with it.
 *
 * WHAT IT DELIBERATELY DOES NOT RETURN: the Pull Request number, the repository URL, the
 * Actions run id or the git ref. The Cloudflare Tunnel routes to `frontend:3000`, so this
 * path is publicly reachable; only version strings may cross it (R3.6/R4.3).
 */

/** Bounded on purpose: a hung backend must not make the panel hang with it (R5.5). */
const BACKEND_TIMEOUT_MS = 2000;

/**
 * The answer is memoized for this long, and the same value is offered to the edge.
 *
 * This path is anonymous and publicly routed, so without a cache every internet request
 * would force one internal request to the backend on a single dev VM — the first public
 * path in the product that costs internal work per call (found by the security panel).
 * A version can only change on deploy, and a deploy restarts this process, so caching
 * costs nothing in freshness. It also blunts the liveness oracle: probing in a loop no
 * longer tracks the backend's state in real time.
 */
const CACHE_TTL_MS = 30_000;

export const dynamic = "force-dynamic";

interface BackendVersion {
  version?: unknown;
}

let cached: { backend: string | null; expiresAt: number } | null = null;

export async function GET(): Promise<Response> {
  const { backendInternalUrl } = getServerConfig();
  // Through the config boundary, not `process.env`: `frontend-foundation` requires
  // application code to read configuration only through `lib/config`.
  const frontend = buildPublicRuntimeConfig().appVersion || null;

  const now = Date.now();
  if (!cached || cached.expiresAt <= now) {
    cached = {
      backend: await readBackendVersion(backendInternalUrl),
      expiresAt: now + CACHE_TTL_MS,
    };
  }

  return Response.json(
    { frontend, backend: cached.backend },
    {
      headers: {
        "Cache-Control": `public, max-age=${Math.floor(CACHE_TTL_MS / 1000)}`,
      },
    },
  );
}

/** Test seam: the module-level cache would otherwise leak between test cases. */
export function __resetVersionCache(): void {
  cached = null;
}

async function readBackendVersion(
  baseUrl: string | undefined,
): Promise<string | null> {
  if (!baseUrl) return null;

  // AbortSignal.timeout rather than a manual race: it aborts the socket too, so a hung
  // backend does not leave the request dangling for the life of the process.
  try {
    const response = await fetch(`${baseUrl.replace(/\/+$/, "")}/version`, {
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
      cache: "no-store",
    });
    if (!response.ok) return null;
    const body = (await response.json()) as BackendVersion;
    return typeof body.version === "string" && body.version.trim()
      ? body.version.trim()
      : null;
  } catch {
    // Every failure mode collapses to "unknown", never to an error response: the panel
    // has to keep working with the backend down, and this endpoint is diagnostics — it
    // must not become one more thing that can break (R5.4).
    return null;
  }
}
