"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import {
  mapIncidentsError,
  useIncidentMessages,
  useSendIncidentMessage,
  type IncidentMessage,
  type PaginatedResponse,
} from "@/features/incidents";

/** The contract's upper bound for `content` (backend `staff-messaging`, D6). */
const MAX_CONTENT = 2000;

/**
 * The technician's staff thread for one incident (R2, R4, design D4, D6).
 *
 * The mirror of `cleaner-task-messages-panel.tsx`, on the incidents data
 * source: the two modules stay separate on purpose (design D2/D7), so the
 * shape is copied, not shared.
 *
 * **Pagination (D4).** Page 1 is the *oldest* page — the backend orders
 * ascending — so «Cargar mensajes más recientes» asks for `page + 1` and the
 * rows it returns are **appended** to what is already on screen, never
 * replacing it. What is on screen is `olderRows` (the pages already left
 * behind, frozen when the reader advanced past them) followed by the open
 * page's live rows, so a refetch of the open page — what the send mutation's
 * invalidation triggers (D5) — refreshes the tail without duplicating a row.
 *
 * **Tail following after a send (R2.2).** A send adds exactly one message, so
 * it grows the thread by at most one page. When the technician was already at
 * the end of the thread and his message spilled onto a new page, the handler
 * reads the refreshed `totalPages` and advances exactly one page — contiguous,
 * so the appended list never has a gap.
 *
 * **Composer (D6).** Native `<textarea maxLength={2000}>`, no form library.
 * Local validation (`trim().length` in 1..2000) disables the submit control
 * *before* any backend call (R2.3), `mutation.isPending` disables it while a
 * send is in flight (R2.4), and the typed text survives a failed send — it is
 * cleared only on success (R4.3).
 *
 * **Why the error copy is picked here and not in the mapper.**
 * `mapIncidentsError` is this module's *generic*, status-only mapper: it takes
 * a query (or mutation) result and returns a `kind`, with no `kind` input
 * parameter and no `messageKey` — unlike `cleaner`'s `mapCleanerError(error,
 * kind)`, which resolves the copy itself. So the mapping from `kind` to an
 * i18n key lives in this component (`sendErrorKey`), which is the only place
 * that knows the surface is a message composer.
 *
 * The query is lazy: `enabled` is the sticky `hasOpenedMessagesTab` flag that
 * `TechIncidentTabs` owns (D1), so nothing is requested until the technician
 * opens the Messages tab.
 *
 * **404 propagation (R4.3, proposal amendment).** A 404 on this query means
 * the incident itself is gone — the same fact `incident`/`context` already
 * detect and react to by replacing the *whole* detail screen. Because this
 * query loads lazily (only once the Messages tab is opened), an incident that
 * looked fine when the other two reads ran can vanish by the time this one
 * does. `onNotFound` tells the parent detail view so it can fold this 404
 * into its own whole-screen not-found branch, on top of (not instead of) the
 * panel-local `EmptyState` below, which stays as the immediate rendering for
 * this panel.
 */
export interface TechIncidentMessagesPanelProps {
  incidentId: string;
  /** The tabs' sticky "messages tab has been opened" flag (design D1). */
  enabled: boolean;
  /** Called (repeatably) whenever the messages read 404s. */
  onNotFound?: () => void;
}

export function TechIncidentMessagesPanel({
  incidentId,
  enabled,
  onNotFound,
}: TechIncidentMessagesPanelProps) {
  const { t, i18n } = useTranslation("tech");
  const locale = i18n.language;

  const [page, setPage] = useState(1);
  const [olderRows, setOlderRows] = useState<IncidentMessage[]>([]);
  const [content, setContent] = useState("");
  const [touched, setTouched] = useState(false);

  const query = useIncidentMessages(incidentId, page, enabled);
  const mutation = useSendIncidentMessage(incidentId);
  const pageData = query.data;

  // What is on screen is the pages already read plus the page currently open,
  // in that order (D4). `olderRows` is only ever written from an event
  // handler, at the moment the reader leaves a page behind: the thread is
  // append-only (no edit/delete endpoint exists), so a page that is no longer
  // the last one cannot change under us, while the open page stays live and
  // picks up the refetch a send triggers.
  const messages = pageData ? [...olderRows, ...pageData.data] : olderRows;

  /** Leaves the page just read behind and opens the next one (D4). */
  function advancePast(read: PaginatedResponse<IncidentMessage>) {
    setOlderRows((rows) => [...rows, ...read.data]);
    setPage(read.page + 1);
  }

  const validationKey = validate(content);
  const hasMoreRecent = pageData ? pageData.totalPages > pageData.page : false;

  // Read straight off the mutation result, which TanStack resets on the next
  // `mutate()` — there is no second copy of the failure in local state to go
  // stale. `mapIncidentsError` accepts the mutation result unchanged.
  const sendErrorKey = mutation.isError
    ? sendErrorKeyFor(mapIncidentsError(mutation).kind)
    : null;

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
          // R4.3 inverted: the text is dropped only once the backend accepted
          // it.
          setContent("");
          setTouched(false);
          // The mutation's `onSettled` invalidation (D5) already refreshes the
          // open page; reading that refresh here is what tells us whether the
          // message just sent spilled onto a *new* page. It can only ever add
          // one, so advancing by one keeps the appended list contiguous and
          // puts the technician's own message on screen (R2.2).
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
        htmlFor="tech-incident-message-content"
        className="block text-xs font-medium text-muted-foreground"
      >
        {t("messages.composer.label")}
      </label>
      <textarea
        id="tech-incident-message-content"
        rows={3}
        maxLength={MAX_CONTENT}
        value={content}
        placeholder={t("messages.composer.placeholder")}
        aria-describedby="tech-incident-message-counter"
        onChange={(event) => {
          setContent(event.target.value);
          setTouched(true);
        }}
        className="w-full rounded-md border bg-background px-2 py-1 text-sm"
      />
      <span
        id="tech-incident-message-counter"
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
      {sendErrorKey ? (
        <span role="alert" className="text-xs text-destructive">
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

  const readState = mapIncidentsError(query);

  // Propagate the 404 up so the parent detail view can replace the whole
  // screen, the same as it already does for the other two parallel reads —
  // see the doc comment above `onNotFound`.
  useEffect(() => {
    if (readState.kind === "not-found") {
      onNotFound?.();
    }
  }, [readState.kind, onNotFound]);

  // R4.2 vs R2.6: a 404 means the incident itself is gone, not that the thread
  // is empty — there is nowhere left to send a draft, so the composer goes
  // with it. Same convention every parallel read of this screen follows.
  if (readState.kind === "not-found") {
    return (
      <div className="flex flex-col gap-4">
        <EmptyState
          title={t("detail.unavailable.title")}
          description={t("detail.unavailable.description")}
        />
      </div>
    );
  }

  const hasReadError =
    readState.kind !== "ok" && readState.kind !== "loading";

  // The list region is what loading/empty/error swap (R4.1, R4.2, R4.3); a
  // failure or a refetch of a *later* page never discards the pages already
  // appended, so the thread does not blink away under the technician.
  let listRegion;
  if (readState.kind === "loading" && messages.length === 0) {
    listRegion = <LoadingState label={t("messages.loading")} />;
  } else if (hasReadError && messages.length === 0) {
    listRegion = (
      <ErrorState
        title={t("messages.error.title")}
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
      aria-labelledby="tech-incident-messages-heading"
      className="flex flex-col gap-4"
    >
      <h2
        id="tech-incident-messages-heading"
        className="text-body-lg font-semibold text-foreground"
      >
        {t("messages.title")}
      </h2>
      {listRegion}
      {hasReadError && messages.length > 0 ? (
        <ErrorState
          title={t("messages.error.title")}
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

/** R2.3 / D6: 1..2000 characters once trimmed, checked before any request. */
function validate(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return "messages.errors.required";
  if (trimmed.length > MAX_CONTENT) return "messages.errors.tooLong";
  return null;
}

/**
 * The failed send's `kind` → the copy the composer shows (R4.3).
 *
 * `validation` is the length `422`, the only one `POST .../messages` can
 * raise — its body carries a single field. `loading` is the mapper's `401`
 * branch, which for a *read* means "the session refresh is in flight, stay
 * quiet"; a send that failed has no such second chance, so it says the generic
 * thing rather than nothing at all.
 */
function sendErrorKeyFor(kind: string): string {
  if (kind === "validation") return "messages.errors.tooLong";
  if (kind === "not-found") return "messages.errors.notFound";
  if (kind === "forbidden") return "messages.errors.forbidden";
  return "messages.errors.generic";
}
