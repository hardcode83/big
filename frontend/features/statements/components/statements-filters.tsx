"use client";

import { useTranslation } from "react-i18next";

import type { OwnerStatementStatus } from "../data";

/** All values of the contract's status enum, in a fixed display order. */
const STATUSES: readonly OwnerStatementStatus[] = ["DRAFT", "READY", "SENT"] as const;

/** The minimal shape this component needs from a property, decoupled from
 * `PropertySummaryDto` so it does not import `features/properties` types
 * directly into this feature's component surface. */
export interface StatementPropertyOption {
  id: string;
  name: string;
}

/**
 * Accessible filter row for the statements list (R1.3, R2.2, R2.3, design D2).
 *
 * `properties` MUST come from the complete active-property directory
 * (`useStatementPropertyDirectory`), never from the current page of
 * statements — the list is never a source of filter options. Only the
 * selected `propertyId` (a UUID) is ever emitted; no `tenant_id` and no
 * property object travels through `onPropertyIdChange`.
 *
 * Mirrors `features/reviews/components/review-filters.tsx` and
 * `features/pricing/components/rule-filters.tsx`: native `<select>`/`<input>`
 * controls with a programmatic `<label htmlFor>`, so every control has an
 * accessible name without `aria-label` duplication, and shadcn/ui inputs
 * are used for consistent focus-visible styling.
 */
export interface StatementsFiltersProps {
  properties: readonly StatementPropertyOption[];
  propertyId?: string;
  onPropertyIdChange: (value?: string) => void;
  periodStartFrom?: string;
  onPeriodStartFromChange: (value?: string) => void;
  periodStartTo?: string;
  onPeriodStartToChange: (value?: string) => void;
  status?: OwnerStatementStatus;
  onStatusChange: (value?: OwnerStatementStatus) => void;
}

export function StatementsFilters({
  properties,
  propertyId,
  onPropertyIdChange,
  periodStartFrom,
  onPeriodStartFromChange,
  periodStartTo,
  onPeriodStartToChange,
  status,
  onStatusChange,
}: StatementsFiltersProps) {
  const { t } = useTranslation("statements");

  return (
    <div
      aria-label={t("filters.label")}
      className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end"
    >
      <div className="flex min-w-0 flex-col gap-1">
        <label
          htmlFor="statements-filter-property"
          className="text-body-base font-medium text-foreground"
        >
          {t("filters.property.label")}
        </label>
        <select
          id="statements-filter-property"
          value={propertyId ?? ""}
          onChange={(e) =>
            onPropertyIdChange(e.target.value === "" ? undefined : e.target.value)
          }
          className="tap-target min-w-0 rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
        >
          <option value="">{t("filters.property.all")}</option>
          {properties.map((property) => (
            <option key={property.id} value={property.id}>
              {property.name}
            </option>
          ))}
        </select>
      </div>

      <div className="flex min-w-0 flex-col gap-1">
        <label
          htmlFor="statements-filter-period-from"
          className="text-body-base font-medium text-foreground"
        >
          {t("filters.periodFrom.label")}
        </label>
        <input
          id="statements-filter-period-from"
          type="date"
          value={periodStartFrom ?? ""}
          onChange={(e) =>
            onPeriodStartFromChange(e.target.value === "" ? undefined : e.target.value)
          }
          className="tap-target min-w-0 rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
        />
      </div>

      <div className="flex min-w-0 flex-col gap-1">
        <label
          htmlFor="statements-filter-period-to"
          className="text-body-base font-medium text-foreground"
        >
          {t("filters.periodTo.label")}
        </label>
        <input
          id="statements-filter-period-to"
          type="date"
          value={periodStartTo ?? ""}
          onChange={(e) =>
            onPeriodStartToChange(e.target.value === "" ? undefined : e.target.value)
          }
          className="tap-target min-w-0 rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
        />
      </div>

      <div className="flex min-w-0 flex-col gap-1">
        <label
          htmlFor="statements-filter-status"
          className="text-body-base font-medium text-foreground"
        >
          {t("filters.status.label")}
        </label>
        <select
          id="statements-filter-status"
          value={status ?? ""}
          onChange={(e) =>
            onStatusChange(
              e.target.value === "" ? undefined : (e.target.value as OwnerStatementStatus),
            )
          }
          className="tap-target min-w-0 rounded-md border border-border bg-background px-2 py-1.5 text-body-base"
        >
          <option value="">{t("filters.status.all")}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`status.${s}`)}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
