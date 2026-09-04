"use client";

import { useMutation, type UseMutationResult } from "@tanstack/react-query";

import {
  getPlatformDataSource,
  type CreateTenantInput,
  type TenantSummaryDto,
} from "../data";

/**
 * Create a tenant (R3.1, design D6). Deliberately does NOT invalidate
 * `platformKeys.tenantsList(...)` — R3.2 explicitly forbids re-fetching the list as part of
 * this flow ("en la misma vista y sin recargar ni volver a pedir la lista de R2"). The list
 * shows the new tenant only on its next natural refetch (revisit, refocus, or the operator
 * manually reopening `/platform`) — an accepted staleness window per the requirement.
 */
export function useCreateTenant(): UseMutationResult<
  TenantSummaryDto,
  Error,
  CreateTenantInput
> {
  return useMutation({
    mutationFn: (input: CreateTenantInput) => getPlatformDataSource().createTenant(input),
    retry: false,
  });
}
