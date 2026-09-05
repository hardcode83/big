import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearSessionTokens,
  getSessionTokens,
  setSessionTokens,
} from "@/lib/auth/session-store";
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

  it("shares one refresh and atomically replaces the access token", async () => {
    setSessionTokens({ accessToken: "old-access" });
    let resolveRefresh!: (tokens: { accessToken: string }) => void;
    const refresh = vi.fn(
      () =>
        new Promise<{ accessToken: string }>((resolve) => {
          resolveRefresh = resolve;
        }),
    );

    const first = refreshSession(refresh);
    const second = refreshSession(refresh);
    resolveRefresh({ accessToken: "new-access" });

    await expect(Promise.all([first, second])).resolves.toEqual([
      { accessToken: "new-access" },
      { accessToken: "new-access" },
    ]);
    expect(refresh).toHaveBeenCalledOnce();
    expect(refresh).toHaveBeenCalledWith();
    expect(getSessionTokens()).toEqual({ accessToken: "new-access" });
    expect(readPresenceCookie()).toBe("1");
  });

  it("fans out one failure, cleans once, and shares no stale in-flight promise", async () => {
    setSessionTokens({ accessToken: "old-access" });
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
  });

  it("calls refresh even when no access token is in memory (reload-with-cookie path)", async () => {
    // No `setSessionTokens` call here: an empty store (e.g. right after a page
    // reload, with the refresh cookie still live) is no longer a reason for
    // this coordinator to skip calling refresh — R6.1 / design D8's "two
    // distinct callers".
    const refresh = vi.fn().mockResolvedValue({ accessToken: "restored-access" });

    await expect(refreshSession(refresh)).resolves.toEqual({
      accessToken: "restored-access",
    });
    expect(refresh).toHaveBeenCalledOnce();
    expect(getSessionTokens()).toEqual({ accessToken: "restored-access" });
  });

  it("discards a refresh result after the session is cleared", async () => {
    setSessionTokens({ accessToken: "old-access" });
    let resolveRefresh!: (tokens: { accessToken: string }) => void;
    const refresh = vi.fn(
      () =>
        new Promise<{ accessToken: string }>((resolve) => {
          resolveRefresh = resolve;
        }),
    );

    const pending = refreshSession(refresh);
    clearSessionTokens();
    resolveRefresh({ accessToken: "late-access" });

    await expect(pending).rejects.toThrow("Session was invalidated");
    expect(getSessionTokens()).toBeNull();
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("does not let an old refresh affect a new login", async () => {
    setSessionTokens({ accessToken: "old-access" });
    let resolveOldRefresh!: (tokens: { accessToken: string }) => void;
    const oldRefresh = vi.fn(
      () =>
        new Promise<{ accessToken: string }>((resolve) => {
          resolveOldRefresh = resolve;
        }),
    );

    const oldPending = refreshSession(oldRefresh);
    clearSessionTokens();
    setSessionTokens({ accessToken: "new-access" });

    const newRefresh = vi.fn().mockResolvedValue({ accessToken: "rotated-access" });
    const newPending = refreshSession(newRefresh);

    resolveOldRefresh({ accessToken: "late-access" });

    await expect(oldPending).rejects.toThrow("Session was invalidated");
    await expect(newPending).resolves.toEqual({ accessToken: "rotated-access" });
    expect(newRefresh).toHaveBeenCalledWith();
    expect(getSessionTokens()).toEqual({ accessToken: "rotated-access" });
  });
});
