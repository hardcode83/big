import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import * as dataModule from "../../data";

const useAuth = vi.hoisted(() =>
  vi.fn(() => ({
    user: { tenant_id: "tenant-from-session", role: "TENANT_OWNER" },
  })),
);
vi.mock("@/lib/auth", () => ({
  useAuth,
  useHasPermission: (permission: string) => {
    const { user } = useAuth();
    if (!user) return false;
    if (permission === "MANAGE_CONVERSATIONS") {
      return user.role === "TENANT_OWNER" || user.role === "PROPERTY_MANAGER";
    }
    return false;
  },
}));

vi.mock("@/lib/api/retry-policy", () => ({
  retryPolicy: () => false,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

const getMock = vi.fn();
const listMessagesMock = vi.fn();
const replyMock = vi.fn();
vi.spyOn(dataModule, "getConversationsDataSource").mockImplementation(
  () =>
    ({
      getConversation: getMock,
      listMessages: listMessagesMock,
      replyToConversation: replyMock,
    }) as unknown as ReturnType<typeof dataModule.getConversationsDataSource>,
);

import { fireEvent } from "@testing-library/react";
import { ConversationThreadView } from "./conversation-thread-view";

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const CONVERSATION = {
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

const MESSAGES = {
  items: [],
  total: 0,
  page: 1,
  perPage: 20,
};

const MESSAGES_WITH_PAGES = {
  items: [
    {
      id: "m1",
      conversationId: "c1",
      senderType: "GUEST" as const,
      senderUserId: null,
      content: "Hola",
      language: "es",
      aiGenerated: false,
      confidenceScore: null,
      intent: null,
      createdAt: "2026-08-22T10:00:00Z",
    },
  ],
  total: 45, // > perPage (20) → pagination controls must render
  page: 1,
  perPage: 20,
};

describe("ConversationThreadView (R3)", () => {
  beforeEach(() => {
    useAuth.mockReset();
    useAuth.mockImplementation(() => ({
      user: { tenant_id: "tenant-from-session", role: "TENANT_OWNER" },
    }));
    getMock.mockReset();
    listMessagesMock.mockReset();
    replyMock.mockReset();
    getMock.mockResolvedValue(CONVERSATION);
    listMessagesMock.mockResolvedValue(MESSAGES);
    replyMock.mockResolvedValue({
      id: "m1",
      conversationId: "c1",
      senderType: "MANAGER" as const,
      senderUserId: "u1",
      content: "Hola",
      language: "es",
      aiGenerated: false,
      confidenceScore: null,
      intent: null,
      createdAt: "2026-08-22T10:00:00Z",
    });
  });

  it("renders the localized 'not found' state when the conversation is unknown or another tenant's", async () => {
    getMock.mockRejectedValueOnce(
      new ApiError({ status: 404, code: "not_found", message: "x" }),
    );
    const view = render(<ConversationThreadView conversationId="c1" />, { wrapper });
    await waitFor(() => expect(view.getByText("fields.notFound")).toBeTruthy());
  });

  it("renders the generic error state with a retry button on 5xx (R3.7)", async () => {
    getMock.mockRejectedValueOnce(new Error("boom"));
    const view = render(<ConversationThreadView conversationId="c1" />, { wrapper });
    await waitFor(() => expect(view.getByText("states:error.title")).toBeTruthy());
    expect(view.getByText("states:error.retry")).toBeTruthy();
  });

  it("a 403 on the messages sub-query shows the localized 'forbidden' copy (R3.7)", async () => {
    // The conversation header resolves successfully, but the messages
    // list is forbidden — e.g. the policy was tightened between the two
    // requests and the user lost read access. The view shows the
    // distinct localized 403 copy on the messages pane rather than the
    // generic error.
    getMock.mockResolvedValue(CONVERSATION);
    listMessagesMock.mockRejectedValueOnce(
      new ApiError({ status: 403, code: "FORBIDDEN", message: "nope" }),
    );
    const view = render(<ConversationThreadView conversationId="c1" />, { wrapper });
    await waitFor(() => expect(view.getByText("channel.WHATSAPP")).toBeTruthy());
    expect(view.getByText("fields.forbidden")).toBeTruthy();
  });

  it("a 403 on the conversation itself maps to the generic error state (R3.7)", async () => {
    // A user from another tenant hitting `/conversations/[id]` for a
    // foreign conversation gets the same 403 — by design, the UI does
    // not filter existence — and the view shows the generic error
    // state, NOT the distinct 'forbidden' copy (that copy is reserved
    // for the messages sub-query).
    getMock.mockRejectedValueOnce(
      new ApiError({ status: 403, code: "FORBIDDEN", message: "nope" }),
    );
    const view = render(<ConversationThreadView conversationId="c1" />, { wrapper });
    await waitFor(() => expect(view.getByText("states:error.title")).toBeTruthy());
    expect(view.getByText("states:error.retry")).toBeTruthy();
    // Distinct forbidden copy does NOT appear here.
    expect(view.queryByText("fields.forbidden")).toBeNull();
  });

  it("renders the loading state initially and the conversation header once the data resolves", async () => {
    const view = render(<ConversationThreadView conversationId="c1" />, { wrapper });
    await waitFor(() => expect(view.getByText("thread.title", { exact: false })).toBeTruthy());
    expect(view.getByText("channel.WHATSAPP")).toBeTruthy();
    expect(view.getByText("escalationStatus.PENDING_HUMAN")).toBeTruthy();
  });

  it("renders the empty messages state when the thread has no items yet", async () => {
    const view = render(<ConversationThreadView conversationId="c1" />, { wrapper });
    await waitFor(() => expect(view.getByText("thread.noMessages")).toBeTruthy());
  });

  it("renders the 'back to inbox' link in the header (R1.4 — deep-linkable thread)", async () => {
    const view = render(<ConversationThreadView conversationId="c1" />, { wrapper });
    await waitFor(() => expect(view.getByText("fields.backToList")).toBeTruthy());
    const link = view.getByRole("link", { name: "fields.backToList" });
    expect(link.getAttribute("href")).toBe("/conversations");
  });

  it("does NOT render pagination controls when the messages fit in a single page (R3.3)", async () => {
    listMessagesMock.mockResolvedValue(MESSAGES); // total: 0 — no pagination
    const view = render(<ConversationThreadView conversationId="c1" />, { wrapper });
    await waitFor(() => expect(view.getByText("thread.noMessages")).toBeTruthy());
    expect(view.queryByRole("button", { name: "fields.prevPage" })).toBeNull();
    expect(view.queryByRole("button", { name: "fields.nextPage" })).toBeNull();
  });

  it("renders prev/next pagination controls when total > perPage (R3.3)", async () => {
    listMessagesMock.mockResolvedValue(MESSAGES_WITH_PAGES);
    const view = render(<ConversationThreadView conversationId="c1" />, { wrapper });
    // The first message has content "Hola" — wait for that to render
    // (proves the messages branch was taken, not the empty branch).
    await waitFor(() => expect(view.getByText("Hola")).toBeTruthy());
    const prev = view.getByRole("button", { name: "fields.prevPage" });
    const next = view.getByRole("button", { name: "fields.nextPage" });
    expect(prev).toBeTruthy();
    expect(next).toBeTruthy();
    // First page: prev disabled, next enabled.
    expect(prev.hasAttribute("disabled")).toBe(true);
    expect(next.hasAttribute("disabled")).toBe(false);
  });

  it("clicking 'next' fetches the next page (R3.3)", async () => {
    listMessagesMock.mockResolvedValue(MESSAGES_WITH_PAGES);
    const view = render(<ConversationThreadView conversationId="c1" />, { wrapper });
    await waitFor(() => expect(view.getByText("Hola")).toBeTruthy());
    const callsBefore = listMessagesMock.mock.calls.length;
    const next = view.getByRole("button", { name: "fields.nextPage" });
    next.click();
    await waitFor(() =>
      expect(listMessagesMock.mock.calls.length).toBeGreaterThan(callsBefore),
    );
    const lastCallArgs = listMessagesMock.mock.calls.at(-1)!;
    expect(lastCallArgs[0]).toBe("tenant-from-session");
    expect(lastCallArgs[1]).toBe("c1");
    expect(lastCallArgs[2]).toBe(2);
  });

  it("does NOT render the reply form when the user lacks MANAGE_CONVERSATIONS (R6.4 / reg perm)", async () => {
    // Re-mock `useAuth` for this test only: a CLEANER has no
    // MANAGE_CONVERSATIONS (messaging-ai R7) so the form must not
    // appear — the operator would otherwise always 403 on submit.
    // Use `mockReturnValue` (not `mockReturnValueOnce`) because the
    // view re-renders after the queries resolve and a second call
    // would otherwise fall back to TENANT_OWNER from the implementation
    // in the mock factory.
    useAuth.mockReturnValue({
      user: { tenant_id: "tenant-from-session", role: "CLEANER" },
    });
    const view = render(<ConversationThreadView conversationId="c1" />, { wrapper });
    await waitFor(() => expect(view.getByText("channel.WHATSAPP")).toBeTruthy());
    // Reply form is not rendered.
    expect(view.container.querySelector("#reply-content")).toBeNull();
    // Localized forbidden copy is shown instead.
    expect(view.getByText("fields.forbidden")).toBeTruthy();
  });
});

describe("ConversationThreadView — PENDING_HUMAN badge updates after reply (R6.7)", () => {
  beforeEach(() => {
    useAuth.mockReset();
    useAuth.mockImplementation(() => ({
      user: { tenant_id: "tenant-from-session", role: "TENANT_OWNER" },
    }));
    replyMock.mockReset();
    listMessagesMock.mockReset();
    getMock.mockReset();
    listMessagesMock.mockResolvedValue(MESSAGES);
    replyMock.mockResolvedValue({
      id: "m1",
      conversationId: "c1",
      senderType: "MANAGER" as const,
      senderUserId: "u1",
      content: "Ya te respondo",
      language: "es",
      aiGenerated: false,
      confidenceScore: null,
      intent: null,
      createdAt: "2026-08-22T10:01:00Z",
    });
  });

  it("the escalation badge flips from PENDING_HUMAN to HUMAN_HANDLING after a successful reply", async () => {
    // Two-phase mock: first call returns PENDING_HUMAN, the refetch
    // after the reply mutation invalidates the detail query returns
    // HUMAN_HANDLING. The badge in the header must reflect the second
    // value without a manual reload (R3.8 / D9 — invalidation in
    // onSettled).
    const initial = { ...CONVERSATION, escalationStatus: "PENDING_HUMAN" as const };
    const after = { ...CONVERSATION, escalationStatus: "HUMAN_HANDLING" as const };
    getMock.mockImplementation(async () =>
      getMock.mock.calls.length === 1 ? initial : after,
    );

    const view = render(<ConversationThreadView conversationId="c1" />, { wrapper });
    await waitFor(() => expect(view.getByText("escalationStatus.PENDING_HUMAN")).toBeTruthy());

    const textarea = view.container.querySelector("#reply-content") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Ya te respondo" } });
    fireEvent.submit(view.getByRole("button", { name: "thread.replySubmit" }).closest("form")!);

    await waitFor(() =>
      expect(view.getByText("escalationStatus.HUMAN_HANDLING")).toBeTruthy(),
    );
    // The stale badge text is gone from the DOM.
    expect(view.queryByText("escalationStatus.PENDING_HUMAN")).toBeNull();
  });
});