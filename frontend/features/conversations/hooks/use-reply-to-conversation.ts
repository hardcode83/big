"use client";

import { useMutation, useQueryClient, type UseMutationResult } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth";

import { getConversationsDataSource, type MessageDto } from "../data";
import { conversationsKeys } from "./query-keys";

export interface ReplyToConversationInput {
  content: string;
}

/**
 * Reply to a conversation as the operator (proposal R4, design D9).
 *
 * The hook **does not** store or return the draft: the `useState` of
 * `ConversationReplyForm` owns the draft exclusively. On success the form
 * clears its own draft; on error the form does not modify it (the
 * backend's `422` is surfaced as a localized copy). The hook is responsible
 * only for the mutation, `retry: false` (rejected writes are not retried,
 * precedent: `useAssignCleaningTask`), and invalidating the three cache
 * keys that a successful reply can move:
 *
 * - `conversationsKeys.listPrefix(tenantId)` — every (filter × page) so the
 *   `lastMessageAt`, `status`, and `escalationStatus` of the row in the
 *   inbox reflect the change.
 * - `conversationsKeys.detail(tenantId, conversationId)` — for `status` /
 *   `escalationStatus` / `lastMessageAt` / `updatedAt`.
 * - `conversationsKeys.messagesPrefix(tenantId, conversationId)` — for the
 *   new message to appear in the thread.
 *
 * No patch-optimistic update: a row showing a message the backend did not
 * confirm is **operational lie** — the guest could see (in their channel,
 * outside the UI) a message the panel says "sent" but the backend rejected.
 *
 * `sender_type` is **never** sent from this hook: `CreateMessageRequest`
 * declares it as `Literal["GUEST"] | null`, and the backend derives it from
 * the caller's role when omitted (`messaging-ai.md` R7, design D9).
 */
export function useReplyToConversation(
  conversationId: string,
): UseMutationResult<MessageDto, Error, ReplyToConversationInput> {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const tenantId = user?.tenant_id;

  return useMutation({
    mutationFn: ({ content }: ReplyToConversationInput) => {
      if (!tenantId) {
        throw new Error("Replying to a conversation requires a tenant context");
      }
      return getConversationsDataSource().replyToConversation(tenantId, conversationId, {
        content,
      });
    },
    retry: false,
    onSettled: () => {
      if (!tenantId) return;
      void queryClient.invalidateQueries({
        queryKey: conversationsKeys.listPrefix(tenantId),
      });
      void queryClient.invalidateQueries({
        queryKey: conversationsKeys.detail(tenantId, conversationId),
      });
      void queryClient.invalidateQueries({
        queryKey: conversationsKeys.messagesPrefix(tenantId, conversationId),
      });
    },
  });
}