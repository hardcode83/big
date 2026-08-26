import {
  clearSessionTokens,
  getSessionGeneration,
  getSessionTokens,
  setSessionTokens,
  type SessionTokens,
} from "./session-store";
import { clearSessionPresent, markSessionPresent } from "./session-presence-cookie";

export type RefreshTokens = (refreshToken: string) => Promise<SessionTokens>;

interface InFlightRefresh {
  generation: number;
  refreshToken: string;
  promise: Promise<SessionTokens>;
}

let inFlight: InFlightRefresh | null = null;

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
  const current = getSessionTokens();
  if (!current) {
    return Promise.reject(new Error("No refresh token available"));
  }

  const generation = getSessionGeneration();
  if (
    inFlight &&
    inFlight.generation === generation &&
    inFlight.refreshToken === current.refreshToken
  ) {
    return inFlight.promise;
  }

  const refreshToken = current.refreshToken;
  const promise = refreshTokens(refreshToken)
    .then((next) => {
      if (getSessionGeneration() !== generation) {
        throw new SessionInvalidatedError();
      }
      setSessionTokens(next);
      markSessionPresent();
      return next;
    })
    .catch((error: unknown) => {
      if (getSessionGeneration() === generation) {
        clearSessionTokens();
        clearSessionPresent();
      }
      throw error;
    })
    .finally(() => {
      if (inFlight?.promise === promise) {
        inFlight = null;
      }
    });

  inFlight = { generation, refreshToken, promise };
  return promise;
}
