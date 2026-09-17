import { describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { getA11yViolations, render, screen } from "@/test/render";

import type { OwnerStatementReservation } from "../data";
import { ReservationsBreakdown } from "./reservations-breakdown";

const RESERVATION: OwnerStatementReservation = {
  id: "res-1",
  checkInDate: "2026-01-05",
  nights: 3,
  grossAmount: "300.00",
  otaCommission: "30.00",
  netAmount: "270.00",
  currency: "EUR",
};

function renderBreakdown(reservations: OwnerStatementReservation[]) {
  return render(
    <I18nProvider locale="es">
      <ReservationsBreakdown reservations={reservations} />
    </I18nProvider>,
  );
}

describe("ReservationsBreakdown — only the contractual fields (R3.2, task 4.2)", () => {
  it("shows check-in date, nights, gross, ota commission, net and currency", () => {
    renderBreakdown([RESERVATION]);
    expect(screen.getByText(/ene 2026/i)).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("EUR")).toBeInTheDocument();
    expect(screen.getByText(/300,00/)).toBeInTheDocument();
    expect(screen.getByText(/30,00/)).toBeInTheDocument();
    expect(screen.getByText(/270,00/)).toBeInTheDocument();
  });

  it("shows the reservation id", () => {
    renderBreakdown([RESERVATION]);
    expect(screen.getByText("res-1")).toBeInTheDocument();
  });

  it("respects each row's own currency instead of a global one", () => {
    renderBreakdown([
      { ...RESERVATION, id: "res-1", currency: "EUR" },
      { ...RESERVATION, id: "res-2", currency: "USD", grossAmount: "500.00" },
    ]);
    expect(screen.getByText("EUR")).toBeInTheDocument();
    expect(screen.getByText("USD")).toBeInTheDocument();
  });
});

describe("ReservationsBreakdown — null amounts render as absent (R3.5)", () => {
  it("never substitutes zero or a computed value for a null gross/ota/net amount", () => {
    renderBreakdown([
      { ...RESERVATION, grossAmount: null, otaCommission: null, netAmount: null },
    ]);
    expect(screen.queryByText(/^0[,.]00/)).not.toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });
});

describe("ReservationsBreakdown — empty state (R3.4)", () => {
  it("shows a translated empty state when there are no reservations", () => {
    renderBreakdown([]);
    expect(screen.getByText("Sin reservas")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("ReservationsBreakdown — accessibility", () => {
  it("has no accessibility violations with rows", async () => {
    const { container } = renderBreakdown([RESERVATION]);
    expect(await getA11yViolations(container)).toEqual([]);
  });

  it("has no accessibility violations when empty", async () => {
    const { container } = renderBreakdown([]);
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
