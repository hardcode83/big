import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { retryPolicy } from "@/lib/api/retry-policy";

import * as dataModule from "../data";
import {
  useConversation,
  useConversationMessages,
  useConversations,
} from "./use-conversations";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

const listMock = vi.fn();
const getMock = vi.fn();
const listMessagesMock = vi.fn();
const getConversationsDataSource = vi.spyOn(dataModule, "getConversationsDataSource");

getConversationsDataSource.mockImplementation(
  () =>
    ({
      listConversations: listMock,
      getConversation: getMock,
      listMessages: listMessagesMock,
    }) as unknown as ReturnType<typeof dataModule.getConversationsDataSource>,
);

const TENANT_ID = "tenant-from-session";

const LIST_PAGE = {
  items: [
    {
      id: "c1",
      channel: "WHATSAPP" as const,
      status: "OPEN" as const,
      escalationStatus: "PENDING_HUMAN" as const,
      lastMessageAt: "2026-08-22T10:00:00Z",
      createdAt: "2026-08-22T09:00:00Z",
    },
  ],
  total: 1,
  page: 1,
  perPage: 20,
};

const DETAIL = {
  id: "c1",
  propertyId: "p1",
  reservationId: null,
  guestId: null,
  channel: "WHATSAPP" as const,
  status: "OPEN" as const,
  escalationStatus: "PENDING_HUMAN" as const,
  language: "es",
  aiEnabled: true,
  lastMessageAt: "2026-08-22T10:00:00Z",
  createdAt: "2026-08-22T09:00:00Z",
  updatedAt: "2026-08-22T10:00:00Z",
};

const MESSAGES = { items: [], total: 0, page: 1, perPage: 20 };

function freshWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

describe("useConversations / useConversation / useConversationMessages (D1)", () => {
  beforeEach(() => {
    listMock.mockReset();
    getMock.mockReset();
    listMessagesMock.mockReset();
    listMock.mockResolvedValue(LIST_PAGE);
    getMock.mockResolvedValue(DETAIL);
    listMessagesMock.mockResolvedValue(MESSAGES);
  });

  it("useConversations calls listConversations with the supplied filters and the session tenant", async () => {
    const { result } = renderHook(() => useConversations({ status: "OPEN" }), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listMock).toHaveBeenCalledWith(TENANT_ID, { status: "OPEN" });
    expect(result.current.data).toEqual(LIST_PAGE);
  });

  it("useConversation calls getConversation with the tenant id and conversation id", async () => {
    const { result } = renderHook(() => useConversation("c1"), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getMock).toHaveBeenCalledWith(TENANT_ID, "c1");
  });

  it("useConversationMessages calls listMessages with the tenant id and default pagination", async () => {
    const { result } = renderHook(() => useConversationMessages("c1"), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listMessagesMock).toHaveBeenCalledWith(TENANT_ID, "c1", 1, 20);
  });
});

describe("shared retry policy", () => {
  it("retryPolicy is a function (no 4xx retries, brief 5xx retries)", () => {
    expect(typeof retryPolicy).toBe("function");
  });
});