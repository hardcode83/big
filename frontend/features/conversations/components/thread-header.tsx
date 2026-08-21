"use client";

import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";

import type { ConversationDetail } from "../data/dto";
import { isMuteChannel } from "../lib/channels";
import {
  CHANNEL_KEYS,
  CONVERSATION_STATUS_KEYS,
  ESCALATION_STATUS_KEYS,
} from "../lib/labels";

/**
 * The thread's header: detected language, channel and both state axes (R3.7).
 *
 * On a mute channel it carries a permanent warning worded as **"it is stored, it is
 * not sent"** rather than "it will fail" — because that is what the backend does.
 * `RecordHumanReplyUseCase` touches no outbound port, so a reply on `AIRBNB_MSG` or
 * `BOOKING_MSG` persists with 201 and is simply never delivered, with no error to
 * warn anyone (design D13). The transcription dialog carries its own, different
 * warning, because that path can lose the guest's message entirely.
 *
 * It also says the thread is not real time: the AI's reply appears because it is
 * generated inside the same request, but anything arriving by another route waits
 * for a reload.
 */
export function ThreadHeader({
  conversation,
}: {
  conversation: ConversationDetail;
}) {
  const { t } = useTranslation("conversations");

  return (
    <header className="flex flex-col gap-2 border-b p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant="outline">{t(CHANNEL_KEYS[conversation.channel])}</Badge>
        <Badge variant="secondary">
          {t(CONVERSATION_STATUS_KEYS[conversation.status])}
        </Badge>
        <Badge variant="outline">
          {t(ESCALATION_STATUS_KEYS[conversation.escalationStatus])}
        </Badge>
        <span className="text-muted-foreground">
          {t("thread.language")}: {conversation.language}
        </span>
      </div>
      {isMuteChannel(conversation.channel) ? (
        <p className="text-xs text-muted-foreground">{t("thread.muteWarning")}</p>
      ) : null}
      <p className="text-xs text-muted-foreground">{t("thread.notRealtime")}</p>
    </header>
  );
}
