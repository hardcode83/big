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
}

export function getServerConfig(): ServerConfig {
  return {
    backendInternalUrl: process.env.BACKEND_INTERNAL_URL,
  };
}
