import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import type { GenerationReport, PricingDataSource } from "../data";
import { usePricingUiStore } from "../state/use-pricing-ui-store";
import { pricingKeys } from "./query-keys";
import { useGenerateRecommendations } from "./use-generate-recommendations";

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

const report: GenerationReport = {
  created: 40,
  updated: 3,
  preserved: 2,
  skipped: 1,
};

function harness() {
  const client = new QueryClient({
    // Mutations default to **retrying** here, deliberately. TanStack's own
    // default is `retry: 0` and the app's shared client sets `mutations.retry =
    // false` globally, so a harness that inherited either would let the
    // "does not retry" tests pass on the ambient default — green even if the
    // hook's own `retry: false` were deleted. Raised by the QA panel on section
    // 5. Defaulting to retry here makes the hook's own option the thing under
    // test: without it, a rejected write would be attempted four times.
    defaultOptions: { queries: { retry: false }, mutations: { retry: 3 } },
  });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, invalidate, Wrapper };
}

beforeEach(() => {
  generateRecommendations.mockReset().mockResolvedValue(report);
  listRecommendations.mockReset();
  listRules.mockReset();
  listProperties.mockReset();
  decideRecommendation.mockReset();
  usePricingUiStore.getState().reset();
  usePricingUiStore.getState().adoptTenant("tenant-1");
});

describe("useGenerateRecommendations — the scope it sweeps (R4.1)", () => {
  it("sends null when no property filter is active", async () => {
    const { Wrapper } = harness();
    const { result } = renderHook(() => useGenerateRecommendations(), {
      wrapper: Wrapper,
    });

    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(generateRecommendations).toHaveBeenCalledWith("tenant-1", null);
  });

  it("sends the property filter of the recommendations tab", async () => {
    usePricingUiStore.getState().setRecommendationPropertyId("queue-scope");
    const { Wrapper } = harness();
    const { result } = renderHook(() => useGenerateRecommendations(), {
      wrapper: Wrapper,
    });

    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(generateRecommendations).toHaveBeenCalledWith(
      "tenant-1",
      "queue-scope",
    );
  });

  it("NEVER takes the scope from the rules tab (R4.1, design D11)", async () => {
    // The silent bug D11 names: a sweep over a scope other than the one on
    // screen, because the Rules tab happened to set a property filter last.
    usePricingUiStore.getState().setRulePropertyId("rule-scope");
    const { Wrapper } = harness();
    const { result } = renderHook(() => useGenerateRecommendations(), {
      wrapper: Wrapper,
    });

    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(generateRecommendations).toHaveBeenCalledWith("tenant-1", null);
  });

  it("prefers the recommendations scope when both tabs have a filter", async () => {
    usePricingUiStore.getState().setRulePropertyId("rule-scope");
    usePricingUiStore.getState().setRecommendationPropertyId("queue-scope");
    const { Wrapper } = harness();
    const { result } = renderHook(() => useGenerateRecommendations(), {
      wrapper: Wrapper,
    });

    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(generateRecommendations).toHaveBeenCalledWith(
      "tenant-1",
      "queue-scope",
    );
  });

  it("ignores a filter left by another tenant's session (security rule 1)", async () => {
    // The store still holds tenant-2's filter and has not been re-adopted yet.
    // Sweeping that scope would send one tenant's identifier in another's write.
    usePricingUiStore.getState().adoptTenant("tenant-2");
    usePricingUiStore.getState().setRecommendationPropertyId("tenant-2-scope");
    const { Wrapper } = harness();
    const { result } = renderHook(() => useGenerateRecommendations(), {
      wrapper: Wrapper,
    });

    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(generateRecommendations).toHaveBeenCalledWith("tenant-1", null);
  });
});

describe("useGenerateRecommendations — report and invalidation (R4.2, R4.4, R3.5)", () => {
  it("returns the four counters", async () => {
    const { Wrapper } = harness();
    const { result } = renderHook(() => useGenerateRecommendations(), {
      wrapper: Wrapper,
    });

    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({
      created: 40,
      updated: 3,
      preserved: 2,
      skipped: 1,
    });
  });

  it("invalidates the recommendations prefix on success (R4.2)", async () => {
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useGenerateRecommendations(), {
      wrapper: Wrapper,
    });

    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: pricingKeys.recommendationsPrefix("tenant-1"),
    });
  });

  it("invalidates on failure too — a failed sweep may have written rows first", async () => {
    // The contract exposes no `failed` counter, so a run that ends in an error
    // cannot be distinguished from one that wrote nothing.
    generateRecommendations.mockRejectedValue(
      new ApiError({ code: "BOOM", message: "half way", status: 500 }),
    );
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useGenerateRecommendations(), {
      wrapper: Wrapper,
    });

    result.current.mutate();

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: pricingKeys.recommendationsPrefix("tenant-1"),
    });
  });

  it("never invalidates the rules key (R3.5)", async () => {
    // Generating reads rules; it does not write them.
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useGenerateRecommendations(), {
      wrapper: Wrapper,
    });

    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const propertiesKey = JSON.stringify(pricingKeys.properties("tenant-1"));
    const rulesKey = JSON.stringify(pricingKeys.rules("tenant-1", {}, 1));
    for (const call of invalidate.mock.calls) {
      const key = JSON.stringify(call[0]?.queryKey);
      expect(rulesKey.startsWith(key.slice(0, -1))).toBe(false);
      expect(key).not.toBe(propertiesKey);
    }
  });

  it("does not retry a failed sweep (R4.4)", async () => {
    // It runs synchronously inside the request; a retry would sweep again.
    generateRecommendations.mockRejectedValue(
      new ApiError({ code: "BOOM", message: "no", status: 500 }),
    );
    const { Wrapper } = harness();
    const { result } = renderHook(() => useGenerateRecommendations(), {
      wrapper: Wrapper,
    });

    result.current.mutate();

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(generateRecommendations).toHaveBeenCalledTimes(1);
  });
});
