import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen, waitFor } from "@/test/render";
import { getA11yViolations } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { ApiError } from "@/lib/api";

const source = vi.hoisted(() => ({
  getStayInfo: vi.fn(),
  getCheckinStatus: vi.fn(),
  submitCheckin: vi.fn(),
  reportIncident: vi.fn(),
}));

vi.mock("@/features/guest-portal/data", () => ({
  getGuestPortalDataSource: () => source,
}));

import { GuestPortalView } from "./guest-portal-view";

const TOKEN = "opaque-secret-token-2f9a";

const STAY = {
  accessCodeMasked: "••1234",
  addressLine1: "Calle Redes 11",
  addressLine2: null,
  arrivalNotes: "Sube al 3º",
  checkInDate: "2026-08-11",
  checkInTime: "15:00",
  checkOutDate: "2026-08-12",
  checkOutTime: "11:00",
  city: "Madrid",
  country: "ES",
  postalCode: "28001",
  propertyName: "Casa Redes",
  province: "Madrid",
  supportChannel: "+34 600 000 000",
  timezone: "Europe/Madrid",
  wifiName: "CasaWifi",
};

const CHECKIN_STATUS = {
  documentStatus: "NOT_PROVIDED" as const,
  legalRegistrationStatus: "PENDING_GUEST_DATA" as const,
  missingFields: ["full_name"],
};

function renderView(token = TOKEN) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <I18nProvider locale="es">{children}</I18nProvider>
    </QueryClientProvider>
  );
  return render(<GuestPortalView token={token} />, { wrapper });
}

function fillCheckin(number = "DOC-VALUE") {
  fireEvent.change(screen.getByLabelText("Nombre completo"), { target: { value: "Ana" } });
  fireEvent.change(screen.getByLabelText("Nacionalidad"), { target: { value: "ES" } });
  fireEvent.change(screen.getByLabelText("Fecha de nacimiento"), { target: { value: "1990-01-01" } });
  fireEvent.change(screen.getByLabelText("Número de documento"), { target: { value: number } });
  fireEvent.change(screen.getByLabelText("Caducidad del documento"), { target: { value: "2030-01-01" } });
}

beforeEach(() => {
  vi.clearAllMocks();
  source.getStayInfo.mockResolvedValue(STAY);
  source.getCheckinStatus.mockResolvedValue(CHECKIN_STATUS);
  source.submitCheckin.mockResolvedValue({ documentStatus: "PROVIDED", legalRegistrationStatus: "SUBMITTED" });
  source.reportIncident.mockResolvedValue({ id: "11111111-1111-1111-1111-111111111111", status: "OPEN", createdAt: "2026-08-11T10:00:00Z" });
});

describe("404 gate (R1.2, task 3.3)", () => {
  it("shows one uniform invalid-link state and hides check-in/incident, without internal detail", async () => {
    source.getStayInfo.mockRejectedValue(
      new ApiError({ code: "NOT_FOUND", message: "tenant xyz reservation gone", status: 404, details: { trace: "app/guest/service.py:42" } }),
    );
    renderView();

    expect(await screen.findByText("Este enlace no es válido")).toBeInTheDocument();
    expect(screen.getByText("Pide a tu anfitrión un enlace nuevo.")).toBeInTheDocument();
    // Check-in and incident forms are not rendered on a dead link.
    expect(screen.queryByText("Check-in")).not.toBeInTheDocument();
    expect(screen.queryByText("Comunicar una incidencia")).not.toBeInTheDocument();
    // No internal cause / trace / tenant leaks into the page.
    expect(document.body.innerHTML).not.toMatch(/tenant xyz|service\.py|trace/i);
  });
});

describe("render security regression (R1.3, R2.2, task 3.4)", () => {
  it("never renders the token anywhere on the page", async () => {
    renderView();
    await screen.findByText("Casa Redes");
    expect(document.body.innerHTML).not.toContain(TOKEN);
    expect(document.title).not.toContain(TOKEN);
  });

  it("does not echo the document number after a successful check-in", async () => {
    renderView();
    await screen.findByText("Casa Redes");
    await screen.findByLabelText("Número de documento");
    fillCheckin("ZZ-SECRET-999");
    fireEvent.click(screen.getByRole("button", { name: "Enviar check-in" }));

    await screen.findByText(/Check-in enviado/);
    const alert = screen.getByText(/Check-in enviado/);
    expect(alert.textContent).not.toContain("ZZ-SECRET-999");
  });

  it("masks nothing itself: renders the already-masked access code verbatim", async () => {
    renderView();
    expect(await screen.findByText("••1234")).toBeInTheDocument();
  });
});

describe("stay & status presentation (R1.1, R1.4, R2.1)", () => {
  it("renders a localized safe absence for null stay fields, never the literal null/undefined", async () => {
    source.getStayInfo.mockResolvedValue({ ...STAY, wifiName: null, arrivalNotes: null });
    renderView();
    await screen.findByText("Casa Redes");
    expect(document.body.innerHTML).not.toMatch(/>\s*(null|undefined)\s*</);
    expect(screen.getAllByText("No disponible").length).toBeGreaterThanOrEqual(2);
  });

  it("shows missing_fields verbatim as backend-declared info, without inferring steps", async () => {
    renderView();
    expect(await screen.findByText("Estado: full_name")).toBeInTheDocument();
  });
});

describe("check-in journey (R2, task 4.3)", () => {
  it("sends exactly the six contract fields and shows both localized statuses", async () => {
    renderView();
    await screen.findByLabelText("Número de documento");
    fillCheckin("X123");
    fireEvent.click(screen.getByRole("button", { name: "Enviar check-in" }));

    await waitFor(() => expect(source.submitCheckin).toHaveBeenCalledTimes(1));
    expect(source.submitCheckin).toHaveBeenCalledWith(TOKEN, {
      full_name: "Ana",
      nationality: "ES",
      date_of_birth: "1990-01-01",
      document_type: "DNI",
      document_number: "X123",
      document_expiry_date: "2030-01-01",
    });
    expect(await screen.findByText(/Aportado/)).toBeInTheDocument();
    expect(screen.getByText(/Enviado/)).toBeInTheDocument();
  });

  it("blocks empty submits client-side without calling the API", async () => {
    renderView();
    await screen.findByLabelText("Nombre completo");
    fireEvent.click(screen.getByRole("button", { name: "Enviar check-in" }));

    expect(await screen.findAllByText("Este campo es obligatorio.")).not.toHaveLength(0);
    expect(source.submitCheckin).not.toHaveBeenCalled();
  });

  it("disables the submit button while the mutation is in flight (no duplicates)", async () => {
    source.submitCheckin.mockReturnValue(new Promise(() => {}));
    renderView();
    await screen.findByLabelText("Número de documento");
    fillCheckin();
    const button = screen.getByRole("button", { name: "Enviar check-in" });
    fireEvent.click(button);

    await waitFor(() => expect(button).toBeDisabled());
    fireEvent.click(button);
    expect(source.submitCheckin).toHaveBeenCalledTimes(1);
  });

  it("maps a 422 to the offending field, without leaking the raw body", async () => {
    source.submitCheckin.mockRejectedValue(
      new ApiError({
        code: "VALIDATION_ERROR",
        message: "Request validation failed",
        status: 422,
        details: { errors: [{ loc: ["body", "full_name"], msg: "RAW_BACKEND_MSG", type: "value_error" }] },
      }),
    );
    renderView();
    await screen.findByLabelText("Número de documento");
    fillCheckin();
    fireEvent.click(screen.getByRole("button", { name: "Enviar check-in" }));

    await waitFor(() => expect(screen.getByLabelText("Nombre completo")).toHaveAttribute("aria-invalid", "true"));
    expect(screen.getByText("Revisa este campo.")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("RAW_BACKEND_MSG");
  });
});

describe("incident journey (R3, task 5.2)", () => {
  it("blocks an invalid report without any API call", async () => {
    renderView();
    await screen.findByLabelText("Título");
    fireEvent.click(screen.getByRole("button", { name: "Enviar aviso" }));

    expect(source.reportIncident).not.toHaveBeenCalled();
  });

  it("sends only title and description and confirms without the UUID", async () => {
    renderView();
    await screen.findByLabelText("Título");
    fireEvent.change(screen.getByLabelText("Título"), { target: { value: "Fuga" } });
    fireEvent.change(screen.getByLabelText("Descripción"), { target: { value: "Agua en la cocina" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar aviso" }));

    await waitFor(() => expect(source.reportIncident).toHaveBeenCalledWith(TOKEN, { title: "Fuga", description: "Agua en la cocina" }));
    expect(await screen.findByText(/Incidencia comunicada/)).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("11111111-1111-1111-1111-111111111111");
  });

  it("on 429 tells the guest to wait without confirming or denying creation", async () => {
    source.reportIncident.mockRejectedValue(new ApiError({ code: "RATE_LIMITED", message: "slow down", status: 429 }));
    renderView();
    await screen.findByLabelText("Título");
    fireEvent.change(screen.getByLabelText("Título"), { target: { value: "Fuga" } });
    fireEvent.change(screen.getByLabelText("Descripción"), { target: { value: "Agua" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar aviso" }));

    const message = await screen.findByText(/Espera antes de volver a intentarlo/);
    expect(message).toBeInTheDocument();
    expect(message.textContent).toMatch(/No sabemos si se recibió/);
  });
});

describe("accessibility (R4.3, task 5.4)", () => {
  it("wires labels and error descriptions and has no axe violations", async () => {
    renderView();
    const numberField = await screen.findByLabelText("Número de documento");
    // Accessible name via label association.
    expect(numberField).toHaveAttribute("id", "document_number");
    fireEvent.click(screen.getByRole("button", { name: "Enviar check-in" }));

    await waitFor(() => expect(numberField).toHaveAttribute("aria-invalid", "true"));
    expect(numberField.getAttribute("aria-describedby")).toBe("document_number-error");
    // The described-by target actually exists and carries the localized error.
    expect(document.getElementById("document_number-error")).toHaveTextContent("Este campo es obligatorio.");
    // page-has-heading-one is a best-practice rule; the portal uses section-level h2s by design (D5).
    expect(await getA11yViolations(document.body, ["page-has-heading-one"])).toEqual([]);
  });
});
