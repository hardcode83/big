/**
 * The date formatter these two screens need (design D17).
 *
 * `locale` is a **parameter**, not the `undefined` of the runtime: `undefined`
 * resolves to the browser's locale rather than i18next's, so a user with an
 * English browser who picks Spanish in the app would read the wrong format on
 * an otherwise Spanish screen. It also makes the behaviour testable, since one
 * process has only one runtime locale.
 *
 * Accepts `null` / `undefined` / `""` and returns the em-dash `—` (U+2014),
 * the typographic placeholder these screens use for missing scalars (R2.6).
 * `?? ""` is forbidden by R2.6 because it concatenates unitless values; the
 * caller passes the raw value and the formatter decides.
 *
 * This is the sixth copy of this formatter in the tree. The project rule
 * ("extract at the third consumer") was met by `pricing-web` D22 extracting
 * the tone palette to `lib/ui/status-tone.ts`; the formatter was extracted for
 * real by the change that picked it up at the seventh consumer. The
 * extraction is recorded as a roadmap candidate (`shared-datetime-formatter`,
 * design D17, resolved at the `/sdd:design` gate OQ1 — a no here for scope,
 * not technique).
 */
export function formatDateTime(
  iso: string | null | undefined,
  locale: string,
): string {
  if (iso === null || iso === undefined || iso === "") {
    return "—";
  }
  const date = new Date(iso);
  // Degrade to the raw value rather than throwing: `Intl.format` raises
  // `RangeError` on an unparseable date, and `iso` arrives straight off the
  // wire with no runtime validation — one malformed value would otherwise
  // take down every row that renders it.
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}