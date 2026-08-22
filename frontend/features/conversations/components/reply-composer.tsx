"use client";

import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import { useSendReply } from "../hooks/use-conversation-actions";
import { errorMessageKey } from "../lib/errors";
import { MAX_MESSAGE_LENGTH } from "../lib/limits";
import type { ActionGate } from "../lib/transitions";

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
  draft,
  onDraftChange,
}: {
  conversationId: string;
  gate: ActionGate;
  /** The draft for this conversation, owned above the keyed boundary (D22). */
  draft: string;
  onDraftChange: (next: string) => void;
}) {
  const { t } = useTranslation("conversations");
  // The draft is **not** this component's state: it is owned by `ConversationsView`,
  // above the boundary that keys this subtree per conversation (D22). That is what
  // makes a failed send survive the operator walking away — the mutation's own error
  // state dies with the remount, so a restored draft is the only thing left that says
  // "this was never sent", and an empty composer can go back to meaning "delivered".
  const content = draft;
  const setContent = onDraftChange;
  // `lastSent` stays local and scoped to its conversation: it is a double-submit
  // guard, not a signal worth surviving a switch, and a component that is only
  // correct while its caller remembers a `key` is a trap.
  const [sent, setSent] = useState<{
    conversationId: string;
    value: string | null;
  }>({ conversationId, value: null });
  const lastSent = sent.conversationId === conversationId ? sent.value : null;
  // Retiring the draft is handed to the mutation itself, so it happens even when the
  // operator has already switched threads and this component is gone — see the note
  // on `useSendReply`. Doing it in `mutate(…, { onSuccess })` would silently skip
  // exactly that case, which is the one that ends in a duplicate reply.
  const send = useSendReply(conversationId, {
    onSent: () => onDraftChange(""),
  });

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
    // Clearing the draft is what turns an empty composer back into "delivered": a
    // failure leaves it untouched, so the text is still there on return.
    // Only the local double-submit guard rides on the mutate-level callback: it is
    // this component's own state, so it is worthless once this component is gone.
    send.mutate(sending, {
      onSuccess: () => {
        setSent({ conversationId, value: sending });
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
