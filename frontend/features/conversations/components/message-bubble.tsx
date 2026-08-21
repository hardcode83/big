"use client";

import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { MessageSenderType, ThreadMessage } from "../data/dto";
import { formatConfidence, formatDateTime } from "../lib/format";
import { SENDER_TYPE_KEYS } from "../lib/labels";

type Side = "guest" | "us" | "system";

/**
 * ASSUMPTION: the backend only ever sends one of the five `MessageSenderType`
 * values the contract declares. Exhaustive over that union, so a sender added to
 * the backend stops compiling here instead of silently landing on the guest's side
 * of the thread (R3.3) — regenerating the contract is what surfaces it, since
 * nothing validates the value at runtime. `AI` sits with us because we generated
 * it, whatever the guest sees.
 */
const SIDE: Record<MessageSenderType, Side> = {
  GUEST: "guest",
  OWNER: "us",
  MANAGER: "us",
  AI: "us",
  SYSTEM: "system",
};

const SIDE_CLASS: Record<Side, string> = {
  guest: "mr-auto items-start",
  us: "ml-auto items-end",
  system: "mx-auto items-center",
};

/**
 * One message in the thread.
 *
 * `content` is rendered as **text and nothing else** (design D15): a `<p>` with
 * `whitespace-pre-wrap` and React's default escaping — no `dangerouslySetInnerHTML`,
 * no markdown, no autolinking, no truncation. What lands there is a guest's
 * verbatim prose, which `steering/security.md` rule 11 exception 4 admits precisely
 * because it is not ours, and which may contain their document number. Turning it
 * into active surface for a convenience nobody asked for is what that rule forbids.
 * `intent` and the language are painted the same way: as data.
 *
 * A reply whose `delivery_status` is `FAILED` carries a localized mark (D14):
 * without it the inbox shows as sent something the guest never received, which is
 * systematic on `PHONE_TRANSCRIPT`.
 */
export function MessageBubble({ message }: { message: ThreadMessage }) {
  const { t, i18n } = useTranslation("conversations");
  const locale = i18n.language;
  const side = SIDE[message.senderType];
  const confidence = formatConfidence(message.confidenceScore, locale);

  return (
    <li
      data-sender={message.senderType}
      data-side={side}
      className={cn("flex w-full max-w-[85%] flex-col gap-1", SIDE_CLASS[side])}
    >
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">
          {t(SENDER_TYPE_KEYS[message.senderType])}
        </span>
        <time dateTime={message.createdAt}>
          {formatDateTime(message.createdAt, locale) ?? message.createdAt}
        </time>
        {message.aiGenerated ? (
          <Badge variant="secondary">{t("message.aiGenerated")}</Badge>
        ) : null}
        {message.aiGenerated && message.intent !== null ? (
          <span>
            {t("message.intent")}: {message.intent}
          </span>
        ) : null}
        {message.aiGenerated && confidence !== null ? (
          <span>
            {t("message.confidence")}: {confidence}
          </span>
        ) : null}
        {message.deliveryStatus === "FAILED" ? (
          <Badge variant="outline">{t("message.notDelivered")}</Badge>
        ) : null}
      </div>
      <p className="whitespace-pre-wrap rounded-md border border-input px-3 py-2 text-sm text-foreground">
        {message.content}
      </p>
    </li>
  );
}
