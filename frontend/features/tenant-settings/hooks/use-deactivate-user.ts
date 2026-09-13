"use client";

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import { getTenantSettingsDataSource } from "../data";
import { tenantSettingsKeys } from "./query-keys";

function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error("Tenant settings requires an authenticated tenant context");
  }
  return user.tenant_id;
}

/**
 * `DELETE /api/v1/users/{id}` (R3.2, design D7) — a dedicated mutation
 * hook, not folded into `useUpdateUser`: it takes no body and its success
 * (`204`) has no updated resource to merge into cache. Invalidates both
 * `usersList` and the row's `userDetail` on success, same as `useUpdateUser`.
 */
export function useDeactivateUser(): UseMutationResult<void, Error, string> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      getTenantSettingsDataSource().deactivateUser(tenantId, userId),
    retry: false,
    onSuccess: (_data, userId) => {
      void queryClient.invalidateQueries({
        queryKey: tenantSettingsKeys.usersList(tenantId),
      });
      void queryClient.invalidateQueries({
        queryKey: tenantSettingsKeys.userDetail(tenantId, userId),
      });
    },
  });
}
