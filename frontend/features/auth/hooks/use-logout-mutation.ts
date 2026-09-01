"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";
import { useRuntimeConfig } from "@/lib/config/runtime-config-provider";
import { purgeSessionCache } from "@/lib/auth/session-cache-purge";
import { clearSessionPresent } from "@/lib/auth/session-presence-cookie";
import {
  clearSessionTokens,
  getSessionTokens,
} from "@/lib/auth/session-store";
import { notifyLogout } from "@/lib/auth/logout-event";

/**
 * Logout as a TanStack Query mutation (design D3, R3). Replaces the previous
 * ad-hoc `useAuth().logout()` callback with a real mutation so the logout
 * shares the same machinery as every other mutation in the app — retry on
 * transient failures, typed response, cache-key invalidation.
 *
 * **Local purge is unconditional** (mirrors `auth-provider.tsx:127-134` and
 * `frontend-auth-session.md:81-86`): the `try/finally` around the endpoint
 * call runs `purgeSessionCache → clearSessionTokens → clearSessionPresent`
 * regardless of success or 5xx/network error. The endpoint is best-effort;
 * the local cleanup is the contract.
 *
 * **Query invalidation** (`onSuccess`): `queryClient.removeQueries` on the
 * `["auth", "me"]` key, so a subsequent `useAuth()` starts in `anonymous`
 * without a stale cached identity (R3 #4). The `try/finally` already purged
 * the entire cache via `purgeSessionCache`; this is the explicit, queryable
 * signal for code that listens for the key by name.
 *
 * **React state**: `useLogoutMutation` lives in a feature module and
 * therefore cannot directly clear the `user` / `status` React state owned
 * by `AuthProvider` in `lib/auth`. After the `try/finally` finishes, it
 * emits `notifyLogout()`; `AuthProvider` subscribes via `useEffect` and
 * resets to `anonymous`/`null` to match the freshly-purged local store
 * (`lib/auth/logout-event.ts`, the same pattern as `notifySessionExpired`).
 *
 * **Retry policy**: `retry: 1`. 5xx and network errors are transient and
 * get one retry; 4xx (the logout endpoint returns 401 once the refresh
 * token has expired) never retry. The `mutationFn` re-throws after the
 * local purge so this retry actually fires — an empty `catch` would make
 * the retry config a no-op (review F6).
 *
 * **Module boundaries**: imports of `@/lib/auth/*` are made against the
 * specific files, not the barrel, to avoid a load-order cycle with
 * `lib/auth/auth-provider.tsx`, which itself imports this hook to keep
 * `useAuth().logout()` as a thin delegating wrapper (R3 #5).
 */
export function useLogoutMutation() {
  const { apiBaseUrl } = useRuntimeConfig();
  const queryClient = useQueryClient();

  const apiClient = useMemo(() => {
    return createAuthenticatedClients({
      apiBaseUrl,
      onSessionExpired: notifySessionExpired,
    }).apiClient;
  }, [apiBaseUrl]);

  return useMutation({
    mutationFn: async () => {
      // We capture the network error so the local purge still runs
      // unconditionally per `frontend-auth-session.md:81-86`, and then
      // re-throw so TanStack Query's `retry: 1` actually fires on transient
      // 5xx / network errors. Without the re-throw, the empty `catch`
      // would silently swallow the failure and the retry config would be
      // a no-op (R3 #3, review F6).
      let networkError: unknown = null;
      try {
        if (getSessionTokens()) {
          await apiClient.request("/api/v1/auth/logout", { method: "POST" });
        }
      } catch (error) {
        networkError = error;
      } finally {
        purgeSessionCache();
        clearSessionTokens();
        clearSessionPresent();
        notifyLogout();
      }
      if (networkError !== null) {
        throw networkError;
      }
    },
    retry: 1,
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ["auth", "me"] });
    },
  });
}