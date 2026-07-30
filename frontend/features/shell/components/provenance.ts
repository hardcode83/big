import type { BuildProvenance } from "@/lib/config/server";

/**
 * The provenance already resolved into what the panel displays — links included.
 *
 * Composed on the server so the repository URL never has to reach the browser as
 * configuration (design D6). What crosses to the client island is a handful of ready-made
 * `href` strings on the operator surface, not the identity of the private repository in
 * the public snapshot.
 *
 * `commitFull` was removed after the security panel pointed out it crossed to the client
 * without ever being rendered: serializing a value nobody displays is pure exposure. The
 * full SHA still reaches the browser inside `commitHref`, where it has a purpose.
 */
export interface ResolvedProvenance {
  commitShort: string | null;
  commitHref: string | null;
  pr: string | null;
  prHref: string | null;
  builtAt: string | null;
  runId: string | null;
  runHref: string | null;
  ref: string | null;
}

/**
 * Whether the operator surface sits behind real authentication.
 *
 * **FALSE on purpose today.** `auth-tenancy` did not touch the frontend, so `/dashboard` is
 * exactly as anonymous as `/login`: anything handed to the panel is serialized into the RSC
 * payload of the page and readable with a plain `curl` by anyone on the internet. The
 * security panel demonstrated it — the repository URL, the Pull Request number and the full
 * commit were going out that way, which is precisely the disclosure design D6 exists to
 * prevent. Closing the public snapshot was not enough; the same data left one path over.
 *
 * While this is false, those details are **not resolved at all**, so they never reach the
 * browser. What stays visible is what was already public by decision: the version strings,
 * the short commit and the build date.
 *
 * Flip it to `true` in the change that gives the frontend authentication (roadmap entry
 * `dashboard-web`). Nothing else needs touching — the panel already renders the links when
 * it receives them, and the tests cover both modes.
 */
export const OPERATOR_SURFACE_IS_AUTHENTICATED = false;

/** Only http(s) can produce a usable link; anything else is dropped rather than rendered. */
function safeBase(repoUrl: string | undefined): string | null {
  if (!repoUrl) return null;
  try {
    const parsed = new URL(repoUrl);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return null;
  } catch {
    return null;
  }
  return repoUrl.replace(/\/+$/, "");
}

/**
 * Builds the display model. Every link is null unless BOTH the repository URL and the
 * value it points at were baked — a half-formed href is worse than no link, because it
 * looks clickable and goes nowhere.
 */
export function resolveProvenance(
  provenance: BuildProvenance,
  includeRepositoryDetails: boolean = OPERATOR_SURFACE_IS_AUTHENTICATED,
): ResolvedProvenance {
  const { commit, pr, builtAt, runId, ref, repoUrl } = provenance;

  // Non-sensitive either way: the short commit and the build date are already public in
  // the badge, by an explicit decision.
  const always = {
    commitShort: commit ? commit.slice(0, 7) : null,
    builtAt: builtAt ?? null,
  };

  if (!includeRepositoryDetails) {
    return {
      ...always,
      commitHref: null,
      pr: null,
      prHref: null,
      runId: null,
      runHref: null,
      ref: null,
    };
  }

  const base = safeBase(repoUrl);
  return {
    ...always,
    commitHref: base && commit ? `${base}/commit/${commit}` : null,
    pr: pr ?? null,
    prHref: base && pr ? `${base}/pull/${pr}` : null,
    runId: runId ?? null,
    runHref: base && runId ? `${base}/actions/runs/${runId}` : null,
    ref: ref ?? null,
  };
}
