"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Card } from "@/components/ui/card";
import {
  mapIncidentsError,
  useIncident,
  useIncidentContext,
} from "@/features/incidents";

import { techAcceptsPhotoUpload } from "../../lib/tech-actions";
import { TechContextBlock } from "./tech-context-block";
import { TechCycleActions } from "./tech-cycle-actions";
import { TechIncidentFields } from "./tech-incident-fields";
import { TechIncidentMessagesPanel } from "./tech-incident-messages-panel";
import { TechIncidentTabs } from "./tech-incident-tabs";
import { TechPhotoGallery } from "./tech-photo-gallery";
import { TechPhotoUpload } from "./tech-photo-upload";

/**
 * `/tech/incidents/[id]` (proposal R2). One column, no horizontal scroll at
 * 360 px, and the action bar at the end of the flow (design D15).
 *
 * A `404` from **either** request is «incident not available», without
 * distinguishing non-existent, other tenant or other technician: the backend
 * makes the three deliberately indistinguishable, so telling them apart here
 * would be inventing information (R2.6).
 *
 * The whole operational stack — fields, context, status cards, gallery,
 * upload and cycle actions — is the **content** tab of `TechIncidentTabs`,
 * active by default (R3.1, design D-mobile); the staff thread lives in the
 * second tab and only requests its first page once that tab is opened (D1).
 * Both panels stay mounted, so the close form, the ETA field and the photo
 * picker keep their local state through a round trip to the messages tab
 * (R3.2).
 *
 * The owner-approval gate is read from the **response** of `resolve`, which is
 * to say from the refreshed incident: `RESOLVED` presents it as closed with
 * `finalCost`, `materials` and `resolvedAt`; `AWAITING_OWNER_APPROVAL` says
 * explicitly that the close has not been accepted, keeps `finalCost` visible and
 * does not invent a `resolvedAt` that arrives `null`. The threshold is never
 * computed, shown or anticipated (R4.4).
 *
 * The messages query (lazy, mounted inside `TechIncidentMessagesPanel`) is not
 * one of the two reads above, but a 404 on it means the same thing — the
 * incident is gone — so `TechIncidentMessagesPanel`'s `onNotFound` callback
 * feeds `messagesNotFound` here, which folds into the same whole-screen
 * not-found branch as `incidentState`/`contextState` (R4.3, proposal
 * amendment).
 */
export function TechIncidentDetailView({
  incidentId,
}: {
  incidentId: string;
}) {
  const { t } = useTranslation("tech");
  const incidentQuery = useIncident(incidentId);
  const contextQuery = useIncidentContext(incidentId);
  // Sticky: once the messages read 404s the incident is gone, and it does not
  // come back by refetching the incident/context queries.
  const [messagesNotFound, setMessagesNotFound] = useState(false);
  const onMessagesNotFound = useCallback(() => setMessagesNotFound(true), []);

  const incidentState = mapIncidentsError(incidentQuery);
  const contextState = mapIncidentsError(contextQuery);

  const backLink = (
    <Link
      href="/tech"
      className="tap-target inline-flex items-center text-body-medium text-primary underline-offset-4 hover:underline"
    >
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
    contextState.kind === "not-found" ||
    messagesNotFound
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
  const offersUpload = techAcceptsPhotoUpload(incident.status);

  return shell(
    <TechIncidentTabs
      content={
        <div className="flex flex-col gap-4">
          <TechIncidentFields incident={incident} />

          {contextState.kind === "ok" ? (
            <TechContextBlock context={contextState.data} />
          ) : (
            <EmptyState
              title={t("context.unavailable.title")}
              description={t("context.unavailable.description")}
            />
          )}

          {incident.status === "AWAITING_OWNER_APPROVAL" ? (
            <section role="status">
              <Card className="p-4">
                <h2 className="text-body-lg font-semibold text-foreground">
                  {t("resolve.awaitingOwner.title")}
                </h2>
                <p className="text-body-base text-muted-foreground">
                  {t("resolve.awaitingOwner.description")}
                </p>
              </Card>
            </section>
          ) : null}

          {incident.status === "RESOLVED" ? (
            <section role="status">
              <Card className="p-4">
                <h2 className="text-body-lg font-semibold text-foreground">
                  {t("resolve.resolved.title")}
                </h2>
                <p className="text-body-base text-muted-foreground">
                  {t("resolve.resolved.description")}
                </p>
              </Card>
            </section>
          ) : null}

          <TechPhotoGallery incidentId={incident.id} />

          {offersUpload ? (
            <TechPhotoUpload incidentId={incident.id} />
          ) : null}

          <TechCycleActions incident={incident} />
        </div>
      }
      renderMessages={(enabled) => (
        <TechIncidentMessagesPanel
          incidentId={incident.id}
          enabled={enabled}
          onNotFound={onMessagesNotFound}
        />
      )}
    />,
  );
}
