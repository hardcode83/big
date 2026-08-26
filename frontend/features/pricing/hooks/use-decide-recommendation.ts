"use client";

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import {
  getPricingDataSource,
  type DecisionStatus,
  type PriceRecommendation,
} from "../data";
import { pricingKeys } from "./query-keys";

export interface DecideRecommendationInput {
  recommendationId: string;
  status: DecisionStatus;
}

/**
 * Approves, rejects, or records a recommendation as published (design D7).
 *
 * It **invalidates and never patches the cache optimistically** (R3.4), which
 * makes R3.6 and R3.8 free rather than extra work: there is no instant in which a
 * row shows a decision the backend did not confirm — and the `409` that R3.6 makes
 * visible is precisely the case where an optimistic patch would have lied.
 *
 * `retry: false`: a rejected write is not retried. Retrying a `409` would re-ask a
 * question already answered, and retrying a `403` would never start succeeding.
 *
 * The invalidation runs in **`onSettled`, so on failure as well as on success**.
 * That is not symmetry for its own sake: after a `409` the row on screen is, by
 * definition, in a state this client no longer believes, so the list has to be
 * refetched precisely when the write failed.
 *
 * It targets the `['tenant', id, 'pricing-recommendations']` **prefix**, which
 * reaches every filter/page combination without enumerating them. Patching would
 * not be enough either: approving moves a row **out of** the `RECOMMENDED` filter,
 * and only refetching the page the current parameters describe reflects that — the
 * `PATCH` response is a single recommendation and knows nothing about `total` or
 * the page it was on.
 *
 * **`pricingKeys.rules` is never invalidated** (R3.5): deciding does not write a
 * rule, so refetching the other tab would be work nobody asked for.
 */
export function useDecideRecommendation(): UseMutationResult<
  PriceRecommendation,
  Error,
  DecideRecommendationInput
> {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const tenantId = user?.tenant_id;

  return useMutation({
    mutationFn: ({ recommendationId, status }: DecideRecommendationInput) => {
      if (!tenantId) {
        throw new Error("Deciding a recommendation requires a tenant context");
      }
      return getPricingDataSource().decideRecommendation(
        tenantId,
        recommendationId,
        status,
      );
    },
    retry: false,
    onSettled: () => {
      if (tenantId) {
        void queryClient.invalidateQueries({
          queryKey: pricingKeys.recommendationsPrefix(tenantId),
        });
      }
    },
  });
}
