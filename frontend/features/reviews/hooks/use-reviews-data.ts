"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { retryPolicy } from "@/lib/api/retry-policy";
import { useAuth } from "@/lib/auth";

import {
  getReviewsDataSource,
  type PropertySummary,
  type Review,
  type ReviewDraft,
  type ReviewFilters,
  type ReviewsPage,
} from "../data";
import { reviewsKeys } from "./query-keys";

/**
 * Read-side hooks for the reviews screen (design D8). They depend ONLY on
 * the `ReviewsDataSource` interface, resolved through the composition point, so
 * the component tests swap the source without touching `lib/api`.
 *
 * **Three independent queries**: a failure on any one leaves the other two
 * untouched, so a property catalog that fails degrades identity to
 * `unavailable` (R2.8) without taking the listings down with it. The detail
 * and the draft are independent too — the detail mounts only when
 * `detailReviewId` is non-null, and the draft mounts only when the detail
 * resolves and is in `DRAFTED` (R6.1).
 *
 * **No `tenant_id` argument** at the call site: every hook reads it from the
 * session, which is the single point at which tenant scoping happens. The
 * backend remains the authority for tenant isolation.
 */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error(
      "The reviews view requires an authenticated tenant context",
    );
  }
  return user.tenant_id;
}

export function useReviewsList(
  filters: ReviewFilters,
  page: number,
): UseQueryResult<ReviewsPage<Review>> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: reviewsKeys.list(tenantId, filters, page),
    queryFn: () =>
      getReviewsDataSource().listReviews(tenantId, filters, page),
    retry: retryPolicy,
  });
}

export function useReviewDetail(
  reviewId: string | null,
): UseQueryResult<Review> {
  const tenantId = useTenantId();
  return useQuery({
    enabled: reviewId !== null,
    queryKey: reviewsKeys.detail(tenantId, reviewId ?? ""),
    queryFn: () => {
      if (!reviewId) {
        // Unreachable due to `enabled`, but the type system needs the guard.
        throw new Error("reviewId is required");
      }
      return getReviewsDataSource().getReview(tenantId, reviewId);
    },
    retry: retryPolicy,
  });
}

export function useReviewDraft(
  reviewId: string | null,
  /** The detail must have resolved as `DRAFTED` to make the draft mount. */
  enabled: boolean,
): UseQueryResult<ReviewDraft> {
  const tenantId = useTenantId();
  return useQuery({
    enabled: enabled && reviewId !== null,
    queryKey: reviewsKeys.draft(tenantId, reviewId ?? ""),
    queryFn: () => {
      if (!reviewId) {
        throw new Error("reviewId is required");
      }
      return getReviewsDataSource().getDraft(tenantId, reviewId);
    },
    retry: retryPolicy,
  });
}

export function usePropertyDirectory(): UseQueryResult<PropertySummary[]> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: reviewsKeys.properties(tenantId),
    queryFn: () => getReviewsDataSource().listProperties(tenantId),
    retry: retryPolicy,
  });
}