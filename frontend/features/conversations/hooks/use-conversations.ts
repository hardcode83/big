"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { retryPolicy } from "@/lib/api/retry-policy";
import { useAuth } from "@/lib/auth";

import {
  getConversationsDataSource,
  type ConversationDetail,
  type ConversationPage,
  type ConversationSummary,
  type InboxFilters,
  type PropertyLabel,
  type ThreadMessage,
} from "../data";
import { conversationKeys } from "./query-keys";

/**
 * Read hooks for the inbox. They depend only on `ConversationsDataSource`,
 * resolved through the composition point (R7.1), and use the shared
 * `retryPolicy`, which does not retry a 4xx — a 403 or a 404 is definitive, and
 * retrying only delays the localized state behind TanStack Query's backoff
 * (R3.6, design D17).
 */
/**
 * ASSUMPTION: these mirror the `per_page` defaults the two routes already declare
 * (`backend/app/messaging/api/router.py`), so the first page the inbox asks for is
 * the one the backend was tuned to answer. They are a UX parameter, not a
 * contract: changing one without the other only changes how many rows a manager
 * sees per page, never correctness — pagination reads its metadata from the
 * response (design D3).
 */
export const INBOX_PAGE_SIZE = 20;
export const THREAD_PAGE_SIZE = 50;

export function useTenantId(): string {
  const { user } = useAuth();
  if (!user) {
    throw new Error("The conversations inbox requires an authenticated session");
  }
  return user.tenant_id;
}

export function useConversationList(
  filters: InboxFilters,
  page: number,
): UseQueryResult<ConversationPage<ConversationSummary>> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: conversationKeys.list(tenantId, filters, page),
    queryFn: () =>
      getConversationsDataSource().listConversations(
        tenantId,
        filters,
        page,
        INBOX_PAGE_SIZE,
      ),
    retry: retryPolicy,
  });
}

export function useConversation(
  conversationId: string,
): UseQueryResult<ConversationDetail> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: conversationKeys.detail(tenantId, conversationId),
    queryFn: () =>
      getConversationsDataSource().getConversation(tenantId, conversationId),
    retry: retryPolicy,
  });
}

export function useThread(
  conversationId: string,
  page: number,
): UseQueryResult<ConversationPage<ThreadMessage>> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: conversationKeys.messages(tenantId, conversationId, page),
    queryFn: () =>
      getConversationsDataSource().listMessages(
        tenantId,
        conversationId,
        page,
        THREAD_PAGE_SIZE,
      ),
    retry: retryPolicy,
  });
}

/**
 * One cached query that labels every row of the list (R1.7) — not one request per
 * row. It outlives filter and page changes because its key carries neither.
 */
export function usePropertyLabels(): UseQueryResult<
  ConversationPage<PropertyLabel>
> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: conversationKeys.propertyLabels(tenantId),
    queryFn: () => getConversationsDataSource().listPropertyLabels(tenantId),
    retry: retryPolicy,
  });
}
