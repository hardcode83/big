"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";
import { retryPolicy } from "@/lib/api/retry-policy";

import { getReservationsDataSource, type GuestAccessTokenStatusDto } from "../data";
import { reservationsKeys } from "./query-keys";

/**
 * Guest portal token hooks for one reservation (proposal R1, R2, R3, design
 * D7). Every hook here is scoped to a single `reservationId`, the same shape
 * `useCreatePlatformUser(tenantId)` and `useReplyToConversation(conversationId)`
 * already use for a resource-scoped mutation.
 *
 * The status query is the read side (R1.1 / R2); the three mutations are the
 * write side (R1.2, R1.3, R3) and each **invalidates the status query key on
 * success** — never optimistically patches the cache — so the visible status
 * always reflects a confirmed backend write (R1.3's "without requiring a page
 * reload" is satisfied by the invalidation + refetch, not by a client-side
 * guess).
 */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error("Guest access token actions require an authenticated tenant context");
  }
  return user.tenant_id;
}

/**
 * Live/none + `issuedAt` for the reservation's guest portal token (R1.1, R2).
 *
 * `enabled` (default `true`) lets `GuestPortalLinkCard` skip the request
 * entirely for a viewer without `MANAGE_GUEST_ACCESS_TOKENS` — an
 * optimization on top of the hidden UI (R1.4), not a substitute for it: the
 * backend still 403s this route on its own terms regardless of what the
 * frontend chooses to fetch.
 */
export function useGuestAccessTokenStatus(
  reservationId: string,
  enabled = true,
): UseQueryResult<GuestAccessTokenStatusDto> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: reservationsKeys.guestAccessTokenStatus(tenantId, reservationId),
    queryFn: () =>
      getReservationsDataSource().getGuestAccessTokenStatus(tenantId, reservationId),
    retry: retryPolicy,
    enabled,
  });
}

/**
 * Mint a fresh token for the reservation (R1.2). Returns the cleartext value
 * exactly once, in `mutation.data`. `gcTime: 0` — same reasoning as
 * `useCreatePlatformUser`'s `temporaryPassword`: without it, TanStack Query's
 * module-level `MutationCache` keeps the plaintext token reachable for the
 * default `gcTime` (5 minutes) after `GuestPortalLinkCard`'s one-time reveal
 * unmounts. `gcTime: 0` garbage-collects the mutation the instant it has no
 * observer, which is what actually happens on unmount.
 */
export function useIssueGuestAccessToken(
  reservationId: string,
): UseMutationResult<string, Error, void> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      getReservationsDataSource().issueGuestAccessToken(tenantId, reservationId),
    retry: false,
    gcTime: 0,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: reservationsKeys.guestAccessTokenStatus(tenantId, reservationId),
      });
    },
  });
}

/** Revoke the reservation's live token, if any (R1.3). Idempotent. */
export function useRevokeGuestAccessToken(
  reservationId: string,
): UseMutationResult<void, Error, void> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      getReservationsDataSource().revokeGuestAccessToken(tenantId, reservationId),
    retry: false,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: reservationsKeys.guestAccessTokenStatus(tenantId, reservationId),
      });
    },
  });
}

/**
 * Mint a fresh token and email it to the guest (R3). Resolves with
 * `delivered` — never the cleartext token (design D5). A send re-mints, so
 * "since when" changes too; the same status-key invalidation covers both
 * facts with one refetch.
 */
export function useSendGuestAccessTokenEmail(
  reservationId: string,
): UseMutationResult<boolean, Error, void> {
  const tenantId = useTenantId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      getReservationsDataSource().sendGuestAccessTokenEmail(tenantId, reservationId),
    retry: false,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: reservationsKeys.guestAccessTokenStatus(tenantId, reservationId),
      });
    },
  });
}
