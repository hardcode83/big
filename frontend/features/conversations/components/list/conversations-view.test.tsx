import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
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
    t: (key: string) => key,
  }),
}));

const listMock = vi.fn();
vi.spyOn(dataModule, "getConversationsDataSource").mockImplementation(
  () =>
    ({
      listConversations: listMock,
    }) as unknown as ReturnType<typeof dataModule.getConversationsDataSource>,
);

import { ConversationsView } from "./conversations-view";

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const PAGE_WITH_ROWS = {
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

const EMPTY_PAGE = { items: [], total: 0, page: 1, perPage: 20 };

describe("ConversationsView (R2)", () => {
  beforeEach(() => {
    listMock.mockReset();
  });

  it("renders the localized empty state when the list comes back with no items", async () => {
    listMock.mockResolvedValue(EMPTY_PAGE);
    const view = render(<ConversationsView />, { wrapper });
    await waitFor(() => expect(view.getByText("states:empty.title")).toBeTruthy());
    expect(view.getByText("states:empty.description")).toBeTruthy();
  });

  it("renders the table rows when items are present and links to the thread", async () => {
    listMock.mockResolvedValue(PAGE_WITH_ROWS);
    const view = render(<ConversationsView />, { wrapper });
    await waitFor(() => expect(view.getAllByRole("link").length).toBeGreaterThan(0));
    const link = view.getByRole("link", { name: "conversations:channel.WHATSAPP" });
    expect(link.getAttribute("href")).toBe("/conversations/c1");
  });

  it("renders the localized error state with a retry button when the source rejects", async () => {
    listMock.mockRejectedValue(new Error("boom"));
    const view = render(<ConversationsView />, { wrapper });
    await waitFor(() => expect(view.getByText("states:error.title")).toBeTruthy());
    expect(view.getByText("states:error.description")).toBeTruthy();
    const retry = view.getByText("states:error.retry");
    retry.click();
    expect(listMock).toHaveBeenCalledTimes(2);
  });
});