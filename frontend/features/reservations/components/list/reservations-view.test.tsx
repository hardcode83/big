import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import esReservations from "@/locales/es/reservations.json";
import esStates from "@/locales/es/states.json";
import { ApiError } from "@/lib/api";

const useReservationsMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-reservations", () => ({
  useReservations: useReservationsMock,
}));

import { ReservationsView } from "./reservations-view";

function renderView() {
  return render(
    <I18nProvider locale="es">
      <ReservationsView />
    </I18nProvider>,
  );
}

const SAMPLE = {
  data: [
    {
      id: "reservation-1",
      propertyId: "property-1",
      status: "PENDING",
      checkInDate: "2026-08-12",
      checkOutDate: "2026-08-15",
      guestId: null,
      channel: "MANUAL",
      currency: "EUR",
      grossAmount: "612.50",
    },
  ],
  page: 1,
  perPage: 20,
  total: 1,
  totalPages: 1,
};

describe("ReservationsView (R2, R3.5, R4, R5.2, R5.4)", () => {
  it("renders the loading state from the locale", () => {
    useReservationsMock.mockReturnValue({
      isPending: true,
      isError: false,
      data: undefined,
      refetch: vi.fn(),
    });
    renderView();
    // The loading state is a non-intrusive role=status region; we assert
    // through the table not being present.
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders one row per summary with localized headers from the ES locale", () => {
    useReservationsMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: SAMPLE,
      refetch: vi.fn(),
    });
    renderView();
    expect(screen.getByRole("table")).toBeInTheDocument();
    // Headers from the locale
    expect(
      screen.getByRole("columnheader", { name: esReservations.fields.guest }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: esReservations.fields.property }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: esReservations.fields.stay }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: esReservations.fields.status }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: esReservations.fields.channel }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: esReservations.fields.amount }),
    ).toBeInTheDocument();
  });

  it("renders the empty state copy when the data array is empty AND keeps the page header (F13)", () => {
    useReservationsMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: { data: [], page: 1, perPage: 20, total: 0, totalPages: 0 },
      refetch: vi.fn(),
    });
    renderView();
    expect(screen.getByText(esStates.empty.title)).toBeInTheDocument();
    // The page heading still anchors the route title even on the empty state.
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Reservas", // routes.reservations.title in ES
      }),
    ).toBeInTheDocument();
  });

  it("renders the localized error state and a retry button for a 500", () => {
    useReservationsMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "SERVER", message: "boom", status: 500 }),
      refetch: vi.fn(),
    });
    renderView();
    expect(screen.getByText(esStates.error.title)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: esStates.error.retry }),
    ).toBeInTheDocument();
  });

  it("renders the localized forbidden state for a 403", () => {
    useReservationsMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "FORBIDDEN", message: "no", status: 403 }),
      refetch: vi.fn(),
    });
    renderView();
    expect(screen.getByRole("alert")).toHaveTextContent(
      esReservations.fields.forbidden,
    );
  });

  it("renders the localized validation state and does NOT leak the backend payload (422 with property_id)", () => {
    useReservationsMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({
        code: "validation_error",
        message: "cualquier cosa",
        details: { property_id: "x" },
        status: 422,
      }),
      refetch: vi.fn(),
    });
    renderView();
    expect(screen.getByRole("alert")).toHaveTextContent(
      esReservations.fields.validation,
    );
    const text = screen.getByRole("alert").textContent ?? "";
    expect(text).not.toContain("cualquier cosa");
    expect(text).not.toContain("property_id");
    expect(text).not.toContain("validation_error");
  });

  it("renders a 404 as a generic error in the list (R3.5) — no notFound copy in the table view", () => {
    useReservationsMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "NOT_FOUND", message: "no", status: 404 }),
      refetch: vi.fn(),
    });
    renderView();
    const container = screen.getByRole("alert", { hidden: true });
    // The 404 case for the list endpoint is treated as a generic error, so the
    // `notFound` copy from the locale must NOT appear in the DOM.
    expect(container.textContent ?? "").not.toContain(
      esReservations.fields.notFound,
    );
  });

  it("guestId null renders as an em-dash, not the id", () => {
    useReservationsMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: SAMPLE,
      refetch: vi.fn(),
    });
    renderView();
    // The row index is the guest cell with the em-dash (the link inside
    // has `aria-label="Abrir reserva"`, so the cell's accessible name is
    // that string, not the dash — the dash is the visible text).
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("the table does NOT include internal_notes or special_requests (detail-only)", () => {
    useReservationsMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: SAMPLE,
      refetch: vi.fn(),
    });
    renderView();
    const table = screen.getByRole("table");
    expect(table.textContent).not.toContain("internalNotes");
    expect(table.textContent).not.toContain("specialRequests");
  });

  it("pagination buttons are labeled in the locale and disabled at the lower edge (page = 1)", () => {
    useReservationsMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: { ...SAMPLE, page: 1, totalPages: 3 },
      refetch: vi.fn(),
    });
    renderView();
    const prev = screen.getByRole("button", {
      name: esReservations.fields.prevPage,
    });
    const next = screen.getByRole("button", {
      name: esReservations.fields.nextPage,
    });
    expect(prev).toBeDisabled();
    expect(next).not.toBeDisabled();
  });

  // F6: the upper edge of pagination (page = totalPages) was not asserted
  // before. With page = totalPages, the next button must be disabled and the
  // prev button enabled.
  it("pagination `next` is disabled at the upper edge (page = totalPages)", () => {
    useReservationsMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: { ...SAMPLE, page: 3, totalPages: 3 },
      refetch: vi.fn(),
    });
    renderView();
    const prev = screen.getByRole("button", {
      name: esReservations.fields.prevPage,
    });
    const next = screen.getByRole("button", {
      name: esReservations.fields.nextPage,
    });
    expect(prev).not.toBeDisabled();
    expect(next).toBeDisabled();
  });

  // F5: the gap before was "no navigate from list row to detail". The first
  // cell now exposes a `<Link>` with the row destination. Screen readers
  // hear the localized "open reservation" name; the visible text is the
  // guest id (or `—` when null).
  it("each row exposes a link to /reservations/{id} with the localized open-reservation label (F5, D5)", () => {
    useReservationsMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: SAMPLE,
      refetch: vi.fn(),
    });
    renderView();
    const link = screen.getByRole("link", {
      name: esReservations.fields.openReservation,
    });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/reservations/reservation-1");
  });
});
