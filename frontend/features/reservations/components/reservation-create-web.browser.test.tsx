import { describe, expect, it, vi } from "vitest";
import { page, userEvent } from "vitest/browser";
import { render, screen } from "@testing-library/react";

import "@/test/artifacts/globals.css";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { AA_NORMAL_TEXT, contrastRatio } from "@/test/wcag-contrast";
import { EditReservationForm } from "./edit/edit-reservation-form";
import { ReservationDetailView } from "./detail/reservation-detail-view";
import { CreateReservationForm } from "./create/create-reservation-form";

const useHasPermissionMock = vi.hoisted(() => vi.fn());
const useReservationMock = vi.hoisted(() => vi.fn());
const useActivePropertiesMock = vi.hoisted(() => vi.fn());
const useCreateReservationMock = vi.hoisted(() => vi.fn());
const useUpdateReservationMock = vi.hoisted(() => vi.fn(() => ({
  isPending: false,
  isError: false,
  isSuccess: false,
  mutate: vi.fn(),
})));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
  useHasPermission: useHasPermissionMock,
}));
vi.mock("@/features/properties", () => ({ useActiveProperties: useActivePropertiesMock }));
vi.mock("../../hooks/use-reservations", () => ({
  useReservation: useReservationMock,
  useCreateReservation: useCreateReservationMock,
  useUpdateReservation: useUpdateReservationMock,
  useCancelReservation: () => ({ isPending: false, isError: false, mutate: vi.fn() }),
}));
vi.mock("../../hooks/use-guest-access-token", () => ({
  useGuestAccessTokenStatus: () => ({ isPending: false, data: undefined }),
  useIssueGuestAccessToken: () => ({ isPending: false, isError: false, data: undefined, mutate: vi.fn() }),
  useRevokeGuestAccessToken: () => ({ isPending: false, isError: false, mutate: vi.fn() }),
  useSendGuestAccessTokenEmail: () => ({ isPending: false, isError: false, isSuccess: false, data: undefined, mutate: vi.fn() }),
}));
vi.mock("next/link", () => ({
  __esModule: true,
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

const DETAIL = {
  id: "reservation-1", propertyId: "property-1", propertyName: "Casa del Mar",
  propertyInternalCode: "CDM-01", guestFullName: "Laura Gómez", status: "CONFIRMED",
  checkInDate: "2026-08-12", checkOutDate: "2026-08-15", nights: 3, totalGuests: 2,
  guestId: "guest-1", channel: "AIRBNB", currency: "EUR", grossAmount: "612.50",
  paymentStatus: "PAID", checkInTime: "15:00", checkOutTime: "11:00", adults: 2,
  children: 0, otaCommission: null, netAmount: "612.50", cleaningRequired: true,
  accessStatus: "DELIVERED", externalChannelId: null, externalPmsId: null,
  internalNotes: "Una nota interna suficientemente larga para probar el ajuste de línea.",
  specialRequests: "Una petición especial suficientemente larga para probar el ajuste de línea.",
  createdAt: "2026-08-01T09:00:00Z", updatedAt: "2026-08-10T09:00:00Z", guest: null,
} as never;

function rgbToHex(value: string): string {
  const channels = value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  if (!channels) throw new Error(`Expected an opaque rgb color, got ${value}`);
  return `#${channels.slice(1, 4).map((channel) => Number(channel).toString(16).padStart(2, "0")).join("")}`;
}

function renderEditForm() {
  useHasPermissionMock.mockReturnValue(true);
  render(<I18nProvider locale="es"><EditReservationForm detail={DETAIL} /></I18nProvider>);
}

function renderDetail() {
  useHasPermissionMock.mockReturnValue(false);
  useReservationMock.mockReturnValue({ isPending: false, isError: false, data: DETAIL, refetch: vi.fn() });
  render(<I18nProvider locale="es"><ReservationDetailView reservationId="reservation-1" /></I18nProvider>);
}

function renderCreateForm() {
  useHasPermissionMock.mockReturnValue(true);
  useActivePropertiesMock.mockReturnValue({
    isPending: false,
    isError: false,
    data: {
      data: [{
        id: "property-1",
        name: "Casa del Mar",
        internalCode: "CDM-01",
        timezone: "Europe/Madrid",
        defaultCheckInTime: "15:00",
        defaultCheckOutTime: "11:00",
      }],
    },
  });
  const mutate = vi.fn();
  useCreateReservationMock.mockReturnValue({ isPending: false, mutate });
  render(<I18nProvider locale="es"><CreateReservationForm /></I18nProvider>);
  return mutate;
}

describe("reservation create web review coverage", () => {
  it("renders and exercises the create form with localized required semantics", async () => {
    const mutate = renderCreateForm();

    expect(screen.getByRole("form")).toBeInTheDocument();
    expect(screen.getByLabelText(/Fecha de entrada \(obligatorio\)/)).toHaveAttribute("aria-required", "true");
    expect(screen.queryByText(/\*$/)).not.toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText(/Propiedad/), "property-1");
    await userEvent.fill(screen.getByLabelText(/Fecha de entrada/), "2026-09-12");
    await userEvent.fill(screen.getByLabelText(/Fecha de salida/), "2026-09-14");
    await userEvent.click(screen.getByRole("button", { name: "Crear reserva" }));

    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0][0]).toMatchObject({
      property_id: "property-1",
      check_in_date: "2026-09-12",
      check_out_date: "2026-09-14",
      adults: 1,
      children: 0,
    });
  });

  it("keeps keyboard focus order on enabled controls and exposes the visible focus indicator", async () => {
    renderEditForm();
    const form = screen.getByRole("form");
    const internalNotes = document.getElementById("reservation-edit-internalNotes");
    const submit = form.querySelector("button[type=submit]");
    expect(internalNotes).not.toBeNull();
    expect(submit).not.toBeNull();

    await userEvent.keyboard("{Tab}");
    expect(document.activeElement).toBe(internalNotes);
    const focusStyle = getComputedStyle(internalNotes!);
    expect(focusStyle.outlineStyle).toBe("solid");
    expect(Number.parseFloat(focusStyle.outlineWidth)).toBeGreaterThanOrEqual(2);

    await userEvent.keyboard("{Tab}");
    expect(document.activeElement).toBe(submit);
    expect(Array.from(form.querySelectorAll("input, textarea")).filter((control) => !control.hasAttribute("disabled"))).toEqual([internalNotes]);
  });

  it("renders the reservation back link with normal-text WCAG contrast", () => {
    renderDetail();
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    const linkStyle = getComputedStyle(links[0]);
    const bodyStyle = getComputedStyle(document.body);
    expect(contrastRatio(rgbToHex(linkStyle.color), rgbToHex(bodyStyle.backgroundColor))).toBeGreaterThanOrEqual(AA_NORMAL_TEXT);
  });

  for (const width of [320, 360, 640]) {
    it(`does not clip horizontally at ${width}px`, async () => {
      await page.viewport(width, 900);
      renderDetail();
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      expect(document.documentElement.scrollWidth, `document overflow at ${width}px`).toBeLessThanOrEqual(document.documentElement.clientWidth);
    });
  }
});
