/**
 * Ephemeral browser-runtime storage for the current JWT pair.
 *
 * This module deliberately has no persistence or hydration side effects. A new
 * JavaScript runtime starts with an empty session by construction.
 *
 * `sessionGeneration` is a monotonic counter that advances when the session
 * identity changes. It moves in `setSessionTokens` (a new pair is installed)
 * and in `purgeSessionCache` (every purge of the singleton `QueryClient`
 * invalidates by construction the snapshots that compare against it). It
 * does not move in `clearSessionTokens` — that function only nullifies the
 * in-memory pair and is safe to call alongside a purge without double-bumping.
 */
export interface SessionTokens {
  accessToken: string;
  refreshToken: string;
}

let currentTokens: SessionTokens | null = null;
let sessionGeneration = 0;

export function getSessionTokens(): SessionTokens | null {
  return currentTokens ? { ...currentTokens } : null;
}

export function getSessionGeneration(): number {
  return sessionGeneration;
}

export function setSessionTokens(tokens: SessionTokens): void {
  currentTokens = { ...tokens };
  sessionGeneration += 1;
}

export function advanceSessionGeneration(): void {
  sessionGeneration += 1;
}

export function clearSessionTokens(): void {
  currentTokens = null;
}
