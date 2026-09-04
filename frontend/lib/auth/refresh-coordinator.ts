import {
  clearSessionTokens,
  getSessionTokens,
  getTokenGeneration,
  setSessionTokens,
  type SessionTokens,
} from "./session-store";
import { clearSessionPresent, markSessionPresent } from "./session-presence-cookie";
import { purgeSessionCache } from "./session-cache-purge";

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

  // Identity, not cache: `getTokenGeneration()` moves only when the in-memory
  // pair actually changes (a write or a clear), never on a bare cache purge.
  // A purge triggered by an unrelated concurrent request's session-expiry
  // listener must not make this guard believe this pair was superseded.
  const generation = getTokenGeneration();
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
      if (getTokenGeneration() !== generation) {
        throw new SessionInvalidatedError();
      }
      setSessionTokens(next);
      markSessionPresent();
      return next;
    })
    /**
     * On failure, the guard fires only when the token generation captured
     * before the refresh still matches: if it did not move under this
     * promise, the tokens still belong to the session that initiated the
     * refresh and clearing them is safe; otherwise the current tokens
     * belong to another session (a `login()` that won the race) and are
     * left untouched. The clear goes through `purgeSessionCache()` so the
     * cache invalidation and the token clear stay coupled here too, instead
     * of depending on every future caller of `refreshSession()` to purge
     * afterward on its own.
     */
    .catch((error: unknown) => {
      if (getTokenGeneration() === generation) {
        purgeSessionCache();
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
