/**
 * Ephemeral browser-runtime storage for the current JWT pair.
 *
 * This module deliberately has no persistence or hydration side effects. A new
 * JavaScript runtime starts with an empty session by construction.
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
}

export function clearSessionTokens(): void {
  currentTokens = null;
  sessionGeneration += 1;
}
