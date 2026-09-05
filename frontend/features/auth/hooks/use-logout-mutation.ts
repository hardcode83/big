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
 * **A missing access token does not skip the call.** The store can be empty at
 * logout time — a mount-refresh that never repopulated it, or a
 * session-expired reset — while the `autohostai.session.refresh` cookie the
 * browser holds may still be perfectly live; skipping the request outright
 * left that server-side session, and its cookie, alive with nothing to ever
 * clear either (review finding: security panel, `auth-session-persistence`).
 * `POST /api/v1/auth/logout` is always called, Bearer or not — `needsCredentials`
 * already sends `credentials: "include"` for this path regardless — and the
 * backend accepts the refresh cookie itself as the credential when no Bearer is
 * presented, the same "the token IS the credential" stance `/auth/refresh`
 * already takes (`get_logout_subject`, `backend/app/auth/api/dependencies.py`).
 *
 * **This replaced an earlier fix that called `refreshSession` first** purely to
 * obtain a Bearer for the empty-store case: that rotated and re-extended the
 * refresh cookie by a fresh week *before* attempting to revoke it, so a POST
 * that then failed left the browser holding a freshly-extended, still-valid
 * session — worse than the one being logged out of (review finding: security
 * panel, second round). Letting the backend read the cookie directly removes
 * that round trip, and with it the window entirely. A stale-but-present token
 * (the common case: an access token that expired without ever being cleared)
 * needs no special handling either — the client's ordinary 401-recovery
 * already retries logout once with a fresh token, now that logout is no
 * longer excluded from it (`lib/api/client.ts`).
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
 * specific files, not the barrel, to avoid a load-order cycle — this hook
 * and `lib/auth/auth-provider.tsx` communicate only through
 * `lib/auth/logout-event.ts`'s pub/sub, never through a direct import of
 * one from the other.
 */
export function useLogoutMutation() {
  const { apiBaseUrl } = useRuntimeConfig();
  const queryClient = useQueryClient();

  const { apiClient } = useMemo(() => {
    return createAuthenticatedClients({
      apiBaseUrl,
      onSessionExpired: notifySessionExpired,
    });
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
        await apiClient.request("/api/v1/auth/logout", { method: "POST" });
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