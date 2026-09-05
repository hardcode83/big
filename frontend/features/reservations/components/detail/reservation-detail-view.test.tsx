import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import esReservations from "@/locales/es/reservations.json";
import esStates from "@/locales/es/states.json";
import { ApiError } from "@/lib/api";

const useReservationMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-reservations", () => ({
  useReservation: useReservationMock,
}));

import { ReservationDetailView } from "./reservation-detail-view";

function renderDetail() {
  return render(
    <I18nProvider locale="es">
      <ReservationDetailView reservationId="reservation-1" />
    </I18nProvider>,
  );
}

const FULL_DETAIL = {
  id: "reservation-1",
  propertyId: "property-1",
  propertyName: "Casa del Mar",
  propertyInternalCode: "CDM-01",
  guestFullName: "Laura Gómez",
  status: "CONFIRMED",
  checkInDate: "2026-08-12",
  checkOutDate: "2026-08-15",
  nights: 3,
  totalGuests: 2,
  guestId: "guest-1",
  channel: "DIRECT",
  currency: "EUR",
  grossAmount: "612.50",
  paymentStatus: "PAID",
  checkInTime: "15:00",
  checkOutTime: "11:00",
  adults: 2,
  children: 0,
  otaCommission: null,
  netAmount: "612.50",
  cleaningRequired: true,
  accessStatus: "DELIVERED",
  externalChannelId: null,
  externalPmsId: null,
  internalNotes: "Allergic to feathers",
  specialRequests: "Late check-in",
  createdAt: "2026-08-01T09:00:00Z",
  updatedAt: "2026-08-10T09:00:00Z",
  guest: {
    id: "guest-1",
    fullName: "Laura Gómez",
    email: "laura@example.com",
    phone: "+34 600 000 000",
    preferredLanguage: "es",
    documentStatus: "VERIFIED",
    legalRegistrationStatus: "REGISTERED",
  },
} as const;

describe("ReservationDetailView (R3, R4, R5.2, R5.4)", () => {
  it("renders the loading state when the query is pending", () => {
    useReservationMock.mockReturnValue({
      isPending: true,
      isError: false,
      data: undefined,
      refetch: vi.fn(),
    });
    renderDetail();
    // The loading state is a non-intrusive status region; the detail blocks
    // are not in the DOM yet.
    expect(screen.queryByText(esReservations.fields.internalNotes)).not.toBeInTheDocument();
  });

  it("renders all sections for a full payload, with localized labels from the ES locale", () => {
    useReservationMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: FULL_DETAIL,
      refetch: vi.fn(),
    });
    renderDetail();
    expect(
      screen.getByText(esReservations.fields.internalNotes),
    ).toBeInTheDocument();
    expect(
      screen.getByText(esReservations.fields.specialRequests),
    ).toBeInTheDocument();
    expect(screen.getByText("Laura Gómez")).toBeInTheDocument();
  });

  it("renders the guest-empty copy when guest is null", () => {
    useReservationMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: { ...FULL_DETAIL, guest: null, guestId: null },
      refetch: vi.fn(),
    });
    renderDetail();
    expect(screen.getByText(esReservations.fields.guestEmpty)).toBeInTheDocument();
  });

  it("renders internalNotes as plain text, not as HTML (R3.3)", () => {
    useReservationMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: {
        ...FULL_DETAIL,
        internalNotes: "<script>alert(1)</script>",
      },
      refetch: vi.fn(),
    });
    renderDetail();
    // The text appears verbatim — there is no <script> element in the DOM.
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });

  it("renders the notFound state for a 404 with a back link (R3.5 — distinct from the list)", () => {
    useReservationMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "NOT_FOUND", message: "no", status: 404 }),
      refetch: vi.fn(),
    });
    renderDetail();
    expect(screen.getByText(esReservations.fields.notFound)).toBeInTheDocument();
    // The detail view exposes a back link to the list.
    const backLink = screen.getByRole("link", {
      name: new RegExp(esReservations.fields.backToList),
    });
    expect(backLink).toBeInTheDocument();
  });

  it("renders the forbidden state for a 403", () => {
    useReservationMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "FORBIDDEN", message: "no", status: 403 }),
      refetch: vi.fn(),
    });
    renderDetail();
    expect(screen.getByRole("alert")).toHaveTextContent(
      esReservations.fields.forbidden,
    );
  });

  it("renders the validation state for a 422 and does NOT leak the backend payload", () => {
    useReservationMock.mockReturnValue({
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
    renderDetail();
    expect(screen.getByRole("alert")).toHaveTextContent(
      esReservations.fields.validation,
    );
    const text = screen.getByRole("alert").textContent ?? "";
    expect(text).not.toContain("cualquier cosa");
    expect(text).not.toContain("property_id");
    expect(text).not.toContain("validation_error");
  });

  it("renders the generic error state for a 500", () => {
    useReservationMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "SERVER", message: "boom", status: 500 }),
      refetch: vi.fn(),
    });
    renderDetail();
    expect(screen.getByText(esStates.error.title)).toBeInTheDocument();
  });

  it("does not render document_number, date_of_birth, document_expiry_date, or nationality (R3.4)", () => {
    useReservationMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: FULL_DETAIL,
      refetch: vi.fn(),
    });
    renderDetail();
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("document_number");
    expect(text).not.toContain("date_of_birth");
    expect(text).not.toContain("document_expiry_date");
    expect(text).not.toContain("nationality");
  });

  // F1: the detail sections previously contained hardcoded English `<dt>`
  // labels ("Adults", "Children", "Gross", "Net", "OTA", "Cleaning required",
  // "Yes", "No", "Name", "Email", "Phone", "Language"). After the fix every
  // visible label is read from the locale. The test asserts the ES labels
  // appear and the bare English literals do not, so a future regression
  // fails in red.
  it("renders localized detail labels from the ES locale (R5.2 / F1)", () => {
    useReservationMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: FULL_DETAIL,
      refetch: vi.fn(),
    });
    renderDetail();
    expect(screen.getByText(esReservations.fields.adults)).toBeInTheDocument();
    expect(screen.getByText(esReservations.fields.children)).toBeInTheDocument();
    expect(screen.getByText(esReservations.fields.gross)).toBeInTheDocument();
    expect(screen.getByText(esReservations.fields.net)).toBeInTheDocument();
    expect(screen.getByText(esReservations.fields.ota)).toBeInTheDocument();
    expect(
      screen.getByText(esReservations.fields.cleaningRequired),
    ).toBeInTheDocument();
    expect(screen.getByText(esReservations.fields.fullName)).toBeInTheDocument();
    expect(screen.getByText(esReservations.fields.email)).toBeInTheDocument();
    expect(screen.getByText(esReservations.fields.phone)).toBeInTheDocument();
    expect(
      screen.getByText(esReservations.fields.preferredLanguage),
    ).toBeInTheDocument();
    // The boolean renders as the localized "yes" / "no" string from the
    // locale, not the bare English literals.
    expect(screen.getByText(esReservations.fields.yes)).toBeInTheDocument();
    // No hardcoded English literals should appear in the detail view.
    // Each is checked as a standalone token (word boundaries) so the
    // localized label "Neto" (which contains "Net" as a substring) does
    // not trigger a false positive. "OTA" is omitted from the list
    // because the English acronym is a legitimate technical term kept in
    // the Spanish label "Comisión OTA" — the F1 finding was about the
    // bare English `<dt>OTA</dt>`, not the acronym itself.
    const body = document.body.textContent ?? "";
    for (const literal of [
      "Adults",
      "Children",
      "Gross",
      "Net",
      "Cleaning required",
      "Name",
      "Email",
      "Phone",
      "Language",
    ]) {
      const token = new RegExp(`(?:^|\\s)${literal}(?:$|\\s|[,.:;])`);
      expect(body, `English literal "${literal}" leaked into the DOM`).not.toMatch(token);
    }
  });

  it("renders null grossAmount/netAmount/otaCommission as three em-dashes with no currency code (R1.2)", () => {
    useReservationMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: {
        ...FULL_DETAIL,
        grossAmount: null,
        netAmount: null,
        otaCommission: null,
      },
      refetch: vi.fn(),
    });
    renderDetail();
    // One em-dash per null amount in the financial block — three total.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
    // No stray currency code: the three nulls must NOT render " EUR".
    expect(document.body.textContent ?? "").not.toContain("EUR");
  });

  it("renders the property identity block with both values present (R4.1)", () => {
    useReservationMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: FULL_DETAIL,
      refetch: vi.fn(),
    });
    renderDetail();
    expect(
      screen.getByText(esReservations.fields.propertyCode),
    ).toBeInTheDocument();
    expect(
      screen.getByText(esReservations.fields.propertyName),
    ).toBeInTheDocument();
    expect(screen.getByText("CDM-01")).toBeInTheDocument();
    expect(screen.getByText("Casa del Mar")).toBeInTheDocument();
  });

  it("renders em-dashes for both property fields when null, without hiding the block (R4.2)", () => {
    useReservationMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: {
        ...FULL_DETAIL,
        propertyName: null,
        propertyInternalCode: null,
      },
      refetch: vi.fn(),
    });
    renderDetail();
    // The block's own labels stay in the DOM — it is not hidden like
    // DetailGuestBlock is when its data is null.
    expect(
      screen.getByText(esReservations.fields.propertyCode),
    ).toBeInTheDocument();
    expect(
      screen.getByText(esReservations.fields.propertyName),
    ).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });
});
