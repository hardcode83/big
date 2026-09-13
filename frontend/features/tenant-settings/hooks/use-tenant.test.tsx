import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useTenant } from "./use-tenant";
import * as dataModule from "../data";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

const getTenantMock = vi.fn();
const getTenantSettingsDataSource = vi.spyOn(dataModule, "getTenantSettingsDataSource");
getTenantSettingsDataSource.mockImplementation(
  () =>
    ({
      getTenant: getTenantMock,
    }) as unknown as ReturnType<typeof dataModule.getTenantSettingsDataSource>,
);

function freshWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

const TENANT_PAYLOAD = {
  id: "tenant-from-session",
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

describe("useTenant", () => {
  beforeEach(() => {
    getTenantMock.mockReset();
  });

  it("calls the source with the tenant id from the session", async () => {
    getTenantMock.mockResolvedValue(TENANT_PAYLOAD);
    const { result } = renderHook(() => useTenant(), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getTenantMock).toHaveBeenCalledWith("tenant-from-session");
  });
});
