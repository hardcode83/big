import {
  clearSessionTokens,
  getSessionGeneration,
  getSessionTokens,
  setSessionTokens,
  type SessionTokens,
} from "./session-store";

export type RefreshTokens = (refreshToken: string) => Promise<SessionTokens>;

let inFlight: Promise<SessionTokens> | null = null;

export class SessionInvalidatedError extends Error {
  constructor() {
    super("Session was invalidated while refresh was in flight");
    this.name = "SessionInvalidatedError";
  }
}

/**
 * Coordinates one refresh operation for the browser runtime. React consumers
 * share this promise but do not own its lifecycle or its cleanup semantics.
 */
export function refreshSession(refreshTokens: RefreshTokens): Promise<SessionTokens> {
  if (inFlight) return inFlight;

  const current = getSessionTokens();
  if (!current) {
    return Promise.reject(new Error("No refresh token available"));
  }

  const generation = getSessionGeneration();
  inFlight = refreshTokens(current.refreshToken)
    .then((next) => {
      if (getSessionGeneration() !== generation) {
        throw new SessionInvalidatedError();
      }
      setSessionTokens(next);
      return next;
    })
    .catch((error: unknown) => {
      if (getSessionGeneration() === generation) {
        clearSessionTokens();
      }
      throw error;
    })
    .finally(() => {
      inFlight = null;
    });

  return inFlight;
}
