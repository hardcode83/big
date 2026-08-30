/**
 * Presentational formatting helpers for dashboard dates. They format the
 * backend's ISO-8601 UTC strings for display in the active locale — no business
 * logic, no timezone assumptions beyond what `Intl` provides.
 */

/**
 * Parses a backend timestamp, or returns `null` when it is not one.
 *
 * `Intl.DateTimeFormat.format` throws `RangeError: Invalid time value` on an
 * invalid `Date`, and `new Date(null)` silently yields the Unix epoch — so a
 * single malformed `due_since` (deploy skew, a partial migration, a backend
 * bug) would either unmount the row that renders it or print «1 ene 1970».
 * Neither is acceptable inside a card whose whole job is to be trusted at a
 * glance, so both cases collapse to `null` and the caller decides what to
 * paint instead.
 */
function parseTimestamp(iso: string): Date | null {
  if (typeof iso !== "string" || iso.trim() === "") {
    return null;
  }
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/**
 * Formats an ISO-8601 timestamp as a localized date + time (short).
 *
 * Returns the input verbatim when it is not a parseable timestamp: showing the
 * raw value tells an operator something is wrong with the data, where an empty
 * string would look like a field the backend simply did not send.
 */
export function formatDateTime(iso: string, locale: string): string {
  const parsed = parseTimestamp(iso);
  if (!parsed) {
    return typeof iso === "string" ? iso : "";
  }
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

/** Formats an ISO-8601 timestamp as a localized date (no time). */
export function formatDate(iso: string, locale: string): string {
  const parsed = parseTimestamp(iso);
  if (!parsed) {
    return typeof iso === "string" ? iso : "";
  }
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(
    parsed,
  );
}
