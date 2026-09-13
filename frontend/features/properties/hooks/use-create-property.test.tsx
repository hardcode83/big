import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { HttpPropertiesSource } from "../data/http/http-properties-source";
import type { PropertyDetailDto } from "../data";
import { propertiesKeys } from "./query-keys";
import { useCreateProperty } from "./use-create-property";

const createProperty = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1" } }),
}));

vi.mock("../data", () => ({
  getPropertiesDataSource: () =>
    ({
      listProperties: vi.fn(),
      getProperty: vi.fn(),
      createProperty,
    }) as unknown as HttpPropertiesSource,
}));

const created: PropertyDetailDto = {
  id: "property-1",
  name: "Redes 11",
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
  updatedAt: "2026-09-01T09:00:00Z",
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
  createProperty.mockReset().mockResolvedValue(created);
});

describe("useCreateProperty (R1.4, design D10)", () => {
  it("forwards the tenant and the input verbatim to the source", async () => {
    const { Wrapper } = harness();
    const { result } = renderHook(() => useCreateProperty(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ name: "Redes 11", internalCode: "REDES11" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(createProperty).toHaveBeenCalledWith("tenant-1", {
      name: "Redes 11",
      internalCode: "REDES11",
    });
    expect(createProperty).toHaveBeenCalledTimes(1);
  });

  it("invalidates the properties list prefix and the dashboard cards on success", async () => {
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useCreateProperty(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ name: "Redes 11", internalCode: "REDES11" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: propertiesKeys.listPrefix("tenant-1"),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["tenant", "tenant-1", "dashboard-cards"],
    });
  });

  it.each([403, 409, 422] as const)(
    "invalidates the same prefixes after a %s too",
    async (status) => {
      createProperty.mockRejectedValue(
        new ApiError({ code: "CODE", message: "no", status }),
      );
      const { invalidate, Wrapper } = harness();
      const { result } = renderHook(() => useCreateProperty(), {
        wrapper: Wrapper,
      });

      result.current.mutate({ name: "Redes 11", internalCode: "REDES11" });
      await waitFor(() => expect(result.current.isError).toBe(true));

      expect(invalidate).toHaveBeenCalledWith({
        queryKey: propertiesKeys.listPrefix("tenant-1"),
      });
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: ["tenant", "tenant-1", "dashboard-cards"],
      });
    },
  );

  it("never retries a rejected write", async () => {
    createProperty.mockRejectedValue(
      new ApiError({ code: "CONFLICT", message: "no", status: 409 }),
    );
    const { Wrapper } = harness();
    const { result } = renderHook(() => useCreateProperty(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ name: "Redes 11", internalCode: "REDES11" });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(createProperty).toHaveBeenCalledTimes(1);
  });

  it("never writes the cache optimistically", async () => {
    const { setQueryData, Wrapper } = harness();
    const { result } = renderHook(() => useCreateProperty(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ name: "Redes 11", internalCode: "REDES11" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(setQueryData).not.toHaveBeenCalled();
  });

  it("does not invalidate another tenant's entries", async () => {
    const { client, Wrapper } = harness();
    const otherTenant = ["tenant", "tenant-2", "properties-list", { page: 1 }];
    client.setQueryData(otherTenant, {
      data: [],
      page: 1,
      perPage: 20,
      total: 0,
      totalPages: 0,
    });

    const { result } = renderHook(() => useCreateProperty(), {
      wrapper: Wrapper,
    });
    result.current.mutate({ name: "Redes 11", internalCode: "REDES11" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryState(otherTenant)?.isInvalidated).toBe(false);
  });
});
