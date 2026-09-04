/**
 * Ephemeral browser-runtime storage for the current JWT pair.
 *
 * This module deliberately has no persistence or hydration side effects. A new
 * JavaScript runtime starts with an empty session by construction.
 *
 * Two independent monotonic counters live here, on purpose:
 *
 * - `sessionGeneration` is the **cache-invalidation** counter: it moves in
 *   `setSessionTokens` and in `purgeSessionCache` (every purge of the singleton
 *   `QueryClient` invalidates by construction the optimistic-mutation snapshots
 *   that compare against it — R1/R4.4). It does NOT move in `clearSessionTokens`.
 *   `use-mark-read.ts` / `use-mark-all-read.ts` are the consumers.
 * - `tokenGeneration` is the **token-identity** counter: it moves ONLY when the
 *   in-memory pair actually changes — `setSessionTokens` (new pair installed)
 *   and `clearSessionTokens` (pair removed). `purgeSessionCache` does NOT move
 *   it. `refresh-coordinator.ts` is the consumer: it needs to know whether
 *   *this specific token pair* is still the live one, and `sessionGeneration`
 *   stopped being a reliable proxy for that once it started moving on every
 *   purge regardless of whether any identity actually changed — a purge
 *   triggered by an unrelated concurrent request's session-expiry listener
 *   could otherwise make a legitimate in-flight refresh believe its session
 *   had been superseded when it had not (found by security review, second
 *   `/sdd:review` round of `auth-session-generation-semantics`).
 *
 * Both counters can advance together (e.g. `login()` calls `setSessionTokens`
 * then `purgeSessionCache`, moving both) or independently (a purge with no
 * token write moves only `sessionGeneration`; nothing today moves only
 * `tokenGeneration`, but the split exists so a future caller could).
 */
export interface SessionTokens {
  accessToken: string;
  refreshToken: string;
}

let currentTokens: SessionTokens | null = null;
let sessionGeneration = 0;
let tokenGeneration = 0;

export function getSessionTokens(): SessionTokens | null {
  return currentTokens ? { ...currentTokens } : null;
}

export function getSessionGeneration(): number {
  return sessionGeneration;
}

export function getTokenGeneration(): number {
  return tokenGeneration;
}

export function setSessionTokens(tokens: SessionTokens): void {
  currentTokens = { ...tokens };
  sessionGeneration += 1;
  tokenGeneration += 1;
}

export function advanceSessionGeneration(): void {
  sessionGeneration += 1;
}

export function clearSessionTokens(): void {
  currentTokens = null;
  tokenGeneration += 1;
}
