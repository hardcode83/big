"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { retryPolicy } from "@/lib/api/retry-policy";
import { useAuth } from "@/lib/auth";

import {
  getPricingDataSource,
  type PriceRecommendation,
  type PricingPage,
  type PricingRule,
  type PricingRuleFilters,
  type PropertySummary,
  type RecommendationFilters,
} from "../data";
import { pricingKeys } from "./query-keys";

/**
 * Read-side hooks for the pricing screen. They depend ONLY on the
 * `PricingDataSource` interface, resolved through the composition point, so the
 * component tests swap the source without touching `lib/api`.
 *
 * The property catalog is keyed without filters or page, so TanStack Query shares
 * one cached copy across every row and across paging and filtering.
 *
 * **The three queries are independent, and that is what R2.8 needs**: a catalog
 * that fails leaves `usePropertyDirectory` in error while the other two are
 * untouched, so the view can degrade the identity without taking the screen down.
 * Nothing here couples them.
 */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user) {
    throw new Error("The pricing view requires an authenticated tenant context");
  }
  return user.tenant_id;
}

export function useRecommendations(
  filters: RecommendationFilters,
  page: number,
): UseQueryResult<PricingPage<PriceRecommendation>> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: pricingKeys.recommendations(tenantId, filters, page),
    queryFn: () =>
      getPricingDataSource().listRecommendations(tenantId, filters, page),
    retry: retryPolicy,
  });
}

export function usePricingRules(
  filters: PricingRuleFilters,
  page: number,
): UseQueryResult<PricingPage<PricingRule>> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: pricingKeys.rules(tenantId, filters, page),
    queryFn: () => getPricingDataSource().listRules(tenantId, filters, page),
    retry: retryPolicy,
  });
}

export function usePropertyDirectory(): UseQueryResult<PropertySummary[]> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: pricingKeys.properties(tenantId),
    queryFn: () => getPricingDataSource().listProperties(tenantId),
    retry: retryPolicy,
  });
}
