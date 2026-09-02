"use client";

import { useMemo } from "react";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";
import { retryPolicy } from "@/lib/api/retry-policy";

import {
  getStallsDataSource,
  type BlockedTransitionPage,
  type BlockedTransitionSummary,
} from "../data";
import { stallsKeys } from "./query-keys";

/**
 * Dashboard card's read hook for blocked transitions (proposal
 * `blocked-transitions-web` R1.1, R1.4).
 *
 * The hook pulls `tenantId` from the session — a `tenantId` parameter would
 * let a caller override isolation in the wrong direction (R1.4). It returns
 * the page's items **and** a `Map<propertyId, items>` pre-sliced and
 * pre-sorted:
 *
 *   - ordered by `due_since` ascending — what an operator actually wants is
 *     what has been stuck the longest (R1.1, design D1);
 *
 *   - tie-broken deterministically on `reservation_id` then `trigger`, so
 *     two stalls with the same `due_since` (think: the calendar emitted
 *     both at the same hour) do not flicker between renders (R1.1);
 *
 *   - keyed by `property_id`, so the card does not have to re-filter on
 *     every render and so the in-place `Map.get(propertyId)` is O(1) for
 *     a typical portfolio of two.
 */

function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error(
      "useBlockedTransitions requires an authenticated tenant context",
    );
  }
  return user.tenant_id;
}

/** Public shape of the hook result. Used by callers that destructure the result. */
interface UseBlockedTransitionsResult {
  /** The first page as the backend returned it, untouched. */
  data: BlockedTransitionPage | undefined;
  /**
   * Stalls grouped per property, each group's list ordered by `due_since`
   * ascending with deterministic tie-break (R1.1).
   */
  byPropertyId: Map<string, BlockedTransitionSummary[]>;
}

/**
 * Stable tie-break: `reservation_id` then `trigger`, both as their canonical
 * strings. Numeric `due_since` strings sort lexicographically in ISO-8601
 * order, so a simple `<`/`>` chain is enough.
 */
function compareStalls(
  a: BlockedTransitionSummary,
  b: BlockedTransitionSummary,
): number {
  if (a.due_since !== b.due_since) {
    return a.due_since < b.due_since ? -1 : 1;
  }
  if (a.reservation_id !== b.reservation_id) {
    return a.reservation_id < b.reservation_id ? -1 : 1;
  }
  if (a.trigger !== b.trigger) {
    return a.trigger < b.trigger ? -1 : 1;
  }
  return 0;
}

export function useBlockedTransitions(): UseQueryResult<BlockedTransitionPage> & {
  byPropertyId: Map<string, BlockedTransitionSummary[]>;
} {
  const tenantId = useTenantId();
  const query = useQuery({
    queryKey: stallsKeys.list(tenantId, 1),
    queryFn: () => getStallsDataSource().listBlockedTransitions(tenantId, 1),
    retry: retryPolicy,
  });

  const byPropertyId = useMemo(() => {
    const map = new Map<string, BlockedTransitionSummary[]>();
    if (!query.data) {
      return map;
    }
    const sorted = [...query.data.data].sort(compareStalls);
    for (const stall of sorted) {
      const bucket = map.get(stall.property_id);
      if (bucket) {
        bucket.push(stall);
      } else {
        map.set(stall.property_id, [stall]);
      }
    }
    return map;
  }, [query.data]);

  return Object.assign(query, { byPropertyId }) as UseQueryResult<
    BlockedTransitionPage
  > & { byPropertyId: Map<string, BlockedTransitionSummary[]> };
}