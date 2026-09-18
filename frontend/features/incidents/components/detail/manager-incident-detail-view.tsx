"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useHasPermission } from "@/lib/auth";

import { mapIncidentsError, useIncident } from "@/features/incidents";

import { useTechnicianDirectory } from "../../hooks/use-incident-management";
import {
  DetailAssignedTechnicianBlock,
  DetailCostsBlock,
  DetailDescriptionBlock,
  DetailHeader,
  DetailIdentifyingBlock,
  DetailMetadataBlock,
} from "./incident-detail-sections";
import { ManagerIncidentActions } from "./manager-incident-actions";
import { ManagerIncidentMessagesPanel } from "./manager-incident-messages-panel";
import { ManagerIncidentTabs } from "./manager-incident-tabs";

/**
 * The manager's detail view for `/incidents/[id]` (proposal R1, R3, design
 * D1, D7). Wraps the same six blocks `IncidentDetailView` composes
 * (`DetailHeader`, `DetailIdentifyingBlock`, `DetailAssignedTechnicianBlock`,
 * `DetailDescriptionBlock`, `DetailCostsBlock`, `DetailMetadataBlock`) plus
 * `ManagerIncidentActions` (gated on `useHasPermission("MANAGE_INCIDENTS")`,
 * same as before), and mounts `ManagerIncidentMessagesPanel` as a second
 * tab.
 *
 * **Same composition, no patchwork on `IncidentDetailView`.** D7 forbids
 * importing `IncidentDetailView` from this wrapper: that would duplicate the
 * state machine and double the `useTechnicianDirectory` call. Instead the
 * blocks live in `incident-detail-sections.tsx` and both views compose them
 * directly — this file is one of the two composers.
 *
 * **404 propagation (R1.5).** A 404 on the messages read means the incident
 * itself is gone — `useIncident` already detects and reacts to that by
 * replacing the whole detail screen, so the panel's `onNotFound` callback
 * sets `messagesNotFound` here, which folds into the same whole-screen
 * not-found branch. `useLayoutEffect` (in the panel) fires before the
 * browser paints, so the whole-screen swap lands in the same frame.
 */
export function ManagerIncidentDetailView({
  incidentId,
}: {
  incidentId: string;
}) {
  const { t } = useTranslation(["incidents", "states", "navigation"]);
  const query = useIncident(incidentId);
  const state = mapIncidentsError(query);
  const canManage = useHasPermission("MANAGE_INCIDENTS");
  // Every viewer resolves the technician's name, not only the manager
  // (same convention `IncidentDetailView` follows): `TENANT_OWNER` has
  // `READ_USERS` and this hook never `403`s for her.
  const technicians = useTechnicianDirectory();

  // Sticky: once the messages read 404s the incident is gone, and it does
  // not come back by refetching the incident query.
  const [messagesNotFound, setMessagesNotFound] = useState(false);
  const onMessagesNotFound = useCallback(
    () => setMessagesNotFound(true),
    [],
  );

  if (state.kind === "loading") {
    return (
      <div className="p-4">
        <LoadingState label={t("states:loading.label", { ns: "states" })} />
      </div>
    );
  }
  if (state.kind === "forbidden") {
    return (
      <p className="p-4 text-body-base text-muted-foreground">
        {t("incidents:fields.forbidden")}
      </p>
    );
  }
  if (state.kind === "not-found" || messagesNotFound) {
    return (
      <section className="flex flex-col gap-2 p-4">
        <EmptyState
          title={t("incidents:fields.notFound")}
          action={
            <Link
              href="/incidents"
              className="tap-target inline-flex items-center text-body-medium text-primary underline-offset-4 hover:underline"
            >
              {t("incidents:fields.backToList")}
            </Link>
          }
        />
      </section>
    );
  }
  if (state.kind === "validation") {
    return (
      <p className="p-4 text-body-base text-muted-foreground">
        {t("incidents:fields.validation")}
      </p>
    );
  }
  if (state.kind === "error") {
    return (
      <ErrorState
        title={t("states:error.title", { ns: "states" })}
        description={t("states:error.description", { ns: "states" })}
        retryLabel={t("states:error.retry", { ns: "states" })}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }

  const d = state.data;
  const technicianName = d.assignedTechnicianId
    ? (technicians.data?.find(
        (technician) => technician.id === d.assignedTechnicianId,
      )?.name ?? null)
    : null;

  return (
    <article
      aria-labelledby="manager-incident-heading"
      className="flex flex-col gap-4 p-4"
    >
      <div className="flex items-center gap-3">
        <h1
          id="manager-incident-heading"
          className="text-xl font-semibold text-foreground"
        >
          {t("navigation:routes.incident-detail.title", { ns: "navigation" })}
        </h1>
        <Link
          href="/incidents"
          className="text-body-base text-primary underline-offset-4 hover:underline"
        >
          {t("incidents:fields.backToList")}
        </Link>
      </div>
      <ManagerIncidentTabs
        content={
          <div className="flex flex-col gap-4">
            <DetailHeader
              title={d.title}
              severity={d.severity}
              status={d.status}
              category={d.category}
              source={d.source}
              ownerApprovalRequired={d.ownerApprovalRequired}
            />
            <DetailIdentifyingBlock
              id={d.id}
              propertyId={d.propertyId}
              reservationId={d.reservationId}
            />
            <DetailAssignedTechnicianBlock
              assignedTechnicianId={d.assignedTechnicianId}
              technicianName={technicianName}
            />
            <DetailDescriptionBlock description={d.description} />
            <DetailCostsBlock
              estimatedCost={d.estimatedCost}
              approvedCost={d.approvedCost}
              finalCost={d.finalCost}
            />
            <DetailMetadataBlock
              aiSummary={d.aiSummary}
              createdAt={d.createdAt}
              updatedAt={d.updatedAt}
              resolvedAt={d.resolvedAt}
            />
            {canManage ? <ManagerIncidentActions incident={d} /> : null}
          </div>
        }
        renderMessages={(enabled) => (
          <ManagerIncidentMessagesPanel
            incidentId={d.id}
            enabled={enabled}
            onNotFound={onMessagesNotFound}
          />
        )}
      />
    </article>
  );
}
