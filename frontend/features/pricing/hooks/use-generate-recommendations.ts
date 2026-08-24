"use client";

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import { getPricingDataSource, type GenerationReport } from "../data";
import { pricingKeys } from "./query-keys";
import { usePricingUiStore } from "../state/use-pricing-ui-store";

/**
 * Runs the generator now, without waiting for the 06:00 UTC job (design D7, R4).
 *
 * **The scope comes from the recommendations slice and from nowhere else** (R4.1,
 * design D11): `property_id` is the property filter of the queue the user is
 * looking at, or `null` to sweep the whole active portfolio. Reading it here
 * rather than taking it as an argument is what makes R4.1's «sin ofrecer un
 * segundo selector de vivienda» structural — there is no parameter through which
 * a caller could pass a different scope, and in particular not the Rules tab's
 * own `propertyId`, which would silently sweep something other than what is on
 * screen.
 *
 * `retry: false` (R4.4): the call runs the whole sweep synchronously inside the
 * request, so a retry would run it again.
 *
 * Same prefix invalidation as deciding, and also in **`onSettled`** — a sweep that
 * ends in an error may still have written rows before failing, and the contract
 * gives no way to tell. `pricingKeys.rules` is never touched (R3.5): generating
 * reads rules, it does not write them.
 */
export function useGenerateRecommendations(): UseMutationResult<
  GenerationReport,
  Error,
  void
> {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const tenantId = user?.tenant_id;
  const filtersTenantId = usePricingUiStore((state) => state.tenantId);
  const propertyId = usePricingUiStore(
    (state) => state.recommendations.propertyId,
  );

  return useMutation({
    mutationFn: () => {
      if (!tenantId) {
        throw new Error("Generating recommendations requires a tenant context");
      }
      // The same staleness guard the view applies to its queries: a filter
      // chosen in another session must not become this one's sweep scope
      // (`steering/security.md` rule 1, frontend side).
      const scope =
        filtersTenantId === tenantId ? (propertyId ?? null) : null;
      return getPricingDataSource().generateRecommendations(tenantId, scope);
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
