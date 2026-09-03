import type { components } from "@/lib/api/generated/openapi";

type TimelineEventType = components["schemas"]["TimelineEventType"];

/**
 * The closed `TimelineEventType` vocabulary, in the order the contract declares
 * it. It is the source of the type filter's options (design D5), replacing the
 * previous derivation from the returned page — which only ever saw page 1 and is
 * therefore wrong by construction once pagination exists.
 */
export const TIMELINE_EVENT_TYPES = [
  "RESERVATION_IMPORTED",
  "RESERVATION_CREATED_MANUAL",
  "RESERVATION_UPDATED",
  "RESERVATION_CANCELLED",
  "CHECKIN_WINDOW_OPENED",
  "CHECKOUT_WINDOW_REACHED",
  "PROPERTY_STATE_CHANGED",
  "ACCESS_CODE_PENDING",
  "ACCESS_CODE_CREATED_EXTERNAL",
  "ACCESS_CODE_MANUAL_ADDED",
  "ACCESS_CODE_DELIVERED",
  "GUEST_MESSAGE_RECEIVED",
  "AI_RESPONSE_SENT",
  "AI_ESCALATED_TO_HUMAN",
  "HUMAN_RESPONSE_SENT",
  "CLEANING_TASK_CREATED",
  "CLEANER_ASSIGNED",
  "CLEANER_ACCEPTED",
  "CLEANER_REJECTED",
  "CLEANING_STARTED",
  "CLEANING_PHOTO_UPLOADED",
  "CLEANING_COMPLETED",
  "CLEANING_FAILED_VALIDATION",
  "INCIDENT_CREATED",
  "INCIDENT_CLASSIFIED",
  "TECHNICIAN_ASSIGNED",
  "TECHNICIAN_ACCEPTED",
  "TECHNICIAN_REJECTED",
  "TECHNICIAN_EN_ROUTE",
  "TECHNICIAN_STARTED",
  "INCIDENT_RESOLVED",
  "INCIDENT_CANCELLED",
  "OWNER_APPROVAL_REQUIRED",
  "OWNER_APPROVED_EXPENSE",
  "OWNER_REJECTED_EXPENSE",
  "LOCK_ALERT_RECEIVED",
  "PRICE_RECOMMENDATION_CREATED",
  "PRICE_UPDATED_EXTERNAL",
  "LEGAL_REGISTRATION_SUBMITTED",
  "REVIEW_IMPORTED",
  "REVIEW_RESPONSE_DRAFTED",
  "REVIEW_RESPONSE_APPROVED",
  "REVIEW_CREATED",
  "REVIEW_DRAFT_EDITED",
  "REVIEW_CLASSIFIED_LOW_CONFIDENCE",
  "REVIEW_IGNORED",
  "REVIEW_POSTED_MANUALLY",
  "SLA_BREACH_WARNING",
  "NOTIFICATION_SENT",
  "NOTIFICATION_FAILED",
  "WEBHOOK_RECEIVED",
  "GUEST_CHECKIN_COMPLETED",
  "OWNER_STATEMENT_GENERATED",
] as const satisfies readonly TimelineEventType[];

type Missing = Exclude<TimelineEventType, (typeof TIMELINE_EVENT_TYPES)[number]>;

/**
 * Compile-time exhaustiveness guard (design D5). If a capability adds a member to
 * the backend enum, `Missing` stops being `never` and `tsc --noEmit` fails on this
 * assignment — earlier and closer to the cause than any test would.
 */
const _exhaustive: Missing extends never ? true : Missing = true;
void _exhaustive;
