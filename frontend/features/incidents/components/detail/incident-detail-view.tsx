"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";

import { useHasPermission } from "@/lib/auth";

import { mapIncidentsError } from "../../lib/error-mapping";
import { useIncident } from "../../hooks/use-incidents";
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

/**
 * The detail view for `/incidents/[id]` (proposal R1-R6, design D7/D13).
 * Composes the read-only section components in order, then — for **every**
 * viewer, permission or not — resolves the assigned technician's name
 * against the tenant's roster (R2.6, design D10: `TENANT_OWNER` has
 * `READ_USERS` too, so this never `403`s for her). `ManagerIncidentActions`
 * mounts only behind `useHasPermission("MANAGE_INCIDENTS")` — without the
 * permission, nothing is imported or rendered, not even an empty slot
 * (R1.1, R1.2).
 */
export function IncidentDetailView({ incidentId }: { incidentId: string }) {
  const { t } = useTranslation(["incidents", "states", "navigation"]);
  const query = useIncident(incidentId);
  const state = mapIncidentsError(query);
  const canManage = useHasPermission("MANAGE_INCIDENTS");
  // Every viewer resolves the technician's name, not only the manager
  // (R2.6, design D10) — this hook is unconditional so it runs the same for
  // `TENANT_OWNER` (who has `READ_USERS` but not `MANAGE_INCIDENTS`).
  const technicians = useTechnicianDirectory();

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
  const technicianName = d.assignedTechnicianId
    ? (technicians.data?.find((technician) => technician.id === d.assignedTechnicianId)
        ?.name ?? null)
    : null;
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
    </article>
  );
}