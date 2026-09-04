import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as dataModule from "../data";
import { useCreateTenant } from "./use-create-tenant";

const createTenantMock = vi.fn();
const getPlatformDataSource = vi.spyOn(dataModule, "getPlatformDataSource");

getPlatformDataSource.mockImplementation(
  () =>
    ({
      createTenant: createTenantMock,
    }) as unknown as ReturnType<typeof dataModule.getPlatformDataSource>,
);

const INPUT = {
  name: "MAGNO",
  billingEmail: "billing@example.com",
  country: "ES",
  timezone: "Europe/Madrid",
  defaultLanguage: "es" as const,
};

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

function freshWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

describe("useCreateTenant (R3.1, R3.2, design D6)", () => {
  beforeEach(() => {
    createTenantMock.mockReset();
    createTenantMock.mockResolvedValue(TENANT_RETURNED);
  });

  it("calls createTenant with the input untouched", async () => {
    const { result } = renderHook(() => useCreateTenant(), { wrapper: freshWrapper() });

    result.current.mutate(INPUT);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(createTenantMock).toHaveBeenCalledTimes(1);
    expect(createTenantMock).toHaveBeenCalledWith(INPUT);
    expect(result.current.data).toEqual(TENANT_RETURNED);
  });

  it("uses retry: false (rejected writes are not retried)", async () => {
    const { result } = renderHook(() => useCreateTenant(), { wrapper: freshWrapper() });

    result.current.mutate(INPUT);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.failureCount).toBe(0);
  });

  it("never invalidates platformKeys.tenantsList on success (R3.2's explicit 'no refetch')", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useCreateTenant(), { wrapper });

    result.current.mutate(INPUT);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("never invalidates anything on failure either", async () => {
    createTenantMock.mockRejectedValue(new Error("conflict"));
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useCreateTenant(), { wrapper });

    result.current.mutate(INPUT);
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(invalidateSpy).not.toHaveBeenCalled();
  });
});
