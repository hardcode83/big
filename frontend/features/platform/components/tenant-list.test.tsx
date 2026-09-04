import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen, waitFor } from "@/test/render";

import type { TenantListDto, TenantSummaryDto } from "../dto";
import * as dataModule from "../data";
import { TenantList } from "./tenant-list";

vi.mock("@/lib/api/retry-policy", () => ({
  retryPolicy: () => false,
}));

const listTenantsMock = vi.fn();
vi.spyOn(dataModule, "getPlatformDataSource").mockImplementation(
  () =>
    ({
      listTenants: listTenantsMock,
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

function tenant(overrides: Partial<TenantSummaryDto> = {}): TenantSummaryDto {
  return {
    id: "t1",
    name: "MAGNO",
    billingEmail: "billing@example.com",
    country: "ES",
    timezone: "Europe/Madrid",
    defaultLanguage: "es",
    status: "ACTIVE",
    createdAt: "2026-09-01T10:00:00Z",
    updatedAt: "2026-09-01T10:00:00Z",
    config: CONFIG,
    ...overrides,
  };
}

function page(overrides: Partial<TenantListDto> = {}): TenantListDto {
  return {
    items: [tenant()],
    total: 1,
    page: 1,
    perPage: 20,
    totalPages: 1,
    ...overrides,
  };
}

function renderList(onAddStaff: (tenant: TenantSummaryDto) => void = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <I18nProvider locale="es">{children}</I18nProvider>
      </QueryClientProvider>
    );
  }
  return render(<TenantList onAddStaff={onAddStaff} />, { wrapper: Wrapper });
}

describe("TenantList (R2.6, design D6)", () => {
  beforeEach(() => {
    listTenantsMock.mockReset();
  });

  it("shows a loading state, then the tenant's name/status/createdAt", async () => {
    listTenantsMock.mockResolvedValue(page());
    renderList();

    await waitFor(() =>
      expect(screen.getByText("MAGNO")).toBeInTheDocument(),
    );
    expect(screen.getByText("Activo")).toBeInTheDocument();
    expect(screen.getByText("2026-09-01")).toBeInTheDocument();
  });

  it("renders the empty state when there are no tenants", async () => {
    listTenantsMock.mockResolvedValue(page({ items: [], total: 0, totalPages: 0 }));
    renderList();

    await waitFor(() =>
      expect(screen.getByText("Sin tenants")).toBeInTheDocument(),
    );
  });

  it("renders the error state and retries on demand", async () => {
    listTenantsMock.mockRejectedValueOnce(new Error("boom"));
    listTenantsMock.mockResolvedValueOnce(page());
    renderList();

    await waitFor(() =>
      expect(
        screen.getByText("No se pudo cargar la lista de tenants"),
      ).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /Reintentar|Volver/ }));
    await waitFor(() => expect(screen.getByText("MAGNO")).toBeInTheDocument());
  });

  it("does not show pagination for a single page", async () => {
    listTenantsMock.mockResolvedValue(page());
    renderList();

    await waitFor(() => expect(screen.getByText("MAGNO")).toBeInTheDocument());
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("shows pagination and asks for the next page when totalPages > 1", async () => {
    listTenantsMock.mockResolvedValue(
      page({ total: 30, totalPages: 2 }),
    );
    renderList();

    await waitFor(() => expect(screen.getByText("MAGNO")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));

    await waitFor(() =>
      expect(listTenantsMock).toHaveBeenLastCalledWith(2, 20),
    );
  });

  it("calls onAddStaff with the row's tenant when its action is clicked", async () => {
    const onAddStaff = vi.fn();
    const row = tenant({ id: "t2", name: "Redes 11" });
    listTenantsMock.mockResolvedValue(page({ items: [row] }));
    renderList(onAddStaff);

    await waitFor(() => expect(screen.getByText("Redes 11")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Añadir personal" }));

    expect(onAddStaff).toHaveBeenCalledWith(row);
  });
});
