"use client";

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import {
  getTenantSettingsDataSource,
  type TenantDto,
  type UpdateTenantInput,
} from "../data";
import { tenantSettingsKeys } from "./query-keys";

function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error("Tenant settings requires an authenticated tenant context");
  }
  return user.tenant_id;
}

/**
 * `PATCH /api/v1/tenants/{id}` (R5.3), sending only the fields that changed,
 * including a nested partial `config`. Invalidates `tenantDetail` on
 * success.
 */
export function useUpdateTenant(): UseMutationResult<
  TenantDto,
  Error,
  UpdateTenantInput
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: UpdateTenantInput) =>
      getTenantSettingsDataSource().updateTenant(tenantId, input),
    retry: false,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: tenantSettingsKeys.tenantDetail(tenantId),
      });
    },
  });
}
