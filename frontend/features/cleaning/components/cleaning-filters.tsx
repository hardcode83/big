"use client";

import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import type { CleaningTaskStatus } from "../data";
import { usePropertyDirectory } from "../hooks/use-cleaning-data";
import { useCleaningFiltersStore } from "../state/use-cleaning-filters-store";
import { CLEANING_TASK_STATUSES } from "../lib/task-status";

/**
 * The two server-side filters (R3.1, R3.2, R3.5). Both write to the Zustand store,
 * whose setters are what return the list to page 1 (design D6) — this component
 * never has to remember that.
 *
 * Native `<select>`, like `features/dashboard/components/detail/property-timeline.tsx`:
 * there is no `Select` primitive in `components/ui/`, and the native element brings
 * keyboard support and the mobile wheel for free (R5.3).
 */
export function CleaningFilters() {
  const { t } = useTranslation("cleaning");
  const {
    propertyId,
    status,
    setPropertyId,
    setStatus,
    clearPropertyId,
    clearStatus,
  } = useCleaningFiltersStore();
  const propertyDirectory = usePropertyDirectory();
  const properties = propertyDirectory.data ?? [];

  return (
    <div className="m-4 flex flex-col gap-3 rounded-lg border border-border bg-surface/60 p-3 backdrop-blur-md sm:flex-row sm:flex-wrap sm:items-end">
      <div className="flex min-w-0 flex-col gap-1">
        <label
          className="text-xs font-medium text-muted-foreground"
          htmlFor="cleaning-filter-property"
        >
          {t("filters.property.label")}
        </label>
        <div className="flex items-center gap-2">
          <select
            id="cleaning-filter-property"
            className="tap-target min-w-0 flex-1 rounded-md border bg-background px-2 py-1 text-sm"
            value={propertyId ?? ""}
            onChange={(event) => setPropertyId(event.target.value || undefined)}
          >
            <option value="">{t("filters.property.all")}</option>
            {properties.map((property) => (
              <option key={property.id} value={property.id}>
                {property.internalCode} {t("separator")} {property.name}
              </option>
            ))}
          </select>
          {propertyId !== undefined ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => clearPropertyId()}
            >
              {t("filters.property.clear")}
            </Button>
          ) : null}
        </div>
      </div>

      <div className="flex min-w-0 flex-col gap-1">
        <label
          className="text-xs font-medium text-muted-foreground"
          htmlFor="cleaning-filter-status"
        >
          {t("filters.status.label")}
        </label>
        <div className="flex items-center gap-2">
          <select
            id="cleaning-filter-status"
            className="tap-target min-w-0 flex-1 rounded-md border bg-background px-2 py-1 text-sm"
            value={status ?? ""}
            onChange={(event) =>
              setStatus((event.target.value || undefined) as
                | CleaningTaskStatus
                | undefined)
            }
          >
            <option value="">{t("filters.status.all")}</option>
            {CLEANING_TASK_STATUSES.map((value) => (
              <option key={value} value={value}>
                {t(`status.${value}`)}
              </option>
            ))}
          </select>
          {status !== undefined ? (
            <Button type="button" variant="outline" onClick={() => clearStatus()}>
              {t("filters.status.clear")}
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
