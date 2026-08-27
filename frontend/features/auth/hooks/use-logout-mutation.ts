"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";
import { useRuntimeConfig } from "@/lib/config/runtime-config-provider";
import {
  clearSessionPresent,
  getSessionTokens,
  purgeSessionCache,
} from "@/lib/auth";
import { clearSessionTokens } from "@/lib/auth/session-store";
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
 * token has expired) never retry.
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
      try {
        if (getSessionTokens()) {
          await apiClient.request("/api/v1/auth/logout", { method: "POST" });
        }
      } catch {
        // Best-effort. The local purge below runs either way.
      } finally {
        purgeSessionCache();
        clearSessionTokens();
        clearSessionPresent();
        notifyLogout();
      }
    },
    retry: 1,
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ["auth", "me"] });
    },
  });
}