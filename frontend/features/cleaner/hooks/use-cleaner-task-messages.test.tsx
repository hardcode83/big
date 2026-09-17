import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import * as dataModule from "../data";
import { cleanerKeys } from "./query-keys";
import {
  useCleanerTaskMessages,
  useSendCleanerTaskMessage,
} from "./use-cleaner-task-messages";

const TENANT = "tenant-from-session";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: TENANT } }),
}));

const getTaskMessagesMock = vi.fn();
const sendTaskMessageMock = vi.fn();

vi.spyOn(dataModule, "getCleanerDataSource").mockImplementation(
  () =>
    ({
      getTaskMessages: getTaskMessagesMock,
      sendTaskMessage: sendTaskMessageMock,
    }) as unknown as ReturnType<typeof dataModule.getCleanerDataSource>,
);

const MESSAGE = {
  id: "message-1",
  authorId: "cleaner-1",
  authorRole: "CLEANER",
  content: "Ya he llegado",
  createdAt: "2026-08-20T10:00:00Z",
} as const;

const MESSAGE_PAGE = {
  data: [MESSAGE],
  total: 1,
  page: 1,
  perPage: 20,
  totalPages: 1,
};

function trackedClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidated: unknown[][] = [];
  vi.spyOn(client, "invalidateQueries").mockImplementation((filters) => {
    invalidated.push([...((filters?.queryKey ?? []) as unknown[])]);
    return Promise.resolve();
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { wrapper, invalidated };
}

describe("useCleanerTaskMessages (R1.1, D1, D4)", () => {
  beforeEach(() => {
    getTaskMessagesMock.mockReset();
    getTaskMessagesMock.mockResolvedValue(MESSAGE_PAGE);
  });

  it("does not fetch while enabled is false (the messages tab has not been opened yet)", async () => {
    const { wrapper } = trackedClient();
    const { result } = renderHook(
      () => useCleanerTaskMessages("task-1", 1, false),
      { wrapper },
    );

    expect(result.current.fetchStatus).toBe("idle");
    expect(getTaskMessagesMock).not.toHaveBeenCalled();
  });

  it("fetches page 1 once enabled, keyed by tenant/task/page", async () => {
    const { wrapper } = trackedClient();
    const { result } = renderHook(
      () => useCleanerTaskMessages("task-1", 1, true),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getTaskMessagesMock).toHaveBeenCalledWith(TENANT, "task-1", 1);
    expect(result.current.data).toEqual(MESSAGE_PAGE);
  });

  it("a later page uses its own query key (D4 — advancing page never replaces the earlier one)", async () => {
    const { wrapper } = trackedClient();
    const { result } = renderHook(
      () => useCleanerTaskMessages("task-1", 2, true),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getTaskMessagesMock).toHaveBeenCalledWith(TENANT, "task-1", 2);
  });
});

describe("useSendCleanerTaskMessage (R1.2, D5)", () => {
  beforeEach(() => {
    sendTaskMessageMock.mockReset();
    sendTaskMessageMock.mockResolvedValue(MESSAGE);
  });

  const MESSAGES_PREFIX = [
    ...cleanerKeys.messagesPrefix(TENANT, "task-1"),
  ];

  it("sends the content and invalidates every cached page on success", async () => {
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(() => useSendCleanerTaskMessage("task-1"), {
      wrapper,
    });

    result.current.mutate({ content: "Ya he llegado" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(sendTaskMessageMock).toHaveBeenCalledWith(
      TENANT,
      "task-1",
      "Ya he llegado",
    );
    expect(invalidated).toEqual([MESSAGES_PREFIX]);
  });

  it("also invalidates on failure — never leaves a stale cache behind (D5)", async () => {
    sendTaskMessageMock.mockRejectedValue(
      new ApiError({ status: 422, code: "VALIDATION_ERROR", message: "nope" }),
    );
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(() => useSendCleanerTaskMessage("task-1"), {
      wrapper,
    });

    result.current.mutate({ content: "" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(sendTaskMessageMock).toHaveBeenCalledTimes(1);
    expect(invalidated).toEqual([MESSAGES_PREFIX]);
  });

  it("never patches the cache optimistically — no setQueryData call (D5, Rejected)", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const setQueryDataSpy = vi.spyOn(client, "setQueryData");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useSendCleanerTaskMessage("task-1"), {
      wrapper,
    });

    result.current.mutate({ content: "Ya he llegado" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(setQueryDataSpy).not.toHaveBeenCalled();
  });
});
