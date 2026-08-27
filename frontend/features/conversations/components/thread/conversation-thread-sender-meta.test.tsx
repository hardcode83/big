import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

import { ConversationThreadSenderMeta } from "./conversation-thread-sender-meta";

describe("ConversationThreadSenderMeta (D8)", () => {
  it("renders the section with the UUID and the localized note when senderUserId is present", () => {
    const view = render(
      <ConversationThreadSenderMeta senderUserId="00000000-0000-0000-0000-000000000001" />,
    );
    expect(view.getByText("fields.senderUserIdSection", { exact: false })).toBeTruthy();
    expect(view.getByText("00000000-0000-0000-0000-000000000001")).toBeTruthy();
    expect(view.getByText("fields.senderUserIdNote")).toBeTruthy();
  });

  it("renders the note exactly once (no duplication)", () => {
    const view = render(
      <ConversationThreadSenderMeta senderUserId="00000000-0000-0000-0000-000000000001" />,
    );
    expect(view.getAllByText("fields.senderUserIdNote")).toHaveLength(1);
  });

  it("renders nothing when senderUserId is null (e.g. SYSTEM or AI messages)", () => {
    const { container } = render(<ConversationThreadSenderMeta senderUserId={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("does NOT render a copy-to-clipboard affordance for the UUID", () => {
    const view = render(
      <ConversationThreadSenderMeta senderUserId="00000000-0000-0000-0000-000000000001" />,
    );
    expect(view.queryByRole("button", { name: /copy/i })).toBeNull();
  });
});