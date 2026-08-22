"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useAuth } from "@/lib/auth";

import { useConversation, useThread } from "../hooks/use-conversations";
import { isForbidden, isNotFound } from "../lib/errors";
import { canManageConversations } from "../lib/permissions";
import { writeMessageGate } from "../lib/transitions";
import { MessageBubble } from "./message-bubble";
import { PageNav } from "./page-nav";
import { ReplyComposer } from "./reply-composer";
import { ThreadActions } from "./thread-actions";
import { ThreadHeader } from "./thread-header";
import { TranscribeDialog } from "./transcribe-dialog";

/**
 * The thread panel for one conversation (R3.1, R3.2, R3.5, R3.6).
 *
 * Messages render in the ascending chronological order the backend returns, with
 * no client-side sorting, and paging **replaces** the rendered page rather than
 * accumulating it.
 *
 * The three read failures are not the same failure (design D17, D18):
 * - 404 → a localized "not found" state with **no** retry. `retryPolicy` will not
 *   re-request a 4xx, so a retry button would be a button that cannot work.
 * - 403 → the localized no-access state, also without retry.
 * - anything else → the shared `ErrorState`, whose retry really re-runs the query.
 *
 * Whether the write controls exist at all is a **role** question (design D12,
 * R6.1): without `MANAGE_CONVERSATIONS` — every role but `PROPERTY_MANAGER` — the
 * composer, the transcription action, escalate and resolve are absent, while the
 * list and the thread stay fully readable. That is UX and not authorization: the
 * backend decides, and a 403 on an action the UI offered is handled like any other
 * failure (R6.2, R6.3).
 */
export function ConversationThread({
  conversationId,
  draft,
  onDraftChange,
  onDraftSent,
}: {
  conversationId: string;
  /** Owned by `ConversationsView`, above the keyed boundary (D22). Forwarded, not held. */
  draft: string;
  onDraftChange: (next: string) => void;
  onDraftSent: (sent: string) => void;
}) {
  const { t } = useTranslation("conversations");
  const { t: tStates } = useTranslation("states");
  const { user } = useAuth();
  const canManage = user !== null && canManageConversations(user.role);
  // The page is stored **with the conversation it belongs to** and derived during
  // render, so selecting another conversation starts at page 1 without an effect:
  // page 3 of a long thread does not exist in a short one, and resetting in an
  // effect would render one query against the wrong page first. `ConversationsView`
  // also keys this component by conversation (review 2026-08-22), which resets the
  // page on its own; this derivation stays so the component does not depend on the
  // caller remembering that key.
  const [selection, setSelection] = useState({ conversationId, page: 1 });
  const page = selection.conversationId === conversationId ? selection.page : 1;
  const setPage = (next: number) => setSelection({ conversationId, page: next });

  const detail = useConversation(conversationId);
  const thread = useThread(conversationId, page);

  if (detail.isPending) {
    return <LoadingState label={t("thread.loading")} />;
  }

  if (detail.isError) {
    if (isNotFound(detail.error)) {
      return (
        <ErrorState
          title={t("thread.notFound.title")}
          description={t("thread.notFound.description")}
        />
      );
    }
    if (isForbidden(detail.error)) {
      return (
        <ErrorState
          title={t("inbox.forbidden.title")}
          description={t("inbox.forbidden.description")}
        />
      );
    }
    return (
      <ErrorState
        title={t("thread.error.title")}
        description={t("thread.error.description")}
        onRetry={() => void detail.refetch()}
        retryLabel={tStates("error.retry")}
      />
    );
  }

  return (
    <section
      aria-label={t("thread.title")}
      className="flex min-h-0 flex-1 flex-col"
    >
      <ThreadHeader conversation={detail.data} />
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
        {thread.isPending ? (
          <LoadingState label={t("thread.loading")} />
        ) : thread.isError ? (
          <ErrorState
            title={t("thread.error.title")}
            description={t("thread.error.description")}
            onRetry={() => void thread.refetch()}
            retryLabel={tStates("error.retry")}
          />
        ) : (
          <>
            {/* Outside the empty check on purpose: a page that comes back empty
                because the thread shrank under us must still offer the way back,
                or the reader is stranded on a page that no longer has content. */}
            <PageNav
              page={thread.data.page}
              totalPages={thread.data.totalPages}
              onPageChange={setPage}
            />
            {thread.data.items.length === 0 ? (
              <EmptyState
                title={t("thread.empty.title")}
                description={t("thread.empty.description")}
              />
            ) : (
              <ul
                aria-label={t("thread.messages")}
                className="flex flex-col gap-3"
              >
                {thread.data.items.map((message) => (
                  <MessageBubble key={message.id} message={message} />
                ))}
              </ul>
            )}
          </>
        )}
      </div>
      {canManage ? (
        <>
          <ThreadActions conversation={detail.data} />
          <div className="flex flex-wrap items-center gap-2 border-t p-3">
            <TranscribeDialog
              conversationId={conversationId}
              channel={detail.data.channel}
              gate={writeMessageGate(detail.data)}
            />
          </div>
          <ReplyComposer
            conversationId={conversationId}
            gate={writeMessageGate(detail.data)}
            draft={draft}
            onDraftChange={onDraftChange}
            onDraftSent={onDraftSent}
          />
        </>
      ) : null}
    </section>
  );
}
