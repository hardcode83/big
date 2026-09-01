import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type {
  IncidentContextDto,
  IncidentDetailDto,
  IncidentFilters,
  IncidentList,
  IncidentPhotoDto,
  IncidentPhotoStage,
  IncidentSummaryDto,
  CloseIncidentInput,
} from "../dto";

type IncidentResponse = components["schemas"]["IncidentResponse"];
type IncidentPageResponse = components["schemas"]["IncidentPageResponse"];
type IncidentContextResponse = components["schemas"]["IncidentContextResponse"];
type IncidentPhotoResponse = components["schemas"]["IncidentPhotoResponse"];
type IncidentPhotoListResponse = components["schemas"]["IncidentPhotoListResponse"];

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
    etaAt: value.eta_at,
    estimatedCost: value.estimated_cost,
    approvedCost: value.approved_cost,
    finalCost: value.final_cost,
    materials: value.materials,
    resolvedAt: value.resolved_at,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
  };
}

/** Map the context projection to `IncidentContextDto` (R2.3). */
function mapIncidentContext(value: IncidentContextResponse): IncidentContextDto {
  return {
    propertyName: value.property_name,
    propertyInternalCode: value.property_internal_code,
    addressLine1: value.address_line1,
    addressLine2: value.address_line2,
    city: value.city,
    province: value.province,
    postalCode: value.postal_code,
    country: value.country,
    timezone: value.timezone,
    accessNotes: value.access_notes,
    assignmentNote: value.assignment_note,
  };
}

/**
 * Map one photo to `IncidentPhotoDto` (R5.1). `url` is copied verbatim and
 * there is no `storage_key` to copy: the response does not carry one (R5.2).
 */
function mapIncidentPhoto(value: IncidentPhotoResponse): IncidentPhotoDto {
  return {
    id: value.id,
    incidentId: value.incident_id,
    stage: value.stage,
    uploadedBy: value.uploaded_by,
    createdAt: value.created_at,
    url: value.url,
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

  /**
   * The property context of one incident (proposal R2.3). No parameter
   * identifies the technician: the backend derives the scoping from the token.
   */
  async getIncidentContext(
    _tenantId: string,
    incidentId: string,
  ): Promise<IncidentContextDto> {
    const response = await this.client.request(
      "/api/v1/incidents/{incident_id}/context",
      { pathParams: { incident_id: incidentId } },
    );
    return mapIncidentContext(response as IncidentContextResponse);
  }

  /**
   * List the photos of one incident (proposal R5.1). The backend serves them
   * oldest first; the order is not rearranged here.
   */
  async listPhotos(
    _tenantId: string,
    incidentId: string,
  ): Promise<IncidentPhotoDto[]> {
    const response = await this.client.request(
      "/api/v1/incidents/{incident_id}/photos",
      { pathParams: { incident_id: incidentId } },
    );
    return (response as IncidentPhotoListResponse).items.map(mapIncidentPhoto);
  }

  /**
   * The technician accepts the job, optionally announcing an ETA (R3.3).
   * With no ETA the body is omitted **entirely**: the router takes
   * `IncidentEtaRequest | None = None`, so a POST with no body is valid, and an
   * empty object would be a different thing to say.
   */
  async accept(
    _tenantId: string,
    incidentId: string,
    etaAt?: string,
  ): Promise<IncidentDetailDto> {
    const response = await this.client.request(
      "/api/v1/incidents/{incident_id}/accept",
      {
        method: "POST",
        pathParams: { incident_id: incidentId },
        ...(etaAt !== undefined ? { body: { eta_at: etaAt } } : {}),
      },
    );
    return mapIncidentDetail(response as IncidentResponse);
  }

  /** The technician is on the way, optionally with an ETA (R3.3). */
  async enRoute(
    _tenantId: string,
    incidentId: string,
    etaAt?: string,
  ): Promise<IncidentDetailDto> {
    const response = await this.client.request(
      "/api/v1/incidents/{incident_id}/en-route",
      {
        method: "POST",
        pathParams: { incident_id: incidentId },
        ...(etaAt !== undefined ? { body: { eta_at: etaAt } } : {}),
      },
    );
    return mapIncidentDetail(response as IncidentResponse);
  }

  /**
   * The technician refuses the job (R3.5). After a 200 the incident goes back
   * to `CLASSIFIED` with its assignment cleared, so `GET /incidents/{id}`
   * answers 404 to whoever refused.
   */
  async reject(
    _tenantId: string,
    incidentId: string,
  ): Promise<IncidentDetailDto> {
    const response = await this.client.request(
      "/api/v1/incidents/{incident_id}/reject",
      { method: "POST", pathParams: { incident_id: incidentId } },
    );
    return mapIncidentDetail(response as IncidentResponse);
  }

  /** The job is paused waiting for a part (R3.1). Takes no body. */
  async waitParts(
    _tenantId: string,
    incidentId: string,
  ): Promise<IncidentDetailDto> {
    const response = await this.client.request(
      "/api/v1/incidents/{incident_id}/wait-parts",
      { method: "POST", pathParams: { incident_id: incidentId } },
    );
    return mapIncidentDetail(response as IncidentResponse);
  }

  /** The part arrived and the job resumes (R3.1). Takes no body. */
  async resume(
    _tenantId: string,
    incidentId: string,
  ): Promise<IncidentDetailDto> {
    const response = await this.client.request(
      "/api/v1/incidents/{incident_id}/resume",
      { method: "POST", pathParams: { incident_id: incidentId } },
    );
    return mapIncidentDetail(response as IncidentResponse);
  }

  /**
   * Close the incident with its real cost (R4.1).
   *
   * `final_cost` travels as a **string** — the contract admits it with a
   * two-decimal pattern — because a float round-trip of a money value is the
   * corruption its string representation exists to prevent (D12). `materials`
   * empty is **omitted**: the schema strips whitespace with `min_length=1`, so
   * sending `""` is a 422; "no materials" is said by leaving the field out.
   */
  async resolve(
    _tenantId: string,
    incidentId: string,
    input: CloseIncidentInput,
  ): Promise<IncidentDetailDto> {
    const materials = input.materials?.trim();
    const response = await this.client.request(
      "/api/v1/incidents/{incident_id}/resolve",
      {
        method: "POST",
        pathParams: { incident_id: incidentId },
        body: {
          final_cost: input.finalCost,
          ...(materials ? { materials } : {}),
        },
      },
    );
    return mapIncidentDetail(response as IncidentResponse);
  }

  /**
   * Upload one photo (R5.3), over the `formData` path of the shared client
   * (D2) so the browser writes the multipart `Content-Type` with its boundary
   * while the session header, the one-shot 401 retry and the error mapping are
   * all preserved.
   */
  async uploadPhoto(
    _tenantId: string,
    incidentId: string,
    file: File,
    stage: IncidentPhotoStage,
  ): Promise<IncidentPhotoDto> {
    const formData = new FormData();
    formData.append("stage", stage);
    formData.append("file", file);
    const response = await this.client.request(
      "/api/v1/incidents/{incident_id}/photos",
      {
        method: "POST",
        pathParams: { incident_id: incidentId },
        formData,
      },
    );
    return mapIncidentPhoto(response as IncidentPhotoResponse);
  }

  /**
   * Resolves one incident from the dashboard card (proposal
   * `blocked-transitions-web` R2.3, R3.1). The wire body is `{ final_cost }`,
   * matching `openapi.d.ts:6383`; `materials` is omitted on purpose from the
   * dashboard's call site (D7) — it is the manager's, but on `/incidents/{id}`,
   * not here.
   *
   * Distinct from `resolve` above, which is the technician's close and carries
   * `materials` (tech-app R4.1). The two call sites send different bodies, so
   * the base-sync of `tech-app` kept both rather than folding one into the
   * other: collapsing them would have silently changed what one of the two
   * screens sends.
   */
  async resolveIncident(
    _tenantId: string,
    incidentId: string,
    finalCost: number | string,
  ): Promise<IncidentDetailDto> {
    const response = await this.client.request(
      "/api/v1/incidents/{incident_id}/resolve",
      {
        method: "POST",
        pathParams: { incident_id: incidentId },
        body: { final_cost: finalCost },
      },
    );
    return mapIncidentDetail(response as IncidentResponse);
  }
}