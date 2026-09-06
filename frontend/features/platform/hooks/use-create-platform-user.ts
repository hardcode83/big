"use client";

import { useMutation, type UseMutationResult } from "@tanstack/react-query";

import {
  getPlatformDataSource,
  type CreatePlatformUserInput,
  type CreatedPlatformUserDto,
} from "../data";

/**
 * Create a user in a named tenant (R4.1, R4.4), scoped to one `tenantId` per hook instance —
 * the same shape `useReplyToConversation(conversationId)` uses. `tenantId` comes from the
 * caller: the tenant just created (R3.2) or a row picked from the list (R2), design D6.
 *
 * `gcTime: 0` (R4.4): the mutation's result — including the one-time `temporaryPassword` —
 * is held by the `QueryClient`'s `MutationCache`, a module-level singleton that outlives the
 * component tree. Without this, TanStack Query's default `gcTime` (5 minutes) keeps the
 * plaintext password reachable in that cache for five minutes after the `Sheet` closes and
 * `TemporaryPasswordReveal` unmounts — a screen the requirement's "vista en memoria de la
 * propia pantalla" ("in the screen's own memory") does not cover. `gcTime: 0` garbage-collects
 * the mutation the instant it has no observer, which is what actually happens when the form
 * unmounts.
 */
export function useCreatePlatformUser(
  tenantId: string,
): UseMutationResult<CreatedPlatformUserDto, Error, CreatePlatformUserInput> {
  return useMutation({
    mutationFn: (input: CreatePlatformUserInput) =>
      getPlatformDataSource().createUserInTenant(tenantId, input),
    retry: false,
    gcTime: 0,
  });
}
