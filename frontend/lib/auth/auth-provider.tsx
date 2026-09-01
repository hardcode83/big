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
