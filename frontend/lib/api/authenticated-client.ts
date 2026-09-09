import type { components } from "./generated/openapi";
import { createApiClient, type ApiClient, type ApiClientOptions } from "./client";
import { refreshSession } from "@/lib/auth/refresh-coordinator";
import {
  getSessionTokens,
  type SessionTokens,
} from "@/lib/auth/session-store";
import { getActiveLocale } from "@/lib/i18n/active-locale";

type AuthStatusChange = "refreshing" | "authenticated" | "expired";
type TokenPairResponse = components["schemas"]["TokenPairResponse"];

type SessionExpiredListener = () => void;
const sessionExpiredListeners = new Set<SessionExpiredListener>();

export function subscribeToSessionExpired(
  listener: SessionExpiredListener,
): () => void {
  sessionExpiredListeners.add(listener);
  return () => sessionExpiredListeners.delete(listener);
}

export function notifySessionExpired(): void {
  for (const listener of sessionExpiredListeners) {
    listener();
  }
}

export interface AuthenticatedClientOptions {
  apiBaseUrl: string;
  onStatusChange?: (status: AuthStatusChange) => void;
  onSessionExpired?: () => void;
  fetchImpl?: ApiClientOptions["fetchImpl"];
}

export interface AuthenticatedClients {
  apiClient: ApiClient;
  refreshTokens: () => Promise<SessionTokens>;
}

export function createAuthenticatedClients(
  options: AuthenticatedClientOptions,
): AuthenticatedClients {
  const authClient = createApiClient({
    baseUrl: options.apiBaseUrl,
    fetchImpl: options.fetchImpl,
  });

  const refreshTokens = async (): Promise<SessionTokens> => {
    // The rotated refresh token travels exclusively via the `Set-Cookie`
    // response header (browser-managed, `credentials: "include"` on this
    // endpoint per D9) — the request body is empty and the response no
    // longer carries a `refresh_token` field.
    const response = await authClient.request("/api/v1/auth/refresh", {
      method: "POST",
    });
    const tokenPair = response as TokenPairResponse;
    return { accessToken: tokenPair.access_token };
  };

  const apiClient = createApiClient({
    baseUrl: options.apiBaseUrl,
    fetchImpl: options.fetchImpl,
    getHeaders: () => {
      const tokens = getSessionTokens();
      const headers: HeadersInit = { "X-Locale": getActiveLocale() };
      if (tokens) {
        headers.Authorization = `Bearer ${tokens.accessToken}`;
      }
      return headers;
    },
    onUnauthorized: async () => {
      options.onStatusChange?.("refreshing");
      try {
        await refreshSession(refreshTokens);
        options.onStatusChange?.("authenticated");
        return true;
      } catch {
        // `onSessionExpired` runs the listener synchronously (R3.1-3): it clears tokens
        // only when no newer session's tokens are live. Forcing "expired" unconditionally
        // here would override a winning login's "authenticated" status a moment after the
        // listener deliberately preserved it, so this mirrors the listener's own check.
        options.onSessionExpired?.();
        if (getSessionTokens() === null) {
          options.onStatusChange?.("expired");
        }
        return false;
      }
    },
  });

  return { apiClient, refreshTokens };
}
