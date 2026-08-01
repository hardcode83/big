"use client";

import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import type { TimelineActorType, TimelineSeverity } from "../../data";
import { usePropertyTimeline } from "../../hooks/use-dashboard-data";
import { formatDateTime } from "../../lib/format";
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
 * Property timeline (PRD §10). Entries render in the immutable order the source
 * returns them, in the active locale. Filters (actor, severity) are lightweight
 * UI state in Zustand and are threaded into the tenant-scoped query key, so each
 * filter combination is cached distinctly. This view holds no server state.
 */
export function PropertyTimeline({ propertyId }: { propertyId: string }) {
  const { t, i18n } = useTranslation("dashboard");
  const { t: tStates } = useTranslation("states");
  const {
    actorType,
    severity,
    eventType,
    setActorType,
    setSeverity,
    setEventType,
    reset,
  } = useTimelineFiltersStore();

  // Filters are page-local: clear them when switching properties.
  useEffect(() => reset(), [propertyId, reset]);

  // Unfiltered companion query: enumerates the event types this property has, so
  // the "type" filter options never collapse to the currently-selected type.
  const optionsQuery = usePropertyTimeline(propertyId, {});
  const eventTypeOptions = useMemo(
    () =>
      Array.from(
        new Set((optionsQuery.data?.data ?? []).map((e) => e.eventType)),
      ).sort(),
    [optionsQuery.data],
  );

  const filters = {
    ...(actorType ? { actorType } : {}),
    ...(severity ? { severity } : {}),
    ...(eventType ? { eventType } : {}),
  };
  const query = usePropertyTimeline(propertyId, filters);

  return (
    <section className="flex flex-col gap-3" aria-label={t("timeline.title")}>
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-foreground">
          {t("timeline.title")}
        </h2>
        <div className="flex flex-wrap items-center gap-2">
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
            {eventTypeOptions.map((type) => (
              <option key={type} value={type}>
                {t(`timeline.eventType.${type}`, type)}
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
        </div>
      </div>

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
      )}
    </section>
  );
}
