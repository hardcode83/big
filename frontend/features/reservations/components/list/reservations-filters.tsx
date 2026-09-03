"use client";

import { useTranslation } from "react-i18next";

import type { ReservationFilters, ReservationStatus } from "../../data";

const RESERVATION_STATUSES: ReservationStatus[] = [
  "PENDING",
  "CONFIRMED",
  "CANCELLED",
  "CHECKED_IN_ESTIMATED",
  "CHECKED_OUT_ESTIMATED",
  "COMPLETED",
  "NO_SHOW",
];

/**
 * The v1 filter bar for `/reservations` (proposal R2, design D4). Controlled
 * component: the parent owns the filters state and is responsible for the
 * query. The bar does NOT render a property picker — `property_id` is out of
 * v1 scope (D4) and a picker would force a second async source.
 *
 * The keys in `next` are emitted in a fixed order
 * (`status`, `dateFrom`, `dateTo`, `page`, `perPage`) so two equivalent
 * renders produce the same query key (precedent: design D4).
 */
export function ReservationsFilters({
  value,
  onChange,
}: {
  value: ReservationFilters;
  onChange: (next: ReservationFilters) => void;
}) {
  const { t } = useTranslation("reservations");

  return (
    <div
      className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface/60 p-3 backdrop-blur-md"
      aria-label={t("fields.status")}
    >
      <div>
        <label
          className="mb-1 block text-xs font-medium text-muted-foreground"
          htmlFor="reservations-status"
        >
          {t("fields.status")}
        </label>
        <select
          id="reservations-status"
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={value.status ?? ""}
          onChange={(e) => {
            const status = (e.target.value || undefined) as
              | ReservationStatus
              | undefined;
            const next: ReservationFilters = {
              ...(status ? { status } : {}),
              ...(value.dateFrom ? { dateFrom: value.dateFrom } : {}),
              ...(value.dateTo ? { dateTo: value.dateTo } : {}),
              page: 1,
            };
            onChange(next);
          }}
        >
          <option value="">{t("fields.status")}</option>
          {RESERVATION_STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`status.${s}`)}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label
          className="mb-1 block text-xs font-medium text-muted-foreground"
          htmlFor="reservations-date-from"
        >
          {t("fields.checkIn")}
        </label>
        <input
          id="reservations-date-from"
          type="date"
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={value.dateFrom ?? ""}
          onChange={(e) => {
            const dateFrom = e.target.value || undefined;
            const next: ReservationFilters = {
              ...(value.status ? { status: value.status } : {}),
              ...(dateFrom ? { dateFrom } : {}),
              ...(value.dateTo ? { dateTo: value.dateTo } : {}),
              page: 1,
            };
            onChange(next);
          }}
        />
      </div>
      <div>
        <label
          className="mb-1 block text-xs font-medium text-muted-foreground"
          htmlFor="reservations-date-to"
        >
          {t("fields.checkOut")}
        </label>
        <input
          id="reservations-date-to"
          type="date"
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={value.dateTo ?? ""}
          onChange={(e) => {
            const dateTo = e.target.value || undefined;
            const next: ReservationFilters = {
              ...(value.status ? { status: value.status } : {}),
              ...(value.dateFrom ? { dateFrom: value.dateFrom } : {}),
              ...(dateTo ? { dateTo } : {}),
              page: 1,
            };
            onChange(next);
          }}
        />
      </div>
      <button
        type="button"
        className="tap-target rounded-md border bg-background px-3 py-1 text-body-base transition-colors hover:bg-accent hover:text-accent-foreground"
        onClick={() => onChange({})}
      >
        {t("fields.clearFilters")}
      </button>
    </div>
  );
}
