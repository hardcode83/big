import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useUpdateTenant } from "./use-update-tenant";
import * as dataModule from "../data";
import { tenantSettingsKeys } from "./query-keys";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

const updateTenantMock = vi.fn();
const getTenantSettingsDataSource = vi.spyOn(dataModule, "getTenantSettingsDataSource");
getTenantSettingsDataSource.mockImplementation(
  () =>
    ({
      updateTenant: updateTenantMock,
    }) as unknown as ReturnType<typeof dataModule.getTenantSettingsDataSource>,
);

const TENANT_PAYLOAD = {
  id: "tenant-from-session",
  name: "Acme Renamed",
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

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useUpdateTenant", () => {
  beforeEach(() => {
    updateTenantMock.mockReset();
  });

  it("sends only the changed fields to the source", async () => {
    updateTenantMock.mockResolvedValue(TENANT_PAYLOAD);
    const client = makeClient();
    const { result } = renderHook(() => useUpdateTenant(), {
      wrapper: wrapperFor(client),
    });
    result.current.mutate({ name: "Acme Renamed" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(updateTenantMock).toHaveBeenCalledWith("tenant-from-session", {
      name: "Acme Renamed",
    });
  });

  it("invalidates tenantDetail on success", async () => {
    updateTenantMock.mockResolvedValue(TENANT_PAYLOAD);
    const client = makeClient();
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useUpdateTenant(), {
      wrapper: wrapperFor(client),
    });
    result.current.mutate({ config: { slaCriticalMinutes: 10 } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: tenantSettingsKeys.tenantDetail("tenant-from-session"),
    });
  });
});
