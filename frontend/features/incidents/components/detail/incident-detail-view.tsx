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
    return <p className="p-4 text-body-base text-muted-foreground">{t("states:loading.label", { ns: "states" })}</p>;
  }
  if (state.kind === "forbidden") {
    return <p className="p-4 text-body-base text-muted-foreground">{t("incidents:fields.forbidden")}</p>;
  }
  if (state.kind === "not-found") {
    return (
      <section className="flex flex-col gap-2 p-4">
        <p className="text-body-base text-muted-foreground">{t("incidents:fields.notFound")}</p>
        <Link href="/incidents" className="text-primary underline-offset-4 hover:underline">
          {t("incidents:fields.backToList")}
        </Link>
      </section>
    );
  }
  if (state.kind === "validation") {
    return <p className="p-4 text-body-base text-muted-foreground">{t("incidents:fields.validation")}</p>;
  }
  if (state.kind === "error") {
    return (
      <div className="flex flex-col gap-2 p-4">
        <p className="text-body-lg font-semibold text-foreground">{t("states:error.title", { ns: "states" })}</p>
        <p className="text-body-base text-muted-foreground">{t("states:error.description", { ns: "states" })}</p>
        <button
          type="button"
          className="tap-target self-start rounded-md border bg-background px-3 py-1 text-body-base transition-colors hover:bg-accent hover:text-accent-foreground"
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
    <article aria-labelledby="incident-heading" className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3">
        <h1 id="incident-heading" className="text-xl font-semibold text-foreground">
          {t("navigation:routes.incident-detail.title", { ns: "navigation" })}
        </h1>
        <Link href="/incidents" className="text-body-base text-primary underline-offset-4 hover:underline">
          {t("incidents:fields.backToList")}
        </Link>
      </div>
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