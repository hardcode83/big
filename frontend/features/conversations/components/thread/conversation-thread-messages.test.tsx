import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

import type { MessageDto } from "../../data";
import { ConversationThreadMessages } from "./conversation-thread-messages";

function message(overrides: Partial<MessageDto> = {}): MessageDto {
  return {
    id: overrides.id ?? "m1",
    conversationId: "c1",
    senderType: overrides.senderType ?? "GUEST",
    senderUserId: overrides.senderUserId ?? null,
    content: overrides.content ?? "Hola",
    language: "es",
    aiGenerated: false,
    confidenceScore: null,
    intent: overrides.intent ?? null,
    createdAt: overrides.createdAt ?? "2026-08-22T10:00:00Z",
  };
}

describe("ConversationThreadMessages (D7, D8)", () => {
  it("renders each message's content as plain text — never as HTML", () => {
    const view = render(
      <ConversationThreadMessages
        messages={[
          message({
            id: "m1",
            content: "<script>alert(1)</script>\nHola",
          }),
        ]}
      />,
    );
    const contentParagraph = view.container.querySelector("p.whitespace-pre-wrap");
    expect(contentParagraph).toBeTruthy();
    expect(contentParagraph?.textContent).toBe("<script>alert(1)</script>\nHola");
    // No <script> element should be rendered in the DOM.
    expect(view.container.querySelector("script")).toBeNull();
  });

  it("localises the role tag per sender_type", () => {
    const view = render(
      <ConversationThreadMessages
        messages={[
          message({ id: "m1", senderType: "GUEST" }),
          message({ id: "m2", senderType: "MANAGER" }),
          message({ id: "m3", senderType: "AI" }),
          message({ id: "m4", senderType: "SYSTEM" }),
        ]}
      />,
    );
    expect(view.getAllByText("senderType.GUEST")).toHaveLength(1);
    expect(view.getAllByText("senderType.MANAGER")).toHaveLength(1);
    expect(view.getAllByText("senderType.AI")).toHaveLength(1);
    expect(view.getAllByText("senderType.SYSTEM")).toHaveLength(1);
  });

  it("shows the intent only when sender_type is AI and intent is present", () => {
    const view = render(
      <ConversationThreadMessages
        messages={[
          message({ id: "m1", senderType: "AI", intent: "WIFI" }),
          message({ id: "m2", senderType: "GUEST", intent: "WIFI" }),
        ]}
      />,
    );
    // The first message (AI) shows the intent; the second (GUEST) does not.
    expect(view.getByText("WIFI")).toBeTruthy();
    // Only one intent label appears (only for the AI message) — the label
    // is split across text nodes, so we match with a partial matcher.
    expect(view.getAllByText("fields.intent", { exact: false })).toHaveLength(1);
  });

  it("shows the empty state when there are no messages", () => {
    const view = render(<ConversationThreadMessages messages={[]} />);
    expect(view.getByText("thread.noMessages")).toBeTruthy();
  });

  it("renders ConversationThreadSenderMeta for MANAGER messages with a non-null senderUserId (R3.5)", () => {
    const view = render(
      <ConversationThreadMessages
        messages={[
          message({
            id: "m1",
            senderType: "MANAGER",
            aiGenerated: false,
            senderUserId: "u1",
          }),
        ]}
      />,
    );
    // The section heading is split across the <strong> and ":" tail —
    // match the label without strict equality.
    expect(view.getByText("fields.senderUserIdSection", { exact: false })).toBeTruthy();
  });

  it("does NOT render the sender-meta section when senderUserId is null", () => {
    const view = render(
      <ConversationThreadMessages messages={[message({ id: "m1", senderUserId: null })]} />,
    );
    expect(view.queryByText("fields.senderUserIdSection")).toBeNull();
  });

  it("does NOT render the sender-meta section when sender_type is AI even if senderUserId is non-null (R3.5)", () => {
    const view = render(
      <ConversationThreadMessages
        messages={[
          message({
            id: "m1",
            senderType: "AI",
            aiGenerated: true,
            senderUserId: "system-1",
          }),
        ]}
      />,
    );
    expect(view.queryByText("fields.senderUserIdSection")).toBeNull();
  });

  it("does NOT render the sender-meta section when sender_type is GUEST even if senderUserId is non-null (R3.5)", () => {
    const view = render(
      <ConversationThreadMessages
        messages={[
          message({
            id: "m1",
            senderType: "GUEST",
            aiGenerated: false,
            senderUserId: "guest-1",
          }),
        ]}
      />,
    );
    expect(view.queryByText("fields.senderUserIdSection")).toBeNull();
  });

  it("renders the sender-meta section when sender_type is MANAGER and aiGenerated is false (R3.5)", () => {
    const view = render(
      <ConversationThreadMessages
        messages={[
          message({
            id: "m1",
            senderType: "MANAGER",
            aiGenerated: false,
            senderUserId: "u1",
          }),
        ]}
      />,
    );
    expect(view.getByText("fields.senderUserIdSection", { exact: false })).toBeTruthy();
  });
});