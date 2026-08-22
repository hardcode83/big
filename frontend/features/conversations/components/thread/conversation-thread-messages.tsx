"use client";

import { useTranslation } from "react-i18next";

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
    return <p>{t("thread.noMessages")}</p>;
  }

  return (
    <ol className="flex flex-col gap-3">
      {messages.map((message) => (
        <li
          key={message.id}
          className="rounded-md border bg-background p-3"
          aria-label={`${t(`senderType.${message.senderType}`)} — ${message.createdAt}`}
        >
          <header className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
            <span className="rounded bg-muted px-2 py-0.5 font-medium">
              {t(`senderType.${message.senderType}`)}
            </span>
            <time dateTime={message.createdAt}>
              {message.createdAt.slice(0, 16).replace("T", " ")}
            </time>
          </header>
          {message.senderType === ("AI" satisfies MessageSenderType) &&
            message.intent && (
              <p className="mb-1 text-xs text-muted-foreground">
                {t("fields.intent")}: <code>{message.intent}</code>
              </p>
            )}
          {/*
            Plain-text rendering. The bracketed comment is the only place
            where the implementation choice is explained; the actual JSX is
            one element with `whitespace-pre-wrap` to preserve line breaks
            and `max-w-prose` to bound the width on desktop.
          */}
          <p className="whitespace-pre-wrap break-words max-w-prose">
            {message.content}
          </p>
          <ConversationThreadSenderMeta senderUserId={message.senderUserId} />
        </li>
      ))}
    </ol>
  );
}