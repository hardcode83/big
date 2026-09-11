"use client";

import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import {
  getPropertiesDataSource,
  type PropertyDetailDto,
  type UpdatePropertyInput,
} from "../data";
import { propertiesKeys } from "./query-keys";

export interface UpdatePropertyMutationInput {
  id: string;
  input: UpdatePropertyInput;
}

/**
 * Updates one property, partially (proposal R2.2, design D8, D9, D10). Same
 * skeleton as `useCreateProperty`/`useCreateCleaningTask`: **no optimistic
 * cache write**, `retry: false` — a rejected write is not retried. Used both
 * by `EditPropertyForm`'s diffed save and by the "Retire property"
 * confirmation's `{ status: "INACTIVE" }` (D9) — the mutation itself does not
 * distinguish the two callers.
 *
 * `onSettled` invalidates, on success and on failure alike:
 *
 *  - `propertiesKeys.listPrefix(tenantId)` — an update can change any of the
 *    columns the list table renders (name, status, city, …).
 *  - `propertiesKeys.detail(tenantId, id)` — so a re-opened edit form or a
 *    revisited detail-adjacent read sees the just-saved values.
 *  - `["tenant", tenantId, "dashboard-cards"]` and
 *    `["tenant", tenantId, "property-detail", id]` — the `dashboard`
 *    feature's tenant-scoped prefixes, reproduced by hand exactly as
 *    `useResolveIncident` already does for the same two shapes:
 *    `features/properties` cannot import `dashboardKeys` (design boundary D10
 *    documents).
 */
export function useUpdateProperty(): UseMutationResult<
  PropertyDetailDto,
  Error,
  UpdatePropertyMutationInput
> {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const tenantId = user?.tenant_id;

  return useMutation({
    mutationFn: ({ id, input }: UpdatePropertyMutationInput) => {
      if (!tenantId) {
        throw new Error("Updating a property requires a tenant context");
      }
      return getPropertiesDataSource().updateProperty(tenantId, id, input);
    },
    retry: false,
    onSettled: (_data, _error, variables) => {
      if (!tenantId) {
        return;
      }
      void queryClient.invalidateQueries({
        queryKey: propertiesKeys.listPrefix(tenantId),
      });
      void queryClient.invalidateQueries({
        queryKey: propertiesKeys.detail(tenantId, variables.id),
      });
      void queryClient.invalidateQueries({
        queryKey: ["tenant", tenantId, "dashboard-cards"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["tenant", tenantId, "property-detail", variables.id],
      });
    },
  });
}
