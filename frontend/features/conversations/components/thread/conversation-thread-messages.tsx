"use client";

import { useTranslation } from "react-i18next";

import { Card } from "@/components/ui/card";

import type { MessageDto, MessageSenderType } from "../../data";
import { ConversationThreadSenderMeta } from "./conversation-thread-sender-meta";

/**
 * The message list of a conversation (proposal R3, design D7).
 *
 * `content` is rendered as **plain text** (`{value}` direct, no
 * `dangerouslySetInnerHTML`, no `react-markdown`, no `parseHtml`,
 * no autolinking), with `whitespace-pre-wrap` for line breaks and
 * `max-w-prose` to bound the line length on desktop. This is a
 * **material** requirement — `messages.content` is declared in the
 * regla 11 of `steering/security.md` as a free-text sink (third-party
 * prose for `sender_type = GUEST`, closed form for `ai_generated = true`)
 * and the regla forbids HTML rendering.
 *
 * `sender_type` is localised with a role tag. When `sender_type = AI`,
 * `intent` is shown if present (the field is free-form on the wire).
 */
export function ConversationThreadMessages({ messages }: { messages: MessageDto[] }) {
  const { t } = useTranslation("conversations");

  if (messages.length === 0) {
    return <p className="text-body-base text-muted-foreground">{t("thread.noMessages")}</p>;
  }

  return (
    <ol className="flex flex-col gap-3">
      {messages.map((message) => (
        <li
          key={message.id}
          className="list-none"
          aria-label={`${t(`senderType.${message.senderType}`)} — ${message.createdAt}`}
        >
          <Card className="p-3">
          <header className="mb-1 flex items-center justify-between text-body-base text-muted-foreground">
            <span className="rounded bg-muted px-2 py-0.5 text-body-medium">
              {t(`senderType.${message.senderType}`)}
            </span>
            <time dateTime={message.createdAt} className="font-mono text-data-mono">
              {message.createdAt.slice(0, 16).replace("T", " ")}
            </time>
          </header>
          {message.senderType === ("AI" satisfies MessageSenderType) &&
            message.intent && (
              <p className="mb-1 text-body-base text-muted-foreground">
                {t("fields.intent")}: <code className="font-mono text-data-mono">{message.intent}</code>
              </p>
            )}
          {/*
            Plain-text rendering. The bracketed comment is the only place
            where the implementation choice is explained; the actual JSX is
            one element with `whitespace-pre-wrap` to preserve line breaks
            and `max-w-prose` to bound the width on desktop.
          */}
          <p className="max-w-prose whitespace-pre-wrap break-words text-body-base text-foreground">
            {message.content}
          </p>
          {/*
            R3.5: render `sender_user_id` only for messages written by one
            of our own actors (`OWNER` / `MANAGER`) and **not** marked as
            AI-generated. `sender_user_id` is `null` for guest/system
            messages on the wire — the additional guards are belt-and-
            braces against future changes that might populate the field
            for non-actor senders.
          */}
          {message.senderUserId !== null &&
            !message.aiGenerated &&
            (message.senderType === "OWNER" ||
              message.senderType === "MANAGER") && (
              <ConversationThreadSenderMeta senderUserId={message.senderUserId} />
            )}
          </Card>
        </li>
      ))}
    </ol>
  );
}