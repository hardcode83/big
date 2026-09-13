"use client";

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import {
  getTenantSettingsDataSource,
  type CreatedUserDto,
  type CreateUserInput,
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
 * Create a user in the acting tenant (R2.1). Invalidates `usersList` on
 * success so the directory reflects the new row.
 *
 * `gcTime: 0` — same reasoning as `useCreatePlatformUser`
 * (`features/platform/hooks/use-create-platform-user.ts`): the mutation's
 * result, including the one-time `temporaryPassword`, is held by the
 * `QueryClient`'s module-level `MutationCache`. Without `gcTime: 0`,
 * TanStack Query's default `gcTime` (5 minutes) keeps the plaintext password
 * reachable in that cache for five minutes after the reveal unmounts —
 * `gcTime: 0` garbage-collects the mutation the instant it has no observer,
 * which is what actually happens when the form/`Sheet` closes.
 */
export function useCreateUser(): UseMutationResult<
  CreatedUserDto,
  Error,
  CreateUserInput
> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateUserInput) =>
      getTenantSettingsDataSource().createUser(tenantId, input),
    retry: false,
    gcTime: 0,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: tenantSettingsKeys.usersList(tenantId),
      });
    },
  });
}
