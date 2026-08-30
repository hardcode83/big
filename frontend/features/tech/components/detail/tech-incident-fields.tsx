"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { TONE_BADGE_CLASS } from "@/lib/ui/status-tone";
import {
  severityColorGroup,
  type IncidentDetailDto,
} from "@/features/incidents";

import { EMPTY_FIELD, formatDateTime } from "../../lib/format";

/**
 * One labelled field. A null value in a populated row is painted with the
 * em-dash `—` (U+2014) as a typographic mark — **not** concatenated with its
 * unit and **not** `?? ""` (R2.4, `sdd/specs/frontend-foundation.md`).
 */
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm text-foreground">{children}</dd>
    </>
  );
}

export function TechIncidentFields({
  incident,
}: {
  incident: IncidentDetailDto;
}) {
  const { t, i18n } = useTranslation(["tech", "incidents"]);
  // `frontend-foundation.md`: the em-dash is a literal character in JSX, never
  // an i18n key — it is not language text and is the same glyph in `es` and `en`.
  const dash = EMPTY_FIELD;

  const cost = (value: string | null) => {
    if (value === null) return dash;
    const num = Number(value);
    if (!Number.isFinite(num)) return value;
    return num.toLocaleString(i18n.language, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  };

  const dateTime = (value: string | null) =>
    value === null ? dash : formatDateTime(value, i18n.language);

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold text-foreground">
        {incident.title}
      </h2>

      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded-full border px-2 py-0.5 text-xs ${
            TONE_BADGE_CLASS[severityColorGroup(incident.severity)]
          }`}
        >
          {t(`incidents:severity.${incident.severity}`)}
        </span>
        <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
          {t(`incidents:status.${incident.status}`)}
        </span>
      </div>

      <p className="whitespace-pre-wrap text-sm text-foreground">
        {incident.description}
      </p>

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <Field label={t("tech:fields.category")}>
          {t(`incidents:category.${incident.category}`)}
        </Field>
        <Field label={t("tech:fields.source")}>
          {t(`incidents:source.${incident.source}`)}
        </Field>
        <Field label={t("tech:fields.etaAt")}>{dateTime(incident.etaAt)}</Field>
        <Field label={t("tech:fields.estimatedCost")}>
          {cost(incident.estimatedCost)}
        </Field>
        <Field label={t("tech:fields.approvedCost")}>
          {cost(incident.approvedCost)}
        </Field>
        <Field label={t("tech:fields.finalCost")}>
          {cost(incident.finalCost)}
        </Field>
        <Field label={t("tech:fields.materials")}>
          {incident.materials ?? dash}
        </Field>
        <Field label={t("tech:fields.ownerApprovalRequired")}>
          {incident.ownerApprovalRequired
            ? t("tech:fields.yes")
            : t("tech:fields.no")}
        </Field>
        <Field label={t("tech:fields.resolvedAt")}>
          {dateTime(incident.resolvedAt)}
        </Field>
        <Field label={t("tech:fields.createdAt")}>
          {dateTime(incident.createdAt)}
        </Field>
      </dl>
    </section>
  );
}
