import { ApiError } from "@/lib/api";

/**
 * The i18n key for a failed notifications operation (R5.3).
 *
 * The rule this exists to enforce: **the server's own text never reaches the screen.** The
 * backend answers in English by convention (`steering/backend.md`), and a cleaner reading the
 * inbox in Spanish must not be shown "No such notification". So every failure resolves to a
 * key in the `notifications` catalogue, and the raw message is dropped here rather than
 * somewhere a component might decide to render it.
 *
 * The shape follows `features/incidents/lib/error-mapping.ts`, with one difference worth
 * naming: that one maps a *query* result to a UI state, and this one maps a *thrown* error
 * from a mutation, because acknowledging is a write and its failure arrives as an exception.
 *
 * `401` is not mapped to a message: the session-expiry flow owns it, and showing an error
 * about a notification while the app is redirecting to the login screen would be noise about
 * the wrong thing.
 */
export const NOTIFICATION_ERROR_KEYS = {
  notFound: "notifications:errors.notFound",
  forbidden: "notifications:errors.forbidden",
  session: "notifications:errors.session",
  generic: "notifications:errors.generic",
} as const;

export type NotificationErrorKey =
  (typeof NOTIFICATION_ERROR_KEYS)[keyof typeof NOTIFICATION_ERROR_KEYS];

export function mapNotificationsError(error: unknown): NotificationErrorKey {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return NOTIFICATION_ERROR_KEYS.session;
    }
    if (error.status === 403) {
      return NOTIFICATION_ERROR_KEYS.forbidden;
    }
    if (error.status === 404) {
      return NOTIFICATION_ERROR_KEYS.notFound;
    }
  }
  return NOTIFICATION_ERROR_KEYS.generic;
}
