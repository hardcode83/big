import type { components } from "./generated/openapi";
import { createApiClient, type ApiClient, type ApiClientOptions } from "./client";
import { refreshSession } from "@/lib/auth/refresh-coordinator";
import {
  getSessionTokens,
  type SessionTokens,
} from "@/lib/auth/session-store";

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
  refreshTokens: (refreshToken: string) => Promise<SessionTokens>;
}

export function createAuthenticatedClients(
  options: AuthenticatedClientOptions,
): AuthenticatedClients {
  const authClient = createApiClient({
    baseUrl: options.apiBaseUrl,
    fetchImpl: options.fetchImpl,
  });

  const refreshTokens = async (refreshToken: string): Promise<SessionTokens> => {
    const response = await authClient.request("/api/v1/auth/refresh", {
      method: "POST",
      body: { refresh_token: refreshToken },
    });
    const tokenPair = response as TokenPairResponse;
    return {
      accessToken: tokenPair.access_token,
      refreshToken: tokenPair.refresh_token,
    };
  };

  const apiClient = createApiClient({
    baseUrl: options.apiBaseUrl,
    fetchImpl: options.fetchImpl,
    getHeaders: () => {
      const tokens = getSessionTokens();
      const headers: HeadersInit = {};
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
        options.onSessionExpired?.();
        options.onStatusChange?.("expired");
        return false;
      }
    },
  });

  return { apiClient, refreshTokens };
}
