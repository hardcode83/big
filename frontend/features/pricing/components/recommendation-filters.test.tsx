import { beforeEach, describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import type { PropertySummary } from "../data";
import { usePricingUiStore } from "../state/use-pricing-ui-store";
import { RecommendationFilters } from "./recommendation-filters";

const PROPERTIES: PropertySummary[] = [
  { id: "p-1", name: "Ático Sol", internalCode: "MAD-01" },
  { id: "p-2", name: "Loft Latina", internalCode: "MAD-02" },
];

function renderFilters(properties: readonly PropertySummary[] = PROPERTIES) {
  return render(
    <I18nProvider locale="es">
      <RecommendationFilters properties={properties} />
    </I18nProvider>,
  );
}

const store = () => usePricingUiStore.getState();

beforeEach(() => {
  store().reset();
});

describe("RecommendationFilters — the four filters (R2.1)", () => {
  it("offers every property of the catalog by code and name", () => {
    renderFilters();
    const select = screen.getByLabelText("Vivienda");
    expect(select).toHaveTextContent("MAD-01 · Ático Sol");
    expect(select).toHaveTextContent("MAD-02 · Loft Latina");
    expect(select).toHaveTextContent("Todas las viviendas");
  });

  it("writes the chosen property to the recommendations slice", () => {
    renderFilters();
    fireEvent.change(screen.getByLabelText("Vivienda"), {
      target: { value: "p-2" },
    });
    expect(store().recommendations.propertyId).toBe("p-2");
    // Never the rules slice — that would silently change what a regeneration
    // sweeps (R4.1, design D11).
    expect(store().rules.propertyId).toBeUndefined();
  });

  it("clears the property filter back to «all»", () => {
    renderFilters();
    const select = screen.getByLabelText("Vivienda");
    fireEvent.change(select, { target: { value: "p-2" } });
    fireEvent.change(select, { target: { value: "" } });
    expect(store().recommendations.propertyId).toBeUndefined();
  });

  it("writes both ends of the date range", () => {
    renderFilters();
    fireEvent.change(screen.getByLabelText("Desde"), {
      target: { value: "2026-09-01" },
    });
    fireEvent.change(screen.getByLabelText("Hasta"), {
      target: { value: "2026-09-30" },
    });
    expect(store().recommendations.dateFrom).toBe("2026-09-01");
    expect(store().recommendations.dateTo).toBe("2026-09-30");
  });

  it("uses native date inputs rather than a bespoke picker", () => {
    renderFilters();
    expect(screen.getByLabelText("Desde")).toHaveAttribute("type", "date");
    expect(screen.getByLabelText("Hasta")).toHaveAttribute("type", "date");
  });

  it("lists the five statuses in PRD §7.18 lifecycle order (R6.4)", () => {
    renderFilters();
    const options = Array.from(
      screen.getByLabelText("Estado").querySelectorAll("option"),
    ).map((option) => option.textContent);
    expect(options).toEqual([
      "Todos los estados",
      "Borrador",
      "Recomendada",
      "Aprobada",
      "Publicada",
      "Rechazada",
    ]);
  });

  it("writes the chosen status", () => {
    renderFilters();
    fireEvent.change(screen.getByLabelText("Estado"), {
      target: { value: "APPROVED" },
    });
    expect(store().recommendations.status).toBe("APPROVED");
  });
});

describe("RecommendationFilters — page reset lives in the store (R2.1)", () => {
  it("returns to page 1 whenever a filter changes", () => {
    renderFilters();
    store().setRecommendationPage(4);
    fireEvent.change(screen.getByLabelText("Estado"), {
      target: { value: "REJECTED" },
    });
    expect(store().recommendations.page).toBe(1);
  });
});

describe("RecommendationFilters — never disabled by a write (design D8)", () => {
  it("leaves every control enabled, so focus is never stolen mid-filter", () => {
    // Disabling a focused element drops focus to `<body>`, stranding a keyboard
    // user because somebody else's decision happened to be in flight.
    renderFilters();
    for (const label of ["Vivienda", "Desde", "Hasta", "Estado"]) {
      expect(screen.getByLabelText(label)).toBeEnabled();
    }
  });
});

describe("RecommendationFilters — accessibility", () => {
  it("labels every control", async () => {
    const { container } = renderFilters();
    expect(await getA11yViolations(container)).toEqual([]);
  });

  it("renders with an empty catalog without breaking", () => {
    renderFilters([]);
    expect(screen.getByLabelText("Vivienda")).toHaveTextContent(
      "Todas las viviendas",
    );
  });
});
