import { describe, expect, it, vi } from "vitest";

import { createAuthenticatedClients } from "@/lib/api/authenticated-client";
import { setSessionTokens } from "@/lib/auth/session-store";

/**
 * Covers the composed `onUnauthorized` path (R3.3): it must not force `status`
 * to `"expired"` when tokens are live by the time the session-expired listener
 * has run, because that would clobber a winning login's `"authenticated"`
 * status a moment after the listener deliberately preserved it (D5). Every
 * `auth-provider.test.tsx` interleaving test fires `notifySessionExpired()`
 * directly to observe the listener in isolation; these tests exercise the
 * real composed `onUnauthorized` catch instead.
 */
function unauthorizedResponse(): Response {
  return new Response(
    JSON.stringify({ error: { code: "UNAUTHENTICATED", message: "expired" } }),
    { status: 401 },
  );
}

describe("createAuthenticatedClients onUnauthorized", () => {
  it("does not clobber status to 'expired' when tokens are live after the session-expired listener runs (a winning login)", async () => {
    setSessionTokens({ accessToken: "old-access", refreshToken: "old-refresh" });

    const statuses: string[] = [];
    const fetchImpl = vi.fn().mockResolvedValue(unauthorizedResponse());

    const { apiClient } = createAuthenticatedClients({
      apiBaseUrl: "https://api",
      fetchImpl,
      onStatusChange: (status) => statuses.push(status),
      onSessionExpired: () => {
        // By the time the real listener (auth-provider.tsx) runs, a concurrent login
        // may already have installed a new pair (D5's "login wins" branch) — simulated
        // directly here rather than depending on refresh-coordinator's cleanup order.
        setSessionTokens({ accessToken: "new-access", refreshToken: "new-refresh" });
      },
    });

    await expect(apiClient.request("/health")).rejects.toThrow();

    expect(statuses).toEqual(["refreshing"]);
  });

  it("still transitions status to 'expired' when no live tokens remain (genuine expiration)", async () => {
    setSessionTokens({ accessToken: "old-access", refreshToken: "old-refresh" });

    const statuses: string[] = [];
    const fetchImpl = vi.fn().mockResolvedValue(unauthorizedResponse());

    const { apiClient } = createAuthenticatedClients({
      apiBaseUrl: "https://api",
      fetchImpl,
      onStatusChange: (status) => statuses.push(status),
    });

    await expect(apiClient.request("/health")).rejects.toThrow();

    expect(statuses).toEqual(["refreshing", "expired"]);
  });
});
