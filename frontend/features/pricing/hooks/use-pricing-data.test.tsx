import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import type { PricingDataSource } from "../data";
import {
  usePricingRules,
  usePropertyDirectory,
  useRecommendations,
} from "./use-pricing-data";

const listRecommendations = vi.hoisted(() => vi.fn());
const listRules = vi.hoisted(() => vi.fn());
const listProperties = vi.hoisted(() => vi.fn());
const decideRecommendation = vi.hoisted(() => vi.fn());
const generateRecommendations = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1" } }),
}));

vi.mock("../data", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../data")>()),
  getPricingDataSource: (): PricingDataSource => ({
    listRecommendations,
    listRules,
    listProperties,
    decideRecommendation,
    generateRecommendations,
  }),
}));

function page(items: unknown[]) {
  return { items, total: items.length, page: 1, perPage: 20, totalPages: 1 };
}

function harness() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, Wrapper };
}

beforeEach(() => {
  listRecommendations.mockReset().mockResolvedValue(page([]));
  listRules.mockReset().mockResolvedValue(page([]));
  listProperties.mockReset().mockResolvedValue([]);
  decideRecommendation.mockReset();
  generateRecommendations.mockReset();
});

describe("useRecommendations (R2.1)", () => {
  it("passes the tenant, the filters and the page to the source", async () => {
    const { Wrapper } = harness();
    const filters = { status: "RECOMMENDED" as const, propertyId: "p-1" };
    const { result } = renderHook(() => useRecommendations(filters, 3), {
      wrapper: Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listRecommendations).toHaveBeenCalledWith("tenant-1", filters, 3);
  });

  it("does not retry a 4xx, per the shared retry policy", async () => {
    listRecommendations.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "no", status: 403 }),
    );
    const client = new QueryClient();
    function Wrapper({ children }: { children: ReactNode }) {
      return (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      );
    }
    const { result } = renderHook(() => useRecommendations({}, 1), {
      wrapper: Wrapper,
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(listRecommendations).toHaveBeenCalledTimes(1);
  });
});

describe("usePricingRules (R5.1)", () => {
  it("passes the tenant, the filters and the page to the source", async () => {
    const { Wrapper } = harness();
    const filters = { active: true, propertyId: "p-2" };
    const { result } = renderHook(() => usePricingRules(filters, 2), {
      wrapper: Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listRules).toHaveBeenCalledWith("tenant-1", filters, 2);
  });
});

describe("the catalog failure is isolated (R2.8)", () => {
  it("leaves the two list queries untouched when the catalog fails", async () => {
    // R2.8: «un fallo del catálogo de viviendas SHALL NOT propagar al estado de
    // error de la vista». The queries are independent, so the catalog can be in
    // error while the data the screen is actually for has arrived.
    // A 403, not a 500: `retryPolicy` refuses to retry a 4xx, so the query
    // settles into error immediately. It is also the realistic case — a role
    // without `READ_PROPERTIES` reaching `/pricing` from the unfiltered sidebar.
    listProperties.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "no catalog", status: 403 }),
    );
    const { Wrapper } = harness();

    const recommendations = renderHook(() => useRecommendations({}, 1), {
      wrapper: Wrapper,
    });
    const rules = renderHook(() => usePricingRules({}, 1), {
      wrapper: Wrapper,
    });
    const catalog = renderHook(() => usePropertyDirectory(), {
      wrapper: Wrapper,
    });

    await waitFor(() => expect(catalog.result.current.isError).toBe(true));
    await waitFor(() =>
      expect(recommendations.result.current.isSuccess).toBe(true),
    );
    expect(rules.result.current.isError).toBe(false);
    expect(recommendations.result.current.isError).toBe(false);
  });

  it("asks for the catalog without filters or page, so one copy is shared", async () => {
    const { Wrapper } = harness();
    const { result } = renderHook(() => usePropertyDirectory(), {
      wrapper: Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listProperties).toHaveBeenCalledWith("tenant-1");
  });

  it("serves both consumers of the catalog from one request", async () => {
    const { Wrapper } = harness();
    const first = renderHook(() => usePropertyDirectory(), {
      wrapper: Wrapper,
    });
    const second = renderHook(() => usePropertyDirectory(), {
      wrapper: Wrapper,
    });

    await waitFor(() => expect(first.result.current.isSuccess).toBe(true));
    await waitFor(() => expect(second.result.current.isSuccess).toBe(true));
    expect(listProperties).toHaveBeenCalledTimes(1);
  });
});
