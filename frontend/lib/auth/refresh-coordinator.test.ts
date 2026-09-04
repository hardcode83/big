import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearSessionTokens,
  getSessionGeneration,
  getSessionTokens,
  setSessionTokens,
} from "@/lib/auth/session-store";
import { purgeSessionCache } from "@/lib/auth/session-cache-purge";
import { refreshSession } from "@/lib/auth/refresh-coordinator";
import { SESSION_PRESENT_COOKIE } from "@/lib/config/constants";

function readPresenceCookie(): string | null {
  const cookies = document.cookie ? document.cookie.split("; ") : [];
  const match = cookies.find((entry) => entry.startsWith(`${SESSION_PRESENT_COOKIE}=`));
  return match ? match.slice(SESSION_PRESENT_COOKIE.length + 1) : null;
}

function clearAllCookies(): void {
  document.cookie.split("; ").forEach((entry) => {
    const name = entry.split("=")[0];
    if (name) {
      document.cookie = `${name}=; path=/; max-age=0; samesite=lax`;
    }
  });
}

describe("refresh coordinator", () => {
  beforeEach(() => {
    clearAllCookies();
  });

  afterEach(() => {
    clearSessionTokens();
    clearAllCookies();
  });

  it("shares one refresh and atomically replaces the pair", async () => {
    setSessionTokens({ accessToken: "old-access", refreshToken: "old-refresh" });
    let resolveRefresh!: (tokens: { accessToken: string; refreshToken: string }) => void;
    const refresh = vi.fn(
      () =>
        new Promise<{ accessToken: string; refreshToken: string }>((resolve) => {
          resolveRefresh = resolve;
        }),
    );

    const first = refreshSession(refresh);
    const second = refreshSession(refresh);
    resolveRefresh({ accessToken: "new-access", refreshToken: "new-refresh" });

    await expect(Promise.all([first, second])).resolves.toEqual([
      { accessToken: "new-access", refreshToken: "new-refresh" },
      { accessToken: "new-access", refreshToken: "new-refresh" },
    ]);
    expect(refresh).toHaveBeenCalledOnce();
    expect(getSessionTokens()).toEqual({
      accessToken: "new-access",
      refreshToken: "new-refresh",
    });
    expect(readPresenceCookie()).toBe("1");
  });

  it("fans out one failure, cleans once, and makes no second refresh", async () => {
    setSessionTokens({ accessToken: "old-access", refreshToken: "old-refresh" });
    const error = new Error("refresh failed");
    const refresh = vi.fn().mockRejectedValue(error);

    const results = await Promise.allSettled([
      refreshSession(refresh),
      refreshSession(refresh),
    ]);

    expect(results).toHaveLength(2);
    expect(results.every((result) => result.status === "rejected")).toBe(true);
    expect(results.map((result) => result.status === "rejected" && result.reason)).toEqual([
      error,
      error,
    ]);
    expect(refresh).toHaveBeenCalledOnce();
    expect(getSessionTokens()).toBeNull();
    expect(readPresenceCookie()).toBeNull();
    await expect(refreshSession(refresh)).rejects.toThrow("No refresh token available");
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("discards a refresh result after the session is cleared", async () => {
    setSessionTokens({ accessToken: "old-access", refreshToken: "old-refresh" });
    let resolveRefresh!: (tokens: { accessToken: string; refreshToken: string }) => void;
    const refresh = vi.fn(
      () =>
        new Promise<{ accessToken: string; refreshToken: string }>((resolve) => {
          resolveRefresh = resolve;
        }),
    );

    const pending = refreshSession(refresh);
    purgeSessionCache();
    clearSessionTokens();
    resolveRefresh({ accessToken: "late-access", refreshToken: "late-refresh" });

    await expect(pending).rejects.toThrow("Session was invalidated");
    expect(getSessionTokens()).toBeNull();
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("does not let an old refresh affect a new login", async () => {
    setSessionTokens({ accessToken: "old-access", refreshToken: "old-refresh" });
    let resolveOldRefresh!: (tokens: { accessToken: string; refreshToken: string }) => void;
    const oldRefresh = vi.fn(
      () =>
        new Promise<{ accessToken: string; refreshToken: string }>((resolve) => {
          resolveOldRefresh = resolve;
        }),
    );

    const oldPending = refreshSession(oldRefresh);
    clearSessionTokens();
    setSessionTokens({ accessToken: "new-access", refreshToken: "new-refresh" });

    const newRefresh = vi.fn().mockResolvedValue({
      accessToken: "rotated-access",
      refreshToken: "rotated-refresh",
    });
    const newPending = refreshSession(newRefresh);

    resolveOldRefresh({ accessToken: "late-access", refreshToken: "late-refresh" });

    await expect(oldPending).rejects.toThrow("Session was invalidated");
    await expect(newPending).resolves.toEqual({
      accessToken: "rotated-access",
      refreshToken: "rotated-refresh",
    });
    expect(newRefresh).toHaveBeenCalledWith("new-refresh");
    expect(getSessionTokens()).toEqual({
      accessToken: "rotated-access",
      refreshToken: "rotated-refresh",
    });
  });

  // Security review (second `/sdd:review` round): the app has 11 independent
  // `createAuthenticatedClients()` instances (one per feature module), all sharing this
  // module's `inFlight` singleton. A purge triggered by one client's session-expired
  // listener must not make a genuinely-unrelated, still-in-flight refresh from another
  // client believe its own session was superseded — only an actual token write or clear
  // should do that. Before the `tokenGeneration` split, both used the same
  // `sessionGeneration` counter, so a bare purge looked identical to an identity change.

  it("does not discard a legitimate token rotation when an unrelated cache purge happens mid-flight", async () => {
    setSessionTokens({ accessToken: "old-access", refreshToken: "old-refresh" });
    let resolveRefresh!: (tokens: { accessToken: string; refreshToken: string }) => void;
    const refresh = vi.fn(
      () =>
        new Promise<{ accessToken: string; refreshToken: string }>((resolve) => {
          resolveRefresh = resolve;
        }),
    );

    const pending = refreshSession(refresh);

    // Simulates a different client's session-expired listener purging the cache for a
    // reason unrelated to this refresh — no token write, no token clear.
    purgeSessionCache();

    resolveRefresh({ accessToken: "rotated-access", refreshToken: "rotated-refresh" });

    await expect(pending).resolves.toEqual({
      accessToken: "rotated-access",
      refreshToken: "rotated-refresh",
    });
    expect(getSessionTokens()).toEqual({
      accessToken: "rotated-access",
      refreshToken: "rotated-refresh",
    });
  });

  it("still clears a genuinely revoked session when an unrelated cache purge happens mid-flight", async () => {
    setSessionTokens({ accessToken: "old-access", refreshToken: "old-refresh" });
    let rejectRefresh!: (error: unknown) => void;
    const refresh = vi.fn(
      () =>
        new Promise<{ accessToken: string; refreshToken: string }>((_resolve, reject) => {
          rejectRefresh = reject;
        }),
    );

    const pending = refreshSession(refresh);

    purgeSessionCache();

    rejectRefresh(new Error("refresh token revoked"));

    await expect(pending).rejects.toThrow("refresh token revoked");
    expect(getSessionTokens()).toBeNull();
    expect(readPresenceCookie()).toBeNull();
  });

  it("advances the cache generation when its own guard clears the session, so no future caller has to purge on its behalf", async () => {
    setSessionTokens({ accessToken: "old-access", refreshToken: "old-refresh" });
    const before = getSessionGeneration();
    const refresh = vi.fn().mockRejectedValue(new Error("revoked"));

    await expect(refreshSession(refresh)).rejects.toThrow("revoked");

    expect(getSessionTokens()).toBeNull();
    expect(getSessionGeneration()).toBeGreaterThan(before);
  });
});
