import type {
  PaginatedResponse,
  PropertyDashboardCard,
  PropertyDetail,
  TimelineEntry,
  TimelineFilters,
} from "./dto";

/**
 * The dashboard's data-access boundary. UI and hooks depend ONLY on this
 * interface, never on a concrete implementation. The runtime implementation is
 * `HttpDashboardSource`, routed through `lib/api`, without changing the UI, the
 * hooks, or this contract (proposal R3). `MockDashboardSource` remains available
 * only for tests and local reference fixtures.
 *
 * `tenantId` is explicit at the boundary so tenant-scoped query keys and the
 * HTTP implementation stays honest; it is provided from the session context.
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
