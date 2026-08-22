import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import esDashboard from "@/locales/es/dashboard.json";
import esProperties from "@/locales/es/properties.json";
import { fireEvent, render, screen } from "@/test/render";

import type { PropertyFilters } from "../../data";
import { PropertiesFilters } from "./properties-filters";

function renderFilters(value: PropertyFilters = {}) {
  const onChange = vi.fn();
  render(
    <I18nProvider locale="es">
      <PropertiesFilters value={value} onChange={onChange} />
    </I18nProvider>,
  );
  return { onChange };
}

const statusSelect = () => screen.getByLabelText(esProperties.filters.status);
const stateSelect = () =>
  screen.getByLabelText(esProperties.filters.operationalState);

describe("PropertiesFilters — the two filters the contract accepts (R2.1)", () => {
  it("offers the two status values plus an 'all' option", () => {
    renderFilters();
    const options = Array.from(statusSelect().querySelectorAll("option")).map(
      (option) => option.textContent,
    );
    expect(options).toEqual([
      esProperties.filters.all,
      esProperties.status.ACTIVE,
      esProperties.status.INACTIVE,
    ]);
  });

  it("offers the eleven operational states plus an 'all' option, labelled from the dashboard namespace", () => {
    renderFilters();
    const options = Array.from(stateSelect().querySelectorAll("option")).map(
      (option) => option.textContent,
    );
    expect(options).toHaveLength(12);
    expect(options[0]).toBe(esProperties.filters.allStates);
    // D10: the eleven labels come from `dashboard`, not from a second catalog.
    const dashboardStates = esDashboard.state as Record<string, string>;
    expect(options.slice(1)).toEqual([
      dashboardStates.VACANT_READY,
      dashboardStates.READY_FOR_NEXT_GUEST,
      dashboardStates.AWAITING_CHECKIN,
      dashboardStates.OCCUPIED_ESTIMATED,
      dashboardStates.CLEANING_IN_PROGRESS,
      dashboardStates.AWAITING_CLEANING,
      dashboardStates.CLEANING_SCHEDULED,
      dashboardStates.MAINTENANCE_REQUIRED,
      dashboardStates.CRITICAL_INCIDENT,
      dashboardStates.BLOCKED_BY_OWNER,
      dashboardStates.OUT_OF_SERVICE,
    ]);
  });

  it("has no control for text search, ordering or city (R2.4)", () => {
    renderFilters();
    // Only the two selects the endpoint admits, and no free-text input at all.
    expect(screen.getAllByRole("combobox")).toHaveLength(2);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
  });
});

describe("PropertiesFilters — what it emits (R2.2, R2.3)", () => {
  it("resets to page 1 on any change, even from a later page", () => {
    const { onChange } = renderFilters({ page: 7 });

    fireEvent.change(statusSelect(), { target: { value: "INACTIVE" } });

    expect(onChange).toHaveBeenCalledWith({ page: 1, status: "INACTIVE" });
  });

  it("emits the absence of the filter, not an empty string, when 'all' is picked", () => {
    const { onChange } = renderFilters({ status: "ACTIVE", page: 2 });

    fireEvent.change(statusSelect(), { target: { value: "" } });

    const emitted = onChange.mock.calls.at(-1)?.[0] as PropertyFilters;
    expect(emitted).not.toHaveProperty("status");
    expect(emitted.page).toBe(1);
  });

  it("preserves the other filter when one changes", () => {
    const { onChange } = renderFilters({
      currentOperationalState: "CRITICAL_INCIDENT",
    });

    fireEvent.change(statusSelect(), { target: { value: "ACTIVE" } });

    expect(onChange).toHaveBeenCalledWith({
      currentOperationalState: "CRITICAL_INCIDENT",
      page: 1,
      status: "ACTIVE",
    });
  });

  it("emits the keys in a fixed order so equivalent states hash alike (R2.3)", () => {
    const { onChange } = renderFilters({ status: "ACTIVE" });

    fireEvent.change(stateSelect(), { target: { value: "VACANT_READY" } });

    const emitted = onChange.mock.calls.at(-1)?.[0] as PropertyFilters;
    expect(Object.keys(emitted)).toEqual([
      "currentOperationalState",
      "page",
      "status",
    ]);
  });

  it("is controlled: it renders the value it is given and stores nothing", () => {
    renderFilters({ status: "INACTIVE", currentOperationalState: "OUT_OF_SERVICE" });
    expect(statusSelect()).toHaveValue("INACTIVE");
    expect(stateSelect()).toHaveValue("OUT_OF_SERVICE");
  });
});
