import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type { DashboardDataSource } from "../dashboard-source";
import type {
  AccessStatus,
  CleaningPhoto,
  FinancialSummary,
  GuestDetail,
  IncidentSummary,
  NextActionSummary,
  PaginatedResponse,
  PendingApproval,
  PropertyDashboardCard,
  PropertyDetail,
  ReservationSummary,
  TimelineEntry,
  TimelineFilters,
} from "../dto";

type CardResponse = components["schemas"]["PropertyDashboardCardResponse"];
type DetailResponse = components["schemas"]["PropertyDetailResponse"];
type ReservationResponse = components["schemas"]["ReservationSummaryResponse"];
type NextActionResponse = components["schemas"]["NextActionResponse"];
type GuestResponse = components["schemas"]["GuestResponse"];
type AccessResponse = components["schemas"]["AccessResponse"];
type PhotoResponse = components["schemas"]["app__dashboard__api__schemas__CleaningPhotoResponse"];
type IncidentResponse = components["schemas"]["IncidentSummaryResponse"];
type FinancialResponse = components["schemas"]["FinancialSummaryResponse"];
type ApprovalResponse = components["schemas"]["PendingApprovalResponse"];
type TimelineResponse = components["schemas"]["TimelineEntryResponse"];
type TimelineEventType = components["schemas"]["TimelineEventType"];

function mapPage<T, U>(
  page: {
    data: T[];
    total: number;
    page: number;
    per_page: number;
    total_pages: number;
  },
  mapItem: (item: T) => U,
): PaginatedResponse<U> {
  return {
    data: page.data.map(mapItem),
    total: page.total,
    page: page.page,
    per_page: page.per_page,
    total_pages: page.total_pages,
  };
}

function mapReservation(value: ReservationResponse): ReservationSummary {
  return {
    id: value.id,
    reference: value.reference,
    guestName: value.guest_name,
    checkIn: value.check_in,
    checkOut: value.check_out,
  };
}

function mapNextAction(value: NextActionResponse): NextActionSummary {
  return { label: value.label, responsible: value.responsible };
}

function mapCard(value: CardResponse): PropertyDashboardCard {
  return {
    propertyId: value.property_id,
    propertyCode: value.property_code,
    operationalState: value.operational_state,
    currentOrNextReservation: value.current_or_next_reservation
      ? mapReservation(value.current_or_next_reservation)
      : null,
    cleaningStatus: value.cleaning_status,
    openIncidentsCount: value.open_incidents_count,
    nextAction: value.next_action ? mapNextAction(value.next_action) : null,
    lastEventLabel: value.last_event_label,
    lastEventAt: value.last_event_at,
  };
}

function mapGuest(value: GuestResponse): GuestDetail {
  return { name: value.name };
}

function mapAccess(value: AccessResponse): AccessStatus {
  return { label: value.label };
}

function mapPhoto(value: PhotoResponse): CleaningPhoto {
  return { id: value.id, url: value.url, takenAt: value.taken_at };
}

function mapIncident(value: IncidentResponse): IncidentSummary {
  return {
    id: value.id,
    title: value.title,
    severity: value.severity,
    openedAt: value.opened_at,
  };
}

function decimalToNumber(value: string | null): number | null {
  return value === null ? null : Number(value);
}

function mapFinancial(value: FinancialResponse): FinancialSummary {
  return {
    currency: value.currency,
    reservationTotal: decimalToNumber(value.reservation_total),
    pendingExpenses: decimalToNumber(value.pending_expenses),
  };
}

function mapApproval(value: ApprovalResponse): PendingApproval {
  return {
    id: value.id,
    label: value.label,
    amount: decimalToNumber(value.amount),
    currency: value.currency,
  };
}

function mapDetail(value: DetailResponse): PropertyDetail {
  return {
    propertyId: value.property_id,
    propertyCode: value.property_code,
    operationalState: value.operational_state,
    currentOrNextReservation: value.current_or_next_reservation
      ? mapReservation(value.current_or_next_reservation)
      : null,
    guest: value.guest ? mapGuest(value.guest) : null,
    access: value.access ? mapAccess(value.access) : null,
    cleaningStatus: value.cleaning_status,
    lastCleaningPhotos: value.last_cleaning_photos.map(mapPhoto),
    openIncidents: value.open_incidents.map(mapIncident),
    financial: value.financial ? mapFinancial(value.financial) : null,
    notes: value.notes,
    pendingApprovals: value.pending_approvals.map(mapApproval),
  };
}

function mapTimelineEntry(value: TimelineResponse): TimelineEntry {
  return {
    id: value.id,
    occurredAt: value.occurred_at,
    actorType: value.actor_type,
    eventType: value.event_type,
    severity: value.severity,
    title: value.title,
    description: value.description,
  };
}

export class HttpDashboardSource implements DashboardDataSource {
  constructor(private readonly client: ApiClient) {}

  async getDashboardCards(
    _tenantId: string,
  ): Promise<PaginatedResponse<PropertyDashboardCard>> {
    const response = await this.client.request("/api/v1/dashboard/properties");
    return mapPage(response, mapCard);
  }

  async getPropertyDetail(
    _tenantId: string,
    propertyId: string,
  ): Promise<PropertyDetail> {
    const response = await this.client.request(
      "/api/v1/properties/{property_id}/dashboard",
      { pathParams: { property_id: propertyId } },
    );
    return mapDetail(response);
  }

  async getPropertyTimeline(
    _tenantId: string,
    propertyId: string,
    filters: TimelineFilters = {},
  ): Promise<PaginatedResponse<TimelineEntry>> {
    const query = {
      ...(filters.eventType !== undefined
        ? { event_type: filters.eventType as TimelineEventType }
        : {}),
      ...(filters.severity !== undefined ? { severity: filters.severity } : {}),
      ...(filters.actorType !== undefined
        ? { actor_type: filters.actorType }
        : {}),
      ...(filters.from !== undefined ? { from: filters.from } : {}),
      ...(filters.to !== undefined ? { to: filters.to } : {}),
    };
    const response = await this.client.request(
      "/api/v1/timeline/{property_id}",
      {
        pathParams: { property_id: propertyId },
        query,
      },
    );
    return mapPage(response, mapTimelineEntry);
  }
}
