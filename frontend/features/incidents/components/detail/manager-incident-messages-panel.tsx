"use client";

import { useLayoutEffect, useState } from "react";
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
 * The manager's staff thread for one incident (R1.1, R1.2, R1.3, R1.4, R1.5;
 * design D3, D7). The mirror of `TechIncidentMessagesPanel` for the
 * manager's surface: same pagination, same composer, same 404 propagation —
 * `staff-messaging-manager-view` design D1/D7 already rejected sharing a
 * single component, so the shape is copied.
 *
 * **Pagination (D3).** Page 1 is the *oldest* page — the backend orders
 * ascending — so «Cargar mensajes más recientes» asks for `page + 1` and the
 * rows it returns are **appended** to what is already on screen, never
 * replacing it. What is on screen is `olderRows` (the pages already left
 * behind) followed by the open page's live rows, so a refetch of the open
 * page — what the send mutation's invalidation triggers — refreshes the
 * tail without duplicating a row.
 *
 * **Tail following after a send (R1.3).** A send adds exactly one message,
 * so it grows the thread by at most one page. When the manager was already
 * at the end of the thread and his message spilled onto a new page, the
 * handler reads the refreshed `totalPages` and advances exactly one page.
 *
 * **Composer (D3).** Native `<textarea maxLength={2000}>`, no form library.
 * Local validation (`trim().length` in 1..2000) disables the submit control
 * *before* any backend call (R1.3), `mutation.isPending` disables it while
 * a send is in flight (R1.4), and the typed text survives a failed send —
 * it is cleared only on success (R1.3, R4.3).
 *
 * **404 propagation (R1.5).** A 404 on this query means the incident itself
 * is gone — the same fact `useIncident` already detects and reacts to by
 * replacing the *whole* detail screen. Because this query loads lazily
 * (only once the Messages tab is opened), an incident that looked fine
 * when the other reads ran can vanish by the time this one does.
 * `onNotFound` tells the parent detail view so it can fold this 404 into
 * its own whole-screen not-found branch, which *replaces* the panel-local
 * `EmptyState` below rather than layering on top of it.
 *
 * When `onNotFound` is supplied the panel renders nothing at all for the
 * 404: the callback fires in a `useLayoutEffect` (synchronously after
 * render, before the browser paints), so the parent's whole-screen swap
 * lands in the same frame. Rendering the panel-local `EmptyState` here
 * instead would paint a weaker, tab-confined not-found surface for exactly
 * one frame before the correct whole-screen one replaced it — a visible
 * flash.
 */
export interface ManagerIncidentMessagesPanelProps {
  incidentId: string;
  /** The tabs' sticky "messages tab has been opened" flag (D3). */
  enabled: boolean;
  /** Called (repeatably) whenever the messages read 404s. */
  onNotFound?: () => void;
}

export function ManagerIncidentMessagesPanel({
  incidentId,
  enabled,
  onNotFound,
}: ManagerIncidentMessagesPanelProps) {
  const { t, i18n } = useTranslation("incidents");
  const locale = i18n.language;

  const [page, setPage] = useState(1);
  const [olderRows, setOlderRows] = useState<IncidentMessage[]>([]);
  const [content, setContent] = useState("");
  const [touched, setTouched] = useState(false);

  const query = useIncidentMessages(incidentId, page, enabled);
  const mutation = useSendIncidentMessage(incidentId);
  const pageData = query.data;

  // What is on screen is the pages already read plus the page currently
  // open, in that order (D3). `olderRows` is only ever written from an
  // event handler, at the moment the reader leaves a page behind.
  const messages = pageData ? [...olderRows, ...pageData.data] : olderRows;

  /** Leaves the page just read behind and opens the next one (D3). */
  function advancePast(read: PaginatedResponse<IncidentMessage>) {
    setOlderRows((rows) => [...rows, ...read.data]);
    setPage(read.page + 1);
  }

  const validationKey = validate(content);
  const hasMoreRecent = pageData ? pageData.totalPages > pageData.page : false;

  // Read straight off the mutation result, which TanStack resets on the
  // next `mutate()` — there is no second copy of the failure in local
  // state to go stale.
  const sendErrorKey = mutation.isError
    ? sendErrorKeyFor(mapIncidentsError(mutation).kind)
    : null;

  // The error shown beneath the composer (R1.3 / R1.4). Client-side
  // validation has priority so the user sees the cursor-side reason first;
  // it only surfaces once the field has been touched. The textarea's
  // `aria-describedby` and `aria-invalid` track this same value so
  // assistive tech gets the same association the eye does.
  const visibleErrorKey =
    touched && validationKey ? validationKey : sendErrorKey;
  const describedById = [
    "manager-incident-message-counter",
    visibleErrorKey ? "manager-incident-message-error" : null,
  ]
    .filter(Boolean)
    .join(" ");

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTouched(true);
    if (validationKey || mutation.isPending) {
      // R1.3: the backend is never called with content the composer already
      // knows is invalid.
      return;
    }
    const wasAtTail = pageData ? pageData.page >= pageData.totalPages : true;
    mutation.mutate(
      { content: content.trim() },
      {
        onSuccess: async () => {
          // R1.3 / R4.3 inverted: the text is dropped only once the backend
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
        htmlFor="manager-incident-message-content"
        className="block text-xs font-medium text-muted-foreground"
      >
        {t("messages.composer.label")}
      </label>
      <textarea
        id="manager-incident-message-content"
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
        id="manager-incident-message-counter"
        className="text-xs text-muted-foreground"
      >
        {t("messages.composer.counter", {
          current: content.length,
          max: MAX_CONTENT,
        })}
      </span>
      {touched && validationKey ? (
        <span
          id="manager-incident-message-error"
          role="alert"
          className="text-xs text-destructive"
        >
          {t(validationKey)}
        </span>
      ) : sendErrorKey ? (
        <span
          id="manager-incident-message-error"
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

  const readState = mapIncidentsError(query);

  // Propagate the 404 up so the parent detail view can replace the whole
  // screen, the same as it already does for the incident read. `useLayoutEffect`,
  // not `useEffect`: it runs before the browser paints, so the parent's swap
  // is the first thing the manager sees.
  useLayoutEffect(() => {
    if (readState.kind === "not-found") {
      onNotFound?.();
    }
  }, [readState.kind, onNotFound]);

  // R1.5: a 404 means the incident itself is gone, not that the thread is
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

  // The list region is what loading/empty/error swap (R1.2, R1.5); a
  // failure or a refetch of a *later* page never discards the pages already
  // appended, so the thread does not blink away under the manager.
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
      aria-labelledby="manager-incident-messages-heading"
      className="flex flex-col gap-4"
    >
      <h2
        id="manager-incident-messages-heading"
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

/** R1.3: 1..2000 characters once trimmed, checked before any request. */
function validate(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return "messages.errors.required";
  if (trimmed.length > MAX_CONTENT) return "messages.errors.tooLong";
  return null;
}

/**
 * The failed send's `kind` → the copy the composer shows (R1.5).
 *
 * `validation` is the length `422`, the only one `POST .../messages` can
 * raise — its body carries a single field. `loading` is the mapper's
 * `401` branch, which for a *read* means "the session refresh is in
 * flight, stay quiet"; a send that failed has no such second chance, so
 * it says the generic thing rather than nothing at all.
 */
function sendErrorKeyFor(kind: string): string {
  if (kind === "validation") return "messages.errors.tooLong";
  if (kind === "not-found") return "messages.errors.notFound";
  if (kind === "forbidden") return "messages.errors.forbidden";
  return "messages.errors.generic";
}
