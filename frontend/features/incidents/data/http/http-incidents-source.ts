import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type {
  IncidentDetailDto,
  IncidentFilters,
  IncidentList,
  IncidentSummaryDto,
} from "../dto";

type IncidentResponse = components["schemas"]["IncidentResponse"];
type IncidentPageResponse = components["schemas"]["IncidentPageResponse"];

/** Map one list-row API response to `IncidentSummaryDto` (D3, D5). */
function mapIncidentSummary(value: IncidentResponse): IncidentSummaryDto {
  return {
    id: value.id,
    status: value.status,
    severity: value.severity,
    category: value.category,
    source: value.source,
    title: value.title,
    createdAt: value.created_at,
  };
}

/** Map the detail endpoint response to `IncidentDetailDto` (all 18 fields). */
function mapIncidentDetail(value: IncidentResponse): IncidentDetailDto {
  return {
    id: value.id,
    propertyId: value.property_id,
    reservationId: value.reservation_id,
    source: value.source,
    category: value.category,
    severity: value.severity,
    status: value.status,
    title: value.title,
    description: value.description,
    aiSummary: value.ai_summary,
    assignedTechnicianId: value.assigned_technician_id,
    ownerApprovalRequired: value.owner_approval_required,
    estimatedCost: value.estimated_cost,
    approvedCost: value.approved_cost,
    finalCost: value.final_cost,
    resolvedAt: value.resolved_at,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
  };
}

/**
 * The HTTP source for the incidents feature. It owns the v1 contract for
 * the list and the detail endpoints and maps snake_case payloads into the
 * camelCase UI DTOs (D3).
 *
 * The class is constructed with the authenticated `ApiClient` by the
 * composition point (`features/incidents/data/index.ts`). UI and hooks
 * depend ONLY on the methods of this class, not on the OpenAPI types.
 */
export class HttpIncidentsSource {
  constructor(private readonly client: ApiClient) {}

  /**
   * List the tenant's incidents, paginated and filterable (proposal R2).
   * `tenantId` is explicit at the boundary so the source stays honest about
   * tenant scoping; the backend is the authority for tenant isolation.
   *
   * Only the keys admitted by the v1 contract are emitted (D4):
   * `status`, `severity`, `page`, `per_page`. `property_id` is NOT in v1 and
   * never appears here — design D4 (the precedent of `reservations-web` D4).
   * A filter that is `undefined` is omitted so the wire payload matches
   * exactly what the test asserts.
   */
  async listIncidents(
    _tenantId: string,
    filters: IncidentFilters = {},
  ): Promise<IncidentList> {
    const query = {
      ...(filters.status !== undefined ? { status: filters.status } : {}),
      ...(filters.severity !== undefined ? { severity: filters.severity } : {}),
      ...(filters.page !== undefined ? { page: filters.page } : {}),
      ...(filters.perPage !== undefined ? { per_page: filters.perPage } : {}),
    };
    const response = await this.client.request("/api/v1/incidents", {
      query,
    });
    const page = response as IncidentPageResponse;
    return {
      items: page.items.map(mapIncidentSummary),
      total: page.total,
      page: page.page,
      perPage: page.per_page,
    };
  }

  /**
   * Fetch a single incident (proposal R3). A 404 from the backend (other
   * tenant, or unknown id) surfaces as an `ApiError` thrown by the client;
   * the UI distinguishes the variant in `useIncidentError`.
   */
  async getIncident(
    _tenantId: string,
    incidentId: string,
  ): Promise<IncidentDetailDto> {
    const response = await this.client.request(
      "/api/v1/incidents/{incident_id}",
      { pathParams: { incident_id: incidentId } },
    );
    return mapIncidentDetail(response as IncidentResponse);
  }
}