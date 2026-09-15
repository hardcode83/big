"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import {
  useCleanerTaskMessages,
  useSendCleanerTaskMessage,
} from "../../hooks/use-cleaner-task-messages";
import { mapCleanerError } from "../../lib/error-mapping";
import type { CleaningTaskMessage, PaginatedResponse } from "../../data";

/** The contract's upper bound for `content` (backend `staff-messaging`, D5). */
const MAX_CONTENT = 2000;

/**
 * The cleaner's staff thread for one cleaning task (R1, R4, design D4, D6).
 *
 * **Pagination (D4).** Page 1 is the *oldest* page — the backend orders
 * ascending — so «Cargar mensajes más recientes» asks for `page + 1` and the
 * rows it returns are **appended** to what is already on screen, never
 * replacing it. What is on screen is `olderRows` (the pages already left
 * behind, frozen when the reader advanced past them) followed by the open
 * page's live rows, so a refetch of the open page — what the send mutation's
 * invalidation triggers (D5) — refreshes the tail without duplicating a row.
 *
 * **Tail following after a send (R1.2).** A send adds exactly one message, so
 * it grows the thread by at most one page. When the cleaner was already at the
 * end of the thread and her message spilled onto a new page, the handler reads
 * the refreshed `totalPages` and advances exactly one page — contiguous, so
 * the appended list never has a gap. When she was reading an older page
 * instead, the view stays where she is and the «cargar más recientes» button
 * remains her way forward.
 *
 * **Composer (D6).** Native `<textarea maxLength={2000}>`, no form library.
 * Local validation (`trim().length` in 1..2000) disables the submit control
 * *before* any backend call (R1.3), `mutation.isPending` disables it while a
 * send is in flight (R1.4), and the typed text survives a failed send —
 * it is cleared only on success (R4.3).
 *
 * The query is lazy: `enabled` is the sticky `hasOpenedMessagesTab` flag that
 * `CleanerTaskTabs` owns (D1), so nothing is requested until the cleaner opens
 * the Messages tab.
 */
export interface CleanerTaskMessagesPanelProps {
  taskId: string;
  /** The tabs' sticky "messages tab has been opened" flag (design D1). */
  enabled: boolean;
}

export function CleanerTaskMessagesPanel({
  taskId,
  enabled,
}: CleanerTaskMessagesPanelProps) {
  const { t, i18n } = useTranslation("cleaner");
  const locale = i18n.language;

  const [page, setPage] = useState(1);
  const [olderRows, setOlderRows] = useState<CleaningTaskMessage[]>([]);
  const [content, setContent] = useState("");
  const [touched, setTouched] = useState(false);
  const [submitErrorKey, setSubmitErrorKey] = useState<string | null>(null);

  const query = useCleanerTaskMessages(taskId, page, enabled);
  const mutation = useSendCleanerTaskMessage(taskId);
  const pageData = query.data;

  // What is on screen is the pages already read plus the page currently open,
  // in that order (D4). `olderRows` is only ever written from an event
  // handler, at the moment the reader leaves a page behind: the thread is
  // append-only (no edit/delete endpoint exists), so a page that is no longer
  // the last one cannot change under us, while the open page stays live and
  // picks up the refetch a send triggers.
  const messages = pageData ? [...olderRows, ...pageData.data] : olderRows;

  /** Leaves the page just read behind and opens the next one (D4). */
  function advancePast(read: PaginatedResponse<CleaningTaskMessage>) {
    setOlderRows((rows) => [...rows, ...read.data]);
    setPage(read.page + 1);
  }

  const validationKey = validate(content);
  const hasMoreRecent = pageData ? pageData.totalPages > pageData.page : false;

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTouched(true);
    if (validationKey || mutation.isPending) {
      // R1.3: the backend is never called with content the composer already
      // knows is invalid.
      return;
    }
    setSubmitErrorKey(null);
    const wasAtTail = pageData ? pageData.page >= pageData.totalPages : true;
    mutation.mutate(
      { content: content.trim() },
      {
        onSuccess: async () => {
          // R4.3 inverted: the text is dropped only once the backend accepted
          // it.
          setContent("");
          setTouched(false);
          // The mutation's `onSettled` invalidation (D5) already refreshes the
          // open page; reading that refresh here is what tells us whether the
          // message just sent spilled onto a *new* page. It can only ever add
          // one, so advancing by one keeps the appended list contiguous and
          // puts the cleaner's own message on screen (R1.2).
          const refreshed = await query.refetch();
          const latest = refreshed.data;
          if (wasAtTail && latest && latest.totalPages > latest.page) {
            advancePast(latest);
          }
        },
        onError: (error) => {
          setSubmitErrorKey(mapCleanerError(error, "sendMessage").messageKey);
        },
      },
    );
  }

  const composer = (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <label
        htmlFor="cleaner-task-message-content"
        className="block text-xs font-medium text-muted-foreground"
      >
        {t("messages.composer.label")}
      </label>
      <textarea
        id="cleaner-task-message-content"
        rows={3}
        maxLength={MAX_CONTENT}
        value={content}
        placeholder={t("messages.composer.placeholder")}
        aria-describedby="cleaner-task-message-counter"
        onChange={(event) => {
          setContent(event.target.value);
          setTouched(true);
        }}
        className="w-full rounded-md border bg-background px-2 py-1 text-sm"
      />
      <span
        id="cleaner-task-message-counter"
        className="text-xs text-muted-foreground"
      >
        {t("messages.composer.counter", {
          current: content.length,
          max: MAX_CONTENT,
        })}
      </span>
      {touched && validationKey ? (
        <span role="alert" className="text-xs text-destructive">
          {t(validationKey)}
        </span>
      ) : null}
      {submitErrorKey ? (
        <span role="alert" className="text-xs text-destructive">
          {t(submitErrorKey)}
        </span>
      ) : null}
      <div className="flex justify-end">
        <Button
          type="submit"
          className="tap-target"
          disabled={validationKey !== null || mutation.isPending}
        >
          {mutation.isPending
            ? t("messages.composer.sending")
            : t("messages.composer.send")}
        </Button>
      </div>
    </form>
  );

  const errorMap = query.isError
    ? mapCleanerError(query.error, "messages")
    : null;

  // R4.2 vs R2.8: a 404 means the task itself is gone, not that the thread is
  // empty — there is nothing to compose against, so the composer goes with it.
  if (errorMap?.state === "not-found") {
    return (
      <div className="flex flex-col gap-4">
        <EmptyState
          title={t(errorMap.messageKey)}
          description={t("detail.unavailable.description")}
        />
      </div>
    );
  }

  // The list region is what loading/empty/error swap (R4.1, R4.2, R4.3); a
  // failure or a refetch of a *later* page never discards the pages already
  // appended, so the thread does not blink away under the cleaner.
  let listRegion;
  if (query.isPending && messages.length === 0) {
    listRegion = <LoadingState label={t("messages.loading")} />;
  } else if (errorMap && messages.length === 0) {
    listRegion = (
      <ErrorState
        title={t(errorMap.messageKey)}
        description={t("messages.error.description")}
      />
    );
  } else if (messages.length === 0) {
    listRegion = (
      <EmptyState
        title={t("messages.empty.title")}
        description={t("messages.empty.description")}
      />
    );
  } else {
    listRegion = (
      <ol className="flex flex-col gap-3">
        {messages.map((message) => (
          <li key={message.id}>
            <Card className="flex flex-col gap-1 p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-label-caps uppercase text-muted-foreground">
                  {t(`messages.roles.${message.authorRole}`)}
                </span>
                <span className="text-xs text-muted-foreground">
                  {new Intl.DateTimeFormat(locale, {
                    dateStyle: "medium",
                    timeStyle: "short",
                  }).format(new Date(message.createdAt))}
                </span>
              </div>
              <p className="whitespace-pre-wrap break-words text-body-medium text-foreground">
                {message.content}
              </p>
            </Card>
          </li>
        ))}
      </ol>
    );
  }

  return (
    <section
      aria-labelledby="cleaner-task-messages-heading"
      className="flex flex-col gap-4"
    >
      <h2
        id="cleaner-task-messages-heading"
        className="text-body-lg font-semibold text-foreground"
      >
        {t("messages.title")}
      </h2>
      {listRegion}
      {errorMap && messages.length > 0 ? (
        <ErrorState
          title={t(errorMap.messageKey)}
          description={t("messages.error.description")}
        />
      ) : null}
      {hasMoreRecent ? (
        <Button
          type="button"
          variant="outline"
          className="tap-target"
          disabled={query.isFetching}
          onClick={() => {
            if (pageData) advancePast(pageData);
          }}
        >
          {t("messages.loadNewer")}
        </Button>
      ) : null}
      {composer}
    </section>
  );
}

/** R1.3 / D6: 1..2000 characters once trimmed, checked before any request. */
function validate(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return "messages.errors.required";
  if (trimmed.length > MAX_CONTENT) return "messages.errors.tooLong";
  return null;
}
