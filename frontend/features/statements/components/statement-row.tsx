"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { TONE_BADGE_CLASS, type Tone } from "@/lib/ui/status-tone";
import { cn } from "@/lib/utils";

import type { OwnerStatement, OwnerStatementStatus } from "../data";

/**
 * The directory this row resolves `propertyId` against. Shaped like
 * `useStatementPropertyDirectory()`'s return value (an id→property `index`
 * plus `isPending`), but only the two fields this component needs — it does
 * not import `UseQueryResult` or any TanStack Query type, keeping this a
 * pure presentational component (design D1: no direct data-layer coupling).
 */
export interface StatementPropertyDirectory {
  index: ReadonlyMap<string, { name: string }>;
  isPending: boolean;
}

/**
 * Design D5-equivalent: DRAFT is not yet final, READY is reviewable, SENT is
 * done. Exported (task 3.3 note) so section 4's `StatementSummary` reuses the
 * same status→tone mapping instead of redefining it for the identical enum.
 */
export const STATUS_TONE: Record<OwnerStatementStatus, Tone> = {
  DRAFT: "gray",
  READY: "blue",
  SENT: "green",
};

/**
 * A `YYYY-MM-DD` day as the locale's medium date, UTC-anchored so the day
 * never shifts with the browser's timezone (same discipline as
 * `features/pricing/lib/format.ts:fmtDay` and `features/reviews/lib/format.ts:fmtDay`).
 * An unparseable value degrades to the raw string rather than throwing.
 *
 * TODO(section 6.2): replace with the shared `features/statements/lib/format.ts`
 * once it exists, instead of keeping this local copy.
 */
function fmtDay(isoDay: string, locale: string): string {
  const date = new Date(isoDay);
  if (Number.isNaN(date.getTime())) {
    return isoDay;
  }
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }).format(
    date,
  );
}

/**
 * A contract decimal string rendered with the locale's separator and two
 * decimals. No currency symbol or code: `OwnerStatementResponse` publishes no
 * `currency` field on its summary (R3.6), so inventing one here would be a
 * fabrication the backend never asserted.
 *
 * TODO(section 6.2): replace with the shared `features/statements/lib/format.ts`.
 */
function fmtAmount(value: string, locale: string): string {
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return value;
  }
  return num.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-0.5 text-body-base", className)}>
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words text-body-medium text-foreground">
        {children}
      </span>
    </div>
  );
}

/**
 * One row of the statements list (R2.1, R2.4, design D2).
 *
 * The property label is resolved **only** from `properties` — the complete
 * active-property directory (`useStatementPropertyDirectory`) — never from a
 * field on `statement` itself (the DTO carries only the `propertyId` UUID).
 * Three shapes distinguish "still loading the directory" from "not found in
 * it", the same discipline `features/reviews`/`features/pricing` use for
 * their own property identity: a pending catalog gets a neutral marker, a
 * catalog that settled without this id gets the "unavailable" copy.
 *
 * Financial fields shown here are the list's own summary fields
 * (`periodStart`/`periodEnd`, `status`, `netOwnerResult`) — the eleven-amount
 * breakdown and `reservations[]`/`expenses[]` belong to the detail view
 * (section 4), not this row.
 */
export interface StatementRowProps {
  statement: OwnerStatement;
  properties: StatementPropertyDirectory;
}

export function StatementRow({ statement, properties }: StatementRowProps) {
  const { t, i18n } = useTranslation("statements");
  const locale = i18n.language;
  const headingId = `statement-row-${statement.id}`;
  const property = properties.index.get(statement.propertyId);

  const propertyLabel = property
    ? property.name
    : properties.isPending
      ? t("identity.loading")
      : t("identity.unavailable");

  return (
    <li aria-labelledby={headingId} className="min-w-0 list-none">
      <Card className="flex min-w-0 flex-col gap-3 p-4">
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
          <h3
            id={headingId}
            className="min-w-0 flex-1 break-words text-body-lg font-semibold text-foreground"
          >
            <span className="sr-only">{t("columns.property")}: </span>
            {propertyLabel}
          </h3>
          <Badge variant="outline" className={cn(TONE_BADGE_CLASS[STATUS_TONE[statement.status]])}>
            <span className="sr-only">{t("columns.status")}: </span>
            {t(`status.${statement.status}`)}
          </Badge>
        </div>

        <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label={t("columns.period")} className="sm:col-span-2">
            {fmtDay(statement.periodStart, locale)} {t("separator")}{" "}
            {fmtDay(statement.periodEnd, locale)}
          </Field>
          <Field label={t("columns.netOwnerResult")}>
            {fmtAmount(statement.netOwnerResult, locale)}
          </Field>
        </div>
      </Card>
    </li>
  );
}
