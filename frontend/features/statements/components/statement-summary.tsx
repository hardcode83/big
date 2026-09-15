"use client";

import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { TONE_BADGE_CLASS } from "@/lib/ui/status-tone";
import { cn } from "@/lib/utils";

import type { OwnerStatementDetail } from "../data";
import { fmtAmount, fmtDay } from "../lib/format";
import { STATUS_TONE } from "./statement-row";

/**
 * The flat summary half of `OwnerStatementDetail` — everything except the two
 * breakdown collections, which `ReservationsBreakdown`/`ExpensesBreakdown`
 * (task 4.2/4.3) render on their own. Kept as a type alias (not a re-export
 * of the private `OwnerStatementSummaryFields` interface in `data/dto.ts`,
 * which is intentionally unexported) so this component only ever depends on
 * the public DTO surface (design D1).
 */
export type StatementSummaryData = Omit<OwnerStatementDetail, "reservations" | "expenses">;

/**
 * The eleven monetary amounts (R3.1), in the same order the backend/dto keep
 * them. Rendered from a single table instead of eleven repeated JSX blocks so
 * a missing amount is a missing i18n key (caught by the parity test), not a
 * silently skipped field.
 */
const AMOUNT_FIELDS: ReadonlyArray<{
  key: keyof StatementSummaryData;
  labelKey: string;
}> = [
  { key: "grossRevenue", labelKey: "detail.summary.amounts.grossRevenue" },
  { key: "otaCommissions", labelKey: "detail.summary.amounts.otaCommissions" },
  { key: "netRevenue", labelKey: "detail.summary.amounts.netRevenue" },
  { key: "cleaningCosts", labelKey: "detail.summary.amounts.cleaningCosts" },
  { key: "laundryCosts", labelKey: "detail.summary.amounts.laundryCosts" },
  { key: "amenitiesCosts", labelKey: "detail.summary.amounts.amenitiesCosts" },
  { key: "maintenanceCosts", labelKey: "detail.summary.amounts.maintenanceCosts" },
  { key: "specialistCosts", labelKey: "detail.summary.amounts.specialistCosts" },
  { key: "otherCosts", labelKey: "detail.summary.amounts.otherCosts" },
  { key: "platformFee", labelKey: "detail.summary.amounts.platformFee" },
  { key: "netOwnerResult", labelKey: "detail.summary.amounts.netOwnerResult" },
];

export interface StatementSummaryProps {
  statement: StatementSummaryData;
}

/**
 * The complete flat summary of a statement detail (R3.1, R3.8, task 4.1):
 * period, status, notes and the eleven monetary amounts. Every field is
 * rendered unconditionally — `notes: null` is shown as an explicit, localized
 * "no notes" state rather than hidden or replaced by any other statement's
 * text (R3.8), and no field is computed, summed or converted here.
 *
 * Dates and amounts use the shared formatters from `../lib/format` (task
 * 6.2) — UTC-anchored medium dates, locale decimals, and NO currency symbol
 * (the summary has no `currency` field — R3.6 forbids inventing one).
 */
export function StatementSummary({ statement }: StatementSummaryProps) {
  const { t, i18n } = useTranslation("statements");
  const locale = i18n.language;

  return (
    <Card className="flex min-w-0 flex-col gap-4 p-4" data-testid="statement-summary">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <h2 className="min-w-0 flex-1 break-words text-headline-md font-semibold text-foreground">
          {t("detail.summary.title")}
        </h2>
        <Badge variant="outline" className={cn(TONE_BADGE_CLASS[STATUS_TONE[statement.status]])}>
          <span className="sr-only">{t("columns.status")}: </span>
          {t(`status.${statement.status}`)}
        </Badge>
      </div>

      <div className="flex min-w-0 flex-col gap-0.5 text-body-base">
        <span className="text-muted-foreground">{t("columns.period")}</span>
        <span className="min-w-0 break-words text-body-medium text-foreground">
          {fmtDay(statement.periodStart, locale)} {t("separator")}{" "}
          {fmtDay(statement.periodEnd, locale)}
        </span>
      </div>

      <div className="flex min-w-0 flex-col gap-0.5 text-body-base">
        <span className="text-muted-foreground">{t("detail.summary.notes.label")}</span>
        <span className="min-w-0 whitespace-pre-wrap break-words text-body-medium text-foreground">
          {statement.notes === null ? t("detail.summary.notes.empty") : statement.notes}
        </span>
      </div>

      <dl className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
        {AMOUNT_FIELDS.map(({ key, labelKey }) => (
          <div key={key} className="flex min-w-0 flex-col gap-0.5 text-body-base">
            <dt className="text-muted-foreground">{t(labelKey)}</dt>
            <dd className="min-w-0 break-words text-body-medium text-foreground">
              {fmtAmount(statement[key] as string, locale)}
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}
