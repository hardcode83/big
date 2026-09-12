import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import * as dataModule from "../data";
import type { PropertyDetailDto } from "../data";
import { propertiesKeys } from "./query-keys";
import { useProperty } from "./use-property";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

const getMock = vi.fn();
const getPropertiesDataSource = vi.spyOn(dataModule, "getPropertiesDataSource");

getPropertiesDataSource.mockImplementation(
  () =>
    ({ getProperty: getMock }) as unknown as ReturnType<
      typeof dataModule.getPropertiesDataSource
    >,
);

/**
 * Copied deliberately from `use-properties.test.tsx`: a wrapper that does NOT
 * override the QueryClient-level retry, so the hook's own `retryPolicy` is
 * what the 4xx/5xx tests actually exercise.
 */
function freshWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retryDelay: 100 } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

const DETAIL: PropertyDetailDto = {
  id: "property-1",
  name: "Redes 11",
  internalCode: "REDES11",
  pmsProvider: "BEDS24",
  pmsExternalId: "ext-1",
  addressLine1: "Calle Redes 11",
  addressLine2: null,
  city: "Madrid",
  province: "Madrid",
  postalCode: "28000",
  country: "ES",
  timezone: "Europe/Madrid",
  maxGuests: 4,
  bedrooms: 2,
  bathrooms: 1,
  currentOperationalState: "VACANT_READY",
  defaultCheckInTime: "16:00:00",
  defaultCheckOutTime: "11:00:00",
  wifiName: "REDES11-WIFI",
  hasWifiPassword: true,
  accessNotes: "código: 1234",
  cleaningNotes: "ojo con la lavadora",
  emergencyNotes: "llamar al 600000000",
  status: "ACTIVE",
  createdAt: "2026-08-01T09:00:00Z",
  updatedAt: "2026-08-02T09:00:00Z",
};

beforeEach(() => {
  getMock.mockReset();
  getMock.mockResolvedValue(DETAIL);
});

describe("propertiesKeys.detail (design D7)", () => {
  it("scopes the key to the tenant and the property id", () => {
    const key = propertiesKeys.detail("tenant-from-session", "property-1");
    expect(key[0]).toBe("tenant");
    expect(key[1]).toBe("tenant-from-session");
    expect(key[2]).toBe("properties-detail");
    expect(key[3]).toBe("property-1");
  });

  it("gives two tenants two different keys, for the same property id", () => {
    const a = propertiesKeys.detail("tenant-a", "property-1");
    const b = propertiesKeys.detail("tenant-b", "property-1");
    expect(a).not.toEqual(b);
    expect(JSON.stringify(a)).not.toContain("tenant-b");
  });

  it("refuses to build a key without a tenant", () => {
    expect(() => propertiesKeys.detail("", "property-1")).toThrow();
  });

  it("gives two different properties two different keys", () => {
    const a = propertiesKeys.detail("tenant-1", "property-1");
    const b = propertiesKeys.detail("tenant-1", "property-2");
    expect(a).not.toEqual(b);
  });
});

describe("useProperty — tenant-scoped fetch (R2.2)", () => {
  it("passes the tenant from the session and the given id to the data source", async () => {
    const { result } = renderHook(() => useProperty("property-1"), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getMock).toHaveBeenCalledWith("tenant-from-session", "property-1");
    expect(result.current.data).toEqual(DETAIL);
  });
});

describe("useProperty — retry policy (mirrors useProperties, R3.7)", () => {
  it("does not retry a 4xx", async () => {
    getMock.mockRejectedValue(
      new ApiError({ code: "NOT_FOUND", message: "no", status: 404 }),
    );

    const { result } = renderHook(() => useProperty("property-1"), {
      wrapper: freshWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(getMock).toHaveBeenCalledTimes(1);
  });

  it("retries a 5xx before giving up", async () => {
    getMock.mockRejectedValue(
      new ApiError({ code: "BOOM", message: "boom", status: 500 }),
    );

    const { result } = renderHook(() => useProperty("property-1"), {
      wrapper: freshWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true), {
      timeout: 5000,
    });
    expect(getMock.mock.calls.length).toBeGreaterThan(1);
  });
});
