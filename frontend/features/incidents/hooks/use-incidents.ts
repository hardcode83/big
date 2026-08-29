"use client";

import {
  useQueries,
  useQuery,
  type UseQueryResult,
} from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";
import { retryPolicy } from "@/lib/api/retry-policy";

import {
  getIncidentsDataSource,
  type IncidentContextDto,
  type IncidentDetailDto,
  type IncidentFilters,
  type IncidentList,
  type IncidentPhotoDto,
  type IncidentSummaryDto,
} from "../data";
import { incidentsKeys } from "./query-keys";

/**
 * Incidents data-access hooks (proposal R2 / R3). They depend ONLY on
 * `getIncidentsDataSource()` (the composition point), never on a concrete
 * implementation, so the source is replaced without touching the UI.
 *
 * The tenant id comes from the authenticated context. The guard owns UX
 * access; the backend remains the authority for tenant isolation.
 *
 * The shared `retryPolicy` from `@/lib/api/retry-policy` (introduced in
 * `guest-portal-web` and present in `main`) is reused: no 4xx retries, brief
 * 5xx/network retries. Detailed coverage lives in
 * `use-dashboard-data.test.tsx` and is not duplicated here — these tests
 * assert the wiring (the hook configures `retry: retryPolicy`), not the
 * policy's branch table.
 */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user) {
    throw new Error("Incidents requires an authenticated tenant context");
  }
  return user.tenant_id;
}

export function useIncidents(
  filters: IncidentFilters = {},
): UseQueryResult<IncidentList> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: incidentsKeys.list(tenantId, filters),
    queryFn: () => getIncidentsDataSource().listIncidents(tenantId, filters),
    retry: retryPolicy,
  });
}

/** What `useIncidentsPages` reports to a caller that accumulates pages. */
export interface IncidentsPagesResult {
  /** Every row of every page requested so far, in the order the backend served them. */
  rows: IncidentSummaryDto[];
  total: number;
  hasMore: boolean;
  isPending: boolean;
  isError: boolean;
  error: Error | null;
  /** The first page, so the caller can reuse `mapIncidentsError` unchanged. */
  data: IncidentList | undefined;
  refetch: () => void;
  /**
   * A page **after the first** failed. Kept apart from `isError` on purpose:
   * the first page failing means the list is unavailable (R1.6, whole-screen
   * `ErrorState`), while a later page failing must not throw away the rows
   * already on screen — but it must not be silent either. Without this the
   * failure had no visible effect at all and, because `hasMore` still counted
   * rows, the next tap skipped straight past the missing page and those
   * incidents were absent from the list for good.
   */
  hasPageError: boolean;
  /** Retries the failed page, so the caller does not have to know which it was. */
  retryPage: () => void;
  /** A page request is in flight; the caller disables «load more» with it. */
  isFetchingMore: boolean;
}

/**
 * The list as an accumulation of pages (R1.4, design D4 + D5).
 *
 * D5 asks for a «load more» that **accumulates**, which one `useIncidents` call
 * cannot express: it returns a single page. So the pages live here, in the data
 * layer, and not inside the screen — D1 is what forbids a view from
 * reimplementing the `queryFn`, the retry policy and the tenant scoping.
 *
 * Every page is its own cache entry under `incidentsKeys.list`, so paging
 * forward never refetches what is already held, and an invalidation of
 * `listPrefix` still reaches all of them.
 *
 * `status` is spread conditionally so a filterless request carries **no**
 * `status` key at all: the key must be identical to the one a first render
 * produced, and `{status: undefined}` is not the same object shape as `{}`.
 */
export function useIncidentsPages(
  filters: IncidentFilters,
  pageCount: number,
  perPage: number,
): IncidentsPagesResult {
  const tenantId = useTenantId();

  const pages = useQueries({
    queries: Array.from({ length: pageCount }, (_, index) => {
      const pageFilters: IncidentFilters = {
        ...(filters.status !== undefined ? { status: filters.status } : {}),
        page: index + 1,
        perPage,
      };
      return {
        queryKey: incidentsKeys.list(tenantId, pageFilters),
        queryFn: () =>
          getIncidentsDataSource().listIncidents(tenantId, pageFilters),
        retry: retryPolicy,
      };
    }),
  });

  const first = pages[0];
  const rows = pages.flatMap((page) => page.data?.items ?? []);
  const total = first?.data?.total ?? 0;
  const failed = pages.slice(1).find((page) => page.isError);

  return {
    rows,
    total,
    // A failed page leaves a hole in `rows`, so the row count no longer tells
    // us where the list ends: offering «load more» here would request the page
    // *after* the hole and strand the missing one permanently.
    hasMore: rows.length < total && !failed,
    isPending: first?.isPending ?? true,
    isError: first?.isError ?? false,
    error: first?.error ?? null,
    data: first?.data,
    refetch: () => {
      void first?.refetch();
    },
    hasPageError: Boolean(failed),
    retryPage: () => {
      void failed?.refetch();
    },
    isFetchingMore: pages.some((page) => page.isFetching),
  };
}

/**
 * The property context of many incidents at once, one entry per id under
 * `incidentsKeys.context` — **the same** key `useIncidentContext` uses for the
 * detail, which is what makes opening a row skip a second request (R1.3, D4).
 *
 * A context that fails degrades to `undefined` for that row: R1.6 governs the
 * failure of the *list* request, not that of an accessory projection.
 */
export function useIncidentContexts(
  incidentIds: readonly string[],
): (IncidentContextDto | undefined)[] {
  const tenantId = useTenantId();

  return useQueries({
    queries: incidentIds.map((incidentId) => ({
      queryKey: incidentsKeys.context(tenantId, incidentId),
      queryFn: () =>
        getIncidentsDataSource().getIncidentContext(tenantId, incidentId),
      retry: retryPolicy,
    })),
    combine: (results) => results.map((result) => result.data),
  });
}

export function useIncident(
  incidentId: string,
): UseQueryResult<IncidentDetailDto> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: incidentsKeys.detail(tenantId, incidentId),
    queryFn: () =>
      getIncidentsDataSource().getIncident(tenantId, incidentId),
    retry: retryPolicy,
  });
}

/**
 * The property context of one incident (R2.3). Its key is `incidentsKeys.context`,
 * the same one the list mounts per row — see the JSDoc there for why that
 * identity is R1.3.
 */
export function useIncidentContext(
  incidentId: string,
): UseQueryResult<IncidentContextDto> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: incidentsKeys.context(tenantId, incidentId),
    queryFn: () =>
      getIncidentsDataSource().getIncidentContext(tenantId, incidentId),
    retry: retryPolicy,
  });
}

/**
 * The photos of one incident (R5.1). No `staleTime` of its own, so it inherits
 * the shell's **60 s** (`lib/query/query-client.ts`) — not TanStack's default of
 * 0, which this comment used to claim. The conclusion D10 needs is unchanged and
 * the margin is still wide: a mount more than 60 s later revalidates, and 60 s is
 * far below the signature's 3600 s, so a URL cannot expire in the cache before it
 * is refreshed. Within that minute the photos are served from cache without a
 * request, which is correct — the signature is still valid.
 */
export function useIncidentPhotos(
  incidentId: string,
): UseQueryResult<IncidentPhotoDto[]> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: incidentsKeys.photos(tenantId, incidentId),
    queryFn: () => getIncidentsDataSource().listPhotos(tenantId, incidentId),
    retry: retryPolicy,
  });
}
