"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { TONE_BADGE_CLASS, type Tone } from "@/lib/ui/status-tone";
import { cn } from "@/lib/utils";

import type { OwnerStatement, OwnerStatementStatus } from "../data";
import { fmtAmount, fmtDay } from "../lib/format";

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
 *
 * Dates and amounts use the shared formatters from `../lib/format` (task
 * 6.2) — UTC-anchored medium dates, locale decimals, and NO currency symbol
 * (the summary has no `currency` field — R3.6 forbids inventing one).
 *
 * **Selection (task 6.3):** when the parent supplies `onSelect`, the row's
 * inner card becomes a `<button>` so it is keyboard-operable, has a focus
 * state, and meets the 44x44 tap-target baseline. The `<li>` stays static;
 * only the card content flips to a button — keyboard tab order is
 * preserved (the button is the sole focusable element inside the row) and
 * screen readers keep `aria-labelledby` on the list item.
 */
export interface StatementRowProps {
  statement: OwnerStatement;
  properties: StatementPropertyDirectory;
  /**
   * When provided, the row becomes a keyboard- and pointer-operable trigger
   * that calls this with `statement.id`. When omitted, the row is purely
   * informational — used by tests and any future read-only listing.
   */
  onSelect?: (statementId: string) => void;
}

export function StatementRow({ statement, properties, onSelect }: StatementRowProps) {
  const { t, i18n } = useTranslation("statements");
  const locale = i18n.language;
  const headingId = `statement-row-${statement.id}`;
  const property = properties.index.get(statement.propertyId);

  const propertyLabel = property
    ? property.name
    : properties.isPending
      ? t("identity.loading")
      : t("identity.unavailable");

  const body = (
    <Card
      className={cn(
        "flex min-w-0 flex-col gap-3 p-4 text-left",
        onSelect ? "tap-target w-full" : null,
      )}
    >
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <h2
          id={headingId}
          className="min-w-0 flex-1 break-words text-body-lg font-semibold text-foreground"
        >
          <span className="sr-only">{t("columns.property")}: </span>
          {propertyLabel}
        </h2>
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
  );

  return (
    <li aria-labelledby={headingId} className="min-w-0 list-none">
      {onSelect ? (
        <button
          type="button"
          onClick={() => onSelect(statement.id)}
          aria-labelledby={headingId}
          className="block min-w-0 cursor-pointer rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {body}
        </button>
      ) : (
        body
      )}
    </li>
  );
}
