import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as dataModule from "../data";
import { conversationsKeys } from "./query-keys";
import { useReplyToConversation } from "./use-reply-to-conversation";

// `vi.hoisted` so the mock factory can close over a mutable value: tests
// for the no-auth path reassign `mockUser.user = null` without re-mocking
// the module per test.
const { mockUser } = vi.hoisted(() => ({
  mockUser: { user: { tenant_id: "tenant-from-session" } } as {
    user: { tenant_id: string } | null;
  },
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => mockUser,
}));

const replyMock = vi.fn();
const getConversationsDataSource = vi.spyOn(dataModule, "getConversationsDataSource");

getConversationsDataSource.mockImplementation(
  () =>
    ({
      replyToConversation: replyMock,
    }) as unknown as ReturnType<typeof dataModule.getConversationsDataSource>,
);

const TENANT_ID = "tenant-from-session";
const CONVERSATION_ID = "c1";

const MESSAGE_RETURNED = {
  id: "m1",
  conversationId: CONVERSATION_ID,
  senderType: "MANAGER" as const,
  senderUserId: "u1",
  content: "Hola",
  language: "es",
  aiGenerated: false,
  confidenceScore: null,
  intent: null,
  createdAt: "2026-08-22T10:00:00Z",
};

function freshWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

describe("useReplyToConversation (D9)", () => {
  beforeEach(() => {
    replyMock.mockReset();
    replyMock.mockResolvedValue(MESSAGE_RETURNED);
  });

  it("calls replyToConversation with the tenant id, conversation id, and content only", async () => {
    const { result } = renderHook(() => useReplyToConversation(CONVERSATION_ID), {
      wrapper: freshWrapper(),
    });

    result.current.mutate({ content: "Hola" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(replyMock).toHaveBeenCalledTimes(1);
    expect(replyMock).toHaveBeenCalledWith(TENANT_ID, CONVERSATION_ID, { content: "Hola" });
  });

  it("never sends sender_type from the UI (D9)", async () => {
    const { result } = renderHook(() => useReplyToConversation(CONVERSATION_ID), {
      wrapper: freshWrapper(),
    });

    result.current.mutate({ content: "Hola" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const input = replyMock.mock.calls[0][2];
    expect(input).not.toHaveProperty("sender_type");
    expect(input).not.toHaveProperty("senderType");
    expect(Object.keys(input)).toEqual(["content"]);
  });

  it("uses retry: false (rejected writes are not retried)", async () => {
    const { result } = renderHook(() => useReplyToConversation(CONVERSATION_ID), {
      wrapper: freshWrapper(),
    });

    result.current.mutate({ content: "Hola" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.failureCount).toBe(0);
  });

  it("onSettled invalidates the three tenant-scoped conversation keys", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useReplyToConversation(CONVERSATION_ID), { wrapper });

    result.current.mutate({ content: "Hola" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const calledWith = invalidateSpy.mock.calls.map((c) => {
      const arg = c[0] as { queryKey?: unknown };
      return arg?.queryKey;
    });
    expect(calledWith).toContainEqual(conversationsKeys.listPrefix(TENANT_ID));
    expect(calledWith).toContainEqual(
      conversationsKeys.detail(TENANT_ID, CONVERSATION_ID),
    );
    expect(calledWith).toContainEqual(
      conversationsKeys.messagesPrefix(TENANT_ID, CONVERSATION_ID),
    );
  });
});

describe("useReplyToConversation — no auth (R6.1, security.md rule 1)", () => {
  beforeEach(() => {
    replyMock.mockReset();
  });

  it("the mutation throws when there is no authenticated user", async () => {
    mockUser.user = null;
    const { result } = renderHook(() => useReplyToConversation(CONVERSATION_ID), {
      wrapper: freshWrapper(),
    });
    result.current.mutate({ content: "Hola" });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toMatch(/tenant context/);
    expect(replyMock).not.toHaveBeenCalled();
  });

  it("onSettled is a no-op when there is no authenticated user (no cross-tenant invalidation)", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    mockUser.user = null;
    const { result } = renderHook(() => useReplyToConversation(CONVERSATION_ID), {
      wrapper,
    });
    result.current.mutate({ content: "Hola" });
    await waitFor(() => expect(result.current.isError).toBe(true));
    // The hook checks `if (!tenantId) return` before invalidating: a
    // missing-tenant mutation must NOT invalidate anyone else's cache.
    expect(invalidateSpy).not.toHaveBeenCalled();
  });
});