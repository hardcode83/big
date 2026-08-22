import { tenantScopedKey, type QueryKey } from "@/lib/query/query-keys";

import type { InboxFilters } from "../data/dto";

/**
 * Tenant-scoped query keys for the inbox (design D16, R2.4). Built on the shell's
 * `tenantScopedKey`, so every key begins `['tenant', tenantId, …]` and a
 * cross-tenant entry cannot be produced by accident.
 *
 * The `*Prefix` keys exist because a mutation invalidates the whole list (every
 * filter combination and page) and the whole thread of one conversation, while the
 * detail is invalidated by its exact key.
 */
export const conversationKeys = {
  listPrefix: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "conversations-list"),
  list: (tenantId: string, filters: InboxFilters, page: number): QueryKey =>
    tenantScopedKey(tenantId, "conversations-list", filters, page),
  detail: (tenantId: string, conversationId: string): QueryKey =>
    tenantScopedKey(tenantId, "conversation-detail", conversationId),
  messagesPrefix: (tenantId: string, conversationId: string): QueryKey =>
    tenantScopedKey(tenantId, "conversation-messages", conversationId),
  messages: (
    tenantId: string,
    conversationId: string,
    page: number,
  ): QueryKey =>
    tenantScopedKey(tenantId, "conversation-messages", conversationId, page),
  propertyLabels: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "conversation-property-labels"),
  /**
   * Identity of the *send* mutation for one conversation. A mutation key is what
   * makes an in-flight reply observable from outside the component that started it:
   * the thread subtree is keyed per conversation (D22), so a remount gets a fresh
   * `useMutation` whose `isPending` is false while the first request is still
   * travelling — and without this the composer would happily send a second copy to
   * the guest (review 2026-08-22).
   */
  sendReply: (tenantId: string, conversationId: string): QueryKey =>
    tenantScopedKey(tenantId, "conversation-send-reply", conversationId),
} as const;
