"use client";

import {
  useQueries,
  useQuery,
  type UseQueryResult,
} from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";
import { retryPolicy } from "@/lib/api/retry-policy";

import {
  getCleanerDataSource,
  type CleaningChecklist,
  type CleaningFilters,
  type CleaningPhoto,
  type CleaningTask,
  type CleaningTaskContext,
  type CleaningTaskListItem,
  type PaginatedResponse,
  type PhotoRequirementsResponse,
} from "../data";
import { cleanerKeys } from "./query-keys";

/**
 * Read-side hooks for the cleaner's task app (design D4).
 *
 * They depend ONLY on `getCleanerDataSource()` (the composition point), never
 * on a concrete implementation, so tests swap the source without touching
 * `lib/api`.
 *
 * The tenant id comes from the authenticated context. The guard owns UX
 * access; the backend remains the authority for tenant isolation — a cleaner
 * sees only her own tasks regardless of any client-side filter.
 *
 * The shared `retryPolicy` from `@/lib/api/retry-policy` is reused: no 4xx
 * retries, brief 5xx/network retries. Detailed coverage lives in
 * `use-dashboard-data.test.tsx` and is not duplicated here.
 */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user) {
    throw new Error("The cleaner view requires an authenticated tenant context");
  }
  return user.tenant_id;
}

/** What `useCleanerTaskPages` reports to a caller that accumulates pages. */
export interface CleanerTaskPagesResult {
  /** Every row of every page requested so far, in the order the backend served them. */
  rows: CleaningTaskListItem[];
  total: number;
  page: number;
  perPage: number;
  totalPages: number;
  hasMore: boolean;
  isPending: boolean;
  isError: boolean;
  error: Error | null;
  data: PaginatedResponse<CleaningTaskListItem> | undefined;
  refetch: () => void;
  /**
   * A page **after the first** failed (D4). Kept apart from `isError` on
   * purpose: the first page failing means the list is unavailable (R1.7,
   * whole-screen `ErrorState` without retry on `4xx`); a later page failing
   * must not throw away the rows already on screen — but it must not be
   * silent either, or a refresh on page 2 strands page 3 silently.
   */
  hasPageError: boolean;
  /** Retries the failed page. */
  retryPage: () => void;
  /** A page request is in flight. */
  isFetchingMore: boolean;
}

/**
 * The list as an accumulation of pages (R1.1, design D4 + D5).
 *
 * Every page is its own cache entry under `cleanerKeys.list`, so paging
 * forward never refetches what is already held and an invalidation of
 * `listPrefix` reaches all of them.
 *
 * `status` is spread conditionally so a filterless request carries **no**
 * `status` key at all: the key must be identical to the one a first render
 * produced, and `{status: undefined}` is not the same shape as `{}`.
 */
export function useCleanerTaskPages(
  filters: CleaningFilters,
  pageCount: number,
  perPage: number,
): CleanerTaskPagesResult {
  const tenantId = useTenantId();

  const pages = useQueries({
    queries: Array.from({ length: pageCount }, (_, index) => {
      const pageFilters: CleaningFilters = {
        ...(filters.status !== undefined ? { status: filters.status } : {}),
        page: index + 1,
        perPage,
      };
      return {
        queryKey: cleanerKeys.list(tenantId, pageFilters),
        queryFn: () =>
          getCleanerDataSource().listTasks(tenantId, pageFilters),
        retry: retryPolicy,
      };
    }),
  });

  const first = pages[0];
  const rows = pages.flatMap((page) => page.data?.data ?? []);
  const total = first?.data?.total ?? 0;
  const failed = pages.slice(1).find((page) => page.isError);

  return {
    rows,
    total,
    page: first?.data?.page ?? 1,
    perPage: first?.data?.perPage ?? perPage,
    totalPages: first?.data?.totalPages ?? 1,
    // A failed page leaves a hole in `rows`, so the row count no longer tells
    // us where the list ends: offering «next page» here would skip the hole.
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
 * The property context of many tasks at once, one entry per id under
 * `cleanerKeys.context` — **the same** key `useCleanerTaskContext` uses for
 * the detail, which is what makes opening a row skip a second request (R1.3,
 * D4).
 *
 * A context that fails degrades the row to `null`: R1.4 governs the failure
 * of the *list* request, not that of an accessory projection.
 */
export function useCleanerTaskContexts(
  taskIds: readonly string[],
): (CleaningTaskContext | null)[] {
  const tenantId = useTenantId();

  return useQueries({
    queries: taskIds.map((taskId) => ({
      queryKey: cleanerKeys.context(tenantId, taskId),
      queryFn: () =>
        getCleanerDataSource().getTaskContext(tenantId, taskId),
      retry: retryPolicy,
    })),
    combine: (results) =>
      results.map((result) => (result.data ? result.data : null)),
  });
}

export function useCleanerTask(
  taskId: string,
): UseQueryResult<CleaningTask> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: cleanerKeys.detail(tenantId, taskId),
    queryFn: () => getCleanerDataSource().getTask(tenantId, taskId),
    retry: retryPolicy,
  });
}

/**
 * The property context of one task (R2.2). Its key is `cleanerKeys.context`,
 * the same one the list mounts per row — see the JSDoc there for why that
 * identity is R1.3.
 */
export function useCleanerTaskContext(
  taskId: string,
): UseQueryResult<CleaningTaskContext> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: cleanerKeys.context(tenantId, taskId),
    queryFn: () =>
      getCleanerDataSource().getTaskContext(tenantId, taskId),
    retry: retryPolicy,
  });
}

export function useCleanerTaskChecklist(
  taskId: string,
): UseQueryResult<CleaningChecklist> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: cleanerKeys.checklist(tenantId, taskId),
    queryFn: () =>
      getCleanerDataSource().getTaskChecklist(tenantId, taskId),
    retry: retryPolicy,
  });
}

export function useCleanerTaskPhotoRequirements(
  taskId: string,
): UseQueryResult<PhotoRequirementsResponse> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: cleanerKeys.photoRequirements(tenantId, taskId),
    queryFn: () =>
      getCleanerDataSource().getTaskPhotoRequirements(tenantId, taskId),
    retry: retryPolicy,
  });
}

export function useCleanerTaskPhotos(
  taskId: string,
): UseQueryResult<CleaningPhoto[]> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: cleanerKeys.photos(tenantId, taskId),
    queryFn: () => getCleanerDataSource().getTaskPhotos(tenantId, taskId),
    retry: retryPolicy,
  });
}