import "server-only";

/**
 * Server-only configuration boundary (design D15). Private and runtime values
 * live here and MUST NOT be imported from a Client Component — the `server-only`
 * import turns any such import into a build error.
 *
 * The Application Shell does not read the backend URL: it is exposed here so a
 * future backend-integration change can consume it, but it is neither required
 * nor validated at boot, preserving R8.1 (the shell renders without a backend).
 */
export interface ServerConfig {
  /** Internal backend base URL, injected by Compose. Optional for the shell. */
  backendInternalUrl: string | undefined;
  /**
   * Build provenance baked into the image as plain ENV — deliberately WITHOUT the
   * `NEXT_PUBLIC_` prefix, so it stays here and never enters the public snapshot that
   * every surface ships to the browser (change `app-version-visibility`, design D6).
   *
   * These feed the provenance panel on the operator surface. Moving any of them to
   * `public.ts` would publish the private repository name and the Pull Request number
   * to anyone loading `/login` or a guest portal link.
   */
  buildProvenance: BuildProvenance;
}

export interface BuildProvenance {
  /** Full 40-char commit SHA, or undefined when nothing was baked. */
  commit: string | undefined;
  /** Pull Request number as baked; empty when the commit reached main directly. */
  pr: string | undefined;
  /** ISO 8601 UTC build timestamp. */
  builtAt: string | undefined;
  /** GitHub Actions run id of the build. */
  runId: string | undefined;
  /** Git ref the build came from. */
  ref: string | undefined;
  /** Repository URL, used to compose the links. */
  repoUrl: string | undefined;
}

/** Normalizes "" to undefined: an unset build-arg still defines the ENV as empty. */
function orUndefined(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

export function getServerConfig(): ServerConfig {
  return {
    backendInternalUrl: process.env.BACKEND_INTERNAL_URL,
    buildProvenance: {
      commit: orUndefined(process.env.BUILD_COMMIT),
      pr: orUndefined(process.env.BUILD_PR),
      builtAt: orUndefined(process.env.BUILT_AT),
      runId: orUndefined(process.env.BUILD_RUN_ID),
      ref: orUndefined(process.env.BUILD_REF),
      repoUrl: orUndefined(process.env.REPO_URL),
    },
  };
}
