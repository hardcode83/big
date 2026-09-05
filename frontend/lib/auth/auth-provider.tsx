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
  logout: () => Promise<void>;
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
 * The entry is keyed on `getSessionGeneration()` and cleared the moment the
 * promise settles, so the guard means "already in flight AND the identity has
 * not resolved yet". A later, genuine remount (after a logout, say) sees an
 * empty slot — or a stale generation — and refreshes again.
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
  const generation = getSessionGeneration();
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
      // The same guard `refresh-coordinator.ts:46` applies before its own
      // `setSessionTokens`, for the same reason: `sessionGeneration` moves on
      // every write to the shared, module-level store, so a value different
      // from the one captured above means the session this refresh belongs to
      // was torn down or superseded while the network call was in flight —
      // a logout, a 401 that declared the session expired, or a login as a
      // different identity. Installing the resolved token now would silently
      // reinstate credentials for a dead session, or clobber the freshly
      // installed correct token with this stale one. Drop it instead and
      // resolve as a failed restore.
      //
      // No `clearSessionTokens()` here, deliberately: whatever the store holds
      // now belongs to the newer session, not to this refresh. That is the
      // mirror image of the coordinator's `catch` guard, which only clears
      // while the generation still matches.
      if (getSessionGeneration() !== generation) {
        return null;
      }
      setSessionTokens({ accessToken });
      postInstallGeneration = getSessionGeneration();
      return await deps.fetchCurrentUser();
    } catch {
      // A refresh that worked but an `/auth/me` that did not leaves an access
      // token backing an identity we never read — drop it rather than resolve
      // `anonymous` while the store still holds credentials.
      //
      // Only while that token is still the one in the store, though: the same
      // generation check the success path applies above, mirrored here exactly
      // as `refresh-coordinator.ts:54` mirrors its own. A concurrent `login()`
      // completing while this `/auth/me` was in flight installs a newer
      // session's tokens and bumps the generation again; clearing then would
      // wipe live credentials that have nothing to do with this refresh. The
      // stale token this branch wanted to drop is already gone — overwritten
      // by that newer write.
      if (
        postInstallGeneration !== null &&
        getSessionGeneration() === postInstallGeneration
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
      purgeSessionCache();
      // A session declared expired must not keep its tokens in memory. Two paths reach this
      // listener WITHOUT `refreshSession` having cleared them: the `SessionInvalidatedError`
      // branch, which deliberately skips `clearSessionTokens` when the generation moved
      // underneath it, and the "No refresh token available" early reject, which never had a
      // token to clear. Both used to leave the store holding credentials for a session the app
      // had just declared over.
      //
      // The consequence that made it visible is `sessionGeneration`, which only moves inside
      // the two token writers: an optimistic mutation in flight compares it in `onError` to
      // decide whether its snapshot still belongs to this session, and on those two paths the
      // number had not moved — so the departing user's cached rows were written back into the
      // `QueryClient` the line above had just emptied, which is exactly what
      // `notifications-inbox-web` R3.4 forbids. Clearing here moves the generation on every purge
      // that goes through THIS listener, which is every 401 of every authenticated client.
      //
      // It is **not** true of every purge in this file: `refresh()` below calls
      // `purgeSessionCache()` on its own, without clearing tokens and without notifying, so
      // that one still leaves the counter where it was. No `useAuth()` call site destructures
      // `refresh`, so it is latent rather than live — measured across the tree during
      // `notifications-inbox-web`'s implementation and confirmed again by its review panel on
      // 2026-08-29. Left unfixed here because moving the bump into `purgeSessionCache()` is a
      // decision about shared auth semantics and not about one feature; it is carried as the
      // roadmap candidate `auth-session-generation-semantics`. Do not read this comment as a
      // licence to purge from anywhere.
      //
      // **This clear deliberately overrides the guard at `refresh-coordinator.ts:57`**, which
      // skips clearing when the generation moved underneath a stale refresh, precisely so a
      // refresh cannot destroy credentials installed after it started. The trade-off, and it is
      // a trade-off rather than an oversight: a stale refresh resolving during a fresh `login()`
      // now drops the NEW session's tokens, leaving a UI that believes it is authenticated with
      // an empty store until the next 401 forces a re-login. Before this change that same race
      // already ended in `expired`, so what is lost is a recovery nothing used — and the
      // alternative, an expired session that keeps its credentials, is worse.
      //
      // All of this was found by `notifications-inbox-web`'s section-5 security panel.
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
      purgeSessionCache();
      setUser(null);
      setStatus("expired");
      return false;
    }
  }, [clients.refreshTokens]);

  /**
   * Logout wrapper kept for backwards compatibility with consumers that
   * already wired `useAuth().logout()` before the TanStack Query migration.
   * New call sites MUST use `useLogoutMutation()` instead.
   *
   * **What this does vs `useLogoutMutation()`**: this method runs the
   * local-state purge only — no server round-trip. The full flow
   * (server POST `/auth/logout` + local purge + cache invalidation +
   * redirect) lives in `useLogoutMutation` and is called by `UserMenu`.
   * Removing the parallel `clients.apiClient.request("/auth/logout")`
   * here closes F5 without making `AuthProvider` depend on a
   * `QueryClient` (which would break the auth-session integration test
   * and any other render tree that mounts `AuthProvider` outside a
   * `QueryProvider`).
   *
   * @deprecated Use `useLogoutMutation()` — design D3/R3 migrated the call
   * site in `UserMenu`. No live consumer reads this method in the current
   * change (`UserMenu` is the only one, and it migrated). Removal is safe
   * in a follow-up change.
   */
  const logout = useCallback(async () => {
    mountRefreshSuperseded.current = true;
    purgeSessionCache();
    clearSessionTokens();
    clearSessionPresent();
    setUser(null);
    setStatus("anonymous");
  }, []);

  const value = useMemo(
    () => ({ user, status, login, logout, refresh }),
    [login, logout, refresh, status, user],
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
