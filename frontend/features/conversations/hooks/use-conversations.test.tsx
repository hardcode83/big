import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import type { ConversationsDataSource } from "../data/conversations-source";
import {
  INBOX_PAGE_SIZE,
  THREAD_PAGE_SIZE,
  useConversation,
  useConversationList,
  usePropertyLabels,
  useThread,
} from "./use-conversations";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

const source = vi.hoisted(() => ({
  listConversations: vi.fn(),
  getConversation: vi.fn(),
  listMessages: vi.fn(),
  createMessage: vi.fn(),
  escalate: vi.fn(),
  resolve: vi.fn(),
  listPropertyLabels: vi.fn(),
}));

vi.mock("../data", () => ({
  getConversationsDataSource: () => source as unknown as ConversationsDataSource,
}));

function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function page<T>(items: T[]) {
  return { items, page: 1, perPage: 20, total: items.length, totalPages: 1 };
}

beforeEach(() => {
  for (const fn of Object.values(source)) {
    fn.mockReset();
  }
});

describe("read hooks — loading and success (task 4.3, R1.1, R3.2, R3.5)", () => {
  it("starts pending and then resolves the list, asking for the inbox page size", async () => {
    source.listConversations.mockResolvedValue(page([{ id: "c1" }]));
    const { result } = renderHook(
      () => useConversationList({ status: "OPEN" }, 2),
      { wrapper: wrapper() },
    );

    expect(result.current.isPending).toBe(true);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(1);
    expect(source.listConversations).toHaveBeenCalledWith(
      "tenant-from-session",
      { status: "OPEN" },
      2,
      INBOX_PAGE_SIZE,
    );
  });

  it("reads one conversation with the tenant from the session", async () => {
    source.getConversation.mockResolvedValue({ id: "c1", status: "OPEN" });
    const { result } = renderHook(() => useConversation("c1"), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(source.getConversation).toHaveBeenCalledWith(
      "tenant-from-session",
      "c1",
    );
  });

  it("reads the thread page with the thread page size", async () => {
    source.listMessages.mockResolvedValue(page([]));
    const { result } = renderHook(() => useThread("c1", 3), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(source.listMessages).toHaveBeenCalledWith(
      "tenant-from-session",
      "c1",
      3,
      THREAD_PAGE_SIZE,
    );
  });

  it("asks for the property labels once and shares them across renders (R1.7)", async () => {
    source.listPropertyLabels.mockResolvedValue(page([{ id: "p1" }]));
    const Wrapper = wrapper();
    const { result } = renderHook(
      () => ({ a: usePropertyLabels(), b: usePropertyLabels() }),
      { wrapper: Wrapper },
    );

    await waitFor(() => expect(result.current.a.isSuccess).toBe(true));
    expect(result.current.b.isSuccess).toBe(true);
    expect(source.listPropertyLabels).toHaveBeenCalledTimes(1);
  });
});

describe("read hooks — no retry on 4xx (task 4.3, R1.4, R3.6)", () => {
  function clientWithSharedRetryPolicy() {
    const client = new QueryClient();
    return function Wrapper({ children }: { children: ReactNode }) {
      return (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      );
    };
  }

  it.each([403, 404])(
    "calls the source exactly once for a %i and surfaces the error",
    async (status) => {
      source.listConversations.mockRejectedValue(
        new ApiError({ code: "FORBIDDEN", message: "denied", status }),
      );
      const { result } = renderHook(() => useConversationList({}, 1), {
        wrapper: clientWithSharedRetryPolicy(),
      });

      await waitFor(() => expect(result.current.isError).toBe(true));
      expect(source.listConversations).toHaveBeenCalledTimes(1);
      expect((result.current.error as ApiError).status).toBe(status);
    },
  );

  it("surfaces a 404 on the thread without retrying either", async () => {
    source.getConversation.mockRejectedValue(
      new ApiError({ code: "NOT_FOUND", message: "gone", status: 404 }),
    );
    const { result } = renderHook(() => useConversation("missing"), {
      wrapper: clientWithSharedRetryPolicy(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(source.getConversation).toHaveBeenCalledTimes(1);
  });
});
