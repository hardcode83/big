import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import type { PriceRecommendation, PricingDataSource } from "../data";
import { pricingKeys } from "./query-keys";
import { useDecideRecommendation } from "./use-decide-recommendation";

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

const decided: PriceRecommendation = {
  id: "rec-1",
  propertyId: "p-1",
  pricingRuleId: "rule-1",
  date: "2026-09-01",
  recommendedPrice: "142.50",
  status: "APPROVED",
  explanation: "Base 120.00 · Season (High) +10.00%",
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
  const setQueryData = vi.spyOn(client, "setQueryData");
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, invalidate, setQueryData, Wrapper };
}

beforeEach(() => {
  decideRecommendation.mockReset().mockResolvedValue(decided);
  listRecommendations.mockReset();
  listRules.mockReset();
  listProperties.mockReset();
  generateRecommendations.mockReset();
});

describe("useDecideRecommendation (R3.1, R3.2, R3.4, R3.5)", () => {
  it("sends exactly the recommendation and the status", async () => {
    const { Wrapper } = harness();
    const { result } = renderHook(() => useDecideRecommendation(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ recommendationId: "rec-1", status: "APPROVED" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(decideRecommendation).toHaveBeenCalledWith(
      "tenant-1",
      "rec-1",
      "APPROVED",
    );
    expect(decideRecommendation).toHaveBeenCalledTimes(1);
  });

  it("carries each of the three legal moves through unchanged", async () => {
    for (const status of ["APPROVED", "REJECTED", "APPLIED_EXTERNAL"] as const) {
      decideRecommendation.mockClear();
      const { Wrapper } = harness();
      const { result } = renderHook(() => useDecideRecommendation(), {
        wrapper: Wrapper,
      });

      result.current.mutate({ recommendationId: "rec-1", status });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(decideRecommendation).toHaveBeenCalledWith(
        "tenant-1",
        "rec-1",
        status,
      );
    }
  });

  it("invalidates the recommendations prefix on success (R3.4)", async () => {
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useDecideRecommendation(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ recommendationId: "rec-1", status: "APPROVED" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: pricingKeys.recommendationsPrefix("tenant-1"),
    });
  });

  it("invalidates on failure too, because onSettled and not onSuccess (R3.4, R3.6)", async () => {
    // The case R3.6 makes visible: after a 409 the row on screen is in a state
    // this client no longer believes, so the refetch matters most when the write
    // failed. `onSuccess` would leave the stale row sitting there.
    decideRecommendation.mockRejectedValue(
      new ApiError({ code: "CONFLICT", message: "wrong state", status: 409 }),
    );
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useDecideRecommendation(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ recommendationId: "rec-1", status: "APPROVED" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: pricingKeys.recommendationsPrefix("tenant-1"),
    });
  });

  it("never invalidates the rules key (R3.5)", async () => {
    // Deciding does not write a rule, so the other tab is not refetched.
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useDecideRecommendation(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ recommendationId: "rec-1", status: "APPROVED" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const rulesPrefix = JSON.stringify(pricingKeys.rules("tenant-1", {}, 1));
    const propertiesKey = JSON.stringify(pricingKeys.properties("tenant-1"));
    for (const call of invalidate.mock.calls) {
      const key = JSON.stringify(call[0]?.queryKey);
      expect(rulesPrefix.startsWith(key.slice(0, -1))).toBe(false);
      expect(key).not.toBe(propertiesKey);
    }
  });

  it("does not patch the cache optimistically (R3.4)", async () => {
    // No instant in which a row shows a decision the backend did not confirm.
    const { setQueryData, Wrapper } = harness();
    const { result } = renderHook(() => useDecideRecommendation(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ recommendationId: "rec-1", status: "APPROVED" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(setQueryData).not.toHaveBeenCalled();
  });

  it("does not retry a rejected write (R3.4)", async () => {
    decideRecommendation.mockRejectedValue(
      new ApiError({ code: "CONFLICT", message: "wrong state", status: 409 }),
    );
    const { Wrapper } = harness();
    const { result } = renderHook(() => useDecideRecommendation(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ recommendationId: "rec-1", status: "APPROVED" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(decideRecommendation).toHaveBeenCalledTimes(1);
  });

  it("exposes the failure rather than swallowing it (R3.8)", async () => {
    decideRecommendation.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "nope", status: 403 }),
    );
    const { Wrapper } = harness();
    const { result } = renderHook(() => useDecideRecommendation(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ recommendationId: "rec-1", status: "APPROVED" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.isSuccess).toBe(false);
    expect((result.current.error as ApiError).status).toBe(403);
  });
});
