/**
 * The two formatters this screen needs (design D14). Both are pure and take the
 * active locale explicitly, so a component passes `i18n.language` exactly as
 * `features/cleaning/components/cleaning-task-row.tsx` already does for its dates.
 */

/**
 * A decimal the contract declares as a **string**, rendered with two decimals and
 * the locale's separator — comma in ES, dot in EN (R6.1, R6.2).
 *
 * `Number(value)` happens **only to format**. No amount is ever compared or
 * arithmetic'd in the client: the backend owns the band and the guardrails, and a
 * float round-trip of a money value is exactly the corruption the string
 * representation exists to prevent. A value that does not parse finitely is
 * returned untouched rather than shown as `NaN`.
 *
 * **No currency symbol and no currency code.** No pricing response carries a
 * `currency` field, so any symbol here would be invented (R6.2).
 *
 * `locale` is a parameter and not the `undefined` of `fmtCost` in
 * `features/incidents/components/detail/incident-detail-sections.tsx` (amendment
 * to D14, agreed at the `/sdd:run` gate on 2026-08-23): `undefined` resolves to the
 * *runtime* locale, not i18next's, so a user with an English browser who picks
 * Spanish in the app would read `1,234.50` on an otherwise Spanish screen — against
 * R6.2's «separador decimal del locale activo». It also made R6.2's own test
 * unwritable, since one process has only one runtime locale.
 */
export function fmtDecimal(value: string, locale: string): string {
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return value;
  }
  return num.toLocaleString(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/**
 * A `YYYY-MM-DD` night as the locale's medium date — no time, and **no timezone
 * conversion** (R6.3).
 *
 * `timeZone: "UTC"` is the whole reason this is a decision and not a one-liner:
 * `new Date("2026-01-01")` parses as midnight **UTC**, so formatting it in the
 * browser's zone prints 31 December anywhere west of UTC. The bug is invisible
 * from Madrid, which is where it would be written.
 */
export function fmtDay(isoDay: string, locale: string): string {
  const date = new Date(isoDay);
  // Degrade the way `fmtDecimal` does instead of throwing. `Intl.format` raises
  // `RangeError: Invalid time value` on an unparseable date, and `date` reaches
  // here straight off the wire with no runtime validation — so one malformed day
  // in a page of sixty would take down every row that renders it, where the same
  // malformation in an amount merely shows as raw text.
  if (Number.isNaN(date.getTime())) {
    return isoDay;
  }
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(date);
}
