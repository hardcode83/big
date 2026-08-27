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
  login: (email: string, password: string) => Promise<void>;
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
