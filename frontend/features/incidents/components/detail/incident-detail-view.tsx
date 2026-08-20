"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";

import { mapIncidentsError } from "../../lib/error-mapping";
import { useIncident } from "../../hooks/use-incidents";
import {
  DetailAssignedTechnicianBlock,
  DetailCostsBlock,
  DetailDescriptionBlock,
  DetailHeader,
  DetailIdentifyingBlock,
  DetailMetadataBlock,
} from "./incident-detail-sections";

/**
 * The detail view for `/incidents/[id]` (proposal R3, design D7).
 * Composes the section components in order. No mutation controls, no
 * `owner-approvals/{id}/respond` button — the approval lives in `/approvals`.
 */
export function IncidentDetailView({ incidentId }: { incidentId: string }) {
  const { t } = useTranslation(["incidents", "states", "navigation"]);
  const query = useIncident(incidentId);
  const state = mapIncidentsError(query);

  if (state.kind === "loading") {
    return <p>{t("states:loading.label", { ns: "states" })}</p>;
  }
  if (state.kind === "forbidden") {
    return <p>{t("incidents:fields.forbidden")}</p>;
  }
  if (state.kind === "not-found") {
    return (
      <section>
        <p>{t("incidents:fields.notFound")}</p>
        <Link href="/incidents">{t("incidents:fields.backToList")}</Link>
      </section>
    );
  }
  if (state.kind === "validation") {
    return <p>{t("incidents:fields.validation")}</p>;
  }
  if (state.kind === "error") {
    return (
      <div>
        <p>{t("states:error.title", { ns: "states" })}</p>
        <p>{t("states:error.description", { ns: "states" })}</p>
        <button
          type="button"
          onClick={() => {
            void query.refetch();
          }}
        >
          {t("states:error.retry", { ns: "states" })}
        </button>
      </div>
    );
  }

  const d = state.data;
  return (
    <article aria-labelledby="incident-heading">
      <h1 id="incident-heading">
        {t("navigation:routes.incident-detail.title", { ns: "navigation" })}
      </h1>
      <Link href="/incidents">{t("incidents:fields.backToList")}</Link>
      <DetailHeader
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
    </article>
  );
}