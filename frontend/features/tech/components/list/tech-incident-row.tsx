"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";

import { TONE_BADGE_CLASS } from "@/lib/ui/status-tone";
import {
  severityColorGroup,
  type IncidentSummaryDto,
} from "@/features/incidents";

import { formatDateTime } from "../../lib/format";

/**
 * One incident as a tappable card, not a table row (design D15): a six-column
 * table does not fit 360 px without horizontal scroll, which R6.3 forbids.
 *
 * `propertyName` and `propertyInternalCode` come from the row's context query,
 * which the view resolves under the very key the detail uses (R1.3). A context
 * that failed degrades this row to `—` without taking the list down (D4), so
 * they arrive already resolved and nullable.
 */
export function TechIncidentRow({
  incident,
  propertyName,
  propertyInternalCode,
}: {
  incident: IncidentSummaryDto;
  propertyName: string | null;
  propertyInternalCode: string | null;
}) {
  const { t, i18n } = useTranslation(["tech", "incidents"]);
  const dash = t("tech:common.empty");

  return (
    <li className="rounded-lg border bg-surface">
      <Link
        href={`/tech/incidents/${incident.id}`}
        className="flex min-h-11 flex-col gap-2 p-4"
      >
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

        <span className="text-base font-semibold text-foreground">
          {incident.title}
        </span>

        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm text-muted-foreground">
          <dt>{t("tech:context.propertyName")}</dt>
          <dd className="text-foreground">{propertyName ?? dash}</dd>
          <dt>{t("tech:context.propertyInternalCode")}</dt>
          <dd className="text-foreground">{propertyInternalCode ?? dash}</dd>
          <dt>{t("tech:fields.category")}</dt>
          <dd className="text-foreground">
            {t(`incidents:category.${incident.category}`)}
          </dd>
          <dt>{t("tech:fields.createdAt")}</dt>
          <dd className="text-foreground">
            {formatDateTime(incident.createdAt, i18n.language)}
          </dd>
        </dl>
      </Link>
    </li>
  );
}
