/**
 * The two formatters this screen needs (design D18).
 *
 * `fmtRating` mirrors `fmtDecimal` from `features/pricing/lib/format.ts:28`
 * but with **one** decimal (the `rating` from the contract is 1.0..5.0, not
 * money), and the `/5` suffix lives in the localized label, not in the
 * formatted number — same discipline as pricing's `max_daily_change_pct`.
 *
 * Both formatters take the active locale explicitly, so a component passes
 * `i18n.language` exactly as `features/cleaning/components/cleaning-task-row.tsx`
 * already does for its dates.
 */

/**
 * A decimal the contract declares as a **string**, rendered with one decimal and
 * the locale's separator — comma in ES, dot in EN (R8.3).
 *
 * `Number(value)` happens **only to format**. No rating is ever compared or
 * arithmetic'd in the client — a float round-trip is exactly the corruption the
 * string representation exists to prevent. A value that does not parse finitely
 * is returned untouched rather than shown as `NaN`.
 *
 * The `/5` is **not** in this function — it travels with the localized label
 * (R8.3) so a screen can write "Rating" or "Puntuación" followed by `4.5/5`
 * without rewriting the formatter.
 *
 * `locale` is a parameter and not `undefined`: `undefined` resolves to the
 * *runtime* locale, not i18next's, so a user with an English browser who picks
 * Spanish in the app would read `4.5` on an otherwise Spanish screen.
 */
export function fmtRating(value: string, locale: string): string {
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return value;
  }
  return num.toLocaleString(locale, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

/**
 * A `YYYY-MM-DD` date as the locale's medium date — no time, and **no timezone
 * conversion** (R8.4).
 *
 * `timeZone: "UTC"` is the whole reason this is a decision and not a one-liner:
 * `new Date("2026-01-01")` parses as midnight **UTC**, so formatting it in the
 * browser's zone prints 31 December anywhere west of UTC. The bug is invisible
 * from Madrid.
 *
 * An unparseable date is returned as the raw input — `Intl.format` raises
 * `RangeError: Invalid time value` on garbage, and one malformed row in a page
 * of sixty would take down every row that renders it.
 */
export function fmtDay(isoDay: string, locale: string): string {
  const date = new Date(isoDay);
  if (Number.isNaN(date.getTime())) {
    return isoDay;
  }
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(date);
}