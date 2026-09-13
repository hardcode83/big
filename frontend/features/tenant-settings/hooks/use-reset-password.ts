"use client";

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import { getTenantSettingsDataSource, type CreatedUserDto } from "../data";
import { tenantSettingsKeys } from "./query-keys";

function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error("Tenant settings requires an authenticated tenant context");
  }
  return user.tenant_id;
}

/**
 * Reset a user's password (R4.1). Invalidates `usersList` on success — same
 * shape as `useCreateUser`, since a reset does not change the row the caller
 * currently has open but the directory's cache should not go stale either.
 *
 * `gcTime: 0` — same one-time-secret reasoning as `useCreateUser`/
 * `useCreatePlatformUser`: the returned `temporaryPassword` must not linger
 * in the `MutationCache` past the reveal screen's unmount.
 */
export function useResetPassword(): UseMutationResult<
  CreatedUserDto,
  Error,
  string
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      getTenantSettingsDataSource().resetPassword(tenantId, userId),
    retry: false,
    gcTime: 0,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: tenantSettingsKeys.usersList(tenantId),
      });
    },
  });
}
