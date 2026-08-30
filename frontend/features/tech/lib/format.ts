/**
 * The typographic placeholder for a nullable scalar rendered inline in a
 * populated row (R2.4).
 *
 * It lives here as a literal rather than in `locales/{es,en}/tech.json`
 * because `frontend-foundation.md` is explicit about it: "The em-dash is a
 * literal character in JSX, never a new i18n key (it is not language text and
 * is the same glyph in `es` and `en`)". The sibling features render the same
 * glyph inline; naming it once keeps the two screens from drifting apart
 * without turning it back into translatable text.
 */
export const EMPTY_FIELD = "\u2014";

/**
 * The date formatter these two screens need (design D17).
 *
 * `locale` is a **parameter**, not the `undefined` of the runtime: `undefined`
 * resolves to the browser's locale rather than i18next's, so a user with an
 * English browser who picks Spanish in the app would read the wrong format on
 * an otherwise Spanish screen. It also makes the behaviour testable, since one
 * process has only one runtime locale.
 *
 * This is the fifth copy of this formatter in the tree. Extracting it to
 * `lib/format/` would touch four features this change declares out of scope, so
 * it is noted as a roadmap candidate (`shared-datetime-formatter`) instead —
 * design D17, resolved at the `/sdd:design` gate (OQ2).
 */
export function formatDateTime(iso: string, locale: string): string {
  const date = new Date(iso);
  // Degrade to the raw value rather than throwing: `Intl.format` raises
  // `RangeError` on an unparseable date, and `iso` arrives straight off the
  // wire with no runtime validation — one malformed value would otherwise take
  // down every row that renders it.
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
