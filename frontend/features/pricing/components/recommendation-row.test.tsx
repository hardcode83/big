import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { getA11yViolations, render, screen } from "@/test/render";

import type { PriceRecommendation, PropertySummary } from "../data";
import { buildPropertyDirectory } from "../lib/property-directory";
import { RecommendationRow } from "./recommendation-row";

const useHasPermission = vi.hoisted(() => vi.fn(() => true));
vi.mock("@/lib/auth", () => ({ useHasPermission }));

const ATICO: PropertySummary = {
  id: "p-1",
  name: "Ático Sol",
  internalCode: "MAD-01",
};

const RECOMMENDATION: PriceRecommendation = {
  id: "rec-1",
  propertyId: "p-1",
  pricingRuleId: "rule-1",
  date: "2026-09-01",
  recommendedPrice: "142.50",
  status: "RECOMMENDED",
  explanation: "Base 120.00 · Season (High) +10.00% · capped by max_price",
};

function renderRow(
  overrides: Partial<PriceRecommendation> = {},
  directory: {
    entries?: readonly PropertySummary[] | undefined;
    isPending?: boolean;
  } = {},
) {
  const onConfirm = vi.fn();
  const result = render(
    <I18nProvider locale="es">
      <ul>
        <RecommendationRow
          recommendation={{ ...RECOMMENDATION, ...overrides }}
          properties={{
            index: buildPropertyDirectory(
              directory.entries === undefined && directory.isPending !== true
                ? [ATICO]
                : directory.entries,
            ),
            isPending: directory.isPending ?? false,
          }}
          decision={{ isPending: false, isBusy: false, onConfirm }}
        />
      </ul>
    </I18nProvider>,
  );
  return { ...result, onConfirm };
}

describe("RecommendationRow — the fields it paints (R2.4)", () => {
  it("shows the property, the night, the price and the status", () => {
    renderRow();
    expect(screen.getByText(/MAD-01/)).toBeInTheDocument();
    expect(screen.getByText(/Ático Sol/)).toBeInTheDocument();
    expect(screen.getByText("1 sept 2026")).toBeInTheDocument();
    expect(screen.getByText("142,50")).toBeInTheDocument();
    expect(screen.getByText("Recomendada")).toBeInTheDocument();
  });

  it("formats the amount with the locale separator and no currency (R6.1, R6.2)", () => {
    renderRow();
    const price = screen.getByText("142,50");
    expect(price.textContent).not.toMatch(/[€$]|EUR|USD/);
  });

  it("formats the night without shifting the day (R6.3)", () => {
    // `new Date("2026-01-01")` is midnight UTC; `fmtDay` pins the zone.
    renderRow({ date: "2026-01-01" });
    expect(screen.getByText("1 ene 2026")).toBeInTheDocument();
  });
});

describe("RecommendationRow — what must never appear (R2.5, R2.6)", () => {
  it("shows no current_price, no confidence and no timestamp", () => {
    // These three do not cross the data boundary at all (design D3), so this
    // asserts the end of that chain rather than the discipline of this file.
    const { container } = renderRow();
    const text = container.textContent ?? "";
    expect(text).not.toContain("1.00");
    expect(text).not.toMatch(/\d{4}-\d{2}-\d{2}T/);
    expect(text).not.toMatch(/hace \d/);
    // The DTO itself cannot carry them.
    expect(Object.keys(RECOMMENDATION)).not.toContain("currentPrice");
    expect(Object.keys(RECOMMENDATION)).not.toContain("confidence");
    expect(Object.keys(RECOMMENDATION)).not.toContain("createdAt");
  });
});

describe("RecommendationRow — the explanation (R2.7, design D16, D23)", () => {
  it("renders markup inside the explanation as literal text, creating no element", () => {
    // The free-text sink: the `name` a manager typed into a season or an event
    // is the only part of the sentence the backend template does not compose.
    const hostile = "Season (<b>x</b>) +10.00% <img src=x onerror=alert(1)>";
    const { container } = renderRow({ explanation: hostile });

    expect(screen.getByText(hostile)).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("folds the explanation into a closed <details> (design D23)", () => {
    const { container } = renderRow();
    const details = container.querySelector("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");
    expect(
      screen.getByText("Ver el cálculo").tagName.toLowerCase(),
    ).toBe("summary");
  });

  it("keeps the explanation in the DOM behind the summary, localized label around it", () => {
    renderRow();
    expect(screen.getByText(RECOMMENDATION.explanation)).toBeInTheDocument();
    expect(screen.getByText("Ver el cálculo")).toBeInTheDocument();
  });
});

describe("RecommendationRow — property identity (R2.8)", () => {
  it("shows the resolved name and code", () => {
    renderRow();
    expect(screen.getByText(/MAD-01 · Ático Sol/)).toBeInTheDocument();
  });

  it("announces a catalog still in flight without inventing an identity", () => {
    renderRow({}, { entries: undefined, isPending: true });
    expect(screen.getByText("Cargando identidad…")).toBeInTheDocument();
    expect(screen.queryByText(/Ático Sol/)).not.toBeInTheDocument();
  });

  it("marks an id the settled catalog does not know as unavailable", () => {
    renderRow({ propertyId: "p-unknown" }, { entries: [ATICO] });
    expect(screen.getByText("Identidad no disponible")).toBeInTheDocument();
  });

  it("never renders the raw property id", () => {
    const { container } = renderRow({}, { entries: [] });
    expect(container.textContent).not.toContain("p-1");
  });
});

describe("RecommendationRow — decision controls", () => {
  it("offers the moves of the row's status", () => {
    renderRow();
    expect(screen.getByRole("button", { name: "Aprobar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rechazar" })).toBeInTheDocument();
  });

  it("offers none on a terminal status", () => {
    renderRow({ status: "APPLIED_EXTERNAL" });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("RecommendationRow — accessibility", () => {
  it("has no violations", async () => {
    const { container } = renderRow();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
