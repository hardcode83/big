import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import type { ReviewsDataSource } from "../data";
import {
  useReviewDetail,
  useReviewDraft,
  useReviewsList,
  usePropertyDirectory,
} from "./use-reviews-data";

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
  listReviews.mockReset().mockResolvedValue(page([]));
  getReview.mockReset();
  getDraft.mockReset();
  createReview.mockReset();
  respondToReview.mockReset();
  listProperties.mockReset().mockResolvedValue([]);
});

describe("useReviewsList (R2.1, R5.1)", () => {
  it("passes the tenant, the filters and the page to the source", async () => {
    const { Wrapper } = harness();
    const filters = { status: "DRAFTED" as const, propertyId: "p-1" };
    const { result } = renderHook(() => useReviewsList(filters, 2), {
      wrapper: Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listReviews).toHaveBeenCalledWith("tenant-1", filters, 2);
  });

  it("does not retry a 4xx, per the shared retry policy", async () => {
    listReviews.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "no", status: 403 }),
    );
    const client = new QueryClient();
    function Wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const { result } = renderHook(() => useReviewsList({}, 1), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(listReviews).toHaveBeenCalledTimes(1);
  });
});

describe("useReviewDetail (R6.1)", () => {
  it("does not fire when reviewId is null", () => {
    const { Wrapper } = harness();
    renderHook(() => useReviewDetail(null), { wrapper: Wrapper });
    expect(getReview).not.toHaveBeenCalled();
  });

  it("fires once given a reviewId", async () => {
    getReview.mockResolvedValue({ id: "rev-1" });
    const { Wrapper } = harness();
    const { result } = renderHook(() => useReviewDetail("rev-1"), {
      wrapper: Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getReview).toHaveBeenCalledWith("tenant-1", "rev-1");
  });
});

describe("useReviewDraft (R6.1: only when the detail resolved DRAFTED)", () => {
  it("does not fire when disabled, even with a reviewId", () => {
    const { Wrapper } = harness();
    renderHook(() => useReviewDraft("rev-1", false), { wrapper: Wrapper });
    expect(getDraft).not.toHaveBeenCalled();
  });

  it("does not fire when reviewId is null, even if enabled", () => {
    const { Wrapper } = harness();
    renderHook(() => useReviewDraft(null, true), { wrapper: Wrapper });
    expect(getDraft).not.toHaveBeenCalled();
  });

  it("fires when enabled and reviewId is present", async () => {
    getDraft.mockResolvedValue({ reviewId: "rev-1", draftContent: "x", language: "en" });
    const { Wrapper } = harness();
    const { result } = renderHook(() => useReviewDraft("rev-1", true), {
      wrapper: Wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getDraft).toHaveBeenCalledWith("tenant-1", "rev-1");
  });
});

describe("usePropertyDirectory — the catalog failure is isolated (R2.8)", () => {
  it("leaves the listings query untouched when the catalog fails", async () => {
    listProperties.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "no catalog", status: 403 }),
    );
    const { Wrapper } = harness();

    const reviews = renderHook(() => useReviewsList({}, 1), { wrapper: Wrapper });
    const catalog = renderHook(() => usePropertyDirectory(), { wrapper: Wrapper });

    await waitFor(() => expect(catalog.result.current.isError).toBe(true));
    await waitFor(() => expect(reviews.result.current.isSuccess).toBe(true));
    expect(reviews.result.current.isError).toBe(false);
  });

  it("asks for the catalog without filters or page, so one copy is shared", async () => {
    const { Wrapper } = harness();
    const { result } = renderHook(() => usePropertyDirectory(), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listProperties).toHaveBeenCalledWith("tenant-1");
  });
});
