import type { NotificationType } from "../data";

/**
 * Type → i18n key for every member of `NotificationType` (R4.1, design D7/D14).
 *
 * **The `Record<NotificationType, string>` annotation is the whole mechanism**, not a
 * formality. `NotificationType` is `components["schemas"]["NotificationType"]`, generated from
 * `backend/openapi.json`, so it is the seventeen names the backend actually knows. A `Record`
 * over a closed union must be exhaustive, which means a type without an entry here fails
 * `npm run typecheck` — a CI gate — instead of reaching a cleaner's screen as a raw
 * identifier. That is what makes R4.1's "los diecisiete, incluidos los nueve que hoy no
 * escribe nadie" enforceable rather than a promise about reviewer attention, and it is why the
 * type comes from the contract instead of being listed by hand: `notification-writers-gap`
 * will add writers for those nine, and if it ever touches the enum this file breaks loudly.
 */
export const NOTIFICATION_COPY_KEYS: Record<NotificationType, string> = {
  CLEANING_TASK_ASSIGNED: "notifications:types.CLEANING_TASK_ASSIGNED",
  CLEANING_NO_RESPONSE: "notifications:types.CLEANING_NO_RESPONSE",
  CLEANING_COMPLETED: "notifications:types.CLEANING_COMPLETED",
  CLEANING_FAILED: "notifications:types.CLEANING_FAILED",
  INCIDENT_CREATED_CRITICAL: "notifications:types.INCIDENT_CREATED_CRITICAL",
  INCIDENT_CREATED_HIGH: "notifications:types.INCIDENT_CREATED_HIGH",
  OWNER_APPROVAL_REQUIRED: "notifications:types.OWNER_APPROVAL_REQUIRED",
  TECHNICIAN_ASSIGNED: "notifications:types.TECHNICIAN_ASSIGNED",
  TECHNICIAN_NO_RESPONSE: "notifications:types.TECHNICIAN_NO_RESPONSE",
  GUEST_ESCALATION: "notifications:types.GUEST_ESCALATION",
  LOCK_ALERT: "notifications:types.LOCK_ALERT",
  CHECKIN_REMINDER_24H: "notifications:types.CHECKIN_REMINDER_24H",
  CHECKIN_REMINDER_2H: "notifications:types.CHECKIN_REMINDER_2H",
  CHECKOUT_REMINDER: "notifications:types.CHECKOUT_REMINDER",
  PRICE_RECOMMENDATION: "notifications:types.PRICE_RECOMMENDATION",
  SLA_BREACH: "notifications:types.SLA_BREACH",
  PASSWORD_RESET_REQUESTED: "notifications:types.PASSWORD_RESET_REQUESTED",
  REVIEW_RESPONSE_APPROVED: "notifications:types.REVIEW_RESPONSE_APPROVED",
};

/** The translated generic of R4.3, for a value the interface does not know. */
export const UNKNOWN_NOTIFICATION_COPY_KEY = "notifications:types.unknown";

/**
 * The i18n key for one row's text (R4.1, R4.3).
 *
 * The cast is deliberate and its safety is the `??`: the column is a free `String(100)` that
 * admits values written before the enum existed, which is why the contract publishes
 * `NotificationType | string` and why the DTO types this field as `string`. An unknown value
 * falls to the translated generic rather than being painted raw or breaking the list.
 */
export function notificationCopyKey(type: string): string {
  // `Object.hasOwn` rather than `??`: nullish coalescing only catches `null`/`undefined`, and a
  // plain object literal answers for its prototype — `NOTIFICATION_COPY_KEYS["constructor"]`
  // returns the `Object` FUNCTION, which is neither, so `??` lets it through and the row's
  // primary text becomes `function Object() { [native code] }`. That is the raw-identifier
  // outcome R4.3 forbids, arriving through the one door the closed-union `Record` cannot
  // close: the column is free text and the cast is what admits it. Found by the section 7-9
  // security panel.
  if (!Object.hasOwn(NOTIFICATION_COPY_KEYS, type)) {
    return UNKNOWN_NOTIFICATION_COPY_KEY;
  }
  const key = NOTIFICATION_COPY_KEYS[type as NotificationType];
  return typeof key === "string" ? key : UNKNOWN_NOTIFICATION_COPY_KEY;
}
