import { beforeEach, describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import type { PropertySummary } from "../data";
import { usePricingUiStore } from "../state/use-pricing-ui-store";
import { RuleFilters } from "./rule-filters";

const PROPERTIES: PropertySummary[] = [
  { id: "p-1", name: "Ático Sol", internalCode: "MAD-01" },
];

function renderFilters() {
  return render(
    <I18nProvider locale="es">
      <RuleFilters properties={PROPERTIES} />
    </I18nProvider>,
  );
}

const store = () => usePricingUiStore.getState();

beforeEach(() => {
  store().reset();
});

describe("RuleFilters (R5.1)", () => {
  it("writes the property to the RULES slice, never the recommendations one", () => {
    // Design D11's silent bug: a property set here must not become the scope a
    // regeneration sweeps.
    renderFilters();
    fireEvent.change(screen.getByLabelText("Vivienda"), {
      target: { value: "p-1" },
    });
    expect(store().rules.propertyId).toBe("p-1");
    expect(store().recommendations.propertyId).toBeUndefined();
  });

  it("offers three states for `active`, not a checkbox", () => {
    // `active` is tri-state on the wire: true, false, or absent.
    renderFilters();
    const options = Array.from(
      screen.getByLabelText("Vigencia").querySelectorAll("option"),
    ).map((option) => option.textContent);
    expect(options).toEqual(["Todas las reglas", "Solo activas", "Solo inactivas"]);
  });

  it("writes active true and false as booleans", () => {
    renderFilters();
    const select = screen.getByLabelText("Vigencia");

    fireEvent.change(select, { target: { value: "true" } });
    expect(store().rules.active).toBe(true);

    fireEvent.change(select, { target: { value: "false" } });
    expect(store().rules.active).toBe(false);
  });

  it("treats the empty option as «no filter», not as false", () => {
    // The distinction the query depends on: absent omits the parameter, `false`
    // asks the backend for inactive rules only.
    renderFilters();
    const select = screen.getByLabelText("Vigencia");
    fireEvent.change(select, { target: { value: "false" } });
    fireEvent.change(select, { target: { value: "" } });
    expect(store().rules.active).toBeUndefined();
  });

  it("returns the rules list to page 1 on any filter change", () => {
    renderFilters();
    store().setRulePage(3);
    fireEvent.change(screen.getByLabelText("Vigencia"), {
      target: { value: "true" },
    });
    expect(store().rules.page).toBe(1);
    // And leaves the other tab's page alone.
    expect(store().recommendations.page).toBe(1);
  });

  it("has no accessibility violations", async () => {
    const { container } = renderFilters();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
