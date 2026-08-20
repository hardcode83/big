"use client";

import { useTranslation } from "react-i18next";

import type {
  IncidentFilters,
  IncidentSeverity,
  IncidentStatus,
} from "../../data";

const INCIDENT_STATUSES: IncidentStatus[] = [
  "OPEN",
  "CLASSIFIED",
  "AWAITING_OWNER_APPROVAL",
  "ASSIGNED",
  "ACCEPTED",
  "IN_PROGRESS",
  "WAITING_EXTERNAL_PARTS",
  "RESOLVED",
  "CANCELLED",
];

const INCIDENT_SEVERITIES: IncidentSeverity[] = [
  "LOW",
  "MEDIUM",
  "HIGH",
  "CRITICAL",
];

// Stable key order for the normalized `IncidentFilters` (D4).
function buildNext(
  prev: IncidentFilters,
  patch: { status?: IncidentStatus; severity?: IncidentSeverity },
): IncidentFilters {
  const status = "status" in patch ? patch.status : prev.status;
  const severity = "severity" in patch ? patch.severity : prev.severity;
  const next: IncidentFilters = {};
  if (status !== undefined) next.status = status;
  if (severity !== undefined) next.severity = severity;
  // Reset to page 1 whenever a filter changes.
  next.page = 1;
  return next;
}

/**
 * The v1 filter bar for `/incidents` (proposal R2, design D4). Controlled
 * component: the parent owns the filters state and is responsible for the
 * query. The bar does NOT render a property picker — `property_id` is out of
 * v1 scope (D4) and a picker would force a second async source.
 *
 * The keys in `next` are emitted in a fixed order
 * (`status`, `severity`, `page`, `perPage`) so two equivalent renders produce
 * the same query key (precedent: design D4).
 */
export function IncidentsFilters({
  value,
  onChange,
}: {
  value: IncidentFilters;
  onChange: (next: IncidentFilters) => void;
}) {
  const { t } = useTranslation("incidents");

  return (
    <div
      className="flex flex-wrap items-end gap-3"
      aria-label={t("fields.status")}
    >
      <div>
        <label
          className="mb-1 block text-xs font-medium text-muted-foreground"
          htmlFor="incidents-status"
        >
          {t("fields.status")}
        </label>
        <select
          id="incidents-status"
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={value.status ?? ""}
          onChange={(e) => {
            const raw = e.target.value;
            const status = raw ? (raw as IncidentStatus) : undefined;
            onChange(buildNext(value, { status, page: 1 }));
          }}
        >
          <option value="">{t("fields.status")}</option>
          {INCIDENT_STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`status.${s}`)}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label
          className="mb-1 block text-xs font-medium text-muted-foreground"
          htmlFor="incidents-severity"
        >
          {t("fields.severity")}
        </label>
        <select
          id="incidents-severity"
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={value.severity ?? ""}
          onChange={(e) => {
            const raw = e.target.value;
            const severity = raw ? (raw as IncidentSeverity) : undefined;
            onChange(buildNext(value, { severity, page: 1 }));
          }}
        >
          <option value="">{t("fields.severity")}</option>
          {INCIDENT_SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {t(`severity.${s}`)}
            </option>
          ))}
        </select>
      </div>
      <button
        type="button"
        className="rounded-md border bg-background px-3 py-1 text-sm"
        onClick={() => onChange({})}
      >
        {t("fields.clearFilters")}
      </button>
    </div>
  );
}