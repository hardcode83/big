"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { TONE_BADGE_CLASS } from "@/lib/ui/status-tone";

import type { IncidentDetailDto } from "../../data";
import { severityColorGroup } from "../../lib/severity-tone";

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

/**
 * One label/value pair of the `<dl>`-section block pattern (design D9). The
 * shape every detail-page section below repeats: an uppercase, muted `<dt>`
 * label and a `<dd>` value in the monospace "data" role — the same
 * "uppercase label + monospace value" reading the mapping table gives for any
 * `<dl>`-shaped data pattern, applied here as this change's first detail-page
 * composition pass (D9's closing note). `mono` defaults to `true`; pass
 * `false` for a value that carries its own typography (a `Badge`, a status
 * pill) so it is never forced into the mono face.
 */
function DetailField({
  label,
  children,
  mono = true,
}: {
  label: string;
  children: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-label-caps uppercase text-muted-foreground">
        {label}
      </dt>
      <dd className={mono ? "font-mono text-data-mono text-foreground" : "text-body-medium text-foreground"}>
        {children}
      </dd>
    </div>
  );
}

export function DetailHeader({
  title,
  severity,
  status,
  category,
  source,
  ownerApprovalRequired,
}: Pick<
  IncidentDetailDto,
  | "title"
  | "severity"
  | "status"
  | "category"
  | "source"
  | "ownerApprovalRequired"
>) {
  const { t } = useTranslation("incidents");
  return (
    <header className="flex flex-col gap-3 border-b border-border pb-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h2 className="min-w-0 flex-1 break-words text-headline-md font-semibold text-foreground">
          {title}
        </h2>
        <span
          className={TONE_BADGE_CLASS[severityColorGroup(severity)]}
        >
          {t(`severity.${severity}`)}
        </span>
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <DetailField label={t("fields.status")} mono={false}>
          {t(`status.${status}`)}
        </DetailField>
        <DetailField label={t("fields.category")} mono={false}>
          {t(`category.${category}`)}
        </DetailField>
        <DetailField label={t("fields.source")} mono={false}>
          {t(`source.${source}`)}
        </DetailField>
      </div>
      {ownerApprovalRequired && (
        <p role="note" className="text-body-base text-muted-foreground">
          {t("fields.ownerApprovalRequired")}
        </p>
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
    <section className="border-b border-border py-4">
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <DetailField label={t("fields.id")}>{id}</DetailField>
        <DetailField label={t("fields.property")}>{propertyId}</DetailField>
        {reservationId && (
          <DetailField label={t("fields.reservation")}>
            {reservationId}
          </DetailField>
        )}
      </dl>
    </section>
  );
}

export function DetailAssignedTechnicianBlock({
  assignedTechnicianId,
}: Pick<IncidentDetailDto, "assignedTechnicianId">) {
  const { t } = useTranslation("incidents");
  if (!assignedTechnicianId) return null;
  return (
    <section aria-label={t("fields.assignedTechnician")} className="border-b border-border py-4">
      <dl>
        <DetailField label={t("fields.assignedTechnician")}>
          {assignedTechnicianId}
        </DetailField>
      </dl>
      <p role="note" className="mt-2 text-body-base text-muted-foreground">
        {t("fields.assignedTechnicianNote")}
      </p>
    </section>
  );
}

export function DetailDescriptionBlock({
  description,
}: Pick<IncidentDetailDto, "description">) {
  const { t } = useTranslation("incidents");
  if (!description) return null;
  return (
    <section className="border-b border-border py-4">
      <h2 className="text-label-caps uppercase text-muted-foreground">
        {t("fields.description")}
      </h2>
      {/* D7 / regla 11 de steering/security.md: render plain text, never HTML */}
      <p className="mt-1 max-w-prose whitespace-pre-wrap text-body-base text-foreground">
        {description}
      </p>
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
    <section className="border-b border-border py-4">
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <DetailField label={t("fields.estimatedCost")}>
          {fmtCost(estimatedCost)}
        </DetailField>
        <DetailField label={t("fields.approvedCost")}>
          {fmtCost(approvedCost)}
        </DetailField>
        <DetailField label={t("fields.finalCost")}>
          {fmtCost(finalCost)}
        </DetailField>
      </dl>
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
    <section className="py-4">
      {aiSummary && (
        <div className="mb-3">
          <h2 className="text-label-caps uppercase text-muted-foreground">
            {t("fields.aiSummary")}
          </h2>
          <p className="mt-1 max-w-prose text-body-base text-foreground">
            {aiSummary}
          </p>
        </div>
      )}
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <DetailField label={t("fields.createdAtFull")}>
          {fmtUtc(createdAt)}
        </DetailField>
        <DetailField label={t("fields.updatedAt")}>
          {fmtUtc(updatedAt)}
        </DetailField>
        {resolvedAt && (
          <DetailField label={t("fields.resolvedAt")}>
            {fmtUtc(resolvedAt)}
          </DetailField>
        )}
      </dl>
    </section>
  );
}