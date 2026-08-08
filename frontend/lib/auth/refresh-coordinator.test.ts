import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clearSessionTokens,
  getSessionTokens,
  setSessionTokens,
} from "@/lib/auth/session-store";
import { refreshSession } from "@/lib/auth/refresh-coordinator";

describe("refresh coordinator", () => {
  afterEach(() => clearSessionTokens());

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
    clearSessionTokens();
    resolveRefresh({ accessToken: "late-access", refreshToken: "late-refresh" });

    await expect(pending).rejects.toThrow("Session was invalidated");
    expect(getSessionTokens()).toBeNull();
    expect(refresh).toHaveBeenCalledOnce();
  });
});
