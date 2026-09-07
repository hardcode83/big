"use client";

import { useTranslation } from "react-i18next";

import type { PropertySummary } from "../data";
import { usePricingUiStore } from "../state/use-pricing-ui-store";

/**
 * The two server-side filters of the rules tab (R5.1). They write to the rules
 * slice of the store, which is deliberately independent of the recommendations
 * slice — see design D11 for why sharing `propertyId` would be a silent bug.
 *
 * `active` is a tri-state on the wire (`true` / `false` / absent), so the
 * `<select>` carries three options and the empty value means «no filter», not
 * «false».
 */
export interface RuleFiltersProps {
  properties: readonly PropertySummary[];
}

export function RuleFilters({ properties }: RuleFiltersProps) {
  const { t } = useTranslation("pricing");
  const {
    rules: { propertyId, active },
    setRulePropertyId,
    setRuleActive,
  } = usePricingUiStore();

  return (
    <div className="m-4 flex flex-col gap-3 rounded-lg border border-border bg-surface/60 p-3 backdrop-blur-md sm:flex-row sm:flex-wrap sm:items-end">
      <div className="flex min-w-0 flex-col gap-1">
        <label
          className="text-xs font-medium text-muted-foreground"
          htmlFor="pricing-rule-filter-property"
        >
          {t("filters.property.label")}
        </label>
        <select
          id="pricing-rule-filter-property"
          className="tap-target min-w-0 rounded-md border bg-background px-2 py-1 text-sm"
          value={propertyId ?? ""}
          onChange={(event) =>
            setRulePropertyId(event.target.value || undefined)
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
          htmlFor="pricing-rule-filter-active"
        >
          {t("filters.active.label")}
        </label>
        <select
          id="pricing-rule-filter-active"
          className="tap-target min-w-0 rounded-md border bg-background px-2 py-1 text-sm"
          value={active === undefined ? "" : String(active)}
          onChange={(event) => {
            const raw = event.target.value;
            // Absent is a third state, not `false`: it means «do not filter».
            setRuleActive(raw === "" ? undefined : raw === "true");
          }}
        >
          <option value="">{t("filters.active.all")}</option>
          <option value="true">{t("filters.active.true")}</option>
          <option value="false">{t("filters.active.false")}</option>
        </select>
      </div>
    </div>
  );
}
