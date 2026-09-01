"use client";

import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

import type { CleaningFilters, CleaningTaskStatus } from "../../data";

/**
 * The seven statuses a cleaner can see on her own rows (design D5, R1.5).
 * `CREATED` is not offered because the backend's `restrict_to_cleaner_id`
 * empties it for `CLEANER`; `FAILED` is not offered because only the manager
 * can write it and it is not a state the cleaner needs to filter by.
 */
export const CLEANER_STATUS_CHIPS: readonly CleaningTaskStatus[] = [
  "ASSIGNED",
  "ACCEPTED",
  "IN_PROGRESS",
  "PENDING_REVIEW",
  "COMPLETED",
  "REJECTED",
  "CANCELLED",
];

/**
 * Status chips for `/cleaner` (design D5). `status` travels as a **single**
 * value — the contract admits no more — and a second tap on the active chip
 * goes back to `{}`, no filter at all (R1.6).
 *
 * The filters object is always built with the same key order so two equivalent
 * renders produce the same query key (D3).
 *
 * Renders nothing in `loading` or `error` branches of the list view (the view
 * decides whether to mount this component at all).
 */
export function CleanerTaskStatusChips({
  value,
  onChange,
}: {
  value: CleaningFilters;
  onChange: (next: CleaningFilters) => void;
}) {
  const { t } = useTranslation(["cleaner", "cleaning"]);

  return (
    <div
      className="flex flex-wrap gap-2"
      role="group"
      aria-label={t("cleaner:filters.label")}
    >
      {CLEANER_STATUS_CHIPS.map((status) => {
        const active = value.status === status;
        return (
          <button
            key={status}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(active ? {} : { status })}
            className={cn(
              "min-h-11 rounded-full border px-4 py-2 text-sm",
              active
                ? "border-primary bg-primary text-primary-foreground"
                : "border-input bg-background text-foreground",
            )}
          >
            {t(`cleaning:status.${status}`)}
          </button>
        );
      })}
    </div>
  );
}