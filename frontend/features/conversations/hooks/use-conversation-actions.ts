"use client";

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import {
  getConversationsDataSource,
  type ConversationDetail,
  type ThreadMessage,
} from "../data";
import { isConflict } from "../lib/errors";
import { conversationKeys } from "./query-keys";
import { useTenantId } from "./use-conversations";

/**
 * Write hooks for the inbox (design D16). Every one of them:
 *
 * - goes with `retry: false` — a write is not idempotent here, and a retried
 *   transcription would run the AI pipeline twice;
 * - invalidates, on success, the whole list (every filter combination and page)
 *   and the whole thread of this conversation by prefix, plus the conversation's
 *   detail by exact key (R4.4, R5.3);
 * - performs **no** optimistic update: the AI's reply and both state axes are
 *   computed by the server inside the same request, so painting first would be
 *   inventing the outcome;
 * - refreshes the same queries after a **409** (design D18). A conflict means the
 *   server's state is not what the UI believed, so the gates that offered the
 *   action were computed from stale data; re-reading is what stops the UI showing
 *   a result that did not happen (R5.2). Any other failure invalidates nothing —
 *   there is nothing new to learn from a 500.
 */
function useConversationInvalidation(conversationId: string): {
  invalidate: () => void;
  refreshOnConflict: (error: Error) => void;
} {
  const queryClient = useQueryClient();
  const tenantId = useTenantId();
  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: conversationKeys.listPrefix(tenantId),
    });
    void queryClient.invalidateQueries({
      queryKey: conversationKeys.messagesPrefix(tenantId, conversationId),
    });
    void queryClient.invalidateQueries({
      queryKey: conversationKeys.detail(tenantId, conversationId),
      exact: true,
    });
  };
  return {
    invalidate,
    refreshOnConflict: (error: Error) => {
      if (isConflict(error)) {
        invalidate();
      }
    },
  };
}

/**
 * Reply as ourselves: no `sender_type`, so the backend derives it (R4.1).
 *
 * `onSent` runs here, in the **mutation's** options, and not in a `mutate(…, {…})`
 * callback at the call site — that is the whole point. React Query drops
 * mutate-level callbacks once the observer has no listeners, and `ConversationsView`
 * keys the thread subtree per conversation (D22), so switching threads while a reply
 * is in flight unsubscribes it. A success landing after that switch still has to
 * retire the draft: otherwise the operator comes back to a delivered reply sitting
 * next to its own text in an enabled composer, and one click sends the guest a
 * duplicate (review 2026-08-22).
 */
export function useSendReply(
  conversationId: string,
  options: { onSent?: () => void } = {},
): UseMutationResult<ThreadMessage, Error, string> {
  const tenantId = useTenantId();
  const { invalidate, refreshOnConflict } =
    useConversationInvalidation(conversationId);
  const { onSent } = options;
  return useMutation({
    mutationFn: (content: string) =>
      getConversationsDataSource().createMessage(tenantId, conversationId, {
        content,
      }),
    retry: false,
    onSuccess: () => {
      invalidate();
      onSent?.();
    },
    onError: refreshOnConflict,
  });
}

/**
 * Transcribe what the guest said: `sender_type: "GUEST"`, which runs the whole AI
 * pipeline server-side and may escalate the conversation (R4.2).
 */
export function useTranscribeGuestMessage(
  conversationId: string,
): UseMutationResult<ThreadMessage, Error, string> {
  const tenantId = useTenantId();
  const { invalidate, refreshOnConflict } =
    useConversationInvalidation(conversationId);
  return useMutation({
    mutationFn: (content: string) =>
      getConversationsDataSource().createMessage(tenantId, conversationId, {
        content,
        senderType: "GUEST",
      }),
    retry: false,
    onSuccess: invalidate,
    onError: refreshOnConflict,
  });
}

export function useEscalate(
  conversationId: string,
): UseMutationResult<ConversationDetail, Error, void> {
  const tenantId = useTenantId();
  const { invalidate, refreshOnConflict } =
    useConversationInvalidation(conversationId);
  return useMutation({
    mutationFn: () =>
      getConversationsDataSource().escalate(tenantId, conversationId),
    retry: false,
    onSuccess: invalidate,
    onError: refreshOnConflict,
  });
}

export function useResolve(
  conversationId: string,
): UseMutationResult<ConversationDetail, Error, void> {
  const tenantId = useTenantId();
  const { invalidate, refreshOnConflict } =
    useConversationInvalidation(conversationId);
  return useMutation({
    mutationFn: () =>
      getConversationsDataSource().resolve(tenantId, conversationId),
    retry: false,
    onSuccess: invalidate,
    onError: refreshOnConflict,
  });
}
