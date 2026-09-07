import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen, waitFor } from "@/test/render";

import * as dataModule from "../data";
import { CreateTenantForm } from "./create-tenant-form";

const createTenantMock = vi.fn();
vi.spyOn(dataModule, "getPlatformDataSource").mockImplementation(
  () =>
    ({
      createTenant: createTenantMock,
    }) as unknown as ReturnType<typeof dataModule.getPlatformDataSource>,
);

const TENANT_RETURNED = {
  id: "t1",
  name: "MAGNO",
  billingEmail: "billing@example.com",
  country: "ES",
  timezone: "Europe/Madrid",
  defaultLanguage: "es",
  status: "ACTIVE" as const,
  createdAt: "2026-09-04T10:00:00Z",
  updatedAt: "2026-09-04T10:00:00Z",
  config: {
    ownerApprovalThresholdEur: "100.00",
    aiConfidenceThreshold: "0.75",
    slaCriticalMinutes: 5,
    slaHighMinutes: 15,
    slaMediumMinutes: 240,
    slaLowMinutes: 480,
    checkinWindowHoursBefore: 2,
    checkoutReadyHoursAfter: 1,
    autoCreateCleaningTask: true,
    cleaningPhotoRequired: true,
    storageType: "LOCAL",
    notificationEmailEnabled: true,
    notificationWhatsappEnabled: false,
    reviewRecurringIssuesTopN: 5,
  },
};

function renderForm(onAddStaff = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <I18nProvider locale="es">{children}</I18nProvider>
      </QueryClientProvider>
    );
  }
  return { ...render(<CreateTenantForm onAddStaff={onAddStaff} />, { wrapper: Wrapper }), onAddStaff };
}

function fillForm() {
  fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "MAGNO" } });
  fireEvent.change(screen.getByLabelText("Email de facturación"), {
    target: { value: "billing@example.com" },
  });
  fireEvent.change(screen.getByLabelText(/País/), { target: { value: "ES" } });
  fireEvent.change(screen.getByLabelText("Zona horaria"), {
    target: { value: "Europe/Madrid" },
  });
}

describe("CreateTenantForm (R3.1, R3.2, R3.3, R3.4, design D5, D6)", () => {
  beforeEach(() => {
    createTenantMock.mockReset();
  });

  it("submits exactly the five CreateTenantRequest fields", async () => {
    createTenantMock.mockResolvedValue(TENANT_RETURNED);
    renderForm();
    fillForm();

    fireEvent.click(screen.getByRole("button", { name: "Crear tenant" }));

    await waitFor(() => expect(createTenantMock).toHaveBeenCalledTimes(1));
    expect(createTenantMock).toHaveBeenCalledWith({
      name: "MAGNO",
      billingEmail: "billing@example.com",
      country: "ES",
      timezone: "Europe/Madrid",
      defaultLanguage: "es",
    });
  });

  it("on success shows the created tenant and an add-staff button that calls onAddStaff", async () => {
    createTenantMock.mockResolvedValue(TENANT_RETURNED);
    const { onAddStaff } = renderForm();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "Crear tenant" }));

    await waitFor(() =>
      expect(screen.getByText(/Tenant «MAGNO» creado/)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Añadir personal" }));
    expect(onAddStaff).toHaveBeenCalledWith(TENANT_RETURNED);
  });

  it("shows per-field errors from a 422 response", async () => {
    createTenantMock.mockRejectedValue(
      new ApiError({
        code: "VALIDATION_ERROR",
        message: "Invalid request",
        status: 422,
        details: {
          errors: [
            { loc: ["body", "name"], type: "value_error", msg: "name is required" },
            {
              loc: ["body", "billing_email"],
              type: "value_error",
              msg: "not a valid email",
            },
          ],
        },
      }),
    );
    renderForm();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "Crear tenant" }));

    await waitFor(() =>
      expect(screen.getByText("name is required")).toBeInTheDocument(),
    );
    expect(screen.getByText("not a valid email")).toBeInTheDocument();
  });

  it("attributes a 409 to the name field", async () => {
    createTenantMock.mockRejectedValue(
      new ApiError({
        code: "CONFLICT",
        message: "A tenant named 'MAGNO' already exists",
        status: 409,
      }),
    );
    renderForm();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "Crear tenant" }));

    await waitFor(() =>
      expect(
        screen.getByText("A tenant named 'MAGNO' already exists"),
      ).toBeInTheDocument(),
    );
  });

  it("shows a generic error for anything else (e.g. 500)", async () => {
    createTenantMock.mockRejectedValue(
      new ApiError({ code: "SERVER_ERROR", message: "boom", status: 500 }),
    );
    renderForm();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "Crear tenant" }));

    await waitFor(() =>
      expect(
        screen.getByText("No se pudo crear el tenant. Vuelve a intentarlo."),
      ).toBeInTheDocument(),
    );
  });

  it("offers no status field", () => {
    renderForm();
    expect(screen.queryByLabelText(/Estado/)).not.toBeInTheDocument();
  });
});
