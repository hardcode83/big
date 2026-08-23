import { fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";

import type { PaginatedResponse, PropertyDashboardCard } from "../../data";
import { useTimelineFiltersStore } from "../../state/use-timeline-filters-store";
import { useTimelinePropertyStore } from "../../state/use-timeline-property-store";
import { TimelineView } from "./timeline-view";

const useDashboardCards = vi.hoisted(() => vi.fn());
const usePropertyTimeline = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-dashboard-data", () => ({
  useDashboardCards,
  usePropertyTimeline,
}));

const useAuth = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth", () => ({ useAuth }));

const TENANT = "tenant-1";

function card(
  propertyId: string,
  propertyCode: string,
): PropertyDashboardCard {
  return {
    propertyId,
    propertyCode,
    operationalState: "VACANT_READY",
    currentOrNextReservation: null,
    cleaningStatus: null,
    openIncidentsCount: 0,
    nextAction: null,
    lastEventLabel: null,
    lastEventAt: null,
  };
}

const CARDS = [card("redes11", "REDES11"), card("pajaritos8", "PAJARITOS8")];

function cardPage(
  cards: PropertyDashboardCard[],
): PaginatedResponse<PropertyDashboardCard> {
  return {
    data: cards,
    total: cards.length,
    page: 1,
    per_page: 20,
    total_pages: cards.length === 0 ? 0 : 1,
  };
}

function renderView() {
  return render(
    <I18nProvider locale="es">
      <TimelineView />
    </I18nProvider>,
  );
}

beforeEach(() => {
  useDashboardCards.mockReset();
  usePropertyTimeline.mockReset();
  useAuth.mockReturnValue({ user: { tenant_id: TENANT } });
  useTimelinePropertyStore.getState().clear();
  useTimelineFiltersStore.getState().reset();
  usePropertyTimeline.mockReturnValue({
    isPending: false,
    isError: false,
    data: { data: [], total: 0, page: 1, per_page: 20, total_pages: 0 },
  });
});

describe("TimelineView (R1)", () => {
  it("offers exactly the properties the cards hook returned, by propertyCode (R1.1)", () => {
    useDashboardCards.mockReturnValue({
      isPending: false,
      isError: false,
      data: cardPage(CARDS),
    });
    renderView();

    const options = Array.from(
      screen.getByLabelText<HTMLSelectElement>("Vivienda").options,
    );
    // Two properties plus the "choose one" placeholder.
    expect(options).toHaveLength(3);
    expect(options[0].value).toBe("");
    expect(options.slice(1).map((o) => o.textContent)).toEqual([
      "REDES11",
      "PAJARITOS8",
    ]);
    // The value is the id the API needs; the label is the code R1.1 names.
    expect(options.slice(1).map((o) => o.value)).toEqual([
      "redes11",
      "pajaritos8",
    ]);
  });

  it("shows the pick-a-property state and queries no timeline (R1.2)", () => {
    useDashboardCards.mockReturnValue({
      isPending: false,
      isError: false,
      data: cardPage(CARDS),
    });
    renderView();

    expect(screen.getByText("Elige una vivienda")).toBeInTheDocument();
    // Not a disabled hook — the timeline is not MOUNTED, so nothing can ask for
    // `GET /api/v1/timeline/{property_id}` (design D4).
    expect(usePropertyTimeline).not.toHaveBeenCalled();
  });

  it("mounts the timeline for the chosen property (R1.3)", () => {
    useDashboardCards.mockReturnValue({
      isPending: false,
      isError: false,
      data: cardPage(CARDS),
    });
    renderView();

    fireEvent.change(screen.getByLabelText("Vivienda"), {
      target: { value: "pajaritos8" },
    });

    expect(usePropertyTimeline).toHaveBeenCalledWith("pajaritos8", {
      page: 1,
      perPage: 20,
    });
    // One timeline, not a second list of its own.
    expect(screen.getAllByRole("region", { name: "Cronología" })).toHaveLength(1);
    expect(screen.queryByText("Elige una vivienda")).not.toBeInTheDocument();
  });

  it("treats a selection stored by another tenant as none (R1.4)", () => {
    useDashboardCards.mockReturnValue({
      isPending: false,
      isError: false,
      data: cardPage(CARDS),
    });
    // `logout` clears the session but not this store, so a pair left by the
    // previous tenant must not become this tenant's selection (design D3).
    useTimelinePropertyStore.getState().select("tenant-OTHER", "redes11");
    renderView();

    expect(screen.getByText("Elige una vivienda")).toBeInTheDocument();
    expect(usePropertyTimeline).not.toHaveBeenCalled();
    expect(
      screen.getByLabelText<HTMLSelectElement>("Vivienda").value,
    ).toBe("");
  });

  it("returns to the picker when the property is deselected", () => {
    useDashboardCards.mockReturnValue({
      isPending: false,
      isError: false,
      data: cardPage(CARDS),
    });
    renderView();

    fireEvent.change(screen.getByLabelText("Vivienda"), {
      target: { value: "redes11" },
    });
    expect(screen.queryByText("Elige una vivienda")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Vivienda"), {
      target: { value: "" },
    });
    expect(screen.getByText("Elige una vivienda")).toBeInTheDocument();
  });

  it("shows the shared loading state while the properties are pending (R1.6)", () => {
    useDashboardCards.mockReturnValue({ isPending: true, isError: false });
    renderView();

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(usePropertyTimeline).not.toHaveBeenCalled();
  });

  it("shows the shared error state with a working retry and no raw detail (R1.6)", () => {
    const refetch = vi.fn();
    useDashboardCards.mockReturnValue({
      isPending: false,
      isError: true,
      error: new Error("connect ECONNREFUSED 10.0.0.1:8000"),
      refetch,
    });
    renderView();

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("No se pudo cargar el panel")).toBeInTheDocument();
    // The raw failure never reaches the DOM.
    expect(screen.queryByText(/ECONNREFUSED/)).not.toBeInTheDocument();
    expect(screen.queryByText(/10\.0\.0\.1/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("keeps its heading from the route registry's navigation catalog", () => {
    useDashboardCards.mockReturnValue({
      isPending: false,
      isError: false,
      data: cardPage(CARDS),
    });
    renderView();

    expect(
      screen.getByRole("heading", { level: 1, name: "Cronología" }),
    ).toBeInTheDocument();
  });
});
