import { fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";

import type { PaginatedResponse, PropertyDashboardCard } from "../data";
import { DashboardView } from "./dashboard-view";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const useDashboardCards = vi.hoisted(() => vi.fn());
const useBlockedTransitions = vi.hoisted(() => vi.fn());
vi.mock("../hooks/use-dashboard-data", () => ({ useDashboardCards }));
vi.mock("@/features/dashboard/stalls", () => ({
  useBlockedTransitions,
  BlockedTransitionsSection: ({ stalls }: { stalls: unknown[] }) =>
    stalls.length > 0 ? (
      <section>
        <h4>Stalls ({stalls.length})</h4>
      </section>
    ) : null,
}));

function page(
  cards: PropertyDashboardCard[],
): PaginatedResponse<PropertyDashboardCard> {
  return {
    data: cards,
    total: cards.length,
    page: 1,
    per_page: cards.length,
    total_pages: cards.length === 0 ? 0 : 1,
  };
}

const sampleCard: PropertyDashboardCard = {
  propertyId: "redes11",
  propertyCode: "REDES11",
  operationalState: "VACANT_READY",
  currentOrNextReservation: null,
  cleaningStatus: null,
  openIncidentsCount: 0,
  nextAction: null,
  lastEventLabel: null,
  lastEventAt: null,
};

function renderView() {
  return render(
    <I18nProvider locale="es">
      <DashboardView />
    </I18nProvider>,
  );
}

beforeEach(() => {
  useDashboardCards.mockReset();
  useBlockedTransitions.mockReset();
  // Default: stalls query is pending — the cards render with no stalls.
  useBlockedTransitions.mockReturnValue({
    isPending: true,
    isError: false,
    byPropertyId: new Map(),
  });
});

describe("DashboardView (R1)", () => {
  it("shows the loading state while pending", () => {
    useDashboardCards.mockReturnValue({ isPending: true, isError: false });
    renderView();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows a localized error with a working retry", () => {
    const refetch = vi.fn();
    useDashboardCards.mockReturnValue({
      isPending: false,
      isError: true,
      refetch,
    });
    renderView();

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("No se pudo cargar el panel")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("shows the empty state when no properties are returned", () => {
    useDashboardCards.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([]),
    });
    renderView();
    expect(screen.getByText("Sin propiedades")).toBeInTheDocument();
  });

  it("renders a card grid on success", () => {
    useDashboardCards.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([
        sampleCard,
        {
          ...sampleCard,
          propertyId: "pajaritos8",
          propertyCode: "PAJARITOS8",
          operationalState: "CRITICAL_INCIDENT",
          openIncidentsCount: 1,
          nextAction: { label: "Revisar incidencia", responsible: "Manager" },
        },
      ]),
    });
    renderView();
    expect(screen.getByText("REDES11")).toBeInTheDocument();
    expect(screen.getByText("PAJARITOS8")).toBeInTheDocument();
    expect(screen.getByText("Libre y lista")).toBeInTheDocument();

    const cards = screen.getAllByRole("article");
    const grid = cards[0].parentElement;
    expect(grid).toHaveClass("items-stretch");
    expect(cards).toHaveLength(2);
    expect(cards.every((card) => card.classList.contains("h-full"))).toBe(true);
  });

  it("omits the stalls section when the stalls query is still pending (R1.4, blocked-transitions-web)", () => {
    useDashboardCards.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([sampleCard]),
    });
    useBlockedTransitions.mockReturnValue({
      isPending: true,
      isError: false,
      byPropertyId: new Map(),
    });
    renderView();
    expect(screen.getByText("REDES11")).toBeInTheDocument();
    // No stalls heading rendered.
    expect(screen.queryByText(/Stalls/)).toBeNull();
  });

  it("slices stalls by property id when the stalls query resolves", () => {
    const byPropertyId = new Map<string, Array<{ reservation_id: string }>>([
      ["pajaritos8", [{ reservation_id: "r-3" }]],
    ]);
    useDashboardCards.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([
        sampleCard,
        {
          ...sampleCard,
          propertyId: "pajaritos8",
          propertyCode: "PAJARITOS8",
        },
      ]),
    });
    useBlockedTransitions.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      byPropertyId,
    });
    renderView();
    expect(screen.getByText("Stalls (1)")).toBeInTheDocument();
  });
});
