import { describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import type { OwnerStatementDetail } from "../data";
import { StatementDetail } from "./statement-detail";

const DETAIL: OwnerStatementDetail = {
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
  netOwnerResult: "790.50",
  notes: null,
  createdAt: "2026-02-01T00:00:00Z",
  updatedAt: "2026-02-01T00:00:00Z",
  reservations: [],
  expenses: [],
};

function renderDetail(overrides: Partial<Parameters<typeof StatementDetail>[0]> = {}) {
  return render(
    <I18nProvider locale="es">
      <StatementDetail statement={DETAIL} {...overrides} />
    </I18nProvider>,
  );
}

describe("StatementDetail — composes the summary (task 4.1)", () => {
  it("renders the summary", () => {
    renderDetail();
    expect(screen.getByTestId("statement-summary")).toBeInTheDocument();
  });

  it("renders an optional downloads slot when supplied, for section 5.3 to fill", () => {
    renderDetail({ downloads: <button type="button">export</button> });
    expect(screen.getByRole("button", { name: "export" })).toBeInTheDocument();
  });

  it("renders nothing extra when the downloads slot is omitted", () => {
    renderDetail();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("StatementDetail — composes the reservations/expenses breakdowns (tasks 4.2, 4.3)", () => {
  it("renders both breakdown sections with their translated empty states when both collections are empty", () => {
    renderDetail();
    expect(screen.getByText("Sin reservas")).toBeInTheDocument();
    expect(screen.getByText("Sin gastos")).toBeInTheDocument();
  });

  it("keeps the summary visible when only one breakdown is empty (R5.3)", () => {
    renderDetail({
      statement: {
        ...DETAIL,
        reservations: [
          {
            id: "res-1",
            checkInDate: "2026-01-05",
            nights: 2,
            grossAmount: "200.00",
            otaCommission: "20.00",
            netAmount: "180.00",
            currency: "EUR",
          },
        ],
        expenses: [],
      },
    });
    expect(screen.getByTestId("statement-summary")).toBeInTheDocument();
    expect(screen.getByTestId("reservations-breakdown")).toBeInTheDocument();
    expect(screen.getByText("Sin gastos")).toBeInTheDocument();
  });
});
