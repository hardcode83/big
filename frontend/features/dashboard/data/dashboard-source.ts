import type {
  PaginatedResponse,
  PropertyDashboardCard,
  PropertyDetail,
  TimelineEntry,
  TimelineFilters,
} from "./dto";

/**
 * The dashboard's data-access boundary. UI and hooks depend ONLY on this
 * interface, never on a concrete implementation. Today the single implementation
 * is `MockDashboardSource` (fixed data); when dashboard-web (backend) ships it is
 * replaced by an HTTP implementation routed through `lib/api`, without changing
 * the UI, the hooks, or this contract (proposal R3).
 *
 * `tenantId` is explicit at the boundary so tenant-scoped query keys and the
 * future HTTP implementation stay honest; it is provided from a dev constant
 * today (ASSUMPTION) and from the session context once auth-tenancy exists.
 *
 * Methods reject with `ApiError` (lib/api) on failure — including a §23
 * not-found envelope when a property id is unknown.
 */
export interface DashboardDataSource {
  /** Property cards for `/dashboard` (PRD §9.1). */
  getDashboardCards(
    tenantId: string,
  ): Promise<PaginatedResponse<PropertyDashboardCard>>;

  /** Full detail for one property (PRD §9.2). */
  getPropertyDetail(
    tenantId: string,
    propertyId: string,
  ): Promise<PropertyDetail>;

  /** Immutable, filterable timeline for one property (PRD §10). */
  getPropertyTimeline(
    tenantId: string,
    propertyId: string,
    filters?: TimelineFilters,
  ): Promise<PaginatedResponse<TimelineEntry>>;
}
