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
 * Builds the display model. Every link is null unless BOTH the repository URL and the
 * value it points at were baked — a half-formed href is worse than no link, because it
 * looks clickable and goes nowhere.
 */
export function resolveProvenance(
  provenance: BuildProvenance,
): ResolvedProvenance {
  const { commit, pr, builtAt, runId, ref, repoUrl } = provenance;
  const base = repoUrl?.replace(/\/+$/, "");

  return {
    commitShort: commit ? commit.slice(0, 7) : null,
    commitHref: base && commit ? `${base}/commit/${commit}` : null,
    pr: pr ?? null,
    prHref: base && pr ? `${base}/pull/${pr}` : null,
    builtAt: builtAt ?? null,
    runId: runId ?? null,
    runHref: base && runId ? `${base}/actions/runs/${runId}` : null,
    ref: ref ?? null,
  };
}
