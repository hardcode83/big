/**
 * Presentational formatting for the inbox (design D8, D9). `Intl` only — this
 * change adds no date library.
 *
 * Every function returns `null` for a `null` input instead of an empty string or
 * an invented value, so the caller substitutes localized copy (R1.3: never an
 * invented date; R3.4: never `null` or `NaN` where a figure would go).
 */

const DIVISIONS = [
  { amount: 60, unit: "second" },
  { amount: 60, unit: "minute" },
  { amount: 24, unit: "hour" },
  { amount: 7, unit: "day" },
  { amount: 4.34524, unit: "week" },
  { amount: 12, unit: "month" },
  { amount: Number.POSITIVE_INFINITY, unit: "year" },
] as const satisfies readonly {
  amount: number;
  unit: Intl.RelativeTimeFormatUnit;
}[];

/**
 * One place decides whether a timestamp is usable, so all three functions answer
 * `null` the same way. `Intl.RelativeTimeFormat.format(NaN)` throws a
 * `RangeError`, which would take down the whole panel rather than degrade a cell.
 */
function parseInstant(iso: string | null): number | null {
  if (iso === null) {
    return null;
  }
  const time = new Date(iso).getTime();
  return Number.isFinite(time) ? time : null;
}

/**
 * Localized age of an ISO-8601 instant, in the coarsest unit that applies.
 * Depends on the clock, so suites that assert it fix the time.
 */
export function formatAge(iso: string | null, locale: string): string | null {
  const instant = parseInstant(iso);
  if (instant === null) {
    return null;
  }
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  let duration = (instant - Date.now()) / 1000;
  for (const division of DIVISIONS) {
    if (Math.abs(duration) < division.amount) {
      return formatter.format(Math.round(duration), division.unit);
    }
    duration /= division.amount;
  }
  return formatter.format(Math.round(duration), "year");
}

/** Localized absolute date + time — the `title` behind a relative age (D9). */
export function formatDateTime(iso: string | null, locale: string): string | null {
  const instant = parseInstant(iso);
  if (instant === null) {
    return null;
  }
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(instant);
}

/**
 * `confidence_score` as a whole percentage. The decimal string is converted here
 * and nowhere earlier: D8 keeps the DTO unrounded so this is the only rounding.
 */
export function formatConfidence(
  value: string | null,
  locale: string,
): string | null {
  if (value === null) {
    return null;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return new Intl.NumberFormat(locale, {
    style: "percent",
    maximumFractionDigits: 0,
  }).format(parsed);
}
