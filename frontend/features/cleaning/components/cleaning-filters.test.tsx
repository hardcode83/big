import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import type { PropertySummary } from "../data";
import { useCleaningFiltersStore } from "../state/use-cleaning-filters-store";
import { CleaningFilters } from "./cleaning-filters";

const usePropertyDirectory = vi.hoisted(() => vi.fn());
vi.mock("../hooks/use-cleaning-data", () => ({ usePropertyDirectory }));

const properties: PropertySummary[] = [
  { id: "property-1", name: "Redes 11", internalCode: "REDES11" },
  { id: "property-2", name: "Pajaritos 8", internalCode: "PAJARITOS8" },
];

function renderFilters(locale: "es" | "en" = "es") {
  return render(
    <I18nProvider locale={locale}>
      <CleaningFilters />
    </I18nProvider>,
  );
}

const propertySelect = () =>
  screen.getByRole("combobox", { name: "Vivienda" });
const statusSelect = () => screen.getByRole("combobox", { name: "Estado" });

beforeEach(() => {
  useCleaningFiltersStore.getState().reset();
  usePropertyDirectory.mockReset().mockReturnValue({
    data: properties,
    isPending: false,
  });
});

describe("CleaningFilters (R3.1, R3.2, R3.5, R5.1, R5.3)", () => {
  it("offers every property of the catalog by code and name", () => {
    renderFilters();
    expect(
      screen.getByRole("option", { name: "REDES11 · Redes 11" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "PAJARITOS8 · Pajaritos 8" }),
    ).toBeInTheDocument();
  });

  it("offers the nine statuses with translated labels, plus 'all'", () => {
    renderFilters();
    const options = Array.from(statusSelect().querySelectorAll("option"));
    expect(options).toHaveLength(10);
    expect(options[0].textContent).toBe("Todos los estados");
    expect(
      screen.getByRole("option", { name: "Pendiente de revisión" }),
    ).toBeInTheDocument();
  });

  it("writes the chosen property into the store (R3.1)", () => {
    renderFilters();
    fireEvent.change(propertySelect(), { target: { value: "property-2" } });
    expect(useCleaningFiltersStore.getState().propertyId).toBe("property-2");
  });

  it("writes the chosen status into the store (R3.2)", () => {
    renderFilters();
    fireEvent.change(statusSelect(), { target: { value: "COMPLETED" } });
    expect(useCleaningFiltersStore.getState().status).toBe("COMPLETED");
  });

  it("keeps both filters when each is chosen in turn (R3.3)", () => {
    renderFilters();
    fireEvent.change(propertySelect(), { target: { value: "property-1" } });
    fireEvent.change(statusSelect(), { target: { value: "CREATED" } });
    expect(useCleaningFiltersStore.getState()).toMatchObject({
      propertyId: "property-1",
      status: "CREATED",
    });
  });

  it("returns to page 1 whenever a filter changes (R3.4)", () => {
    renderFilters();
    useCleaningFiltersStore.getState().setPage(4);
    fireEvent.change(statusSelect(), { target: { value: "FAILED" } });
    expect(useCleaningFiltersStore.getState().page).toBe(1);
  });

  it("offers an explicit clear for each filter and only once it is set (R3.5)", () => {
    renderFilters();
    expect(
      screen.queryByRole("button", { name: "Quitar el filtro de vivienda" }),
    ).not.toBeInTheDocument();

    fireEvent.change(propertySelect(), { target: { value: "property-1" } });
    fireEvent.change(statusSelect(), { target: { value: "CREATED" } });

    fireEvent.click(
      screen.getByRole("button", { name: "Quitar el filtro de vivienda" }),
    );
    expect(useCleaningFiltersStore.getState()).toMatchObject({
      propertyId: undefined,
      status: "CREATED",
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Quitar el filtro de estado" }),
    );
    expect(useCleaningFiltersStore.getState().status).toBeUndefined();
  });

  it("clears a filter by choosing the 'all' option too", () => {
    renderFilters();
    fireEvent.change(propertySelect(), { target: { value: "property-1" } });
    fireEvent.change(propertySelect(), { target: { value: "" } });
    expect(useCleaningFiltersStore.getState().propertyId).toBeUndefined();
  });

  it("exposes both controls with an accessible label and reachable by keyboard (R5.3)", () => {
    renderFilters();
    for (const control of [propertySelect(), statusSelect()]) {
      expect(control).toBeEnabled();
      expect(control.tabIndex).toBeGreaterThanOrEqual(0);
      control.focus();
      expect(control).toHaveFocus();
    }
  });

  it("still renders with the catalog in flight, so filtering is never blocked", () => {
    usePropertyDirectory.mockReturnValue({ data: undefined, isPending: true });
    renderFilters();
    expect(propertySelect()).toBeInTheDocument();
    expect(statusSelect()).toBeInTheDocument();
  });

  it("still renders when the property catalog failed (design D5)", () => {
    usePropertyDirectory.mockReturnValue({ data: undefined, isPending: false });
    renderFilters();
    expect(
      Array.from(propertySelect().querySelectorAll("option")),
    ).toHaveLength(1);
    expect(statusSelect()).toBeInTheDocument();
  });

  it("renders the English catalog when the locale is en (R5.1)", () => {
    renderFilters("en");
    expect(
      screen.getByRole("combobox", { name: "Property" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "All statuses" }),
    ).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { container } = renderFilters();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
