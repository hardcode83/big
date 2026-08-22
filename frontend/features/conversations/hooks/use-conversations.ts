"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";
import { retryPolicy } from "@/lib/api/retry-policy";

import {
  getConversationsDataSource,
  type ConversationDetailDto,
  type ConversationFilters,
  type ConversationList,
  type MessageList,
} from "../data";
import { conversationsKeys } from "./query-keys";

/**
 * Conversations data-access hooks (proposal R2 / R3). They depend ONLY on
 * `getConversationsDataSource()` (the composition point, design D1), never
 * on a concrete implementation, so the source is replaced without touching
 * the UI.
 *
 * The tenant id comes from the authenticated context. The guard owns UX
 * access; the backend remains the authority for tenant isolation (R1 of
 * `sdd/specs/messaging-ai.md` — the JOIN with `conversations` is the only
 * isolation mechanism for `messages`).
 *
 * The shared `retryPolicy` from `@/lib/api/retry-policy` is reused (precedent
 * `incidents-web`): no 4xx retries, brief 5xx/network retries.
 */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user) {
    throw new Error("Conversations requires an authenticated tenant context");
  }
  return user.tenant_id;
}

export function useConversations(
  filters: ConversationFilters = {},
): UseQueryResult<ConversationList> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: conversationsKeys.list(tenantId, filters),
    queryFn: () => getConversationsDataSource().listConversations(tenantId, filters),
    retry: retryPolicy,
  });
}

export function useConversation(
  conversationId: string,
): UseQueryResult<ConversationDetailDto> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: conversationsKeys.detail(tenantId, conversationId),
    queryFn: () =>
      getConversationsDataSource().getConversation(tenantId, conversationId),
    retry: retryPolicy,
  });
}

export function useConversationMessages(
  conversationId: string,
  page: number = 1,
  perPage: number = 20,
): UseQueryResult<MessageList> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: conversationsKeys.messages(tenantId, conversationId),
    queryFn: () =>
      getConversationsDataSource().listMessages(tenantId, conversationId, page, perPage),
    retry: retryPolicy,
  });
}