"use client";

import { useLayoutEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import {
  useCleanerTaskMessages,
  useSendCleanerTaskMessage,
  type CleaningTaskMessage,
  type PaginatedResponse,
} from "@/features/cleaner";

import { mapCleaningError, sendErrorKeyForCleaning } from "../../lib/messages-error";

/** The contract's upper bound for `content` (backend `staff-messaging`, D5). */
const MAX_CONTENT = 2000;

/**
 * The manager's staff thread for one cleaning task (R2.1, R2.2, R2.3, R2.4,
 * R2.5; design D4, D5, D6). The mirror of `CleanerTaskMessagesPanel` for the
 * manager's surface, sharing the same pagination, composer and 404
 * propagation rules; the section-2 UI/UX review standardised the ErrorState
 * retry wiring and the dynamic `aria-describedby` / `aria-invalid` on the
 * textarea, so the panel adopts that convention from the start (the
 * cleaner-side panel predates the standard).
 *
 * **Pagination (D4).** Page 1 is the *oldest* page — the backend orders
 * ascending — so «Cargar mensajes más recientes» asks for `page + 1` and the
 * rows it returns are **appended** to what is already on screen, never
 * replacing it. What is on screen is `olderRows` (the pages already left
 * behind) followed by the open page's live rows, so a refetch of the open
 * page — what the send mutation's invalidation triggers — refreshes the tail
 * without duplicating a row.
 *
 * **Tail following after a send (R2.3).** A send adds exactly one message,
 * so it grows the thread by at most one page. When the manager was already
 * at the end of the thread and his message spilled onto a new page, the
 * handler reads the refreshed `totalPages` and advances exactly one page.
 *
 * **Composer (D5).** Native `<textarea maxLength={2000}>`, no form library.
 * Local validation (`trim().length` in 1..2000) disables the submit control
 * *before* any backend call (R2.3), `mutation.isPending` disables it while a
 * send is in flight (R2.4), and the typed text survives a failed send — it
 * is cleared only on success (R2.3, R4.3). The textarea's `aria-describedby`
 * is rebuilt dynamically to include the error span id, and `aria-invalid`
 * toggles in sync — the section-2 UI/UX standard.
 *
 * **404 propagation (R2.5).** A 404 on this query means the task itself is
 * gone — the same fact `useCleaningTask` already detects and reacts to by
 * replacing the *whole* detail screen. Because this query loads lazily
 * (only once the Messages tab is opened), a task that looked fine when the
 * detail read ran can vanish by the time this one does. `onNotFound` tells
 * the parent detail view so it can fold this 404 into its own whole-screen
 * not-found branch, which *replaces* the panel-local `EmptyState` below
 * rather than layering on top of it.
 *
 * When `onNotFound` is supplied the panel renders nothing at all for the
 * 404: the callback fires in a `useLayoutEffect` (synchronously after
 * render, before the browser paints), so the parent's whole-screen swap
 * lands in the same frame. Rendering the panel-local `EmptyState` here
 * instead would paint a weaker, tab-confined not-found surface for exactly
 * one frame before the correct whole-screen one replaced it — a visible
 * flash.
 */
export interface ManagerCleaningTaskMessagesPanelProps {
  taskId: string;
  /** The tabs' sticky "messages tab has been opened" flag (design D4). */
  enabled: boolean;
  /** Called (repeatably) whenever the messages read 404s. */
  onNotFound?: () => void;
}

export function ManagerCleaningTaskMessagesPanel({
  taskId,
  enabled,
  onNotFound,
}: ManagerCleaningTaskMessagesPanelProps) {
  const { t, i18n } = useTranslation("cleaning");
  const locale = i18n.language;

  const [page, setPage] = useState(1);
  const [olderRows, setOlderRows] = useState<CleaningTaskMessage[]>([]);
  const [content, setContent] = useState("");
  const [touched, setTouched] = useState(false);

  const query = useCleanerTaskMessages(taskId, page, enabled);
  const mutation = useSendCleanerTaskMessage(taskId);
  const pageData = query.data;

  // What is on screen is the pages already read plus the page currently
  // open, in that order (D4). `olderRows` is only ever written from an
  // event handler, at the moment the reader leaves a page behind.
  const messages = pageData ? [...olderRows, ...pageData.data] : olderRows;

  /** Leaves the page just read behind and opens the next one (D4). */
  function advancePast(read: PaginatedResponse<CleaningTaskMessage>) {
    setOlderRows((rows) => [...rows, ...read.data]);
    setPage(read.page + 1);
  }

  const validationKey = validate(content);
  const hasMoreRecent = pageData ? pageData.totalPages > pageData.page : false;

  // Read straight off the mutation result, which TanStack resets on the
  // next `mutate()` — there is no second copy of the failure in local
  // state to go stale.
  const sendErrorKey = mutation.isError
    ? sendErrorKeyForCleaning(mapCleaningError(mutation).kind)
    : null;

  // The error shown beneath the composer (R2.3 / R2.4). Client-side
  // validation has priority so the user sees the cursor-side reason first;
  // it only surfaces once the field has been touched. The textarea's
  // `aria-describedby` and `aria-invalid` track this same value so
  // assistive tech gets the same association the eye does — the
  // section-2 standard the panel adopts from the start.
  const visibleErrorKey =
    touched && validationKey ? validationKey : sendErrorKey;
  const describedById = [
    "manager-cleaning-message-counter",
    visibleErrorKey ? "manager-cleaning-message-error" : null,
  ]
    .filter(Boolean)
    .join(" ");

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTouched(true);
    if (validationKey || mutation.isPending) {
      // R2.3: the backend is never called with content the composer already
      // knows is invalid.
      return;
    }
    const wasAtTail = pageData ? pageData.page >= pageData.totalPages : true;
    mutation.mutate(
      { content: content.trim() },
      {
        onSuccess: async () => {
          // R2.3 / R4.3 inverted: the text is dropped only once the backend
          // accepted it.
          setContent("");
          setTouched(false);
          // The mutation's `onSettled` invalidation already refreshes the
          // open page; reading that refresh here is what tells us whether
          // the message just sent spilled onto a *new* page.
          const refreshed = await query.refetch();
          const latest = refreshed.data;
          if (wasAtTail && latest && latest.totalPages > latest.page) {
            advancePast(latest);
          }
        },
      },
    );
  }

  const composer = (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <label
        htmlFor="manager-cleaning-message-content"
        className="block text-xs font-medium text-muted-foreground"
      >
        {t("messages.composer.label")}
      </label>
      <textarea
        id="manager-cleaning-message-content"
        rows={3}
        maxLength={MAX_CONTENT}
        value={content}
        placeholder={t("messages.composer.placeholder")}
        aria-describedby={describedById}
        aria-invalid={visibleErrorKey !== null}
        onChange={(event) => {
          setContent(event.target.value);
          setTouched(true);
        }}
        className="w-full rounded-md border bg-background px-2 py-1 text-sm"
      />
      <span
        id="manager-cleaning-message-counter"
        className="text-xs text-muted-foreground"
      >
        {t("messages.composer.counter", {
          current: content.length,
          max: MAX_CONTENT,
        })}
      </span>
      {touched && validationKey ? (
        <span
          id="manager-cleaning-message-error"
          role="alert"
          className="text-xs text-destructive"
        >
          {t(validationKey)}
        </span>
      ) : sendErrorKey ? (
        <span
          id="manager-cleaning-message-error"
          role="alert"
          className="text-xs text-destructive"
        >
          {t(sendErrorKey)}
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

  const readState = mapCleaningError(query);

  // Propagate the 404 up so the parent detail view can replace the whole
  // screen, the same as it already does for the detail read. `useLayoutEffect`,
  // not `useEffect`: it runs before the browser paints, so the parent's
  // swap is the first thing the manager sees.
  useLayoutEffect(() => {
    if (readState.kind === "not-found") {
      onNotFound?.();
    }
  }, [readState.kind, onNotFound]);

  // R2.5: a 404 means the task itself is gone, not that the thread is
  // empty — there is nowhere left to send a draft, so the composer goes
  // with it. With a parent listening, render nothing: the whole-screen
  // EmptyState is already on its way in.
  if (readState.kind === "not-found") {
    if (onNotFound) {
      return null;
    }
    return (
      <div className="flex flex-col gap-4">
        <EmptyState
          title={t("messages.error.title")}
          description={t("messages.error.description")}
        />
      </div>
    );
  }

  const hasReadError =
    readState.kind !== "ok" && readState.kind !== "loading";

  // The list region is what loading/empty/error swap (R2.2, R2.5); a
  // failure or a refetch of a *later* page never discards the pages
  // already appended, so the thread does not blink away under the manager.
  let listRegion;
  if (readState.kind === "loading" && messages.length === 0) {
    listRegion = <LoadingState label={t("messages.loading")} />;
  } else if (hasReadError && messages.length === 0) {
    listRegion = (
      <ErrorState
        title={t("messages.error.title")}
        description={t("messages.error.description")}
        retryLabel={t("states:error.retry", { ns: "states" })}
        onRetry={() => {
          void query.refetch();
        }}
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
      aria-labelledby="manager-cleaning-messages-heading"
      className="flex flex-col gap-4"
    >
      <h2
        id="manager-cleaning-messages-heading"
        className="text-body-lg font-semibold text-foreground"
      >
        {t("messages.title")}
      </h2>
      {listRegion}
      {hasReadError && messages.length > 0 ? (
        <ErrorState
          title={t("messages.error.title")}
          description={t("messages.error.description")}
          retryLabel={t("states:error.retry", { ns: "states" })}
          onRetry={() => {
            void query.refetch();
          }}
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

/** R2.3: 1..2000 characters once trimmed, checked before any request. */
function validate(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return "messages.errors.required";
  if (trimmed.length > MAX_CONTENT) return "messages.errors.tooLong";
  return null;
}
