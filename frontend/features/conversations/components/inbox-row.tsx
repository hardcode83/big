"use client";

import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { ConversationSummary, PropertyLabel } from "../data/dto";
import { formatAge, formatDateTime } from "../lib/format";
import {
  CHANNEL_KEYS,
  CONVERSATION_STATUS_KEYS,
  ESCALATION_STATUS_KEYS,
} from "../lib/labels";

export interface InboxRowProps {
  conversation: ConversationSummary;
  /** Resolved from the cached label catalogue; `undefined` when it is not in it. */
  property: PropertyLabel | undefined;
  isSelected: boolean;
  onSelect: (conversationId: string) => void;
}

/**
 * One inbox row (R1.2). The whole row is the control, so its accessible name is
 * its own content, prefixed by the localized action.
 *
 * The age goes in a `<time>` whose `title` is the absolute instant (design D9):
 * "3 days ago" must not be the only thing a manager can read. A conversation
 * nobody has written to says so in words rather than showing an invented date
 * (R1.3), and a property missing from the cached catalogue degrades to a
 * localized placeholder instead of breaking the row (R1.7).
 */
export function InboxRow({
  conversation,
  property,
  isSelected,
  onSelect,
}: InboxRowProps) {
  const { t, i18n } = useTranslation("conversations");
  const locale = i18n.language;
  const { lastMessageAt } = conversation;

  const propertyText =
    conversation.propertyId === null
      ? t("inbox.noProperty")
      : (property?.internalCode ?? t("inbox.unknownProperty"));

  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(conversation.id)}
        aria-current={isSelected ? "true" : undefined}
        className={cn(
          "flex w-full flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-left text-sm",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          isSelected
            ? "border-primary bg-accent"
            : "border-input hover:bg-accent",
        )}
      >
        <span className="sr-only">{t("inbox.openConversation")}</span>
        <span className="font-medium text-foreground">{propertyText}</span>
        <Badge variant="outline">{t(CHANNEL_KEYS[conversation.channel])}</Badge>
        <Badge variant="secondary">
          {t(CONVERSATION_STATUS_KEYS[conversation.status])}
        </Badge>
        <Badge variant="outline">
          {t(ESCALATION_STATUS_KEYS[conversation.escalationStatus])}
        </Badge>
        <span className="text-muted-foreground">{conversation.language}</span>
        {lastMessageAt === null ? (
          <span className="ml-auto text-muted-foreground">
            {t("inbox.noMessages")}
          </span>
        ) : (
          <time
            className="ml-auto text-muted-foreground"
            dateTime={lastMessageAt}
            title={formatDateTime(lastMessageAt, locale) ?? undefined}
          >
            {formatAge(lastMessageAt, locale) ?? lastMessageAt}
          </time>
        )}
      </button>
    </li>
  );
}
