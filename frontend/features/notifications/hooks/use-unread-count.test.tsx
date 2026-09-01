import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { retryPolicy } from "@/lib/api/retry-policy";

import * as dataModule from "../data";
import { UNREAD_POLL_INTERVAL_MS, useUnreadCount } from "./use-unread-count";
import { useNotifications } from "./use-notifications";

const authState = { status: "authenticated", user: { tenant_id: "t1", id: "u1" } };
vi.mock("@/lib/auth", () => ({ useAuth: () => authState }));

const countUnread = vi.fn();
const listNotifications = vi.fn();
vi.spyOn(dataModule, "getNotificationsDataSource").mockImplementation(
  () =>
    ({ countUnread, listNotifications }) as unknown as ReturnType<
      typeof dataModule.getNotificationsDataSource
    >,
);

const useQuerySpy = vi.hoisted(() => vi.fn());
vi.mock("@tanstack/react-query", async () => {
  const actual =
    await vi.importActual<typeof import("@tanstack/react-query")>(
      "@tanstack/react-query",
    );
  return {
    ...actual,
    useQuery: (options: unknown) => {
      useQuerySpy(options);
      return actual.useQuery(options as never);
    },
  };
});

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  authState.status = "authenticated";
  authState.user = { tenant_id: "t1", id: "u1" };
});

describe("useUnreadCount (R3.3, design D11)", () => {
  it("polls every 60 s, never in a background tab, and retries with the shared policy", async () => {
    countUnread.mockResolvedValue(4);

    const { result } = renderHook(() => useUnreadCount(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.data).toBe(4));

    // This is the first refetchInterval in the repository, so this assertion is what fixes
    // the cadence — there is no other test in the tree that would notice it changing.
    const options = useQuerySpy.mock.calls[0][0];
    expect(options.refetchInterval).toBe(60_000);
    expect(UNREAD_POLL_INTERVAL_MS).toBe(60_000);
    expect(options.refetchIntervalInBackground).toBe(false);
    expect(options.retry).toBe(retryPolicy);
  });

  it("asks nothing while the session is still resolving (D16)", () => {
    authState.status = "loading";

    const { result } = renderHook(() => useUnreadCount(), { wrapper: wrapper() });

    expect(countUnread).not.toHaveBeenCalled();
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("keys the counter by tenant and by user", async () => {
    countUnread.mockResolvedValue(1);

    renderHook(() => useUnreadCount(), { wrapper: wrapper() });
    await waitFor(() => expect(countUnread).toHaveBeenCalled());

    expect(useQuerySpy.mock.calls[0][0].queryKey).toEqual([
      "tenant",
      "t1",
      "notifications-unread",
      "u1",
    ]);
  });
});

describe("useNotifications (R4.5, design D11)", () => {
  it("does NOT poll — a list that reloads under the reader's finger is a defect", async () => {
    listNotifications.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      perPage: 20,
      totalPages: 0,
    });

    const { result } = renderHook(() => useNotifications({ page: 2 }), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const options = useQuerySpy.mock.calls[0][0];
    expect(options.refetchInterval).toBeUndefined();
    expect(options.refetchIntervalInBackground).toBeUndefined();
    expect(options.retry).toBe(retryPolicy);
  });

  it("passes the filters through to the source and into the key", async () => {
    listNotifications.mockResolvedValue({
      items: [],
      total: 0,
      page: 2,
      perPage: 5,
      totalPages: 0,
    });

    renderHook(() => useNotifications({ page: 2, perPage: 5, unread: true }), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(listNotifications).toHaveBeenCalled());

    expect(listNotifications).toHaveBeenCalledWith("t1", {
      page: 2,
      perPage: 5,
      unread: true,
    });
    expect(useQuerySpy.mock.calls[0][0].queryKey).toEqual([
      "tenant",
      "t1",
      "notifications-list",
      "u1",
      { page: 2, perPage: 5, unread: true },
    ]);
  });
});
