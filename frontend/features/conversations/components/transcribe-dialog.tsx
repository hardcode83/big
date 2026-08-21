"use client";

import { useState } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { DialogShell } from "@/components/ui/dialog-shell";

import type { ConversationChannel } from "../data/dto";
import { useTranscribeGuestMessage } from "../hooks/use-conversation-actions";
import { isMuteChannel } from "../lib/channels";
import { errorMessageKey, rejectedWithoutStoring } from "../lib/errors";
import { MAX_MESSAGE_LENGTH } from "../lib/limits";
import type { ActionGate } from "../lib/transitions";

const REASON_ID = "transcribe-reason";

/**
 * Transcribing what the guest said (R4.2): the same endpoint as a reply, but with
 * `sender_type: "GUEST"`, which is what runs the whole AI pipeline server-side —
 * language detection, classification, escalation policy, and either an automatic
 * reply or a handover to a person.
 *
 * A separate, unambiguously labelled action rather than a mode of the composer,
 * because the two do different things and only this one can speak as the guest.
 *
 * Two warnings, and they are not the same warning (design D13):
 * - always: this triggers the AI's reply and may escalate the conversation;
 * - on a mute channel: the transcription can be lost **entirely**. The pipeline
 *   reaches `_reply`, finds no adapter, raises `PMSChannelUnavailableError` → 422,
 *   and because it all runs in one transaction the guest's message is not stored
 *   either. Hence the error state says explicitly that nothing was stored — but
 *   **only for the failures where that is derivable** (a 4xx). A 5xx or a dropped
 *   connection may have committed the row, and telling the operator otherwise
 *   hides a guest's prose that is really there (review 2026-08-21).
 *
 * The dialog stays open on failure: closing it would hide the one sentence that
 * tells the operator their transcription did not survive.
 */
export function TranscribeDialog({
  conversationId,
  channel,
  gate,
}: {
  conversationId: string;
  channel: ConversationChannel;
  gate: ActionGate;
}) {
  const { t } = useTranslation("conversations");
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState("");
  const transcribe = useTranscribeGuestMessage(conversationId);

  const tooLong = content.length > MAX_MESSAGE_LENGTH;
  const canSubmit =
    gate.enabled &&
    content.trim().length > 0 &&
    !tooLong &&
    !transcribe.isPending;

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setContent("");
      transcribe.reset();
    }
  }

  return (
    <>
      <DialogShell
        open={open}
        onOpenChange={handleOpenChange}
        title={t("transcribe.title")}
        description={t("transcribe.description")}
        trigger={
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!gate.enabled}
            aria-describedby={gate.enabled ? undefined : REASON_ID}
          >
            {t("transcribe.open")}
          </Button>
        }
        footer={
          <>
            <DialogPrimitive.Close asChild>
              <Button type="button" variant="outline">
                {t("transcribe.cancel")}
              </Button>
            </DialogPrimitive.Close>
            <Button
              type="button"
              disabled={!canSubmit}
              onClick={() =>
                transcribe.mutate(content, {
                  onSuccess: () => handleOpenChange(false),
                })
              }
            >
              {transcribe.isPending
                ? t("composer.sending")
                : t("transcribe.submit")}
            </Button>
          </>
        }
      >
        {isMuteChannel(channel) ? (
          <p className="text-sm text-muted-foreground">
            {t("transcribe.muteWarning")}
          </p>
        ) : null}
        <label className="sr-only" htmlFor="transcribe-content">
          {t("transcribe.field")}
        </label>
        <textarea
          id="transcribe-content"
          className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          placeholder={t("transcribe.placeholder")}
          value={content}
          disabled={transcribe.isPending}
          onChange={(event) => setContent(event.target.value)}
        />
        <span className="text-xs text-muted-foreground">
          {t("composer.counter", {
            current: content.length,
            max: MAX_MESSAGE_LENGTH,
          })}
        </span>
        {tooLong ? (
          <p className="text-xs text-destructive">
            {t("composer.tooLong", { max: MAX_MESSAGE_LENGTH })}
          </p>
        ) : null}
        {transcribe.isError ? (
          <p role="alert" className="text-xs text-destructive">
            {rejectedWithoutStoring(transcribe.error)
              ? t("transcribe.errorTitle")
              : t("transcribe.errorTitleUncertain")}{" "}
            {t(errorMessageKey(transcribe.error))}
          </p>
        ) : null}
      </DialogShell>
      {gate.enabled ? null : (
        <p id={REASON_ID} className="text-xs text-muted-foreground">
          {t(gate.reasonKey)}
        </p>
      )}
    </>
  );
}
