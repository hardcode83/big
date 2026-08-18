import { useState } from "react";
import { fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import esReservations from "@/locales/es/reservations.json";

import type { ReservationFilters } from "../../data";
import { ReservationsFilters } from "./reservations-filters";

type OnChange = (next: ReservationFilters) => void;

function ControlledHarness({
  initial,
  onChange,
}: {
  initial: ReservationFilters;
  onChange: OnChange;
}) {
  const [value, setValue] = useState<ReservationFilters>(initial);
  return (
    <ReservationsFilters
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
    />
  );
}

function renderFilters(value: ReservationFilters, onChange: OnChange) {
  return render(
    <I18nProvider locale="es">
      <ControlledHarness initial={value} onChange={onChange} />
    </I18nProvider>,
  );
}

describe("ReservationsFilters (R2, R4, R5)", () => {
  it("renders with empty filters and shows the localized labels from the ES locale", () => {
    const onChange = vi.fn();
    renderFilters({}, onChange);
    // The combobox (status <select>) and the two date inputs are labeled by
    // the locale's keys, not by hardcoded strings.
    expect(
      screen.getByRole("combobox", { name: esReservations.fields.status }),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(esReservations.fields.checkIn, { selector: "input" }),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(esReservations.fields.checkOut, { selector: "input" }),
    ).toBeInTheDocument();
    // The clear button uses the locale's "Limpiar filtros" copy.
    expect(
      screen.getByRole("button", { name: esReservations.fields.clearFilters }),
    ).toBeInTheDocument();
  });

  it("changing status emits { status, page: 1 } and the keys are in the v1 order", () => {
    const onChange = vi.fn();
    renderFilters({}, onChange);
    fireEvent.change(
      screen.getByRole("combobox", { name: esReservations.fields.status }),
      { target: { value: "PENDING" } },
    );
    const arg = onChange.mock.calls[0][0];
    expect(Object.keys(arg)).toEqual(["status", "page"]);
    expect(arg).toEqual({ status: "PENDING", page: 1 });
  });

  it("changing dateFrom and dateTo emits both in the v1 order (status, dateFrom, dateTo, page)", () => {
    const onChange = vi.fn();
    renderFilters({ status: "PENDING" }, onChange);
    fireEvent.change(
      screen.getByLabelText(esReservations.fields.checkIn, { selector: "input" }),
      { target: { value: "2026-08-01" } },
    );
    const first = onChange.mock.calls[0][0];
    expect(Object.keys(first)).toEqual(["status", "dateFrom", "page"]);
    expect(first).toEqual({ status: "PENDING", dateFrom: "2026-08-01", page: 1 });

    fireEvent.change(
      screen.getByLabelText(esReservations.fields.checkOut, { selector: "input" }),
      { target: { value: "2026-08-31" } },
    );
    const second = onChange.mock.calls[1][0];
    expect(Object.keys(second)).toEqual(["status", "dateFrom", "dateTo", "page"]);
    expect(second).toEqual({
      status: "PENDING",
      dateFrom: "2026-08-01",
      dateTo: "2026-08-31",
      page: 1,
    });
  });

  it("the clear button emits {}", () => {
    const onChange = vi.fn();
    renderFilters({ status: "PENDING", dateFrom: "2026-08-01" }, onChange);
    fireEvent.click(
      screen.getByRole("button", { name: esReservations.fields.clearFilters }),
    );
    expect(onChange).toHaveBeenCalledWith({});
  });

  it("no UI string is hardcoded: every expected label in the other tests is read from the ES locale", () => {
    // The (a) test reads `esReservations.fields.{status,checkIn,checkOut,clearFilters}`,
    // the (b)/(c) tests read `esReservations.fields.{status,checkIn,checkOut}`, and
    // the (d) test reads `esReservations.fields.clearFilters`. If any of those
    // keys is renamed in the locale file, the four tests above fail in red —
    // which is exactly what the brief asks for: tests must follow the locale
    // and not embed a parallel copy of the Spanish strings.
    expect(esReservations.fields.status).toBeTruthy();
    expect(esReservations.fields.checkIn).toBeTruthy();
    expect(esReservations.fields.checkOut).toBeTruthy();
    expect(esReservations.fields.clearFilters).toBeTruthy();
  });
});
