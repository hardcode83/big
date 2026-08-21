"use client";

import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import { useSendReply } from "../hooks/use-conversation-actions";
import { errorMessageKey } from "../lib/errors";
import type { ActionGate } from "../lib/transitions";

/** `CreateMessageRequest.content` is capped at 4000 characters by the contract. */
export const MAX_MESSAGE_LENGTH = 4000;

const REASON_ID = "reply-composer-reason";
const ERROR_ID = "reply-composer-error";

/**
 * The reply composer (R4.1, R4.3, R4.5). It posts **without** `sender_type`, so the
 * backend derives the sender from the caller's role — a manager cannot write as the
 * guest from here, which is what the separate transcription action is for.
 *
 * The 4000-character limit and the empty-content rule are enforced before the
 * request, so the manager sees the limit instead of a 422. A failed send **keeps
 * the text** and never presents the message as sent: there is no optimistic
 * append, so nothing has to be rolled back.
 */
export function ReplyComposer({
  conversationId,
  gate,
}: {
  conversationId: string;
  gate: ActionGate;
}) {
  const { t } = useTranslation("conversations");
  // The draft is stored **with the conversation it was typed in** and derived
  // during render, exactly as `ConversationThread` does with the page. Selecting
  // another conversation does not unmount this component when the target thread
  // is already cached (`useConversation` has no `placeholderData`, so there is no
  // pending early return to remount it), and a draft left under someone else's id
  // is one click away from a reply delivered to the wrong guest. `lastSent` is
  // scoped the same way, or an identical legitimate reply to another guest would
  // be refused as a double submit.
  const [draft, setDraft] = useState<{
    conversationId: string;
    content: string;
    lastSent: string | null;
  }>({ conversationId, content: "", lastSent: null });
  const mine = draft.conversationId === conversationId;
  const content = mine ? draft.content : "";
  const lastSent = mine ? draft.lastSent : null;
  const setContent = (next: string) =>
    setDraft({ conversationId, content: next, lastSent });
  const send = useSendReply(conversationId);

  const tooLong = content.length > MAX_MESSAGE_LENGTH;
  const isEmpty = content.trim().length === 0;
  // Re-sending the exact text we just sent is almost always a double submit.
  const isRepeat = lastSent !== null && content === lastSent;
  const blocked = !gate.enabled || send.isPending;
  const canSend = !blocked && !isEmpty && !tooLong && !isRepeat;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSend) {
      return;
    }
    const sending = content;
    // `conversationId` is the one captured at submit time, so a success that lands
    // after the operator moved on records the sent text against the conversation it
    // was actually sent to — never against whichever thread is on screen by then.
    send.mutate(sending, {
      onSuccess: () => {
        setDraft({ conversationId, content: "", lastSent: sending });
      },
    });
  }

  const describedBy = [
    gate.enabled ? undefined : REASON_ID,
    send.isError ? ERROR_ID : undefined,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2 border-t p-3">
      <label className="sr-only" htmlFor="reply-composer-content">
        {t("composer.label")}
      </label>
      <textarea
        id="reply-composer-content"
        className="min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        placeholder={t("composer.placeholder")}
        value={content}
        disabled={blocked}
        aria-describedby={describedBy === "" ? undefined : describedBy}
        onChange={(event) => setContent(event.target.value)}
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">
          {t("composer.counter", {
            current: content.length,
            max: MAX_MESSAGE_LENGTH,
          })}
        </span>
        <Button type="submit" size="sm" disabled={!canSend}>
          {send.isPending ? t("composer.sending") : t("composer.send")}
        </Button>
      </div>
      {tooLong ? (
        <p className="text-xs text-destructive">
          {t("composer.tooLong", { max: MAX_MESSAGE_LENGTH })}
        </p>
      ) : null}
      {!gate.enabled ? (
        <p id={REASON_ID} className="text-xs text-muted-foreground">
          {t(gate.reasonKey)}
        </p>
      ) : null}
      {send.isError ? (
        <p id={ERROR_ID} role="alert" className="text-xs text-destructive">
          {t("composer.errorTitle")} {t(errorMessageKey(send.error))}
        </p>
      ) : null}
    </form>
  );
}
