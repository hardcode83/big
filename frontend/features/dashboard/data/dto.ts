/**
 * DTOs for the owner/manager dashboard presentation layer.
 *
 * They replicate the real API contract (PRD §23): list payloads use the §23
 * pagination envelope; errors travel as the §23 error envelope, which `lib/api`
 * turns into a thrown `ApiError`, so these DTOs model success shapes only. Dates
 * are ISO-8601 UTC strings. Types only — no business logic, no runtime code.
 *
 * DEBT (dashboard-web): these shapes are the contract that `MockDashboardSource`
 * satisfies today and `HttpDashboardSource` must satisfy tomorrow, against
 * GET /api/v1/properties, /properties/{id}, /properties/{id}/dashboard and
 * /timeline/{property_id}. Keep them aligned with the real endpoints; the mock is
 * replaced without changing this file.
 */

/** ISO-8601 timestamp with UTC timezone (PRD §23 date convention). */
export type IsoDateTime = string;

/** Pagination envelope — PRD §23: `{ data, total, page, per_page, total_pages }`. */
export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

/**
 * A human-readable string already localized by the backend in the authenticated
 * user's language (PRD §10 timeline, §9.1 next-action). It is dynamic *data*, not
 * static UI chrome — the frontend localizes chrome via react-i18next, and does
 * not translate these values.
 */
export type LocalizedText = string;

/**
 * Canonical `PropertyOperationalState` values (PRD §3.1 / §7). Exact literals,
 * never translated. Color mapping lives in the feature (§9.1), not here.
 */
export type PropertyOperationalState =
  | "VACANT_READY"
  | "READY_FOR_NEXT_GUEST"
  | "AWAITING_CHECKIN"
  | "OCCUPIED_ESTIMATED"
  | "CLEANING_IN_PROGRESS"
  | "AWAITING_CLEANING"
  | "CLEANING_SCHEDULED"
  | "MAINTENANCE_REQUIRED"
  | "CRITICAL_INCIDENT"
  | "BLOCKED_BY_OWNER"
  | "OUT_OF_SERVICE";

/** `TimelineEvent.actor_type` (PRD §7.8). */
export type TimelineActorType =
  | "SYSTEM"
  | "USER"
  | "GUEST"
  | "SCHEDULER"
  | "WEBHOOK"
  | "AI";

/** `TimelineEvent.severity` (PRD §7.8). */
export type TimelineSeverity = "INFO" | "WARNING" | "ERROR" | "CRITICAL";

/** `Incident.severity` (PRD §7). */
export type IncidentSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

/** Current or next reservation shown on a card / detail (PRD §9.1-9.2). */
export interface ReservationSummary {
  id: string;
  /** Channel + external reference, e.g. "Booking.com #1234". */
  reference: string | null;
  guestName: string | null;
  checkIn: IsoDateTime;
  checkOut: IsoDateTime;
}

/** Next required action and who is responsible for it (PRD §9.1). */
export interface NextActionSummary {
  label: LocalizedText;
  responsible: string | null;
}

/** One property card on `/dashboard` (PRD §9.1). */
export interface PropertyDashboardCard {
  propertyId: string;
  propertyCode: string;
  operationalState: PropertyOperationalState;
  currentOrNextReservation: ReservationSummary | null;
  /** Cleaning state label; mirrors `CleaningTask.status` (domain-foundation-ops). */
  cleaningStatus: LocalizedText | null;
  openIncidentsCount: number;
  nextAction: NextActionSummary | null;
  lastEventLabel: LocalizedText | null;
  lastEventAt: IsoDateTime | null;
}

/** One immutable timeline entry (PRD §7.8, §10). */
export interface TimelineEntry {
  id: string;
  occurredAt: IsoDateTime;
  actorType: TimelineActorType;
  /** `TimelineEventType` (PRD §7.8); kept as string to stay open to new types. */
  eventType: string;
  severity: TimelineSeverity;
  title: LocalizedText;
  description: LocalizedText | null;
}

/** Timeline filters (PRD §10: type, severity, actor, date range). */
export interface TimelineFilters {
  eventType?: string;
  severity?: TimelineSeverity;
  actorType?: TimelineActorType;
  from?: IsoDateTime;
  to?: IsoDateTime;
}

/** Guest data on the detail page — masked/PII-free (security.md rules 3-4). */
export interface GuestDetail {
  name: string | null;
}

/** Access state label — never the code itself (security.md rules 3-4). */
export interface AccessStatus {
  label: LocalizedText | null;
}

/** Last-cleaning photo — URL is a backend signed URL, never built client-side. */
export interface CleaningPhoto {
  id: string;
  /** Signed URL provided by the backend (security.md rule 5, frontend.md). */
  url: string;
  takenAt: IsoDateTime;
}

/** Open incident shown on the detail page (PRD §9.2). */
export interface IncidentSummary {
  id: string;
  title: LocalizedText;
  severity: IncidentSeverity;
  openedAt: IsoDateTime;
}

/** Financial summary block on the detail page (PRD §9.2). */
export interface FinancialSummary {
  currency: string;
  reservationTotal: number | null;
  pendingExpenses: number | null;
}

/** A pending owner approval (PRD §9.2, §26.4 approvals). */
export interface PendingApproval {
  id: string;
  label: LocalizedText;
  amount: number | null;
  currency: string | null;
}

/** Full property detail composed on `/properties/[id]` (PRD §9.2). */
export interface PropertyDetail {
  propertyId: string;
  propertyCode: string;
  operationalState: PropertyOperationalState;
  currentOrNextReservation: ReservationSummary | null;
  guest: GuestDetail | null;
  access: AccessStatus | null;
  cleaningStatus: LocalizedText | null;
  lastCleaningPhotos: CleaningPhoto[];
  openIncidents: IncidentSummary[];
  financial: FinancialSummary | null;
  notes: LocalizedText | null;
  pendingApprovals: PendingApproval[];
}
