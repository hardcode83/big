/**
 * Localized formatters shared by every `features/statements` component
 * (task 6.2).
 *
 * These four helpers replace the four `TODO(section 6.2)` copies that were
 * sitting in `statement-row.tsx`/`statement-summary.tsx`/
 * `reservations-breakdown.tsx`/`expenses-breakdown.tsx`. The discipline mirrors
 * `features/pricing/lib/format.ts` and `features/reviews/lib/format.ts`:
 *
 * - `Number(value)` happens **only to format**. No amount is ever compared or
 *   arithmeticked in the client — the backend owns the band and the
 *   guardrails, and a float round-trip of a money value is exactly the
 *   corruption the string representation exists to prevent (R3.5, R3.6).
 * - `locale` is a parameter, not the runtime default: a user with an English
 *   browser who picks Spanish in the app must read the ES separator
 *   everywhere, not the runtime's.
 * - `timeZone: "UTC"` is the whole reason `fmtDay` is not a one-liner: a bare
 *   `Intl.format` on a `YYYY-MM-DD` prints 31 December anywhere west of UTC,
 *   and the bug is invisible from Madrid.
 * - An unparseable value degrades to the raw input rather than throwing — a
 *   single malformed row must not take down a whole page of sixty.
 * - **No cross-currency conversion, no global currency invention.** Each
 *   `currency`-bearing row gets `fmtCurrency`; the summary's currency-less
 *   fields get `fmtAmount`; a `null` amount gets `absentAmount` (R3.5).
 */

import esStatements from "@/locales/es/statements.json";
import enStatements from "@/locales/en/statements.json";

type Catalog = typeof esStatements;
type CatalogPath = string[];

/**
 * Walks a JSON catalog the same way i18next does for a dotted key.
 * `key` is namespaced (`"statements:detail.absent.value"`); the part before
 * the colon is the namespace and the rest is the path inside the table.
 *
 * Kept local to this module rather than reaching for the active i18next
 * instance because `absentAmount` is intentionally callable from any code
 * path — including tests and non-component modules — without a `<Provider>`
 * in scope. The catalog content is the source of truth (the parity test in
 * `lib/i18n/catalog-parity.test.ts` keeps ES and EN identical), so reading
 * it directly here is equivalent to going through i18next for the marker.
 */
function resolveCatalogPath(table: Catalog, path: CatalogPath): unknown {
  let acc: unknown = table;
  for (const segment of path) {
    if (acc === null || typeof acc !== "object") return undefined;
    acc = (acc as Record<string, unknown>)[segment];
  }
  return acc;
}

const ABSENT_KEY = "statements:detail.absent.value";
const ABSENT_NS = "statements";
const ABSENT_PATH = ABSENT_KEY.slice(ABSENT_NS.length + 1).split(".");

/**
 * A `YYYY-MM-DD` day as the locale's medium date, UTC-anchored so the day
 * never shifts with the browser's timezone (R5.4). Identical contract to
 * `features/pricing/lib/format.ts:fmtDay` and
 * `features/reviews/lib/format.ts:fmtDay`.
 *
 * An unparseable value degrades to the raw input rather than throwing —
 * `Intl.format` raises `RangeError: Invalid time value` on garbage, and one
 * malformed day in a page of sixty would otherwise take down every row that
 * renders it.
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

/**
 * A contract decimal string rendered with the locale's separator and two
 * decimals. **No currency symbol, no currency code.** `OwnerStatementResponse`
 * publishes no `currency` field on its summary (R3.6), so inventing one here
 * would be a fabrication the backend never asserted.
 *
 * A value that does not parse finitely is returned untouched rather than
 * shown as `NaN` (R5.4 — never render backend text, never show `NaN`).
 */
export function fmtAmount(value: string, locale: string): string {
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
 * A row's own decimal amount formatted with **its own** `currency` (R3.6):
 * each reservation/expense row may carry a different currency, so the
 * summary's currency-less `fmtAmount` would be wrong here.
 * `Intl.NumberFormat`'s `style: "currency"` both localizes the decimals and
 * paints the right symbol/code for that row — no cross-row aggregation and
 * no conversion happen anywhere.
 *
 * A currency code `Intl` cannot resolve (never expected from this API, but
 * the contract is open and we do not validate server-side codes here) falls
 * back to a plain decimal + the raw code rather than throwing, so one
 * pathological row never takes down the page.
 */
export function fmtCurrency(value: string, currency: string, locale: string): string {
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return value;
  }
  try {
    return new Intl.NumberFormat(locale, { style: "currency", currency }).format(num);
  } catch {
    return `${num.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
  }
}

/**
 * The localized "absent value" marker used wherever the contract declares a
 * nullable amount (R3.5). This is **never** `0` and **never** a computed
 * substitute — `null` from the wire stays `null` in the UI; we just render it
 * through the ES/EN catalogs (`statements:detail.absent.value`, currently the
 * literal "—") so the absence glyph itself is not hardcoded in JSX.
 *
 * Reads the active catalog directly (see `resolveCatalogPath` rationale) so
 * callers do not need a React provider in scope.
 */
export function absentAmount(locale: string): string {
  const table = locale === "en" ? enStatements : esStatements;
  const value = resolveCatalogPath(table, ABSENT_PATH);
  return typeof value === "string" ? value : "—";
}
