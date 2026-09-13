import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import type { Review, ReviewsDataSource } from "../data";
import { reviewsKeys } from "./query-keys";
import { useCreateReview, useRespondToReview } from "./use-respond-to-review";

const listReviews = vi.hoisted(() => vi.fn());
const getReview = vi.hoisted(() => vi.fn());
const getDraft = vi.hoisted(() => vi.fn());
const createReview = vi.hoisted(() => vi.fn());
const respondToReview = vi.hoisted(() => vi.fn());
const listProperties = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1" } }),
}));

vi.mock("../data", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../data")>()),
  getReviewsDataSource: (): ReviewsDataSource => ({
    listReviews,
    getReview,
    getDraft,
    createReview,
    respondToReview,
    listProperties,
  }),
}));

const RESPONDED: Review = {
  id: "rev-1",
  propertyId: "p-1",
  reviewerName: "Jane",
  rating: "4.0",
  content: "ok",
  sentiment: "POSITIVE",
  aiSummary: null,
  recurringIssues: [],
  status: "APPROVED",
  publishedAt: "2026-09-01",
  channel: "AIRBNB",
  language: "en",
};

function harness(mutationRetry: number | boolean = 3) {
  // Mutations default to **retrying** here, deliberately (raised by the QA
  // panel on pricing-web's equivalent hook, section 5): TanStack's own
  // default is `retry: 0` and the app's shared client sets
  // `mutations.retry = false` globally, so a harness that inherited either
  // would let a "does not retry" test pass on the ambient default. Setting
  // it here makes the hook's own `retry: false` option the thing under test.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: mutationRetry } },
  });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const setQueryData = vi.spyOn(client, "setQueryData");
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, invalidate, setQueryData, Wrapper };
}

beforeEach(() => {
  listReviews.mockReset();
  getReview.mockReset();
  getDraft.mockReset();
  createReview.mockReset();
  respondToReview.mockReset().mockResolvedValue(RESPONDED);
  listProperties.mockReset();
});

describe("useRespondToReview (R3.1-R3.5, design D8)", () => {
  it("sends the discriminated input as-is for the three simple moves", async () => {
    const { Wrapper } = harness();
    const { result } = renderHook(() => useRespondToReview(), { wrapper: Wrapper });

    result.current.mutate({ reviewId: "rev-1", action: "APPROVE" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(respondToReview).toHaveBeenCalledWith("tenant-1", {
      reviewId: "rev-1",
      action: "APPROVE",
    });
  });

  it("carries draftContent through for EDIT", async () => {
    const { Wrapper } = harness();
    const { result } = renderHook(() => useRespondToReview(), { wrapper: Wrapper });

    result.current.mutate({
      reviewId: "rev-1",
      action: "EDIT",
      draftContent: "Updated",
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(respondToReview).toHaveBeenCalledWith("tenant-1", {
      reviewId: "rev-1",
      action: "EDIT",
      draftContent: "Updated",
    });
  });

  it("invalidates the reviews prefix on success (R3.4)", async () => {
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useRespondToReview(), { wrapper: Wrapper });

    result.current.mutate({ reviewId: "rev-1", action: "APPROVE" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: reviewsKeys.listPrefix("tenant-1"),
    });
  });

  it("invalidates on failure too, because onSettled and not onSuccess (R3.5)", async () => {
    respondToReview.mockRejectedValue(
      new ApiError({ code: "CONFLICT", message: "wrong state", status: 409 }),
    );
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useRespondToReview(), { wrapper: Wrapper });

    result.current.mutate({ reviewId: "rev-1", action: "APPROVE" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: reviewsKeys.listPrefix("tenant-1"),
    });
  });

  it("does not patch the cache optimistically (R3.4)", async () => {
    const { setQueryData, Wrapper } = harness();
    const { result } = renderHook(() => useRespondToReview(), { wrapper: Wrapper });

    result.current.mutate({ reviewId: "rev-1", action: "APPROVE" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(setQueryData).not.toHaveBeenCalled();
  });

  it("does not retry a rejected write", async () => {
    respondToReview.mockRejectedValue(
      new ApiError({ code: "CONFLICT", message: "wrong state", status: 409 }),
    );
    const { Wrapper } = harness();
    const { result } = renderHook(() => useRespondToReview(), { wrapper: Wrapper });

    result.current.mutate({ reviewId: "rev-1", action: "APPROVE" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(respondToReview).toHaveBeenCalledTimes(1);
  });

  it("exposes the failure rather than swallowing it", async () => {
    respondToReview.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "nope", status: 403 }),
    );
    const { Wrapper } = harness();
    const { result } = renderHook(() => useRespondToReview(), { wrapper: Wrapper });

    result.current.mutate({ reviewId: "rev-1", action: "APPROVE" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as ApiError).status).toBe(403);
  });
});

describe("useCreateReview (R5.1, design D8/D11)", () => {
  it("sends the input to createReview with the tenant", async () => {
    createReview.mockResolvedValue(RESPONDED);
    const { Wrapper } = harness();
    const { result } = renderHook(() => useCreateReview(), { wrapper: Wrapper });

    result.current.mutate({ propertyId: "p-1", channel: "AIRBNB", rating: 5 });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(createReview).toHaveBeenCalledWith("tenant-1", {
      propertyId: "p-1",
      channel: "AIRBNB",
      rating: 5,
    });
  });

  it("invalidates the same reviews prefix on success, so both tabs refresh", async () => {
    createReview.mockResolvedValue(RESPONDED);
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useCreateReview(), { wrapper: Wrapper });

    result.current.mutate({ propertyId: "p-1", channel: "AIRBNB", rating: 5 });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: reviewsKeys.listPrefix("tenant-1"),
    });
  });

  it("does not retry a rejected create", async () => {
    createReview.mockRejectedValue(
      new ApiError({ code: "UNPROCESSABLE_ENTITY", message: "bad", status: 422 }),
    );
    const { Wrapper } = harness();
    const { result } = renderHook(() => useCreateReview(), { wrapper: Wrapper });

    result.current.mutate({ propertyId: "p-1", channel: "AIRBNB", rating: 5 });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(createReview).toHaveBeenCalledTimes(1);
  });
});
