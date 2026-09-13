"use client";

import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import {
  getPropertiesDataSource,
  type CreatePropertyInput,
  type PropertyDetailDto,
} from "../data";
import { propertiesKeys } from "./query-keys";

/**
 * Creates one property (proposal R1.4, design D10). Same skeleton as
 * `useCreateCleaningTask`: **no optimistic cache write**, `retry: false` — a
 * rejected write is not retried.
 *
 * `onSettled` invalidates, on success and on failure alike:
 *
 *  - `propertiesKeys.listPrefix(tenantId)` — this feature's own list cache; a
 *    creation changes `total`/`totalPages` on every cached page.
 *  - `["tenant", tenantId, "dashboard-cards"]` — the `dashboard` feature's
 *    card cube gains a card. Reproduced by hand, exactly as
 *    `useResolveIncident` does for the same prefix: `features/properties`
 *    cannot import `dashboardKeys` (design boundary D10 documents).
 */
export function useCreateProperty(): UseMutationResult<
  PropertyDetailDto,
  Error,
  CreatePropertyInput
> {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const tenantId = user?.tenant_id;

  return useMutation({
    mutationFn: (input: CreatePropertyInput) => {
      if (!tenantId) {
        throw new Error("Creating a property requires a tenant context");
      }
      return getPropertiesDataSource().createProperty(tenantId, input);
    },
    retry: false,
    onSettled: () => {
      if (!tenantId) {
        return;
      }
      void queryClient.invalidateQueries({
        queryKey: propertiesKeys.listPrefix(tenantId),
      });
      void queryClient.invalidateQueries({
        queryKey: ["tenant", tenantId, "dashboard-cards"],
      });
    },
  });
}
