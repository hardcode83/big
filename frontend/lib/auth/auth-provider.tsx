"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
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

export function AuthProvider({ children }: { children: ReactNode }) {
  const { apiBaseUrl } = useRuntimeConfig();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("anonymous");

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
    return subscribeToSessionExpired(() => {
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
      // Two paths still reach this listener with tokens live, and that part of the
      // previous comment is preserved verbatim because it remains true:
      //   * the `SessionInvalidatedError` branch of `refreshSession`, which deliberately
      //     skips `clearSessionTokens` when the generation moved underneath it; and
      //   * the "No refresh token available" early reject, which never had a token to
      //     clear.
      // On both paths the listener must still call `purgeSessionCache()` so that the
      // counter advances and the `QueryClient` is emptied; it must NOT, however, run
      // the cleanup below — those tokens (when they exist) belong to a session that
      // won the race.
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
      setUser(null);
      setStatus("anonymous");
    });
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      setStatus("loading");
      try {
        const tokens = await clients.apiClient.request("/api/v1/auth/login", {
          method: "POST",
          body: { email, password },
        });
        setSessionTokens({
          accessToken: tokens.access_token,
          refreshToken: tokens.refresh_token,
        });
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
