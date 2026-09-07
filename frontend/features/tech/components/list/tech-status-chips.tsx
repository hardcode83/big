"use client";

import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import type { IncidentFilters, IncidentStatus } from "@/features/incidents";

/**
 * The six statuses a technician can see on their own rows (R1's `ASSUMPTION`).
 * `OPEN`, `CLASSIFIED` and `CANCELLED` are not offered: in none of the three is
 * the incident assigned to anybody, so the filter would always come back empty.
 */
export const TECH_STATUS_CHIPS: readonly IncidentStatus[] = [
  "ASSIGNED",
  "ACCEPTED",
  "IN_PROGRESS",
  "WAITING_EXTERNAL_PARTS",
  "AWAITING_OWNER_APPROVAL",
  "RESOLVED",
];

/**
 * Status chips for `/tech` (design D5). `status` travels as a **single** value —
 * the contract admits no more — and a second tap on the active chip goes back
 * to `{}`, no filter at all.
 *
 * The filters object is always built with the same key order, as
 * `incidentsKeys.list` asks, so two equivalent renders produce the same query
 * key and TanStack does not invalidate on its own.
 */
export function TechStatusChips({
  value,
  onChange,
}: {
  value: IncidentFilters;
  onChange: (next: IncidentFilters) => void;
}) {
  const { t } = useTranslation(["tech", "incidents"]);

  return (
    <div
      className="flex flex-wrap gap-2"
      role="group"
      aria-label={t("tech:filters.label")}
    >
      {TECH_STATUS_CHIPS.map((status) => {
        const active = value.status === status;
        return (
          <button
            key={status}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(active ? {} : { status })}
            className={cn(
              "tap-target rounded-full border px-4 py-2 text-body-medium transition-colors",
              active
                ? "border-primary bg-primary text-primary-foreground"
                : "border-input bg-background text-foreground hover:bg-accent/50",
            )}
          >
            {t(`incidents:status.${status}`)}
          </button>
        );
      })}
    </div>
  );
}
