import { describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { getA11yViolations, render, screen } from "@/test/render";

import type { OwnerStatement } from "../data";
import { StatementRow, type StatementPropertyDirectory } from "./statement-row";

const STATEMENT: OwnerStatement = {
  id: "st-1",
  propertyId: "p-1",
  periodStart: "2026-01-01",
  periodEnd: "2026-01-31",
  status: "READY",
  grossRevenue: "1000.00",
  otaCommissions: "100.00",
  netRevenue: "900.00",
  cleaningCosts: "50.00",
  laundryCosts: "20.00",
  amenitiesCosts: "10.00",
  maintenanceCosts: "0.00",
  specialistCosts: "0.00",
  otherCosts: "0.00",
  platformFee: "30.00",
  netOwnerResult: "790.5",
  notes: null,
  createdAt: "2026-02-01T00:00:00Z",
  updatedAt: "2026-02-01T00:00:00Z",
};

function directory(
  entries: Array<[string, { name: string }]> = [["p-1", { name: "Ático Sol" }]],
  isPending = false,
): StatementPropertyDirectory {
  return { index: new Map(entries), isPending };
}

function renderRow(overrides: Partial<Parameters<typeof StatementRow>[0]> = {}) {
  return render(
    <I18nProvider locale="es">
      <ul>
        <StatementRow statement={STATEMENT} properties={directory()} {...overrides} />
      </ul>
    </I18nProvider>,
  );
}

describe("StatementRow — resolves property from the directory, never from the row (R2.1, R2.2, D2)", () => {
  it("shows the resolved property name", () => {
    renderRow();
    expect(screen.getByText("Ático Sol")).toBeInTheDocument();
  });

  it("shows a neutral loading marker while the directory is still pending", () => {
    renderRow({ properties: directory([], true) });
    expect(screen.getByText("Cargando catálogo…")).toBeInTheDocument();
  });

  it("shows 'unavailable' when the directory settled without this id", () => {
    renderRow({ properties: directory([], false) });
    expect(screen.getByText("Vivienda no disponible")).toBeInTheDocument();
  });
});

describe("StatementRow — period, status and net result from the summary (R2.1)", () => {
  it("shows the period range", () => {
    renderRow();
    expect(screen.getByText(/ene 2026/i)).toBeInTheDocument();
  });

  it("shows the localized status label", () => {
    renderRow();
    expect(screen.getByText("Lista")).toBeInTheDocument();
  });

  it("shows the net owner result with locale decimals and no invented currency", () => {
    renderRow();
    expect(screen.getByText("790,50")).toBeInTheDocument();
    expect(screen.queryByText(/€|EUR|\$|USD/)).not.toBeInTheDocument();
  });
});

describe("StatementRow — accessibility", () => {
  it("exposes an accessible name for the row via aria-labelledby", () => {
    renderRow();
    const item = screen.getByRole("listitem");
    expect(item).toHaveAccessibleName(/Ático Sol/);
  });

  it("has no accessibility violations", async () => {
    const { container } = renderRow();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
