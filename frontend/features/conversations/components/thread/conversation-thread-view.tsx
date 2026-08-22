"use client";

import { useTranslation } from "react-i18next";

import { mapConversationsError } from "../../lib/error-mapping";
import {
  useConversation,
  useConversationMessages,
} from "../../hooks/use-conversations";
import { ConversationThreadMessages } from "./conversation-thread-messages";
import { ConversationReplyForm } from "./conversation-reply-form";

/**
 * The thread view for `/conversations/[id]` (proposal R3, design D7).
 *
 * The view consumes two queries — `useConversation(id)` for the
 * conversation header and `useConversationMessages(id)` for the thread —
 * and renders the conversation's metadata, the message list (delegated
 * to `ConversationThreadMessages`) and the reply form (delegated to
 * `ConversationReplyForm`).
 *
 * 404 (other tenant or unknown id) is a localized "not found" state
 * distinct from the generic error (R3.7). 401/403/5xx map to the
 * generic error state. The 422 envelope is **never** read; the UI shows
 * localized copy only (R6R6.4).
 */
export function ConversationThreadView({
  conversationId,
}: {
  conversationId: string;
}) {
  const { t } = useTranslation(["conversations", "states"]);
  const conversationQuery = useConversation(conversationId);
  const messagesQuery = useConversationMessages(conversationId);
  const conversationState = mapConversationsError(conversationQuery);
  const messagesState = mapConversationsError(messagesQuery);

  if (conversationState.kind === "loading") {
    return <p>{t("states:loading.label", { ns: "states" })}</p>;
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
      <div>
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

  return (
    <section aria-labelledby="conversation-thread-heading">
      <h1 id="conversation-thread-heading">
        {t("thread.title")} — {conversation.id}
      </h1>
      <dl className="mb-4 grid grid-cols-2 gap-2 text-sm">
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
          <dd>{t(`escalationStatus.${conversation.escalationStatus}`)}</dd>
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
        <p>{t("states:loading.label", { ns: "states" })}</p>
      ) : messagesState.kind === "forbidden" ? (
        <p>{t("fields.forbidden")}</p>
      ) : messagesState.kind === "validation" ? (
        <p>{t("fields.validation")}</p>
      ) : messagesState.kind === "not-found" ||
        messagesState.kind === "error" ? (
        <div>
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
        <ConversationThreadMessages messages={messagesState.data.items} />
      )}
      <h2 className="mt-4 text-base font-medium">{t("thread.replyHeading")}</h2>
      <ConversationReplyForm conversationId={conversationId} />
    </section>
  );
}