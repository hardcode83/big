"use client";

import { useTranslation } from "react-i18next";

import { PROPERTY_OPERATIONAL_STATES } from "@/components/property-state-badge";

import type {
  PropertyFilters,
  PropertyOperationalState,
  PropertyStatus,
} from "../../data";

const PROPERTY_STATUSES: PropertyStatus[] = ["ACTIVE", "INACTIVE"];

/**
 * The eleven states come from `PROPERTY_OPERATIONAL_STATES`, not from a list
 * written out here again.
 *
 * That constant is derived from the `Record<PropertyOperationalState, …>` color
 * map, so its completeness is enforced by the compiler: if the backend adds a
 * twelfth state, the build breaks and this `<select>` picks it up for free. A
 * hand-written list would silently stop offering the new state and no test
 * would go red — the same divergence design D10 names for label catalogs.
 */
const OPERATIONAL_STATES: readonly PropertyOperationalState[] =
  PROPERTY_OPERATIONAL_STATES;

/**
 * The v1 filter bar for `/properties` (proposal R2, design D7). Controlled
 * component: the parent owns the filters state and issues the query; this bar
 * stores nothing.
 *
 * Two invariants live here rather than in the parent:
 *
 * - **Every change resets to page 1** (R2.2). Filtering from page 3 could
 *   otherwise request a page the filtered set does not have, which comes back
 *   as an empty `data` the screen cannot tell apart from "no properties match".
 * - **Keys are emitted in a fixed order** (`currentOperationalState`, `page`,
 *   `status`) so two equivalent renders produce the same query key (R2.3).
 *   `normalizePropertyFilters` in `hooks/query-keys.ts` enforces this again at
 *   the key boundary; doing it here too keeps the object the parent holds
 *   canonical.
 *
 * There is no text search, no ordering control and no city filter: the endpoint
 * accepts none of them (R2.4).
 *
 * The operational-state labels come from the `dashboard` namespace, which owns
 * the only catalog of those eleven strings (design D10).
 */
export function PropertiesFilters({
  value,
  onChange,
}: {
  value: PropertyFilters;
  onChange: (next: PropertyFilters) => void;
}) {
  const { t } = useTranslation("properties");
  const { t: tDashboard } = useTranslation("dashboard");

  function emit(next: {
    status?: PropertyStatus;
    currentOperationalState?: PropertyOperationalState;
  }) {
    onChange({
      ...(next.currentOperationalState
        ? { currentOperationalState: next.currentOperationalState }
        : {}),
      page: 1,
      ...(next.status ? { status: next.status } : {}),
    });
  }

  return (
    <div className="flex flex-wrap items-end gap-3">
      <div>
        <label
          className="mb-1 block text-xs font-medium text-muted-foreground"
          htmlFor="properties-status"
        >
          {t("filters.status")}
        </label>
        <select
          id="properties-status"
          className="tap-target rounded-md border bg-background px-2 py-1 text-sm"
          value={value.status ?? ""}
          onChange={(event) => {
            const status = (event.target.value || undefined) as
              | PropertyStatus
              | undefined;
            emit({
              status,
              currentOperationalState: value.currentOperationalState,
            });
          }}
        >
          <option value="">{t("filters.all")}</option>
          {PROPERTY_STATUSES.map((status) => (
            <option key={status} value={status}>
              {t(`status.${status}`)}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label
          className="mb-1 block text-xs font-medium text-muted-foreground"
          htmlFor="properties-operational-state"
        >
          {t("filters.operationalState")}
        </label>
        <select
          id="properties-operational-state"
          className="tap-target rounded-md border bg-background px-2 py-1 text-sm"
          value={value.currentOperationalState ?? ""}
          onChange={(event) => {
            const currentOperationalState = (event.target.value || undefined) as
              | PropertyOperationalState
              | undefined;
            emit({ status: value.status, currentOperationalState });
          }}
        >
          <option value="">{t("filters.allStates")}</option>
          {OPERATIONAL_STATES.map((state) => (
            <option key={state} value={state}>
              {tDashboard(`state.${state}`)}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
