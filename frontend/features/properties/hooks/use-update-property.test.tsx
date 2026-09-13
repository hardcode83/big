import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { HttpPropertiesSource } from "../data/http/http-properties-source";
import type { PropertyDetailDto } from "../data";
import { propertiesKeys } from "./query-keys";
import { useUpdateProperty } from "./use-update-property";

const updateProperty = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1" } }),
}));

vi.mock("../data", () => ({
  getPropertiesDataSource: () =>
    ({
      listProperties: vi.fn(),
      getProperty: vi.fn(),
      updateProperty,
    }) as unknown as HttpPropertiesSource,
}));

const updated: PropertyDetailDto = {
  id: "property-1",
  name: "Redes 12",
  internalCode: "REDES11",
  pmsProvider: null,
  pmsExternalId: null,
  addressLine1: null,
  addressLine2: null,
  city: null,
  province: null,
  postalCode: null,
  country: "ES",
  timezone: "Europe/Madrid",
  maxGuests: 2,
  bedrooms: 1,
  bathrooms: 1,
  currentOperationalState: "VACANT_READY",
  defaultCheckInTime: "15:00:00",
  defaultCheckOutTime: "11:00:00",
  wifiName: null,
  hasWifiPassword: false,
  accessNotes: null,
  cleaningNotes: null,
  emergencyNotes: null,
  status: "ACTIVE",
  createdAt: "2026-09-01T09:00:00Z",
  updatedAt: "2026-09-02T09:00:00Z",
};

function harness() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: 3 } },
  });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const setQueryData = vi.spyOn(client, "setQueryData");
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, invalidate, setQueryData, Wrapper };
}

beforeEach(() => {
  updateProperty.mockReset().mockResolvedValue(updated);
});

describe("useUpdateProperty (R2.2, R2.6, design D8, D9, D10)", () => {
  it("forwards the tenant, id and input verbatim to the source", async () => {
    const { Wrapper } = harness();
    const { result } = renderHook(() => useUpdateProperty(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ id: "property-1", input: { name: "Redes 12" } });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(updateProperty).toHaveBeenCalledWith("tenant-1", "property-1", {
      name: "Redes 12",
    });
    expect(updateProperty).toHaveBeenCalledTimes(1);
  });

  it("forwards exactly { status: 'INACTIVE' } for the retire path (R2.6)", async () => {
    const { Wrapper } = harness();
    const { result } = renderHook(() => useUpdateProperty(), {
      wrapper: Wrapper,
    });

    result.current.mutate({
      id: "property-1",
      input: { status: "INACTIVE" },
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(updateProperty).toHaveBeenCalledWith("tenant-1", "property-1", {
      status: "INACTIVE",
    });
  });

  it("invalidates exactly the four documented prefixes on success (design D10)", async () => {
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useUpdateProperty(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ id: "property-1", input: { name: "Redes 12" } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const called = invalidate.mock.calls.map((call) => call[0]?.queryKey);
    expect(called).toEqual(
      expect.arrayContaining([
        propertiesKeys.listPrefix("tenant-1"),
        propertiesKeys.detail("tenant-1", "property-1"),
        ["tenant", "tenant-1", "dashboard-cards"],
        ["tenant", "tenant-1", "property-detail", "property-1"],
      ]),
    );
    expect(called).toHaveLength(4);
  });

  it("invalidates the same four prefixes after a 4xx too", async () => {
    updateProperty.mockRejectedValue(
      new ApiError({ code: "CONFLICT", message: "no", status: 409 }),
    );
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useUpdateProperty(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ id: "property-1", input: { name: "Redes 12" } });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const called = invalidate.mock.calls.map((call) => call[0]?.queryKey);
    expect(called).toEqual(
      expect.arrayContaining([
        propertiesKeys.listPrefix("tenant-1"),
        propertiesKeys.detail("tenant-1", "property-1"),
        ["tenant", "tenant-1", "dashboard-cards"],
        ["tenant", "tenant-1", "property-detail", "property-1"],
      ]),
    );
  });

  it("never retries a rejected write", async () => {
    updateProperty.mockRejectedValue(
      new ApiError({ code: "CONFLICT", message: "no", status: 409 }),
    );
    const { Wrapper } = harness();
    const { result } = renderHook(() => useUpdateProperty(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ id: "property-1", input: { name: "Redes 12" } });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(updateProperty).toHaveBeenCalledTimes(1);
  });

  it("never writes the cache optimistically", async () => {
    const { setQueryData, Wrapper } = harness();
    const { result } = renderHook(() => useUpdateProperty(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ id: "property-1", input: { name: "Redes 12" } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(setQueryData).not.toHaveBeenCalled();
  });

  it("does not invalidate another tenant's entries", async () => {
    const { client, Wrapper } = harness();
    const otherTenantDetail = propertiesKeys.detail("tenant-2", "property-1");
    client.setQueryData(otherTenantDetail, updated);

    const { result } = renderHook(() => useUpdateProperty(), {
      wrapper: Wrapper,
    });
    result.current.mutate({ id: "property-1", input: { name: "Redes 12" } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryState(otherTenantDetail)?.isInvalidated).toBe(false);
  });
});
