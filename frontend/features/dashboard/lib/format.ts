/**
 * Presentational formatting helpers for dashboard dates. They format the
 * backend's ISO-8601 UTC strings for display in the active locale — no business
 * logic, no timezone assumptions beyond what `Intl` provides.
 */

/** Formats an ISO-8601 timestamp as a localized date + time (short). */
export function formatDateTime(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

/** Formats an ISO-8601 timestamp as a localized date (no time). */
export function formatDate(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(
    new Date(iso),
  );
}
