import {
  clearSessionTokens,
  getSessionGeneration,
  setSessionTokens,
  type SessionTokens,
} from "./session-store";
import { clearSessionPresent, markSessionPresent } from "./session-presence-cookie";

export type RefreshTokens = () => Promise<SessionTokens>;

interface InFlightRefresh {
  generation: number;
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
 *
 * The refresh token itself never passes through this module — it travels via
 * the `autohostai.session.refresh` httpOnly cookie, attached by the browser on
 * the credentialed `/auth/refresh` request `refreshTokens` makes. This
 * coordinator only dedupes concurrent within-tab callers on
 * `sessionGeneration`; it does not gate on whether an access token currently
 * sits in memory — a page reload legitimately starts with an empty store and
 * a live cookie, and that path is served by the mount-refresh effect, not
 * here (design D8's "two distinct callers").
 */
export function refreshSession(refreshTokens: RefreshTokens): Promise<SessionTokens> {
  const generation = getSessionGeneration();
  if (inFlight && inFlight.generation === generation) {
    return inFlight.promise;
  }

  const promise = refreshTokens()
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

  inFlight = { generation, promise };
  return promise;
}
