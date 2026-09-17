import { describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { getA11yViolations, render, screen } from "@/test/render";

import { StatementSummary, type StatementSummaryData } from "./statement-summary";

const SUMMARY: StatementSummaryData = {
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
  maintenanceCosts: "5.00",
  specialistCosts: "15.00",
  otherCosts: "2.50",
  platformFee: "30.00",
  netOwnerResult: "790.50",
  notes: null,
  createdAt: "2026-02-01T00:00:00Z",
  updatedAt: "2026-02-01T00:00:00Z",
};

function renderSummary(overrides: Partial<StatementSummaryData> = {}) {
  return render(
    <I18nProvider locale="es">
      <StatementSummary statement={{ ...SUMMARY, ...overrides }} />
    </I18nProvider>,
  );
}

describe("StatementSummary — the flat summary is rendered in full (R3.1, R3.8, task 4.1)", () => {
  it("shows the period range with localized dates", () => {
    renderSummary();
    expect(screen.getByText(/ene 2026/i)).toBeInTheDocument();
  });

  it("shows the localized status", () => {
    renderSummary();
    expect(screen.getByText("Lista")).toBeInTheDocument();
  });

  it("shows all eleven monetary amounts with locale decimals and no invented currency", () => {
    renderSummary();
    expect(screen.getByText("1000,00")).toBeInTheDocument(); // grossRevenue
    expect(screen.getByText("100,00")).toBeInTheDocument(); // otaCommissions
    expect(screen.getByText("900,00")).toBeInTheDocument(); // netRevenue
    expect(screen.getByText("50,00")).toBeInTheDocument(); // cleaningCosts
    expect(screen.getByText("20,00")).toBeInTheDocument(); // laundryCosts
    expect(screen.getByText("10,00")).toBeInTheDocument(); // amenitiesCosts
    expect(screen.getByText("5,00")).toBeInTheDocument(); // maintenanceCosts
    expect(screen.getByText("15,00")).toBeInTheDocument(); // specialistCosts
    expect(screen.getByText("2,50")).toBeInTheDocument(); // otherCosts
    expect(screen.getByText("30,00")).toBeInTheDocument(); // platformFee
    expect(screen.getByText("790,50")).toBeInTheDocument(); // netOwnerResult
    expect(screen.queryByText(/€|EUR|\$|USD/)).not.toBeInTheDocument();
  });

  it("shows a localized 'no notes' placeholder when notes is null, never another statement's text", () => {
    renderSummary({ notes: null });
    expect(screen.getByText("Sin notas")).toBeInTheDocument();
  });

  it("shows the real notes text when present", () => {
    renderSummary({ notes: "Pago retrasado por el propietario." });
    expect(screen.getByText("Pago retrasado por el propietario.")).toBeInTheDocument();
    expect(screen.queryByText("Sin notas")).not.toBeInTheDocument();
  });
});

describe("StatementSummary — accessibility", () => {
  it("has no accessibility violations", async () => {
    const { container } = renderSummary();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
