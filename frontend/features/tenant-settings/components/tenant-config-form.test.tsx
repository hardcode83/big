import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { fireEvent, render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";

const useTenantMock = vi.hoisted(() => vi.fn());
vi.mock("../hooks/use-tenant", () => ({ useTenant: useTenantMock }));

const useUpdateTenantMock = vi.hoisted(() => vi.fn());
vi.mock("../hooks/use-update-tenant", () => ({ useUpdateTenant: useUpdateTenantMock }));

const useHasPermissionMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth", () => ({ useHasPermission: useHasPermissionMock }));

import { TenantConfigForm } from "./tenant-config-form";

const TENANT = {
  id: "tenant-1",
  name: "Acme",
  billingEmail: "billing@acme.test",
  country: "ES",
  timezone: "Europe/Madrid",
  defaultLanguage: "es",
  status: "ACTIVE",
  createdAt: "2026-08-01T09:00:00Z",
  updatedAt: "2026-08-01T09:00:00Z",
  config: {
    ownerApprovalThresholdEur: "100.00",
    aiConfidenceThreshold: "0.80",
    slaCriticalMinutes: 15,
    slaHighMinutes: 30,
    slaMediumMinutes: 60,
    slaLowMinutes: 120,
    checkinWindowHoursBefore: 2,
    checkoutReadyHoursAfter: 2,
    autoCreateCleaningTask: true,
    cleaningPhotoRequired: false,
    storageType: "S3",
    notificationEmailEnabled: true,
    notificationWhatsappEnabled: false,
    reviewRecurringIssuesTopN: 5,
  },
};

function renderForm() {
  return render(<TenantConfigForm />, {
    wrapper: ({ children }) => <I18nProvider locale="es">{children}</I18nProvider>,
  });
}

describe("TenantConfigForm (R5)", () => {
  const mutate = vi.fn();

  beforeEach(() => {
    mutate.mockReset();
    useTenantMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: TENANT,
      refetch: vi.fn(),
    });
    useUpdateTenantMock.mockReturnValue({
      mutate,
      isPending: false,
      isError: false,
      isSuccess: false,
    });
  });

  it("shows the loading state", () => {
    useTenantMock.mockReturnValue({
      isPending: true,
      isError: false,
      data: undefined,
      refetch: vi.fn(),
    });
    useHasPermissionMock.mockReturnValue(true);
    renderForm();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the error state with a working retry", () => {
    const refetch = vi.fn();
    useTenantMock.mockReturnValue({ isPending: false, isError: true, data: undefined, refetch });
    useHasPermissionMock.mockReturnValue(true);
    renderForm();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("renders read-only for PROPERTY_MANAGER: fields shown, no submit control at all (R5.2, design D5)", () => {
    useHasPermissionMock.mockReturnValue(false);
    renderForm();
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("100.00")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Guardar cambios" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
  });

  it("sends only the changed top-level field on submit (R5.3)", () => {
    useHasPermissionMock.mockReturnValue(true);
    renderForm();

    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Acme Corp" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));

    expect(mutate).toHaveBeenCalledTimes(1);
    const [input] = mutate.mock.calls[0];
    expect(input).toEqual({ name: "Acme Corp" });
  });

  it("sends only the changed nested config field, wrapped under `config`, when only config changes", () => {
    useHasPermissionMock.mockReturnValue(true);
    renderForm();

    fireEvent.change(screen.getByLabelText("SLA — crítico (minutos)"), {
      target: { value: "20" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));

    expect(mutate).toHaveBeenCalledTimes(1);
    const [input] = mutate.mock.calls[0];
    expect(input).toEqual({ config: { slaCriticalMinutes: 20 } });
  });

  it("sends the threshold as the exact string typed, not a JS number (Numeric-field convention)", () => {
    useHasPermissionMock.mockReturnValue(true);
    renderForm();

    fireEvent.change(screen.getByLabelText("Umbral de aprobación del propietario (EUR)"), {
      target: { value: "250.75" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));

    const [input] = mutate.mock.calls[0];
    expect(input).toEqual({ config: { ownerApprovalThresholdEur: "250.75" } });
  });

  it("rejects client-side before any request when the time zone is invalid (R5.3)", () => {
    useHasPermissionMock.mockReturnValue(true);
    renderForm();

    fireEvent.change(screen.getByLabelText("Zona horaria"), { target: { value: "Not/AZone" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));

    expect(mutate).not.toHaveBeenCalled();
    expect(
      screen.getByText("Not a recognized IANA time zone (e.g. Europe/Madrid)."),
    ).toBeInTheDocument();
  });

  it("rejects client-side before any request when the threshold is negative (R5.3)", () => {
    useHasPermissionMock.mockReturnValue(true);
    renderForm();

    fireEvent.change(screen.getByLabelText("Umbral de aprobación del propietario (EUR)"), {
      target: { value: "-5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));

    expect(mutate).not.toHaveBeenCalled();
    expect(screen.getByText("Cannot be negative.")).toBeInTheDocument();
  });

  it("shows the inline caveat next to default_language (R5.4)", () => {
    useHasPermissionMock.mockReturnValue(true);
    renderForm();
    expect(
      screen.getByText(
        "Cambiar esto no afecta al idioma preferido ya establecido en los usuarios existentes.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the inline caveat next to owner_approval_threshold_eur (R5.5)", () => {
    useHasPermissionMock.mockReturnValue(true);
    renderForm();
    expect(
      screen.getByText(
        "Cambiar esto no reevalúa las aprobaciones del propietario ya generadas.",
      ),
    ).toBeInTheDocument();
  });

  it("surfaces a backend 422 via mapFieldErrors under the matching field", () => {
    useHasPermissionMock.mockReturnValue(true);
    useUpdateTenantMock.mockReturnValue({
      mutate,
      isPending: false,
      isError: true,
      isSuccess: false,
      error: new ApiError({
        code: "VALIDATION_ERROR",
        message: "Validation failed",
        status: 422,
        details: {
          errors: [
            {
              loc: ["body", "config", "owner_approval_threshold_eur"],
              type: "value_error",
              msg: "owner_approval_threshold_eur cannot be negative",
            },
          ],
        },
      }),
    });
    renderForm();
    expect(
      screen.getByText("owner_approval_threshold_eur cannot be negative"),
    ).toBeInTheDocument();
  });

  it("disables the submit button while the mutation is pending", () => {
    useHasPermissionMock.mockReturnValue(true);
    useUpdateTenantMock.mockReturnValue({
      mutate,
      isPending: true,
      isError: false,
      isSuccess: false,
    });
    renderForm();
    expect(screen.getByRole("button", { name: "Guardando…" })).toBeDisabled();
  });

  it("keeps a natural keyboard focus order: name first, submit reachable", () => {
    useHasPermissionMock.mockReturnValue(true);
    renderForm();
    const name = screen.getByLabelText("Nombre");
    name.focus();
    expect(name).toHaveFocus();

    const submit = screen.getByRole("button", { name: "Guardar cambios" });
    expect(submit.tabIndex).toBeGreaterThanOrEqual(0);
    submit.focus();
    expect(submit).toHaveFocus();
  });
});
