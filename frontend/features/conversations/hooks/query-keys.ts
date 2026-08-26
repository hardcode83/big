import { tenantScopedKey, type QueryKey } from "@/lib/query/query-keys";

import type { ConversationFilters } from "../data";

/**
 * Tenant-scoped query keys for the conversations resources (design D4, D9).
 * Built on the shell's `tenantScopedKey`, so every key begins with
 * `['tenant', tenantId, ...]` and a cross-tenant key cannot be produced by
 * accident.
 *
 * The list key takes the filters object directly (precedent:
 * `incidentsKeys.list(tenantId, filters)`, `reservationsKeys.list(tenantId,
 * filters)`). The caller is responsible for passing an object whose key
 * order is stable across renders — that is what guarantees two equivalent
 * renders produce the same key and TanStack Query does not invalidate.
 *
 * `listPrefix` / `messagesPrefix` are intentionally **broader** than any
 * single key: `useReplyToConversation`'s `onSettled` invalidates by prefix so
 * every (filter × page) combination and every message page is reached in
 * one call. Precedent: `cleaningKeys.tasksPrefix(tenantId)` in
 * `useAssignCleaningTask`.
 */
export const conversationsKeys = {
  list: (tenantId: string, filters: ConversationFilters = {}): QueryKey =>
    tenantScopedKey(tenantId, "conversations-list", filters),
  detail: (tenantId: string, conversationId: string): QueryKey =>
    tenantScopedKey(tenantId, "conversations-detail", conversationId),
  messages: (tenantId: string, conversationId: string, page: number): QueryKey =>
    tenantScopedKey(tenantId, "conversations-messages", conversationId, page),
  listPrefix: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "conversations-list"),
  messagesPrefix: (tenantId: string, conversationId: string): QueryKey =>
    tenantScopedKey(tenantId, "conversations-messages", conversationId),
} as const;