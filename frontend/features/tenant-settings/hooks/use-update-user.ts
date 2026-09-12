"use client";

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import {
  getTenantSettingsDataSource,
  type UpdateUserInput,
  type UserDto,
} from "../data";
import { tenantSettingsKeys } from "./query-keys";

function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error("Tenant settings requires an authenticated tenant context");
  }
  return user.tenant_id;
}

interface UpdateUserVariables {
  userId: string;
  input: UpdateUserInput;
}

/**
 * `PATCH /api/v1/users/{id}` (R3.1) — profile/role edits, sending only the
 * changed fields, and reactivation (design D7) via `{status: "ACTIVE"}`, the
 * same call. Invalidates both `usersList` (the row's summary in the
 * directory) and the row's own `userDetail` (the open detail view) on
 * success.
 */
export function useUpdateUser(): UseMutationResult<
  UserDto,
  Error,
  UpdateUserVariables
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, input }: UpdateUserVariables) =>
      getTenantSettingsDataSource().updateUser(tenantId, userId, input),
    retry: false,
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({
        queryKey: tenantSettingsKeys.usersList(tenantId),
      });
      void queryClient.invalidateQueries({
        queryKey: tenantSettingsKeys.userDetail(tenantId, variables.userId),
      });
    },
  });
}
