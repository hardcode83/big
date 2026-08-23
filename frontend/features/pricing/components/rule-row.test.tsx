import { describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { getA11yViolations, render, screen } from "@/test/render";

import type { PricingRule, PropertySummary } from "../data";
import { buildPropertyDirectory } from "../lib/property-directory";
import { RuleRow } from "./rule-row";

const ATICO: PropertySummary = {
  id: "p-1",
  name: "Ático Sol",
  internalCode: "MAD-01",
};

const RULE: PricingRule = {
  id: "rule-1",
  propertyId: "p-1",
  name: "Temporada alta",
  active: true,
  basePrice: "120.00",
  minPrice: "80.00",
  maxPrice: "300.00",
  maxDailyChangePct: "15.00",
  modifierCounts: {
    weekday: 2,
    leadTime: 1,
    occupancy: 3,
    seasonality: 0,
    event: 1,
  },
};

function renderRule(
  overrides: Partial<PricingRule> = {},
  entries: readonly PropertySummary[] = [ATICO],
) {
  return render(
    <I18nProvider locale="es">
      <ul>
        <RuleRow
          rule={{ ...RULE, ...overrides }}
          properties={{
            index: buildPropertyDirectory(entries),
            isPending: false,
          }}
        />
      </ul>
    </I18nProvider>,
  );
}

describe("RuleRow — the fields it paints (R5.2)", () => {
  it("shows the name, the scope, the state and the price band", () => {
    renderRule();
    expect(screen.getByText("Temporada alta")).toBeInTheDocument();
    expect(screen.getByText(/MAD-01 · Ático Sol/)).toBeInTheDocument();
    expect(screen.getByText("Activa")).toBeInTheDocument();
    expect(screen.getByText("80,00")).toBeInTheDocument();
    expect(screen.getByText("120,00")).toBeInTheDocument();
    expect(screen.getByText("300,00")).toBeInTheDocument();
  });

  it("shows the maximum daily change with the % in the label, not the number", () => {
    renderRule();
    expect(screen.getByText("15,00")).toBeInTheDocument();
    expect(
      screen.getByText("Variación diaria máxima (%)"),
    ).toBeInTheDocument();
    expect(screen.queryByText("15,00 %")).not.toBeInTheDocument();
  });

  it("marks an inactive rule as such", () => {
    renderRule({ active: false });
    expect(screen.getByText("Inactiva")).toBeInTheDocument();
  });

  it("formats every amount with the locale separator and no currency (R6.1, R6.2)", () => {
    const { container } = renderRule();
    expect(container.textContent).not.toMatch(/[€$]|EUR|USD/);
  });
});

describe("RuleRow — the five counters, never their contents (R5.2, R5.4)", () => {
  it("shows a count for each of the five JSONB columns", () => {
    renderRule();
    expect(screen.getByText("Día de la semana: 2")).toBeInTheDocument();
    expect(screen.getByText("Antelación: 1")).toBeInTheDocument();
    expect(screen.getByText("Ocupación: 3")).toBeInTheDocument();
    expect(screen.getByText("Temporada: 0")).toBeInTheDocument();
    expect(screen.getByText("Eventos: 1")).toBeInTheDocument();
  });

  it("renders no content from inside any JSONB column", () => {
    // R5.4. The DTO cannot carry it (design D3), so this asserts the end of the
    // chain: even a rule whose counts are high paints only numbers.
    const { container } = renderRule();
    const text = container.textContent ?? "";
    for (const inner of ["FRI", "SAT", "Feria", "pct", "days", "from"]) {
      expect(text).not.toContain(inner);
    }
    expect(Object.keys(RULE)).not.toContain("weekdayModifiers");
    expect(Object.keys(RULE)).not.toContain("eventRules");
  });

  it("shows a zero count rather than hiding the row of a column with none", () => {
    renderRule({
      modifierCounts: {
        weekday: 0,
        leadTime: 0,
        occupancy: 0,
        seasonality: 0,
        event: 0,
      },
    });
    expect(screen.getByText("Día de la semana: 0")).toBeInTheDocument();
    expect(screen.getByText("Eventos: 0")).toBeInTheDocument();
  });
});

describe("RuleRow — scope (R5.3)", () => {
  it("names a null property as the whole portfolio, not an unresolved name", () => {
    renderRule({ propertyId: null });
    expect(screen.getByText("Toda la cartera")).toBeInTheDocument();
    expect(screen.queryByText("Identidad no disponible")).not.toBeInTheDocument();
  });

  it("marks an id the catalog does not know as unavailable", () => {
    renderRule({ propertyId: "p-unknown" });
    expect(screen.getByText("Identidad no disponible")).toBeInTheDocument();
    // And that is a different statement from «whole portfolio».
    expect(screen.queryByText("Toda la cartera")).not.toBeInTheDocument();
  });

  it("never renders the raw property id", () => {
    const { container } = renderRule({}, []);
    expect(container.textContent).not.toContain("p-1");
  });
});

describe("RuleRow — `name` is a free-text sink too (steering/security.md rule 11)", () => {
  it("renders a rule name containing markup as literal text, creating no element", () => {
    // `pricing_rules.name` carries its own row in rule 11's census — free text a
    // manager typed, and it «sí se propaga». It reaches the DOM exactly like
    // `explanation` does, so it gets the same proof rather than relying on the
    // reader noticing that React escapes. Raised by the security panel on
    // sections 7–8, which observed the two sinks were covered asymmetrically.
    const hostile = 'Alta <b>x</b> <img src=x onerror="alert(1)">';
    const { container } = renderRule({ name: hostile });

    expect(screen.getByText(hostile)).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("RuleRow — read-only (R5.5)", () => {
  it("offers no control of any kind", () => {
    renderRule();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});

describe("RuleRow — accessibility", () => {
  it("has no violations", async () => {
    const { container } = renderRule();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
