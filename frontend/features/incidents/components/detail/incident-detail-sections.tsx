"use client";

import { useTranslation } from "react-i18next";

import type { IncidentDetailDto } from "../../data";

const SEVERITY_COLOR: Record<string, string> = {
  LOW: "bg-gray-100 text-gray-700",
  MEDIUM: "bg-blue-100 text-blue-700",
  HIGH: "bg-amber-100 text-amber-800",
  CRITICAL: "bg-red-100 text-red-700",
};

function fmtUtc(value: string): string {
  return value.slice(0, 16).replace("T", " ");
}

/** Format a cost `string` (e.g. `"120.50"`) with two decimals and the locale's
 * decimal separator. R5.5: NO currency symbol — there is no source of
 * currency within scope. */
function fmtCost(value: string | null): string {
  if (value === null) return "—";
  const num = Number(value);
  if (!Number.isFinite(num)) return value;
  return num.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function DetailHeader({
  severity,
  status,
  category,
  source,
  ownerApprovalRequired,
}: Pick<
  IncidentDetailDto,
  "severity" | "status" | "category" | "source" | "ownerApprovalRequired"
>) {
  const { t } = useTranslation("incidents");
  return (
    <header>
      <span
        className={
          SEVERITY_COLOR[severity] ?? "bg-gray-100 text-gray-700"
        }
      >
        {t(`severity.${severity}`)}
      </span>
      <span>{t(`status.${status}`)}</span>
      <span>{t(`category.${category}`)}</span>
      <span>{t(`source.${source}`)}</span>
      {ownerApprovalRequired && (
        <p role="note">{t("fields.ownerApprovalRequired")}</p>
      )}
    </header>
  );
}

export function DetailIdentifyingBlock({
  id,
  propertyId,
  reservationId,
}: Pick<IncidentDetailDto, "id" | "propertyId" | "reservationId">) {
  const { t } = useTranslation("incidents");
  return (
    <section>
      <h2>{t("fields.id")}</h2>
      <p>{id}</p>
      <h2>{t("fields.property")}</h2>
      <p>{propertyId}</p>
      {reservationId && (
        <>
          <h2>{t("fields.reservation")}</h2>
          <p>{reservationId}</p>
        </>
      )}
    </section>
  );
}

export function DetailAssignedTechnicianBlock({
  assignedTechnicianId,
}: Pick<IncidentDetailDto, "assignedTechnicianId">) {
  const { t } = useTranslation("incidents");
  if (!assignedTechnicianId) return null;
  return (
    <section aria-label={t("fields.assignedTechnician")}>
      <h2>{t("fields.assignedTechnician")}</h2>
      <p>{assignedTechnicianId}</p>
      <p role="note">{t("fields.assignedTechnicianNote")}</p>
    </section>
  );
}

export function DetailDescriptionBlock({
  description,
}: Pick<IncidentDetailDto, "description">) {
  const { t } = useTranslation("incidents");
  if (!description) return null;
  return (
    <section>
      <h2>{t("fields.description")}</h2>
      {/* D7 / regla 11 de steering/security.md: render plain text, never HTML */}
      <p className="whitespace-pre-wrap max-w-prose">{description}</p>
    </section>
  );
}

export function DetailCostsBlock({
  estimatedCost,
  approvedCost,
  finalCost,
}: Pick<IncidentDetailDto, "estimatedCost" | "approvedCost" | "finalCost">) {
  const { t } = useTranslation("incidents");
  return (
    <section>
      <h2>{t("fields.estimatedCost")}</h2>
      <p>{fmtCost(estimatedCost)}</p>
      <h2>{t("fields.approvedCost")}</h2>
      <p>{fmtCost(approvedCost)}</p>
      <h2>{t("fields.finalCost")}</h2>
      <p>{fmtCost(finalCost)}</p>
    </section>
  );
}

export function DetailMetadataBlock({
  aiSummary,
  createdAt,
  updatedAt,
  resolvedAt,
}: Pick<
  IncidentDetailDto,
  "aiSummary" | "createdAt" | "updatedAt" | "resolvedAt"
>) {
  const { t } = useTranslation("incidents");
  return (
    <section>
      {aiSummary && (
        <>
          <h2>{t("fields.aiSummary")}</h2>
          <p>{aiSummary}</p>
        </>
      )}
      <h2>{t("fields.createdAtFull")}</h2>
      <p>{fmtUtc(createdAt)}</p>
      <h2>{t("fields.updatedAt")}</h2>
      <p>{fmtUtc(updatedAt)}</p>
      {resolvedAt && (
        <>
          <h2>{t("fields.resolvedAt")}</h2>
          <p>{fmtUtc(resolvedAt)}</p>
        </>
      )}
    </section>
  );
}