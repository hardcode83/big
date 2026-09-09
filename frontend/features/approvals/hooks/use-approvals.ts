"use client";

import {
  useQueries,
  useQuery,
  type UseQueryResult,
} from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";
import { retryPolicy } from "@/lib/api/retry-policy";

import {
  getApprovalsDataSource,
  type OwnerApprovalListItemDto,
  type OwnerApprovalPage,
} from "../data";
import { approvalsKeys } from "./query-keys";

/**
 * Approvals data-access hooks (R2.1, R2.3, design D9). They depend ONLY on
 * `getApprovalsDataSource()` (the composition point), never on a concrete
 * implementation, so the source is replaced without touching the UI.
 *
 * The tenant id comes from the authenticated context. The guard owns UX
 * access; the backend remains the authority for tenant isolation.
 *
 * The shared `retryPolicy` from `@/lib/api/retry-policy` is reused: no 4xx
 * retries, brief 5xx/network retries — same convention `useIncidents` follows.
 */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error("Approvals requires an authenticated tenant context");
  }
  return user.tenant_id;
}

/**
 * The pending queue (R2.1). No status filter: the backend's own default
 * (design D5's single-valued `status` parameter) is `PENDING`, oldest request
 * first — exactly the to-do-list order R1.1/R1.2 ask for.
 */
export function useApprovals(): UseQueryResult<OwnerApprovalPage> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: approvalsKeys.list(tenantId),
    queryFn: () => getApprovalsDataSource().listApprovals(tenantId),
    retry: retryPolicy,
  });
}

/** What `useApprovalsHistory` reports to the caller. */
export interface ApprovalsHistoryResult {
  /** Up to five most recently answered approvals, newest first. */
  items: OwnerApprovalListItemDto[];
  isPending: boolean;
  isError: boolean;
  error: Error | null;
}

const HISTORY_PER_PAGE = 5;

/**
 * The short history of the last five answered approvals, `APPROVED` and
 * `REJECTED` merged and re-sorted by `respondedAt` descending (R2.3, design
 * D9). Two requests — one per answered status — because the backend's
 * `status` filter is single-valued (D5); each branch already asks for its own
 * five most recent, so merging the two five-item pages and slicing to five is
 * correct by construction: the five most recently answered overall can never
 * come from *beyond* the fifth item of whichever status contributes them.
 *
 * `useQueries` is the pattern `useIncidentContexts`/`useIncidentsPages`
 * already use in this codebase for "several independent queries, one combined
 * result" (D9).
 */
export function useApprovalsHistory(): ApprovalsHistoryResult {
  const tenantId = useTenantId();

  const results = useQueries({
    queries: (["APPROVED", "REJECTED"] as const).map((status) => ({
      queryKey: approvalsKeys.list(tenantId, {
        status,
        perPage: HISTORY_PER_PAGE,
      }),
      queryFn: () =>
        getApprovalsDataSource().listApprovals(tenantId, {
          status,
          perPage: HISTORY_PER_PAGE,
        }),
      retry: retryPolicy,
    })),
  });

  const items = results
    .flatMap((result) => result.data?.items ?? [])
    .sort((a, b) => {
      // `respondedAt` is never null on an APPROVED/REJECTED row — both
      // branches only ever request answered statuses.
      const left = a.respondedAt ?? "";
      const right = b.respondedAt ?? "";
      return right.localeCompare(left);
    })
    .slice(0, HISTORY_PER_PAGE);

  return {
    items,
    isPending: results.some((result) => result.isPending),
    isError: results.some((result) => result.isError),
    error: (results.find((result) => result.isError)?.error as Error) ?? null,
  };
}
