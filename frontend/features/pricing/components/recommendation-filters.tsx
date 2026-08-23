"use client";

import { useTranslation } from "react-i18next";

import type { PriceRecommendationStatus, PropertySummary } from "../data";
import { RECOMMENDATION_STATUS_ORDER } from "../lib/recommendation-status";
import { usePricingUiStore } from "../state/use-pricing-ui-store";

/**
 * The four server-side filters of the recommendations queue (R2.1). All four
 * write to the Zustand store, whose setters are what return the list to page 1 —
 * this component never has to remember that.
 *
 * Native `<select>` and native `<input type="date">`: there is no `Select` or
 * `DatePicker` primitive in `components/ui/`, and the platform brings keyboard
 * support and the mobile wheel/calendar for free. Same posture as
 * `cleaning-filters.tsx`.
 *
 * **The controls are never disabled while a write is in flight** (design D8).
 * Disabling an element that currently has focus makes the browser drop focus to
 * `<body>`, which would strand a keyboard user mid-filter because somebody's
 * decision happened to be flying. Choosing is harmless; only sending waits.
 */
export interface RecommendationFiltersProps {
  properties: readonly PropertySummary[];
}

export function RecommendationFilters({
  properties,
}: RecommendationFiltersProps) {
  const { t } = useTranslation("pricing");
  const {
    recommendations: { propertyId, dateFrom, dateTo, status },
    setRecommendationPropertyId,
    setRecommendationDateFrom,
    setRecommendationDateTo,
    setRecommendationStatus,
  } = usePricingUiStore();

  return (
    <div className="flex flex-col gap-3 border-b px-4 py-3 sm:flex-row sm:flex-wrap sm:items-end">
      <div className="flex min-w-0 flex-col gap-1">
        <label
          className="text-xs font-medium text-muted-foreground"
          htmlFor="pricing-filter-property"
        >
          {t("filters.property.label")}
        </label>
        <select
          id="pricing-filter-property"
          className="tap-target min-w-0 rounded-md border bg-background px-2 py-1 text-sm"
          value={propertyId ?? ""}
          onChange={(event) =>
            setRecommendationPropertyId(event.target.value || undefined)
          }
        >
          <option value="">{t("filters.property.all")}</option>
          {properties.map((property) => (
            <option key={property.id} value={property.id}>
              {property.internalCode} {t("separator")} {property.name}
            </option>
          ))}
        </select>
      </div>

      <div className="flex min-w-0 flex-col gap-1">
        <label
          className="text-xs font-medium text-muted-foreground"
          htmlFor="pricing-filter-date-from"
        >
          {t("filters.dateFrom.label")}
        </label>
        <input
          id="pricing-filter-date-from"
          type="date"
          className="tap-target min-w-0 rounded-md border bg-background px-2 py-1 text-sm"
          value={dateFrom ?? ""}
          onChange={(event) =>
            setRecommendationDateFrom(event.target.value || undefined)
          }
        />
      </div>

      <div className="flex min-w-0 flex-col gap-1">
        <label
          className="text-xs font-medium text-muted-foreground"
          htmlFor="pricing-filter-date-to"
        >
          {t("filters.dateTo.label")}
        </label>
        <input
          id="pricing-filter-date-to"
          type="date"
          className="tap-target min-w-0 rounded-md border bg-background px-2 py-1 text-sm"
          value={dateTo ?? ""}
          onChange={(event) =>
            setRecommendationDateTo(event.target.value || undefined)
          }
        />
      </div>

      <div className="flex min-w-0 flex-col gap-1">
        <label
          className="text-xs font-medium text-muted-foreground"
          htmlFor="pricing-filter-status"
        >
          {t("filters.status.label")}
        </label>
        <select
          id="pricing-filter-status"
          className="tap-target min-w-0 rounded-md border bg-background px-2 py-1 text-sm"
          value={status ?? ""}
          onChange={(event) =>
            setRecommendationStatus(
              (event.target.value || undefined) as
                | PriceRecommendationStatus
                | undefined,
            )
          }
        >
          <option value="">{t("filters.status.all")}</option>
          {/* Derived from the exhaustive Record, in PRD §7.18 lifecycle order. */}
          {RECOMMENDATION_STATUS_ORDER.map((value) => (
            <option key={value} value={value}>
              {t(`status.${value}`)}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
