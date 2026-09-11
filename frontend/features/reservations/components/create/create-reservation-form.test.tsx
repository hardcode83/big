import { fireEvent, render, screen, waitFor } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { beforeEach, describe, expect, it, vi } from "vitest";

const useActivePropertiesMock = vi.hoisted(() => vi.fn());
const useCreateReservationMock = vi.hoisted(() => vi.fn());
const useHasPermissionMock = vi.hoisted(() => vi.fn());
vi.mock("@/features/properties", () => ({ useActiveProperties: useActivePropertiesMock }));
vi.mock("../../hooks/use-reservations", () => ({ useCreateReservation: useCreateReservationMock }));
vi.mock("@/lib/auth", () => ({ useHasPermission: useHasPermissionMock }));

import { buildCreatePayload, CreateReservationForm } from "./create-reservation-form";

const values = {
  propertyId: "property-1",
  checkInDate: "2026-09-12",
  checkOutDate: "2026-09-14",
  checkInTime: "",
  checkOutTime: "",
  adults: "2",
  children: "0",
  channel: "DIRECT" as const,
  grossAmount: "",
  netAmount: "",
  otaCommission: "",
  currency: "EUR",
  internalNotes: "",
  specialRequests: "",
  fullName: "",
  email: "",
  phone: "",
  preferredLanguage: "es" as const,
};

describe("buildCreatePayload (manual creation, R1/R2/R4)", () => {
  it("keeps required values, omits blank optionals, and never creates guest_id", () => {
    expect(buildCreatePayload(values)).toEqual({
      property_id: "property-1",
      check_in_date: "2026-09-12",
      check_out_date: "2026-09-14",
      adults: 2,
      children: 0,
      channel: "DIRECT",
      currency: "EUR",
    });
    expect(JSON.stringify(buildCreatePayload(values))).not.toContain("guest_id");
  });

  it("sends the allowed guest block and optional values without empty strings", () => {
    const payload = buildCreatePayload({
      ...values,
      channel: "MANUAL",
      checkInTime: "15:00",
      grossAmount: "125.50",
      fullName: "  Ada Lovelace ",
      email: " ada@example.com ",
      phone: " +34123456789 ",
      preferredLanguage: "en",
    });
    expect(payload).toMatchObject({
      channel: "MANUAL",
      check_in_time: "15:00",
      gross_amount: 125.5,
      guest: {
        full_name: "Ada Lovelace",
        email: "ada@example.com",
        phone: "+34123456789",
        preferred_language: "en",
      },
    });
    expect(payload).not.toHaveProperty("guest_id");
    expect(payload).not.toHaveProperty("check_out_time");
    expect(payload).not.toHaveProperty("internal_notes");
  });
});

const PROPERTY = {
  id: "property-1", name: "Casa Ada", internalCode: "CASA-001", timezone: "Europe/Madrid",
  defaultCheckInTime: "15:00", defaultCheckOutTime: "11:00",
};

function renderForm(locale = "es" as const) {
  return render(<I18nProvider locale={locale}><CreateReservationForm /></I18nProvider>);
}

beforeEach(() => {
  useHasPermissionMock.mockReturnValue(true);
  useActivePropertiesMock.mockReturnValue({ isPending: false, isError: false, data: { data: [PROPERTY] } });
  useCreateReservationMock.mockReturnValue({ isPending: false, isSuccess: false, mutate: vi.fn() });
});

describe("CreateReservationForm section 3 panel findings", () => {
  it("renders localized channel labels while preserving enum values", () => {
    renderForm();
    expect(screen.getByRole("option", { name: "Directa" })).toHaveValue("DIRECT");
    expect(screen.getByRole("option", { name: "Manual" })).toHaveValue("MANUAL");
  });

  it("associates the missing guest name error with the full-name input", () => {
    renderForm();
    fireEvent.change(screen.getByLabelText("Propiedad"), { target: { value: "property-1" } });
    fireEvent.change(screen.getByLabelText(/Fecha de entrada/), { target: { value: "2026-09-12" } });
    fireEvent.change(screen.getByLabelText(/Fecha de salida/), { target: { value: "2026-09-14" } });
    fireEvent.change(screen.getByLabelText("Correo electrónico"), {
      target: { value: "ada@example.com" },
    });
    fireEvent.submit(screen.getByRole("button", { name: "Crear reserva" }).closest("form")!);

    const fullName = screen.getByLabelText("Nombre completo");
    expect(fullName).toHaveAttribute("aria-invalid", "true");
    const errorId = fullName.getAttribute("aria-describedby");
    expect(errorId).toBe("reservation-create-fullName-error");
    expect(document.getElementById(errorId!)).toHaveTextContent(
      "Indica el nombre si añades datos de contacto del huésped.",
    );
  });

  it.each([
    ["adults", ""], ["adults", "abc"], ["adults", "NaN"], ["adults", "0"], ["adults", "-1"],
    ["children", ""], ["children", "abc"], ["children", "NaN"], ["children", "-1"],
    ["grossAmount", "abc"], ["grossAmount", "NaN"], ["grossAmount", "-1"],
  ] as const)("rejects invalid %s=%s with an accessible localized error", (field, value) => {
    renderForm();
    fireEvent.change(screen.getByLabelText(new RegExp(field === "grossAmount" ? "Importe bruto" : field === "adults" ? "Adultos" : "Niños")), { target: { value } });
    fireEvent.submit(screen.getByRole("button", { name: "Crear reserva" }).closest("form")!);
    const input = screen.getByLabelText(new RegExp(field === "grossAmount" ? "Importe bruto" : field === "adults" ? "Adultos" : "Niños"));
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby");
    expect(screen.getByRole("alert")).toHaveTextContent("Corrige los campos marcados");
  });

  it("uses a distinct Spanish error for adults below one", () => {
    renderForm();
    fireEvent.change(screen.getByLabelText(/Adultos/), { target: { value: "0" } });
    fireEvent.submit(screen.getByRole("button", { name: "Crear reserva" }).closest("form")!);
    expect(screen.getByText("Indica un número entero de adultos igual o mayor que uno.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Adultos/)).toHaveAccessibleDescription("Indica un número entero de adultos igual o mayor que uno.");
  });

  it.each([
    ["es", "La fecha de salida debe ser posterior o igual a la entrada.", /Fecha de entrada/, /Fecha de salida/, "Crear reserva"],
    ["en", "Check-out must be on or after check-in.", /Check-in date/, /Check-out date/, "Create reservation"],
  ] as const)("blocks inverted date intervals with localized feedback in %s", (locale, expected, checkInLabel, checkOutLabel, buttonName) => {
    renderForm(locale);
    fireEvent.change(screen.getByLabelText(/Property|Propiedad/), { target: { value: "property-1" } });
    fireEvent.change(screen.getByLabelText(checkInLabel), { target: { value: "2026-09-14" } });
    fireEvent.change(screen.getByLabelText(checkOutLabel), { target: { value: "2026-09-12" } });
    fireEvent.submit(screen.getByRole("button", { name: buttonName }).closest("form")!);
    expect(screen.getByRole("alert")).toHaveTextContent(expected);
    expect(screen.getByLabelText(checkOutLabel)).toHaveAccessibleDescription(expected);
  });

  it("allows same-day check-in and check-out when the backend accepts it", () => {
    const mutate = vi.fn();
    useCreateReservationMock.mockReturnValue({ isPending: false, isSuccess: false, mutate });
    renderForm();
    fireEvent.change(screen.getByLabelText("Propiedad"), { target: { value: "property-1" } });
    fireEvent.change(screen.getByLabelText(/Fecha de entrada/), { target: { value: "2026-09-12" } });
    fireEvent.change(screen.getByLabelText(/Fecha de salida/), { target: { value: "2026-09-12" } });
    fireEvent.submit(screen.getByRole("button", { name: "Crear reserva" }).closest("form")!);

    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0][0]).toMatchObject({
      check_in_date: "2026-09-12",
      check_out_date: "2026-09-12",
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("uses the shared 44px tap-target convention for the primary submit", () => {
    renderForm();
    expect(screen.getByRole("button", { name: "Crear reserva" })).toHaveClass("tap-target");
  });

  it("shows property loading, error and empty states", () => {
    useActivePropertiesMock.mockReturnValue({ isPending: true });
    renderForm();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
    useActivePropertiesMock.mockReturnValue({ isPending: false, isError: true, refetch: vi.fn() });
    renderForm();
    expect(screen.getByText("No se pudieron cargar las propiedades")).toBeInTheDocument();
    useActivePropertiesMock.mockReturnValue({ isPending: false, isError: false, data: { data: [] } });
    renderForm();
    expect(screen.getByText("No hay propiedades activas")).toBeInTheDocument();
  });

  it("does not submit twice while pending and does not perform a GET or persist PII", () => {
    const mutate = vi.fn();
    useCreateReservationMock.mockReturnValue({ isPending: true, mutate });
    const startUrl = window.location.href;
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    renderForm();
    const form = screen.getByRole("button", { name: "Creando reserva…" }).closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(mutate).not.toHaveBeenCalled();
    expect(window.location.href).toBe(startUrl);
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });

  it("blocks a rapid double submit from idle while the first mutation remains pending", () => {
    const mutate = vi.fn();
    useCreateReservationMock.mockReturnValue({ isPending: false, mutate });
    renderForm();
    fireEvent.change(screen.getByLabelText("Propiedad"), { target: { value: "property-1" } });
    fireEvent.change(screen.getByLabelText(/Fecha de entrada/), { target: { value: "2026-09-12" } });
    fireEvent.change(screen.getByLabelText(/Fecha de salida/), { target: { value: "2026-09-14" } });
    const form = screen.getByRole("button", { name: "Crear reserva" }).closest("form")!;

    fireEvent.submit(form);
    fireEvent.submit(form);

    expect(mutate).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Creando reserva…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Creando reserva…" })).toHaveAttribute("aria-busy", "true");
  });

  it("shows the selected property's timezone and default check-in/out context", () => {
    renderForm();
    fireEvent.change(screen.getByLabelText("Propiedad"), { target: { value: "property-1" } });
    expect(screen.getByText("Zona horaria: Europe/Madrid · Horas por defecto: 15:00–11:00")).toBeInTheDocument();
  });

  it("retains values on mutation errors and shows returned identifying success detail", async () => {
    const mutate = vi.fn((_payload, options) => options.onError(new Error("server detail")));
    useCreateReservationMock.mockReturnValue({ isPending: false, mutate });
    renderForm();
    fireEvent.change(screen.getByLabelText("Propiedad"), { target: { value: "property-1" } });
    fireEvent.change(screen.getByLabelText(/Fecha de entrada/), { target: { value: "2026-09-12" } });
    fireEvent.change(screen.getByLabelText(/Fecha de salida/), { target: { value: "2026-09-14" } });
    fireEvent.change(screen.getByLabelText(/Adultos/), { target: { value: "3" } });
    fireEvent.submit(screen.getByRole("button", { name: "Crear reserva" }).closest("form")!);
    expect(screen.getByLabelText(/Adultos/)).toHaveValue("3");
    expect(screen.getByRole("alert")).toHaveTextContent("No se pudo conectar para crear la reserva");

    mutate.mockImplementation((_payload, options) => options.onSuccess({
      id: "reservation-created", propertyName: "Casa Ada", checkInDate: "2026-09-12",
      checkOutDate: "2026-09-14", status: "PENDING",
    }));
    fireEvent.submit(screen.getByRole("button", { name: "Crear reserva" }).closest("form")!);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("reservation-created"));
    expect(screen.getByRole("status")).toHaveTextContent("Casa Ada");
  });

  it("renders nothing and cannot submit without MANAGE_RESERVATIONS", () => {
    useHasPermissionMock.mockReturnValue(false);
    renderForm();
    expect(screen.queryByText("Crear reserva")).not.toBeInTheDocument();
  });

  it("renders the English channel localization", () => {
    renderForm("en");
    expect(screen.getByRole("option", { name: "Direct" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Manual" })).toBeInTheDocument();
  });
});
