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

export const dynamic = "force-dynamic";

interface BackendVersion {
  version?: unknown;
}

export async function GET(): Promise<Response> {
  const { backendInternalUrl } = getServerConfig();
  // Through the config boundary, not `process.env`: `frontend-foundation` requires
  // application code to read configuration only through `lib/config`.
  const frontend = buildPublicRuntimeConfig().appVersion || null;

  return Response.json({
    frontend,
    backend: await readBackendVersion(backendInternalUrl),
  });
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
