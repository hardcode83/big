"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import {
  mapIncidentsError,
  useIncident,
  useIncidentContext,
} from "@/features/incidents";

import { TechContextBlock } from "./tech-context-block";
import { TechCycleActions } from "./tech-cycle-actions";
import { TechIncidentFields } from "./tech-incident-fields";
import { TechPhotoGallery } from "./tech-photo-gallery";
import { TechPhotoUpload } from "./tech-photo-upload";

const PHOTO_UPLOAD_STATUSES = ["IN_PROGRESS", "WAITING_EXTERNAL_PARTS"];

/**
 * `/tech/incidents/[id]` (proposal R2). One column, no horizontal scroll at
 * 360 px, and the action bar at the end of the flow (design D15).
 *
 * A `404` from **either** request is «incident not available», without
 * distinguishing non-existent, other tenant or other technician: the backend
 * makes the three deliberately indistinguishable, so telling them apart here
 * would be inventing information (R2.6).
 *
 * The owner-approval gate is read from the **response** of `resolve`, which is
 * to say from the refreshed incident: `RESOLVED` presents it as closed with
 * `finalCost`, `materials` and `resolvedAt`; `AWAITING_OWNER_APPROVAL` says
 * explicitly that the close has not been accepted, keeps `finalCost` visible and
 * does not invent a `resolvedAt` that arrives `null`. The threshold is never
 * computed, shown or anticipated (R4.4).
 */
export function TechIncidentDetailView({
  incidentId,
}: {
  incidentId: string;
}) {
  const { t } = useTranslation("tech");
  const incidentQuery = useIncident(incidentId);
  const contextQuery = useIncidentContext(incidentId);

  const incidentState = mapIncidentsError(incidentQuery);
  const contextState = mapIncidentsError(contextQuery);

  const backLink = (
    <Link href="/tech" className="text-sm underline">
      {t("detail.back")}
    </Link>
  );

  const shell = (children: React.ReactNode) => (
    <section className="mx-auto flex w-full max-w-md flex-col gap-4 p-4">
      {backLink}
      {children}
    </section>
  );

  if (incidentState.kind === "loading" || contextState.kind === "loading") {
    return shell(<LoadingState label={t("detail.loading")} />);
  }

  if (
    incidentState.kind === "not-found" ||
    contextState.kind === "not-found"
  ) {
    return shell(
      <EmptyState
        title={t("detail.unavailable.title")}
        description={t("detail.unavailable.description")}
      />,
    );
  }

  if (incidentState.kind !== "ok") {
    return shell(
      <ErrorState
        title={t("detail.error.title")}
        description={t("detail.error.description")}
        retryLabel={t("detail.error.retry")}
        onRetry={() => {
          void incidentQuery.refetch();
        }}
      />,
    );
  }

  const incident = incidentState.data;
  const offersUpload = PHOTO_UPLOAD_STATUSES.includes(incident.status);

  return shell(
    <>
      <TechIncidentFields incident={incident} />

      {contextState.kind === "ok" ? (
        <TechContextBlock context={contextState.data} />
      ) : (
        <p className="text-sm text-muted-foreground">
          {t("context.unavailable")}
        </p>
      )}

      {incident.status === "AWAITING_OWNER_APPROVAL" ? (
        <section role="status" className="rounded-lg border bg-surface p-4">
          <h2 className="text-base font-semibold text-foreground">
            {t("resolve.awaitingOwner.title")}
          </h2>
          <p className="text-sm text-muted-foreground">
            {t("resolve.awaitingOwner.description")}
          </p>
        </section>
      ) : null}

      {incident.status === "RESOLVED" ? (
        <section role="status" className="rounded-lg border bg-surface p-4">
          <h2 className="text-base font-semibold text-foreground">
            {t("resolve.resolved.title")}
          </h2>
          <p className="text-sm text-muted-foreground">
            {t("resolve.resolved.description")}
          </p>
        </section>
      ) : null}

      <TechPhotoGallery incidentId={incident.id} />

      {offersUpload ? (
        <TechPhotoUpload incidentId={incident.id} status={incident.status} />
      ) : null}

      <TechCycleActions incident={incident} />
    </>,
  );
}
