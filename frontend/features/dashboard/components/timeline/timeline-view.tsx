"use client";

import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useAuth } from "@/lib/auth";

import { useDashboardCards } from "../../hooks/use-dashboard-data";
import {
  useSelectedTimelineProperty,
  useTimelinePropertyStore,
} from "../../state/use-timeline-property-store";
import { PropertyTimeline } from "../detail/property-timeline";

/**
 * Client view for `/timeline` (PRD §24). The route is flat while the endpoint
 * requires a property (`GET /api/v1/timeline/{property_id}`), so this screen is
 * the picker that closes that gap: it chooses a property and mounts the SAME
 * `PropertyTimeline` that `/properties/[id]` renders (design D1, D2). It holds no
 * event list, no timeline hook and no filters store of its own.
 *
 * Nothing is queried until a property is chosen. That is a consequence of not
 * MOUNTING the timeline rather than of disabling its hook (design D4): keeping the
 * condition in the tree instead of in the data layer is what guarantees no request
 * to `/api/v1/timeline/` on first paint without leaving a half-live cache entry.
 * There is no autoselection either — with N properties any automatic choice is
 * arbitrary, and the first paint should not fetch a feed nobody asked for.
 */
export function TimelineView() {
  const { t } = useTranslation("dashboard");
  const { t: tNav } = useTranslation("navigation");
  const { t: tStates } = useTranslation("states");
  const { user } = useAuth();
  const tenantId = user?.tenant_id ?? "";

  const query = useDashboardCards();
  const select = useTimelinePropertyStore((state) => state.select);
  const clear = useTimelinePropertyStore((state) => state.clear);
  // Honoured only for the tenant that made it: `logout` clears the session but
  // not this store, so a stale pair must read as "none" (design D3).
  const propertyId = useSelectedTimelineProperty(tenantId);

  const heading = (
    <h1 className="text-xl font-semibold text-foreground">
      {tNav("routes.timeline.title")}
    </h1>
  );

  if (query.isPending) {
    return (
      <div className="flex flex-col gap-4 p-4">
        {heading}
        <LoadingState label={tStates("loading.label")} />
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="flex flex-col gap-4 p-4">
        {heading}
        <ErrorState
          title={t("cards.error.title")}
          description={t("cards.error.description")}
          onRetry={() => void query.refetch()}
          retryLabel={tStates("error.retry")}
        />
      </div>
    );
  }

  const cards = query.data.data;

  return (
    <div className="flex flex-col gap-4 p-4">
      {heading}

      <div>
        <label
          className="mb-1 block text-xs font-medium text-muted-foreground"
          htmlFor="timeline-property"
        >
          {t("timeline.picker.label")}
        </label>
        <select
          id="timeline-property"
          className="tap-target rounded-md border bg-background px-2 py-1 text-sm"
          value={propertyId ?? ""}
          onChange={(e) =>
            e.target.value ? select(tenantId, e.target.value) : clear()
          }
        >
          <option value="">{t("timeline.picker.placeholder")}</option>
          {cards.map((card) => (
            <option key={card.propertyId} value={card.propertyId}>
              {card.propertyCode}
            </option>
          ))}
        </select>
      </div>

      {propertyId ? (
        <PropertyTimeline propertyId={propertyId} />
      ) : (
        <EmptyState
          title={t("timeline.picker.empty.title")}
          description={t("timeline.picker.empty.description")}
        />
      )}
    </div>
  );
}
