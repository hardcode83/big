"use client";

import { useQueries, useQuery, type UseQueryResult } from "@tanstack/react-query";

import { retryPolicy } from "@/lib/api/retry-policy";
import { useAuth } from "@/lib/auth";

import {
  getPropertiesDataSource,
  type PropertyFilters,
  type PropertyList,
} from "../data";
import { propertiesKeys } from "./query-keys";

/**
 * Properties data-access hook (proposal R1, R2). It depends ONLY on
 * `getPropertiesDataSource()` (the composition point, design D4), never on a
 * concrete implementation, so the source can be replaced without touching UI.
 *
 * The tenant id comes from the authenticated context; the route guard owns UX
 * access and the backend remains the authority for tenant isolation.
 *
 * The shared `retryPolicy` from `@/lib/api/retry-policy` is reused rather than
 * re-declared: it does not retry 4xx and retries 5xx/network twice (R3.7). Its
 * branch table is covered by `use-dashboard-data.test.tsx`; the test here
 * asserts the wiring, not the policy.
 */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error("Properties requires an authenticated tenant context");
  }
  return user.tenant_id;
}

export function useProperties(
  filters: PropertyFilters = {},
): UseQueryResult<PropertyList> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: propertiesKeys.list(tenantId, filters),
    queryFn: () => getPropertiesDataSource().listProperties(tenantId, filters),
    retry: retryPolicy,
  });
}

/** Fetch every active-property page for selectors that must not silently cap options. */
export function useActiveProperties(): UseQueryResult<PropertyList> {
  const tenantId = useTenantId();
  const firstPage = useProperties({ status: "ACTIVE", page: 1, perPage: 100 });
  const pageCount = firstPage.data?.totalPages ?? 0;
  const rest = useQueries({
    queries: Array.from({ length: Math.max(0, pageCount - 1) }, (_, index) => {
      const page = index + 2;
      return {
        queryKey: propertiesKeys.list(tenantId, { status: "ACTIVE", page, perPage: 100 }),
        queryFn: () => getPropertiesDataSource().listProperties(tenantId, { status: "ACTIVE", page, perPage: 100 }),
        retry: retryPolicy,
      };
    }),
  });
  const pages = [firstPage.data, ...rest.map((query) => query.data)].filter(
    (page): page is PropertyList => page !== undefined,
  );
  const data = pages.length > 0
    ? { ...pages[0], data: pages.flatMap((page) => page.data) }
    : undefined;
  const error = firstPage.error ?? rest.find((query) => query.error)?.error ?? null;
  return {
    ...firstPage,
    data,
    error,
    isError: firstPage.isError || rest.some((query) => query.isError),
    isPending: firstPage.isPending || rest.some((query) => query.isPending),
    refetch: async () => {
      await Promise.all([firstPage.refetch(), ...rest.map((query) => query.refetch())]);
      return firstPage;
    },
  } as UseQueryResult<PropertyList>;
}
