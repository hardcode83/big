import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as dataModule from "../../data";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

vi.mock("@/lib/api/retry-policy", () => ({
  retryPolicy: () => false,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { count?: number }) =>
      options?.count !== undefined ? `${key}:${options.count}` : key,
  }),
}));

const replyMock = vi.fn();
vi.spyOn(dataModule, "getConversationsDataSource").mockImplementation(
  () =>
    ({
      replyToConversation: replyMock,
    }) as unknown as ReturnType<typeof dataModule.getConversationsDataSource>,
);

import { ConversationReplyForm } from "./conversation-reply-form";

const CONVERSATION_ID = "c1";

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("ConversationReplyForm (R4, D9)", () => {
  beforeEach(() => {
    replyMock.mockReset();
  });

  it("renders the character counter reflecting the draft length", () => {
    const view = render(<ConversationReplyForm conversationId={CONVERSATION_ID} />, {
      wrapper,
    });
    const textarea = view.container.querySelector("#reply-content") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Hola" } });
    expect(view.getByText("fields.characterCount:4")).toBeTruthy();
  });

  it("does NOT disable the button when the draft approaches 4000 chars (only while in flight)", () => {
    replyMock.mockResolvedValue({
      id: "m1",
      conversationId: CONVERSATION_ID,
      senderType: "MANAGER",
      senderUserId: "u1",
      content: "x",
      language: "es",
      aiGenerated: false,
      confidenceScore: null,
      intent: null,
      createdAt: "2026-08-22T10:00:00Z",
    });
    const view = render(<ConversationReplyForm conversationId={CONVERSATION_ID} />, {
      wrapper,
    });
    const textarea = view.container.querySelector("#reply-content") as HTMLTextAreaElement;
    fireEvent.change(textarea, {
      target: { value: "a".repeat(3999) },
    });
    const button = view.getByRole("button", { name: "thread.replySubmit" });
    expect(button.hasAttribute("disabled")).toBe(false);
  });

  it("clears the draft on successful submission", async () => {
    replyMock.mockResolvedValue({
      id: "m1",
      conversationId: CONVERSATION_ID,
      senderType: "MANAGER",
      senderUserId: "u1",
      content: "Hola",
      language: "es",
      aiGenerated: false,
      confidenceScore: null,
      intent: null,
      createdAt: "2026-08-22T10:00:00Z",
    });
    const view = render(<ConversationReplyForm conversationId={CONVERSATION_ID} />, {
      wrapper,
    });
    const textarea = view.container.querySelector("#reply-content") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Hola" } });
    fireEvent.submit(view.getByRole("button", { name: "thread.replySubmit" }).closest("form")!);
    await waitFor(() =>
      expect(
        (view.container.querySelector("#reply-content") as HTMLTextAreaElement).value,
      ).toBe(""),
    );
  });

  it("preserves the draft on error", async () => {
    replyMock.mockRejectedValueOnce(new Error("boom"));
    const view = render(<ConversationReplyForm conversationId={CONVERSATION_ID} />, {
      wrapper,
    });
    const textarea = view.container.querySelector("#reply-content") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Hola" } });
    fireEvent.submit(view.getByRole("button", { name: "thread.replySubmit" }).closest("form")!);
    await waitFor(() => expect(view.getByRole("alert")).toBeTruthy());
    expect(
      (view.container.querySelector("#reply-content") as HTMLTextAreaElement).value,
    ).toBe("Hola");
  });
});