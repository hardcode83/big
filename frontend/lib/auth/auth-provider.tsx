"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  createAuthenticatedClients,
  notifySessionExpired,
  subscribeToSessionExpired,
} from "@/lib/api/authenticated-client";
import type { components } from "@/lib/api/generated/openapi";
import { useRuntimeConfig } from "@/lib/config/runtime-config-provider";
import { refreshSession } from "./refresh-coordinator";
import {
  clearSessionTokens,
  getSessionGeneration,
  getSessionTokens,
  getTokenGeneration,
  setSessionTokens,
  type SessionTokens,
} from "./session-store";
import { clearSessionPresent, markSessionPresent } from "./session-presence-cookie";
import { purgeSessionCache } from "./session-cache-purge";
import { subscribeToLogout } from "./logout-event";

type CurrentUser = components["schemas"]["CurrentUserResponse"];
export type AuthStatus =
  | "loading"
  | "refreshing"
  | "authenticated"
  | "anonymous"
  | "expired"
  | "error";

export interface AuthContextValue {
  user: CurrentUser | null;
  status: AuthStatus;
  /**
   * Authenticate against `/auth/login` + `/auth/me` and resolve with the
   * fetched `CurrentUser`. The promise REJECTS on any 4xx/5xx/network error
   * after the local state has been reset to `error` (no tokens retained,
   * presence cookie cleared).
   *
   * The return value is what `LoginForm` uses to route on first paint — the
   * render-closure `user` is still `null` at the moment `handleSubmit` resumes
   * after `await login(...)`, because React state updates happen on the next
   * render, not within the in-flight handler. Reading from this resolved value
   * is the only path that avoids the closure-staleness bug that R2 #1
   * describes (`/welcome` was being bypassed for fresh CLEANER/TECHNICIAN
   * logins because the closure held `user=null`). See the integration test
   * `login-form.test.tsx` — the CLEANER/TECHNICIAN cases set `mocks.user=null`
   * before render and resolve `mocks.login` with the role, exercising the
   * production path.
   */
  login: (email: string, password: string) => Promise<CurrentUser | null>;
  refresh: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

interface MountRefreshDeps {
  refreshTokens: () => Promise<SessionTokens>;
  fetchCurrentUser: () => Promise<CurrentUser>;
}

/**
 * The single in-flight silent mount-refresh (design D11), module-level so that
 * every `AuthProvider` mounted in this runtime shares ONE network round-trip:
 * React StrictMode's double-invoke in dev, and two routes each mounting their
 * own guarded subtree, both join the promise already running instead of firing
 * a second `POST /auth/refresh` (which would rotate the cookie twice and race
 * itself). A per-component `useRef` cannot do this — it does not survive the
 * remount, which is exactly the case D11 rejected it for.
 *
 * The entry is keyed on `getTokenGeneration()` (identity, not cache — see
 * `session-store.ts`) and cleared the moment the promise settles, so the guard
 * means "already in flight AND the identity has not resolved yet". A later,
 * genuine remount (after a logout, say) sees an empty slot — or a stale
 * generation — and refreshes again.
 */
let inFlightMountRefresh: {
  generation: number;
  promise: Promise<CurrentUser | null>;
} | null = null;

/**
 * Resolves with the restored `CurrentUser`, or `null` when the session could
 * not be restored. It NEVER rejects: R5.3 wants a failed restore to be
 * indistinguishable from "never had a session" for the user, so there is no
 * error to surface and nothing to catch at the call site.
 *
 * The shared value carries the resolved identity (design D11) so that a
 * provider joining an in-flight refresh gets the user without issuing a second
 * `GET /auth/me` of its own.
 */
function runMountRefresh(deps: MountRefreshDeps): Promise<CurrentUser | null> {
  const generation = getTokenGeneration();
  if (inFlightMountRefresh?.generation === generation) {
    return inFlightMountRefresh.promise;
  }

  const promise = (async () => {
    // `null` until this mount-refresh installs its own access token; then the
    // generation the store reported immediately after that write, so the
    // failure path below can tell "the token I just installed" from "a newer
    // session someone else installed while my `/auth/me` was in flight".
    let postInstallGeneration: number | null = null;
    try {
      const { accessToken } = await deps.refreshTokens();
      // The same guard `refresh-coordinator.ts` applies before its own
      // `setSessionTokens`, for the same reason: `tokenGeneration` (identity,
      // not cache — see `session-store.ts`) moves on every write to the
      // shared, module-level store, so a value different from the one
      // captured above means the session this refresh belongs to was torn
      // down or superseded while the network call was in flight — a logout, a
      // 401 that declared the session expired, or a login as a different
      // identity. Installing the resolved token now would silently reinstate
      // credentials for a dead session, or clobber the freshly installed
      // correct token with this stale one. Drop it instead and resolve as a
      // failed restore.
      //
      // No `clearSessionTokens()` here, deliberately: whatever the store holds
      // now belongs to the newer session, not to this refresh. That is the
      // mirror image of the coordinator's `catch` guard, which only clears
      // while the generation still matches.
      if (getTokenGeneration() !== generation) {
        return null;
      }
      setSessionTokens({ accessToken });
      postInstallGeneration = getTokenGeneration();
      return await deps.fetchCurrentUser();
    } catch {
      // A refresh that worked but an `/auth/me` that did not leaves an access
      // token backing an identity we never read — drop it rather than resolve
      // `anonymous` while the store still holds credentials.
      //
      // Only while that token is still the one in the store, though: the same
      // generation check the success path applies above, mirrored here exactly
      // as `refresh-coordinator.ts` mirrors its own. A concurrent `login()`
      // completing while this `/auth/me` was in flight installs a newer
      // session's tokens and bumps the generation again; clearing then would
      // wipe live credentials that have nothing to do with this refresh. The
      // stale token this branch wanted to drop is already gone — overwritten
      // by that newer write.
      if (
        postInstallGeneration !== null &&
        getTokenGeneration() === postInstallGeneration
      ) {
        clearSessionTokens();
      }
      return null;
    }
  })();

  inFlightMountRefresh = { generation, promise };
  void promise.then(() => {
    if (inFlightMountRefresh?.promise === promise) {
      inFlightMountRefresh = null;
    }
  });
  return promise;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const { apiBaseUrl } = useRuntimeConfig();
  const [user, setUser] = useState<CurrentUser | null>(null);
  // A runtime that starts without tokens is about to attempt the silent
  // mount-refresh below, so it starts `loading`, not `anonymous` (R5.1). This
  // has to be the INITIAL state and not a `setStatus` inside the effect:
  // child effects run before parent effects, so an `AuthGuard` underneath
  // would read `anonymous` on the very first commit and fire a redirect to
  // `/login` before the provider ever got the chance to restore the session.
  const [status, setStatus] = useState<AuthStatus>(() =>
    getSessionTokens() ? "anonymous" : "loading",
  );
  /**
   * Set by every other identity transition (login, logout, refresh, the two
   * subscriptions below). A mount-refresh that settles afterwards must not
   * overwrite the newer, deliberate state — the user who typed credentials
   * while the silent restore was still in flight owns the outcome.
   */
  const mountRefreshSuperseded = useRef(false);

  const clients = useMemo(() => {
    return createAuthenticatedClients({
      apiBaseUrl,
      onStatusChange: (nextStatus) => {
        setStatus(nextStatus);
      },
      // Funnel the 401 → refresh-failure path through the same listener the
      // feature clients use (D3 row 4). The listener at the useEffect below
      // purges the cache before resetting user/status, so a session that the
      // AuthProvider's own apiClient loses through refresh failure ends up in
      // the same state as any other 401.
      onSessionExpired: notifySessionExpired,
    });
  }, [apiBaseUrl]);

  useEffect(() => {
    // Silent mount-refresh (R5, design D8): a fresh JavaScript runtime holds no
    // access token by construction (`session-store.ts` never persists), but the
    // browser may still hold the `httpOnly` refresh cookie from a previous page
    // view. Ask for a new access token once, with `credentials: "include"` and
    // no `Authorization` header — that posture is `needsCredentials()`'s job in
    // `client.ts`, keyed on the `/api/v1/auth/refresh` path, which is why this
    // goes through `clients.refreshTokens` (the `authClient`) and not through
    // `apiClient.request`.
    //
    // Deliberately NOT `refreshSession()` from `refresh-coordinator.ts`: that
    // one serves the 401-recovery path of an already-authenticated session and
    // reports failure as an expired session. Mount starts from anonymous, and a
    // failure here is the ordinary "no session yet" case (D8).
    if (getSessionTokens()) {
      return;
    }
    let applies = true;
    void runMountRefresh({
      refreshTokens: clients.refreshTokens,
      fetchCurrentUser: () => clients.apiClient.request("/api/v1/auth/me"),
    }).then((restoredUser) => {
      if (!applies || mountRefreshSuperseded.current) {
        return;
      }
      if (restoredUser) {
        markSessionPresent();
        setUser(restoredUser);
        setStatus("authenticated");
        return;
      }
      // R5.3: no visible error. The login form appears only if the user walks
      // into a protected route, which is `AuthGuard`'s decision, not ours.
      setStatus("anonymous");
    });
    return () => {
      applies = false;
    };
  }, [clients]);

  useEffect(() => {
    return subscribeToSessionExpired(() => {
      mountRefreshSuperseded.current = true;
      // Capture the session generation on entry. The body is synchronous today,
      // so a comparison `captured === getSessionGeneration()` after `purgeSessionCache()`
      // would be trivially true and useless; the captured value is preserved here as a
      // JSDoc anchor (R3.1) and as the natural extension point if this listener ever
      // becomes async or if more than one listener is mounted in the future.
      const captured = getSessionGeneration();
      void captured;
      // `purgeSessionCache()` advances `sessionGeneration` by construction (see
      // `session-cache-purge.ts`) and empties the singleton `QueryClient`. Any in-flight
      // optimistic snapshot whose `onMutate` captured a previous generation is invalidated
      // by this bump — that is the guarantee `use-mark-read.ts:109` and
      // `use-mark-all-read.ts:99` rely on.
      purgeSessionCache();
      // The reliable signal for the race described in R3.2 is whether the token store
      // already holds a NEW pair: a `login()` that won against an in-flight refresh has
      // already installed its tokens and pushed `status` to `"authenticated"` (R4.2).
      // The coordinator's guard in `refresh-coordinator.ts` expresses the same intent
      // from the other side — "if the *token* generation moved, the tokens now belong to
      // another session" — and this listener honours it instead of overriding it: when
      // tokens are live, we leave tokens, presence and `status` exactly as the new
      // session installed them. Note the coordinator compares `getTokenGeneration()`, a
      // separate counter from the `sessionGeneration` this listener bumps two lines up —
      // a bare cache purge must not look like an identity change to that guard, or a
      // legitimate concurrent refresh under a different session can be wrongly discarded
      // (or a genuinely dead session wrongly kept alive); see `session-store.ts`'s module
      // doc for why the two counters are split.
      //
      // This listener can still fire while tokens are live — notably the
      // `SessionInvalidatedError` branch of `refreshSession`, which deliberately skips
      // `clearSessionTokens` when the generation moved underneath it, but also any
      // `notifySessionExpired()` call that lands after an unrelated `login()`/mount-refresh
      // already installed a newer pair (R4.2/R4.3). The listener must still call
      // `purgeSessionCache()` so that the counter advances and the `QueryClient` is
      // emptied; it must NOT, however, run the cleanup below — those tokens (when they
      // exist) belong to a session that won the race.
      if (getSessionTokens() !== null) {
        return;
      }
      clearSessionTokens();
      setUser(null);
      clearSessionPresent();
      setStatus("expired");
    });
  }, []);

  useEffect(() => {
    // `useLogoutMutation` (in `features/auth/hooks/`) cannot directly reset the
    // React state owned here, so it emits a logout event after its `try/finally`
    // finishes. We mirror the post-logout state to match the freshly-purged
    // store — tokens, cookie and QueryClient are already gone by the time
    // `notifyLogout()` fires.
    return subscribeToLogout(() => {
      mountRefreshSuperseded.current = true;
      setUser(null);
      setStatus("anonymous");
    });
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      mountRefreshSuperseded.current = true;
      setStatus("loading");
      try {
        const tokens = await clients.apiClient.request("/api/v1/auth/login", {
          method: "POST",
          body: { email, password },
        });
        setSessionTokens({ accessToken: tokens.access_token });
        purgeSessionCache();
        markSessionPresent();
        const currentUser = await clients.apiClient.request("/api/v1/auth/me");
        setUser(currentUser);
        setStatus("authenticated");
        // Return the resolved user so callers (notably `LoginForm`) can route
        // on first paint without depending on the closure of `useAuth().user`,
        // which is still `null` until React re-renders.
        return currentUser;
      } catch (error) {
        // A background refresh started under a still-valid previous session may be in
        // flight and resolve after this catch runs. `clearSessionTokens()` bumps
        // `tokenGeneration` by construction, so refresh-coordinator's success branch
        // sees the mismatch and rejects instead of calling setSessionTokens(), which
        // would otherwise resurrect a token pair into a session this catch just tore
        // down. `purgeSessionCache()` is still called first for cache hygiene (nothing
        // this session cached should survive), but the resurrection guard no longer
        // depends on it.
        purgeSessionCache();
        clearSessionTokens();
        clearSessionPresent();
        setUser(null);
        setStatus("error");
        throw error;
      }
    },
    [clients.apiClient],
  );

  const refresh = useCallback(async () => {
    mountRefreshSuperseded.current = true;
    setStatus("refreshing");
    try {
      await refreshSession(clients.refreshTokens);
      setStatus("authenticated");
      return true;
    } catch {
      // Same guard as the listener (D5) and authenticated-client.ts's onUnauthorized
      // (D7): a refresh started under a departing session can settle here after a
      // newer login has already installed its own tokens. Forcing user/status/presence
      // to "expired" unconditionally would clobber that winning session even though its
      // tokens are still live — purge unconditionally for cache hygiene, but only do
      // the full cleanup when no live tokens remain.
      purgeSessionCache();
      if (getSessionTokens() === null) {
        setUser(null);
        clearSessionPresent();
        setStatus("expired");
      }
      return false;
    }
  }, [clients.refreshTokens]);

  const value = useMemo(
    () => ({ user, status, login, refresh }),
    [login, refresh, status, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
