/**
 * Presentational date formatting for the inbox (R4.4).
 *
 * Same shape and same reasoning as `features/dashboard/lib/format.ts` and
 * `features/pricing/lib/format.ts`: the backend sends ISO-8601 UTC, `Intl` turns it into the
 * active locale, and nothing here decides anything about the business.
 */

/**
 * An inbox row's timestamp, localized (R4.4).
 *
 * Date **and** time, not date alone: notifications from one day are the common case — a
 * cleaning assigned this morning and an incident opened this afternoon are two different
 * things to a manager, and a list where both read "29 ago 2026" tells them nothing about
 * which came first.
 */
export function formatNotificationDate(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}
