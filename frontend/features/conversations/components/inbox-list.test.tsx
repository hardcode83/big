import { fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import type { ConversationPage, ConversationSummary } from "../data/dto";
import { useInboxFiltersStore } from "../state/use-inbox-filters-store";
import { InboxList } from "./inbox-list";

const useConversationList = vi.hoisted(() => vi.fn());
const usePropertyLabels = vi.hoisted(() => vi.fn());
vi.mock("../hooks/use-conversations", () => ({
  useConversationList,
  usePropertyLabels,
}));

function conversation(
  id: string,
  overrides: Partial<ConversationSummary> = {},
): ConversationSummary {
  return {
    id,
    propertyId: "property-1",
    guestId: null,
    reservationId: null,
    channel: "WHATSAPP",
    status: "OPEN",
    escalationStatus: "NONE",
    language: "es",
    aiEnabled: true,
    lastMessageAt: null,
    createdAt: "2026-08-10T09:00:00Z",
    updatedAt: "2026-08-10T09:00:00Z",
    ...overrides,
  };
}

function page(
  items: ConversationSummary[],
  overrides: Partial<ConversationPage<ConversationSummary>> = {},
): ConversationPage<ConversationSummary> {
  return {
    items,
    page: 1,
    perPage: 20,
    total: items.length,
    totalPages: 1,
    ...overrides,
  };
}

function renderList(selectedId: string | null = null) {
  const onSelect = vi.fn();
  render(
    <I18nProvider locale="es">
      <InboxList selectedId={selectedId} onSelect={onSelect} />
    </I18nProvider>,
  );
  return { onSelect };
}

beforeEach(() => {
  useConversationList.mockReset();
  usePropertyLabels.mockReset();
  usePropertyLabels.mockReturnValue({
    data: page([]) as unknown,
  });
  useInboxFiltersStore.getState().reset();
});

describe("InboxList — order and rows (task 5.2, R1.1)", () => {
  it("renders one row per conversation in the order the backend returned them", () => {
    usePropertyLabels.mockReturnValue({
      data: {
        items: [
          { id: "property-1", internalCode: "REDES11", name: "Redes 11" },
          { id: "property-2", internalCode: "PAJARITOS8", name: "Pajaritos 8" },
        ],
        page: 1,
        perPage: 100,
        total: 2,
        totalPages: 1,
      },
    });
    useConversationList.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([
        conversation("c1"),
        conversation("c2", { propertyId: "property-2" }),
        conversation("c3"),
      ]),
    });

    renderList();

    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("REDES11");
    expect(rows[1]).toHaveTextContent("PAJARITOS8");
    expect(rows[2]).toHaveTextContent("REDES11");
  });

  it("does not reorder by state, however loud the state is", () => {
    useConversationList.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([
        conversation("c1", { status: "OPEN", escalationStatus: "NONE" }),
        conversation("c2", {
          status: "ESCALATED",
          escalationStatus: "PENDING_HUMAN",
        }),
      ]),
    });
    const { onSelect } = renderList();

    const rows = screen.getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Abierta");
    expect(rows[1]).toHaveTextContent("Escalada");

    fireEvent.click(rows[1].querySelector("button")!);
    expect(onSelect).toHaveBeenCalledWith("c2");
  });
});

describe("InboxList — the three states (task 5.2, R1.4, R1.5)", () => {
  it("renders the shared loading state while pending", () => {
    useConversationList.mockReturnValue({ isPending: true, isError: false });
    renderList();

    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
  });

  it("renders a localized error with a retry that re-runs the query, and no raw detail", () => {
    const refetch = vi.fn();
    useConversationList.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({
        code: "SERVER_ERROR",
        message: "Request failed with status 500",
        status: 500,
      }),
      refetch,
    });
    renderList();

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("No se pudo cargar la bandeja");
    expect(alert).not.toHaveTextContent("500");
    expect(alert).not.toHaveTextContent("Request failed");

    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("renders the empty state, distinct from error and from loading", () => {
    useConversationList.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([]),
    });
    renderList();

    expect(screen.getByText("Sin conversaciones")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("renders the no-access state without a retry button on a 403 (D17)", () => {
    const refetch = vi.fn();
    useConversationList.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "FORBIDDEN", message: "denied", status: 403 }),
      refetch,
    });
    renderList();

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Sin acceso a las conversaciones",
    );
    expect(screen.queryByRole("button", { name: "Reintentar" })).toBeNull();
    expect(refetch).not.toHaveBeenCalled();
  });
});

describe("InboxList — paging replaces, never accumulates (task 5.3, R1.6)", () => {
  it("offers no navigation for a single page", () => {
    useConversationList.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([conversation("c1")]),
    });
    renderList();
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("moves the store page and replaces the rendered items instead of concatenating", () => {
    useConversationList.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([conversation("c1"), conversation("c2")], {
        page: 1,
        total: 4,
        totalPages: 2,
      }),
    });
    const view = render(
      <I18nProvider locale="es">
        <InboxList selectedId={null} onSelect={vi.fn()} />
      </I18nProvider>,
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Página 1 de 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(useInboxFiltersStore.getState().page).toBe(2);

    // Re-render the SAME mounted instance, which is what a real page change does:
    // unmounting first would wipe any component-local accumulation and let an
    // appending implementation pass.
    useConversationList.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([conversation("c3"), conversation("c4")], {
        page: 2,
        total: 4,
        totalPages: 2,
      }),
    });
    view.rerender(
      <I18nProvider locale="es">
        <InboxList selectedId={null} onSelect={vi.fn()} />
      </I18nProvider>,
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Página 2 de 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
  });
});
