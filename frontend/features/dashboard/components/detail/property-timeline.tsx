"use client";

import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import type { TimelineActorType, TimelineSeverity } from "../../data";
import { usePropertyTimeline } from "../../hooks/use-dashboard-data";
import { formatDateTime } from "../../lib/format";
import { TIMELINE_EVENT_TYPES } from "../../lib/timeline-event-types";
import { isInverseRange } from "../../lib/timeline-range";
import { useTimelineFiltersStore } from "../../state/use-timeline-filters-store";

const ACTOR_TYPES: TimelineActorType[] = [
  "SYSTEM",
  "USER",
  "GUEST",
  "SCHEDULER",
  "WEBHOOK",
  "AI",
];
const SEVERITIES: TimelineSeverity[] = ["INFO", "WARNING", "ERROR", "CRITICAL"];

/**
 * Page size, sent explicitly rather than left to the server default so the cache
 * key declares the size of the envelope it holds (design D6). It is deliberately
 * not exposed in the UI (R3.2) — only `page` is navigated.
 */
const PER_PAGE = 20;

/** `''` is what a cleared date input emits; the range helpers need a real day. */
function day(value: string): string | undefined {
  return value || undefined;
}

/**
 * Property timeline (PRD §10). Entries render in the immutable order the source
 * returns them, in the active locale. Filters (type, actor, severity, date range)
 * and the current page are lightweight UI state in Zustand and are threaded into
 * the tenant-scoped query key, so each combination — page included — is cached
 * distinctly. This view holds no server state.
 *
 * One component, two mount points (design D2): `/properties/[id]` and `/timeline`
 * render this same section, so everything added here is inherited by both.
 */
export function PropertyTimeline({ propertyId }: { propertyId: string }) {
  const { t, i18n } = useTranslation("dashboard");
  const { t: tStates } = useTranslation("states");
  const {
    actorType,
    severity,
    eventType,
    fromDate,
    toDate,
    from,
    to,
    page,
    setActorType,
    setSeverity,
    setEventType,
    setRange,
    setPage,
    reset,
  } = useTimelineFiltersStore();

  // Filters are page-local: clear them when switching properties.
  useEffect(() => reset(), [propertyId, reset]);

  /*
    The inputs show the draft; the query sends the committed pair, which the store
    only advances from a valid draft (design D8). So while the range is inverse this
    render shows the field error and the query arguments below do not change at all.
  */
  const rangeIsInverse = isInverseRange(fromDate, toDate);

  const filters = {
    ...(actorType ? { actorType } : {}),
    ...(severity ? { severity } : {}),
    ...(eventType ? { eventType } : {}),
    ...(from ? { from } : {}),
    ...(to ? { to } : {}),
    page,
    perPage: PER_PAGE,
  };
  const query = usePropertyTimeline(propertyId, filters);

  return (
    <section className="flex flex-col gap-3" aria-label={t("timeline.title")}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 className="text-base font-semibold text-foreground">
          {t("timeline.title")}
        </h2>
        <div className="flex flex-wrap items-end gap-2">
          <label className="sr-only" htmlFor="timeline-type">
            {t("timeline.filters.type")}
          </label>
          <select
            id="timeline-type"
            className="rounded-md border bg-background px-2 py-1 text-sm"
            value={eventType ?? ""}
            onChange={(e) => setEventType(e.target.value || undefined)}
          >
            <option value="">{t("timeline.filters.type")}</option>
            {TIMELINE_EVENT_TYPES.map((type) => (
              <option key={type} value={type}>
                {t(`timeline.eventType.${type}`)}
              </option>
            ))}
          </select>
          <label className="sr-only" htmlFor="timeline-actor">
            {t("timeline.filters.actor")}
          </label>
          <select
            id="timeline-actor"
            className="rounded-md border bg-background px-2 py-1 text-sm"
            value={actorType ?? ""}
            onChange={(e) =>
              setActorType((e.target.value || undefined) as TimelineActorType)
            }
          >
            <option value="">{t("timeline.filters.actor")}</option>
            {ACTOR_TYPES.map((a) => (
              <option key={a} value={a}>
                {t(`timeline.actor.${a}`)}
              </option>
            ))}
          </select>
          <label className="sr-only" htmlFor="timeline-severity">
            {t("timeline.filters.severity")}
          </label>
          <select
            id="timeline-severity"
            className="rounded-md border bg-background px-2 py-1 text-sm"
            value={severity ?? ""}
            onChange={(e) =>
              setSeverity((e.target.value || undefined) as TimelineSeverity)
            }
          >
            <option value="">{t("timeline.filters.severity")}</option>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {t(`timeline.severity.${s}`)}
              </option>
            ))}
          </select>
          <div>
            <label
              className="mb-1 block text-xs font-medium text-muted-foreground"
              htmlFor="timeline-from"
            >
              {t("timeline.range.from")}
            </label>
            <input
              id="timeline-from"
              type="date"
              className="rounded-md border bg-background px-2 py-1 text-sm"
              value={fromDate ?? ""}
              aria-invalid={rangeIsInverse || undefined}
              aria-describedby={
                rangeIsInverse ? "timeline-range-error" : undefined
              }
              onChange={(e) => setRange(day(e.target.value), toDate)}
            />
          </div>
          <div>
            <label
              className="mb-1 block text-xs font-medium text-muted-foreground"
              htmlFor="timeline-to"
            >
              {t("timeline.range.to")}
            </label>
            <input
              id="timeline-to"
              type="date"
              className="rounded-md border bg-background px-2 py-1 text-sm"
              value={toDate ?? ""}
              aria-invalid={rangeIsInverse || undefined}
              aria-describedby={
                rangeIsInverse ? "timeline-range-error" : undefined
              }
              onChange={(e) => setRange(fromDate, day(e.target.value))}
            />
          </div>
        </div>
      </div>

      {rangeIsInverse ? (
        <p
          id="timeline-range-error"
          role="alert"
          className="text-xs text-destructive"
        >
          {t("timeline.range.errorInverse")}
        </p>
      ) : null}

      {query.isPending ? (
        <LoadingState label={t("timeline.title")} />
      ) : query.isError ? (
        <ErrorState
          title={t("cards.error.title")}
          description={t("cards.error.description")}
          onRetry={() => void query.refetch()}
          retryLabel={tStates("error.retry")}
        />
      ) : query.data.data.length === 0 ? (
        <EmptyState title={t("timeline.empty")} />
      ) : (
        <>
          <ol className="flex flex-col gap-3">
            {query.data.data.map((entry) => (
              <li key={entry.id} className="border-l-2 border-border pl-3">
                <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
                  <time dateTime={entry.occurredAt}>
                    {formatDateTime(entry.occurredAt, i18n.language)}
                  </time>
                  <span>· {t(`timeline.actor.${entry.actorType}`)}</span>
                  <span>· {t(`timeline.severity.${entry.severity}`)}</span>
                </div>
                <p className="text-sm text-foreground">{entry.title}</p>
                {entry.description ? (
                  <p className="text-sm text-muted-foreground">
                    {entry.description}
                  </p>
                ) : null}
              </li>
            ))}
          </ol>

          {/*
            Only offered when there is somewhere to go (design D6, following
            `features/properties/components/list/properties-view.tsx`): a bar whose
            two arrows are permanently disabled is dead furniture, and with 20 per
            page a two-property timeline usually fits on one.
          */}
          {query.data.total_pages > 1 ? (
            <nav
              className="mt-1 flex items-center justify-between gap-3"
              aria-label={t("timeline.pagination.label")}
            >
              <button
                type="button"
                className="tap-target rounded-md border bg-background px-3 py-1 text-sm disabled:opacity-50"
                disabled={query.data.page <= 1}
                onClick={() => setPage(Math.max(1, query.data.page - 1))}
              >
                {t("timeline.pagination.prev")}
              </button>
              <span className="text-sm text-muted-foreground">
                {t("timeline.pagination.position", {
                  page: query.data.page,
                  totalPages: query.data.total_pages,
                })}
              </span>
              <button
                type="button"
                className="tap-target rounded-md border bg-background px-3 py-1 text-sm disabled:opacity-50"
                disabled={query.data.page >= query.data.total_pages}
                onClick={() => setPage(query.data.page + 1)}
              >
                {t("timeline.pagination.next")}
              </button>
            </nav>
          ) : null}
        </>
      )}
    </section>
  );
}
