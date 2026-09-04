import type { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { purgeSessionCache } from "@/lib/auth/session-cache-purge";
import {
  clearSessionTokens,
  getSessionGeneration,
  getSessionTokens,
  setSessionTokens,
} from "@/lib/auth/session-store";
import { makeQueryClient } from "@/lib/query/query-client";

/**
 * `getQueryClient()` is mocked to a fresh per-test instance (same pattern as
 * `auth-provider.test.tsx`) so the tests below can assert against the exact
 * client `purgeSessionCache()` clears, instead of an unrelated client that
 * happens to also start empty.
 */
const cacheClientRef = vi.hoisted(() => ({
  current: null as QueryClient | null,
}));

vi.mock("@/lib/query/query-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/query/query-client")>();
  return {
    ...actual,
    getQueryClient: () => cacheClientRef.current ?? actual.getQueryClient(),
  };
});

describe("session cache purge", () => {
  beforeEach(() => {
    clearSessionTokens();
    cacheClientRef.current = makeQueryClient();
  });

  it("advances getSessionGeneration() by exactly 1 per call from any starting value", () => {
    const initial = getSessionGeneration();

    purgeSessionCache();
    expect(getSessionGeneration()).toBe(initial + 1);

    purgeSessionCache();
    expect(getSessionGeneration()).toBe(initial + 2);

    purgeSessionCache();
    expect(getSessionGeneration()).toBe(initial + 3);
  });

  it("empties the QueryClient singleton returned by getQueryClient()", () => {
    const client = cacheClientRef.current!;
    client.setQueryData(["probe"], { value: 1 });
    expect(client.getQueryCache().getAll().length).toBe(1);

    purgeSessionCache();

    expect(client.getQueryCache().getAll().length).toBe(0);
  });

  it("advances the counter even when the QueryClient cache is already empty", () => {
    const client = cacheClientRef.current!;
    expect(client.getQueryCache().getAll().length).toBe(0);

    purgeSessionCache();
    expect(client.getQueryCache().getAll().length).toBe(0);

    const afterFirst = getSessionGeneration();

    purgeSessionCache();
    expect(client.getQueryCache().getAll().length).toBe(0);
    expect(getSessionGeneration()).toBe(afterFirst + 1);
  });

  it("does not touch getSessionTokens() before or after the purge", () => {
    const tokens = { accessToken: "access", refreshToken: "refresh" };
    setSessionTokens(tokens);

    expect(getSessionTokens()).toEqual(tokens);

    purgeSessionCache();

    expect(getSessionTokens()).toEqual(tokens);
  });

  it("does not advance getSessionGeneration() when clearSessionTokens() is called alone", () => {
    setSessionTokens({ accessToken: "access", refreshToken: "refresh" });

    const generationAfterSet = getSessionGeneration();

    clearSessionTokens();

    expect(getSessionGeneration()).toBe(generationAfterSet);
  });
});
