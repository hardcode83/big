import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as dataModule from "../data";
import { notificationsKeys } from "./query-keys";
import { useMarkRead } from "./use-mark-read";
import { useMarkAllRead } from "./use-mark-all-read";
import { purgeSessionCache } from "@/lib/auth/session-cache-purge";

const authState = { status: "authenticated", user: { tenant_id: "t1", id: "u1" } };
// The mock's `getSessionGeneration` proxies to the REAL implementation in
// `session-store.ts`. The revert consults `getSessionGeneration()` to decide whether its
// snapshot still belongs to the session in the tab; if the real counter advances mid-flight
// (which only happens when something goes through `purgeSessionCache()`), the revert is
// skipped. Proxying to the real counter is what makes R4.4 a real test of R1 — without the
// proxy the test could pass even if `purgeSessionCache()` stopped advancing the counter.
vi.mock("@/lib/auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/auth")>();
  return {
    ...real,
    useAuth: () => authState,
  };
});

const markRead = vi.fn();
const markAllRead = vi.fn();
vi.spyOn(dataModule, "getNotificationsDataSource").mockImplementation(
  () =>
    ({ markRead, markAllRead }) as unknown as ReturnType<
      typeof dataModule.getNotificationsDataSource
    >,
);

/**
 * Cache shim for the R4.4 test: when a test registers a per-test QueryClient via
 * `useCacheClient()`, the mock at `@/lib/query/query-client` returns it from
 * `getQueryClient()`. That makes the real `purgeSessionCache()` (the path the
 * listener actually exercises) clear the same client the test reads from, so the
 * assertions about the cache being empty after the rejection are observed against
 * the production-shaped code path instead of a hand-written `client.clear()`.
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

function useCacheClient(client: QueryClient): QueryClient {
  cacheClientRef.current = client;
  return client;
}

const UNREAD_KEY = notificationsKeys.unread("t1", "u1");
const LIST_KEY = notificationsKeys.list("t1", "u1", { page: 1 });

function seededClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  client.setQueryData(UNREAD_KEY, 2);
  client.setQueryData(LIST_KEY, {
    items: [
      { id: "n1", type: "CLEANING_TASK_ASSIGNED", relatedType: null, relatedId: null, createdAt: "2026-08-29T08:00:00Z", readAt: null },
      { id: "n2", type: "SLA_BREACH", relatedType: null, relatedId: null, createdAt: "2026-08-29T07:00:00Z", readAt: null },
    ],
    total: 2,
    page: 1,
    perPage: 20,
    totalPages: 1,
  });
  return client;
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function readList(client: QueryClient) {
  return client.getQueryData<{ items: Array<{ id: string; readAt: string | null }> }>(
    LIST_KEY,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  authState.status = "authenticated";
  cacheClientRef.current = null;
});

describe("useMarkRead (R5.1, R5.3, R5.4, design D13)", () => {
  it("stamps the row and drops the counter BEFORE the server answers", async () => {
    const client = seededClient();
    let release: (() => void) | undefined;
    markRead.mockImplementation(
      () => new Promise<void>((resolve) => { release = resolve; }),
    );
    const { result } = renderHook(() => useMarkRead(), { wrapper: wrapperFor(client) });

    act(() => { result.current.mutate("n1"); });

    // The whole point of R5.1: this holds while the request is still in flight.
    await waitFor(() => expect(client.getQueryData(UNREAD_KEY)).toBe(1));
    expect(readList(client)?.items[0].readAt).not.toBeNull();
    expect(readList(client)?.items[1].readAt).toBeNull();

    act(() => { release?.(); });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("restores BOTH the row and the counter when the acknowledgement fails (R5.3)", async () => {
    const client = seededClient();
    markRead.mockRejectedValue(new Error("network"));
    const { result } = renderHook(() => useMarkRead(), { wrapper: wrapperFor(client) });

    act(() => { result.current.mutate("n1"); });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(client.getQueryData(UNREAD_KEY)).toBe(2);
    expect(readList(client)?.items[0].readAt).toBeNull();
  });

  it("invalidates the counter and the whole list family after success (R5.4)", async () => {
    const client = seededClient();
    markRead.mockResolvedValue(undefined);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useMarkRead(), { wrapper: wrapperFor(client) });

    act(() => { result.current.mutate("n1"); });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidate.mock.calls.map(([options]) => options?.queryKey);
    expect(keys).toContainEqual(UNREAD_KEY);
    // The PREFIX, not one page's key: a filtered page 2 must be refetched too.
    expect(keys).toContainEqual(notificationsKeys.listPrefix("t1", "u1"));
  });

  it("does not take a second off the bell when the row was already read (R1.3)", async () => {
    const client = seededClient();
    client.setQueryData(LIST_KEY, {
      items: [
        { id: "n1", type: "SLA_BREACH", relatedType: null, relatedId: null, createdAt: "2026-08-29T08:00:00Z", readAt: "2026-08-29T09:00:00Z" },
      ],
      total: 1,
      page: 1,
      perPage: 20,
      totalPages: 1,
    });
    markRead.mockResolvedValue(undefined);
    const { result } = renderHook(() => useMarkRead(), { wrapper: wrapperFor(client) });

    act(() => { result.current.mutate("n1"); });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryData(UNREAD_KEY)).not.toBe(1);
  });

  it("never paints a negative bell", async () => {
    const client = seededClient();
    client.setQueryData(UNREAD_KEY, 0);
    markRead.mockResolvedValue(undefined);
    const { result } = renderHook(() => useMarkRead(), { wrapper: wrapperFor(client) });

    act(() => { result.current.mutate("n1"); });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryData<number>(UNREAD_KEY)).toBeGreaterThanOrEqual(0);
  });
});

describe("useMarkAllRead (R5.2, R5.3, R5.4)", () => {
  it("zeroes the counter and stamps every unread row, then invalidates both families", async () => {
    const client = seededClient();
    markAllRead.mockResolvedValue(2);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useMarkAllRead(), { wrapper: wrapperFor(client) });

    act(() => { result.current.mutate(); });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toBe(2);
    expect(readList(client)?.items.every((item) => item.readAt !== null)).toBe(true);
    const keys = invalidate.mock.calls.map(([options]) => options?.queryKey);
    expect(keys).toContainEqual(UNREAD_KEY);
    expect(keys).toContainEqual(notificationsKeys.listPrefix("t1", "u1"));
  });

  it("restores the snapshot when it fails (R5.3)", async () => {
    const client = seededClient();
    markAllRead.mockRejectedValue(new Error("network"));
    const { result } = renderHook(() => useMarkAllRead(), { wrapper: wrapperFor(client) });

    act(() => { result.current.mutate(); });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(client.getQueryData(UNREAD_KEY)).toBe(2);
    expect(readList(client)?.items.every((item) => item.readAt === null)).toBe(true);
  });

  it("treats zero moved rows as the normal answer of an inbox up to date (D6)", async () => {
    const client = seededClient();
    markAllRead.mockResolvedValue(0);
    const { result } = renderHook(() => useMarkAllRead(), { wrapper: wrapperFor(client) });

    act(() => { result.current.mutate(); });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toBe(0);
    expect(result.current.isError).toBe(false);
  });
});

describe("the revert does not survive the session that started it (R3.4)", () => {
  it("useMarkRead writes nothing back when the session ended mid-flight", async () => {
    const client = useCacheClient(seededClient());
    markRead.mockImplementation(async () => {
      // What really happens on a 401: the authenticated client purges the whole cache and
      // the session generation moves, and only THEN does the request reject. We go through
      // the real `purgeSessionCache()` so the generation bump comes from the production path,
      // not from a hand-written counter.
      purgeSessionCache();
      throw new Error("session expired");
    });
    const { result } = renderHook(() => useMarkRead(), { wrapper: wrapperFor(client) });

    act(() => { result.current.mutate("n1"); });
    await waitFor(() => expect(result.current.isError).toBe(true));

    // The departing user's rows and counter must NOT be resurrected into the cleared cache.
    expect(client.getQueryData(UNREAD_KEY)).toBeUndefined();
    expect(client.getQueryData(LIST_KEY)).toBeUndefined();
  });

  it("useMarkRead does not resurrect rows when a mid-flight purgeSessionCache() advances the generation (R4.4)", async () => {
    // R4.4: the production path is `notifySessionExpired` → listener → `purgeSessionCache()`,
    // which advances `sessionGeneration` by 1 (D1 / R1.1). `use-mark-read.onError` compares
    // `getSessionGeneration()` against the snapshot captured at `onMutate`; if the generation
    // moved, the rollback is skipped. Without section 1, `purgeSessionCache()` did not bump
    // the generation, the guard fired late or not at all, and the departing user's rows came
    // back into a cache that was just emptied to keep the next person from seeing them.
    //
    // The test depends on the mock of `@/lib/auth` proxying `getSessionGeneration` to the
    // real `session-store.ts` (see the `vi.mock` at the top of this file). Without that
    // proxy, the test could pass even if `purgeSessionCache()` stopped advancing the real
    // counter — making it useless as a guard of R1. With the proxy, a regression that
    // removes the bump inside `purgeSessionCache()` is caught here: the real counter does
    // not move, `getSessionGeneration()` returns the captured value, the guard lets the
    // revert run, and the seeded rows come back into the cleared cache.
    //
    // The test registers the local `QueryClient` as the singleton via `useCacheClient`
    // so that the real `purgeSessionCache()` clears the same client the assertions read
    // from — the cache invariant (`getQueryData(...)` returns `undefined`) is observed
    // against the production-shaped code path instead of a hand-written `client.clear()`.
    const client = useCacheClient(seededClient());
    markRead.mockImplementation(async () => {
      purgeSessionCache();
      throw new Error("session expired");
    });
    const { result } = renderHook(() => useMarkRead(), { wrapper: wrapperFor(client) });

    act(() => { result.current.mutate("n1"); });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(client.getQueryData(UNREAD_KEY)).toBeUndefined();
    expect(client.getQueryData(LIST_KEY)).toBeUndefined();
  });

  it("useMarkAllRead writes nothing back when the session ended mid-flight", async () => {
    const client = useCacheClient(seededClient());
    markAllRead.mockImplementation(async () => {
      purgeSessionCache();
      throw new Error("session expired");
    });
    const { result } = renderHook(() => useMarkAllRead(), { wrapper: wrapperFor(client) });

    act(() => { result.current.mutate(); });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(client.getQueryData(UNREAD_KEY)).toBeUndefined();
    expect(client.getQueryData(LIST_KEY)).toBeUndefined();
  });

  it("still reverts normally when the session is the same one", async () => {
    const client = seededClient();
    markRead.mockRejectedValue(new Error("network"));
    const { result } = renderHook(() => useMarkRead(), { wrapper: wrapperFor(client) });

    act(() => { result.current.mutate("n1"); });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(client.getQueryData(UNREAD_KEY)).toBe(2);
  });
});

describe("reverting a counter that had never loaded (R5.3)", () => {
  it("useMarkAllRead does not strand the optimistic zero on the bell", async () => {
    // The hole: `onMutate` zeroes the counter whether or not there was a snapshot, so a
    // revert that only ran when one existed left the bell saying "nothing waiting" after a
    // failed "mark all" — and `onSettled`'s refetch fails for the same reason the write did.
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    markAllRead.mockRejectedValue(new Error("network"));
    const { result } = renderHook(() => useMarkAllRead(), { wrapper: wrapperFor(client) });

    act(() => { result.current.mutate(); });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(client.getQueryData(UNREAD_KEY)).not.toBe(0);
    expect(client.getQueryData(UNREAD_KEY)).toBeUndefined();
  });

  it("useMarkRead leaves a counter it never touched alone", async () => {
    // Its optimistic write is already guarded, so with no snapshot it never decremented
    // anything — and a revert that reset the query anyway would be destroying the bell's
    // first, still-unresolved load on behalf of a mutation that did not modify it.
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    client.setQueryData(LIST_KEY, {
      items: [
        { id: "n1", type: "SLA_BREACH", relatedType: null, relatedId: null, createdAt: "2026-08-29T08:00:00Z", readAt: null },
      ],
      total: 1,
      page: 1,
      perPage: 20,
      totalPages: 1,
    });
    const reset = vi.spyOn(client, "resetQueries");
    const remove = vi.spyOn(client, "removeQueries");
    markRead.mockRejectedValue(new Error("network"));
    const { result } = renderHook(() => useMarkRead(), { wrapper: wrapperFor(client) });

    act(() => { result.current.mutate("n1"); });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const unreadResets = reset.mock.calls.filter(
      ([options]) => JSON.stringify(options?.queryKey) === JSON.stringify(UNREAD_KEY),
    );
    expect(unreadResets).toHaveLength(0);
    expect(remove).not.toHaveBeenCalled();
    // And the row it DID patch is still reverted.
    expect(readList(client)?.items[0].readAt).toBeNull();
  });

  it("useMarkAllRead resets rather than removes, so a mounted bell refetches at once", async () => {
    // `removeQueries` deletes the entry without re-pointing the attached observers, so the
    // bell would keep painting the optimistic zero until its next render or its next 60 s
    // poll — and `onSettled`'s invalidation would match nothing to heal it.
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const reset = vi.spyOn(client, "resetQueries");
    const remove = vi.spyOn(client, "removeQueries");
    markAllRead.mockRejectedValue(new Error("network"));
    const { result } = renderHook(() => useMarkAllRead(), { wrapper: wrapperFor(client) });

    act(() => { result.current.mutate(); });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(
      reset.mock.calls.some(
        ([options]) => JSON.stringify(options?.queryKey) === JSON.stringify(UNREAD_KEY),
      ),
    ).toBe(true);
    expect(remove).not.toHaveBeenCalled();
  });
});
