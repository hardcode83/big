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
  // Mirrors the real component's contract: an errored query renders the
  // section with its localized error instead of collapsing to `null` (R5.3).
  BlockedTransitionsSection: ({
    stalls,
    hasError,
  }: {
    stalls: unknown[];
    hasError?: boolean;
  }) => {
    if (hasError) {
      return (
        <section>
          <p role="alert">stalls-error</p>
        </section>
      );
    }
    return stalls.length > 0 ? (
      <section>
        <h4>Stalls ({stalls.length})</h4>
      </section>
    ) : null;
  },
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


/**
 * R5.3. Before this, `dashboard-view` folded `isError` into the same empty
 * `Map()` it used for `isPending`, so a 5xx on `GET /blocked-transitions`
 * rendered a card identical to «this property has nothing blocked» — the
 * silent failure the whole change exists to end.
 */
describe("DashboardView — a failed stalls query is visible (R5.3)", () => {
  it("renders the stalls error inside each card without hiding the cards", async () => {
    useDashboardCards.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([sampleCard]),
    });
    useBlockedTransitions.mockReturnValue({
      isSuccess: false,
      isError: true,
      byPropertyId: new Map(),
    });

    renderView();

    // The card itself is still on screen — no global error state.
    expect(await screen.findByText("REDES11")).toBeTruthy();
    // And the stalls section carries the failure.
    expect(screen.getByRole("alert").textContent).toBe("stalls-error");
  });

  it("stays silent while the stalls query is merely pending", async () => {
    useDashboardCards.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([sampleCard]),
    });
    useBlockedTransitions.mockReturnValue({
      isSuccess: false,
      isError: false,
      byPropertyId: new Map(),
    });

    renderView();

    expect(await screen.findByText("REDES11")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("does not escalate a stalls failure to the page-level error state", async () => {
    useDashboardCards.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([sampleCard]),
    });
    useBlockedTransitions.mockReturnValue({
      isSuccess: false,
      isError: true,
      byPropertyId: new Map(),
    });

    renderView();

    // The cards-query error copy must not appear: only the stalls one.
    expect(await screen.findByText("REDES11")).toBeTruthy();
    expect(screen.queryByText(/No se pudo cargar el panel/)).toBeNull();
  });
});
