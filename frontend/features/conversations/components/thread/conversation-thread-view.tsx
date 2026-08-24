"use client";

import Link from "next/link";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { LoadingState } from "@/components/states";
import { useHasPermission } from "@/lib/auth";

import { mapConversationsError } from "../../lib/error-mapping";
import {
  useConversation,
  useConversationMessages,
} from "../../hooks/use-conversations";
import { ESCALATION_BADGE } from "../list/conversations-view";
import { ConversationThreadMessages } from "./conversation-thread-messages";
import { ConversationReplyForm } from "./conversation-reply-form";

/**
 * The thread view for `/conversations/[id]` (proposal R3, design D7).
 *
 * The view consumes two queries — `useConversation(id)` for the
 * conversation header and `useConversationMessages(id, page)` for the
 * thread — and renders the conversation's metadata, the message list
 * (delegated to `ConversationThreadMessages`) and the reply form
 * (delegated to `ConversationReplyForm`).
 *
 * **Pagination (R3.3)**: the messages page is local state. The query
 * key includes the page (`conversationsKeys.messages(tenantId, id,
 * page)`), so TanStack Query keys each page separately. `lastPage` is
 * derived in the client — same formula as the list (R2.5) — and
 * prev/next are disabled at the ends.
 *
 * **Back link (R1.4)**: a `<Link href="/conversations">` in the header
 * carries the operator from the deep-linkable thread back to the
 * inbox. R1.4 asks the flujo lista → hilo to be deep-linkable in
 * both directions; the link is the second half.
 *
 * **404 (R3.7)**: the conversation's 404 is a localised "not found"
 * distinct from the generic error. 401/403/5xx map to the generic
 * error. The 422 envelope is **never** read; the UI shows localised
 * copy only (R6.4).
 */
export function ConversationThreadView({
  conversationId,
}: {
  conversationId: string;
}) {
  const { t } = useTranslation(["conversations", "states"]);
  const conversationQuery = useConversation(conversationId);
  const [messagesPage, setMessagesPage] = useState(1);
  const messagesQuery = useConversationMessages(conversationId, messagesPage);
  const messagesState = mapConversationsError(messagesQuery);
  const conversationState = mapConversationsError(conversationQuery);
  const canReply = useHasPermission("MANAGE_CONVERSATIONS");

  if (conversationState.kind === "loading") {
    return <LoadingState label={t("states:loading.label", { ns: "states" })} />;
  }
  if (conversationState.kind === "not-found") {
    return (
      <div>
        <p>{t("fields.notFound")}</p>
      </div>
    );
  }
  if (
    conversationState.kind === "forbidden" ||
    conversationState.kind === "validation" ||
    conversationState.kind === "error"
  ) {
    return (
      <div role="alert">
        <p>{t("states:error.title", { ns: "states" })}</p>
        <p>{t("states:error.description", { ns: "states" })}</p>
        <button
          type="button"
          onClick={() => {
            void conversationQuery.refetch();
          }}
        >
          {t("states:error.retry", { ns: "states" })}
        </button>
      </div>
    );
  }

  const conversation = conversationState.data;

  // Pagination (R3.3) — only meaningful when the messages query has
  // succeeded. `lastPage = max(1, ceil(total / perPage))`. While
  // loading / in error the controls are not rendered.
  let lastMessagesPage = 1;
  let totalMessages = 0;
  if (messagesState.kind === "ok") {
    totalMessages = messagesState.data.total;
    lastMessagesPage = Math.max(
      1,
      Math.ceil(messagesState.data.total / messagesState.data.perPage),
    );
  }
  const messagesIsFirstPage = messagesPage <= 1;
  const messagesIsLastPage = messagesPage >= lastMessagesPage;

  return (
    <section aria-labelledby="conversation-thread-heading">
      <header className="mb-4 flex items-center justify-between">
        <h1 id="conversation-thread-heading">
          {t("thread.title")} — {conversation.id}
        </h1>
        <Link
          href="/conversations"
          className="text-sm text-muted-foreground underline"
        >
          {t("fields.backToList")}
        </Link>
      </header>
      <dl className="mb-4 grid grid-cols-2 gap-2 text-sm">
        <div>
          <dt className="text-muted-foreground">{t("fields.id")}</dt>
          <dd className="font-mono">{conversation.id}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.channel")}</dt>
          <dd>{t(`channel.${conversation.channel}`)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.status")}</dt>
          <dd>{t(`status.${conversation.status}`)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.escalationStatus")}</dt>
          <dd>
            <span
              className={
                ESCALATION_BADGE[conversation.escalationStatus] ??
                "bg-gray-100 text-gray-700"
              }
            >
              {t(`escalationStatus.${conversation.escalationStatus}`)}
            </span>
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.language")}</dt>
          <dd>{conversation.language}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.aiEnabled")}</dt>
          <dd>{conversation.aiEnabled ? "✓" : "—"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.property")}</dt>
          <dd className="font-mono">{conversation.propertyId}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.reservation")}</dt>
          <dd className="font-mono">{conversation.reservationId ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.guest")}</dt>
          <dd className="font-mono">{conversation.guestId ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.createdAtFull")}</dt>
          <dd>
            {conversation.createdAt.slice(0, 16).replace("T", " ")}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.updatedAt")}</dt>
          <dd>
            {conversation.updatedAt.slice(0, 16).replace("T", " ")}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.lastMessageAt")}</dt>
          <dd>
            {conversation.lastMessageAt
              ? conversation.lastMessageAt.slice(0, 16).replace("T", " ")
              : "—"}
          </dd>
        </div>
      </dl>
      <h2 className="text-base font-medium">{t("thread.messagesHeading")}</h2>
      {messagesState.kind === "loading" ? (
        <LoadingState label={t("states:loading.label", { ns: "states" })} />
      ) : messagesState.kind === "forbidden" ? (
        <p>{t("fields.forbidden")}</p>
      ) : messagesState.kind === "validation" ? (
        <p>{t("fields.validation")}</p>
      ) : messagesState.kind === "not-found" ||
        messagesState.kind === "error" ? (
        <div role="alert">
          <p>{t("states:error.title", { ns: "states" })}</p>
          <button
            type="button"
            onClick={() => {
              void messagesQuery.refetch();
            }}
          >
            {t("states:error.retry", { ns: "states" })}
          </button>
        </div>
      ) : (
        <>
          <ConversationThreadMessages messages={messagesState.data.items} />
          {totalMessages > messagesState.data.perPage && (
            <nav aria-label={t("thread.messagesHeading")} className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={() => setMessagesPage((p) => Math.max(1, p - 1))}
                disabled={messagesIsFirstPage}
                aria-label={t("fields.prevPage")}
                className="rounded-md border bg-background px-3 py-1 text-sm"
              >
                {t("fields.prevPage")}
              </button>
              <button
                type="button"
                onClick={() => setMessagesPage((p) => Math.min(lastMessagesPage, p + 1))}
                disabled={messagesIsLastPage}
                aria-label={t("fields.nextPage")}
                className="rounded-md border bg-background px-3 py-1 text-sm"
              >
                {t("fields.nextPage")}
              </button>
            </nav>
          )}
        </>
      )}
      {canReply ? (
        <>
          <h2 className="mt-4 text-base font-medium">{t("thread.replyHeading")}</h2>
          <ConversationReplyForm
            conversationId={conversationId}
            onReplySuccess={() => setMessagesPage(1)}
          />
        </>
      ) : (
        <p className="mt-4 text-sm text-muted-foreground" role="status">
          {t("fields.forbidden")}
        </p>
      )}
    </section>
  );
}