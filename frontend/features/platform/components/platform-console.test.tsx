import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen, waitFor } from "@/test/render";

import * as dataModule from "../data";
import { PlatformConsole } from "./platform-console";

vi.mock("@/lib/api/retry-policy", () => ({
  retryPolicy: () => false,
}));

const listTenantsMock = vi.fn();
const createTenantMock = vi.fn();
const createUserMock = vi.fn();
vi.spyOn(dataModule, "getPlatformDataSource").mockImplementation(
  () =>
    ({
      listTenants: listTenantsMock,
      createTenant: createTenantMock,
      createUserInTenant: createUserMock,
    }) as unknown as ReturnType<typeof dataModule.getPlatformDataSource>,
);

const CONFIG = {
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
};

const EXISTING_TENANT = {
  id: "t-existing",
  name: "Redes 11",
  billingEmail: "billing@example.com",
  country: "ES",
  timezone: "Europe/Madrid",
  defaultLanguage: "es" as const,
  status: "ACTIVE" as const,
  createdAt: "2026-09-01T10:00:00Z",
  updatedAt: "2026-09-01T10:00:00Z",
  config: CONFIG,
};

const NEW_TENANT = {
  id: "t-new",
  name: "MAGNO",
  billingEmail: "billing@magno.example.com",
  country: "ES",
  timezone: "Europe/Madrid",
  defaultLanguage: "es" as const,
  status: "ACTIVE" as const,
  createdAt: "2026-09-04T10:00:00Z",
  updatedAt: "2026-09-04T10:00:00Z",
  config: CONFIG,
};

const CREATED_USER = {
  temporaryPassword: "temp-pass-123",
  user: {
    id: "u1",
    tenantId: "t-new",
    name: "Persona Nueva",
    email: "new@example.com",
    role: "PROPERTY_MANAGER" as const,
    status: "ACTIVE" as const,
    phone: null,
    preferredLanguage: "es",
    lastLoginAt: null,
    createdAt: "2026-09-04T10:00:00Z",
    updatedAt: "2026-09-04T10:00:00Z",
  },
};

function renderConsole() {
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
  return { ...render(<PlatformConsole />, { wrapper: Wrapper }), client };
}

describe("PlatformConsole (R2, R3, R4, design D6)", () => {
  beforeEach(() => {
    listTenantsMock.mockReset();
    createTenantMock.mockReset();
    createUserMock.mockReset();
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    listTenantsMock.mockResolvedValue({
      items: [EXISTING_TENANT],
      total: 1,
      page: 1,
      perPage: 20,
      totalPages: 1,
    });
  });

  it("no Sheet is open initially, and no list refetch happens after opening/closing it", async () => {
    renderConsole();
    await waitFor(() => expect(screen.getByText("Redes 11")).toBeInTheDocument());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(listTenantsMock).toHaveBeenCalledTimes(1);
  });

  it("goes from 'new tenant' through create-tenant, add-staff, create-user, to the temporary password — one continuous flow, no navigation", async () => {
    createTenantMock.mockResolvedValue(NEW_TENANT);
    createUserMock.mockResolvedValue(CREATED_USER);
    renderConsole();
    await waitFor(() => expect(screen.getByText("Redes 11")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Nuevo tenant" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "MAGNO" } });
    fireEvent.change(screen.getByLabelText("Email de facturación"), {
      target: { value: "billing@magno.example.com" },
    });
    fireEvent.change(screen.getByLabelText(/País/), { target: { value: "ES" } });
    fireEvent.change(screen.getByLabelText("Zona horaria"), {
      target: { value: "Europe/Madrid" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear tenant" }));

    await waitFor(() =>
      expect(screen.getByText(/Tenant «MAGNO» creado/)).toBeInTheDocument(),
    );
    // R3.2: the list is not re-fetched as part of this flow.
    expect(listTenantsMock).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Añadir personal" }));
    fireEvent.change(screen.getByLabelText("Nombre completo"), {
      target: { value: "Persona Nueva" },
    });
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "new@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear cuenta" }));

    await waitFor(() =>
      expect(screen.getByText("temp-pass-123")).toBeInTheDocument(),
    );
    expect(createUserMock).toHaveBeenCalledWith(
      "t-new",
      expect.objectContaining({ fullName: "Persona Nueva" }),
    );
    // Still the same Sheet the whole way — the flow never navigated.
    expect(listTenantsMock).toHaveBeenCalledTimes(1);
  });

  it("a tenant row's 'add staff' action opens the create-user form pre-scoped to that row's id, without going through create-tenant", async () => {
    createUserMock.mockResolvedValue(CREATED_USER);
    renderConsole();
    await waitFor(() => expect(screen.getByText("Redes 11")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Añadir personal" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Nombre completo")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Nombre completo"), {
      target: { value: "Persona Nueva" },
    });
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "new@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear cuenta" }));

    await waitFor(() =>
      expect(createUserMock).toHaveBeenCalledWith(
        "t-existing",
        expect.anything(),
      ),
    );
  });

  it("does not retain the temporary password in the query client's mutation cache once the Sheet closes (R4.4)", async () => {
    createUserMock.mockResolvedValue(CREATED_USER);
    const { client } = renderConsole();
    await waitFor(() => expect(screen.getByText("Redes 11")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Añadir personal" }));
    fireEvent.change(screen.getByLabelText("Nombre completo"), {
      target: { value: "Persona Nueva" },
    });
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "new@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear cuenta" }));
    await waitFor(() => expect(screen.getByText("temp-pass-123")).toBeInTheDocument());

    // `useCreatePlatformUser`'s `gcTime: 0` (fixed after the section-6 security review)
    // means the mutation is garbage-collected as soon as it has no observer — i.e. the
    // instant `CreateUserForm` unmounts, not after TanStack Query's default 5-minute
    // `gcTime`. Closing the Sheet is what unmounts it.
    fireEvent.click(screen.getByRole("button", { name: "Cerrar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    const serialisedCache = JSON.stringify(
      client.getMutationCache().getAll().map((mutation) => mutation.state),
    );
    expect(serialisedCache).not.toContain("temp-pass-123");
  });
});
