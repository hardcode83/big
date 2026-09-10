import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type {
  OwnerApprovalFilters,
  OwnerApprovalIncidentRefDto,
  OwnerApprovalListItemDto,
  OwnerApprovalPage,
  OwnerApprovalPropertyRefDto,
  RespondOwnerApprovalInput,
} from "../dto";

type OwnerApprovalListItemResponse =
  components["schemas"]["OwnerApprovalListItemResponse"];
type OwnerApprovalPageResponse =
  components["schemas"]["OwnerApprovalPageResponse"];
type OwnerApprovalIncidentRefResponse =
  components["schemas"]["OwnerApprovalIncidentRefResponse"];
type OwnerApprovalPropertyRefResponse =
  components["schemas"]["OwnerApprovalPropertyRefResponse"];

function mapIncidentRef(
  value: OwnerApprovalIncidentRefResponse,
): OwnerApprovalIncidentRefDto {
  return {
    id: value.id,
    title: value.title,
    category: value.category,
    severity: value.severity,
  };
}

function mapPropertyRef(
  value: OwnerApprovalPropertyRefResponse,
): OwnerApprovalPropertyRefDto {
  return {
    id: value.id,
    name: value.name,
    internalCode: value.internal_code,
  };
}

/** Map one list-row API response to `OwnerApprovalListItemDto` (R1.3). */
function mapOwnerApprovalListItem(
  value: OwnerApprovalListItemResponse,
): OwnerApprovalListItemDto {
  return {
    id: value.id,
    relatedType: value.related_type,
    status: value.status,
    amount: value.amount,
    currency: value.currency,
    requestedAt: value.requested_at,
    respondedAt: value.responded_at,
    incident: value.incident ? mapIncidentRef(value.incident) : null,
    property: mapPropertyRef(value.property),
  };
}

/**
 * The HTTP source for the approvals feature. It owns the v1 contract for the
 * list and respond endpoints and maps snake_case payloads into the camelCase
 * UI DTOs — same shape as `HttpIncidentsSource` (design D9/D10).
 *
 * The class is constructed with the authenticated `ApiClient` by the
 * composition point (`features/approvals/data/index.ts`). UI and hooks
 * depend ONLY on the methods of this class, not on the OpenAPI types.
 */
export class HttpApprovalsSource {
  constructor(private readonly client: ApiClient) {}

  /**
   * List the tenant's owner approvals, paginated and filterable (R1.1, R1.2).
   * `tenantId` is explicit at the boundary so the source stays honest about
   * tenant scoping; the backend is the authority for tenant isolation.
   *
   * Only the keys the v1 contract admits are emitted: `status`, `page`,
   * `per_page`. A filter that is `undefined` is omitted so the wire payload
   * matches exactly what the test asserts (mirroring
   * `HttpIncidentsSource.listIncidents`).
   */
  async listApprovals(
    _tenantId: string,
    filters: OwnerApprovalFilters = {},
  ): Promise<OwnerApprovalPage> {
    const query = {
      ...(filters.status !== undefined ? { status: filters.status } : {}),
      ...(filters.page !== undefined ? { page: filters.page } : {}),
      ...(filters.perPage !== undefined ? { per_page: filters.perPage } : {}),
    };
    const response = await this.client.request("/api/v1/owner-approvals", {
      query,
    });
    const page = response as OwnerApprovalPageResponse;
    return {
      items: page.items.map(mapOwnerApprovalListItem),
      total: page.total,
      page: page.page,
      perPage: page.per_page,
    };
  }

  /**
   * The owner answers a pending approval (R3.3). The wire body carries only
   * `status` and `response_notes` — `response_notes` sent verbatim, omitted
   * entirely when absent rather than sent as an empty string (R3.1, R3.6).
   *
   * The response is the **incident**, not the approval (the backend's own
   * contract) — this source discards it: the caller refreshes the queue by
   * invalidating the approvals list, not by reading this response body.
   */
  async respond(
    _tenantId: string,
    input: RespondOwnerApprovalInput,
  ): Promise<void> {
    await this.client.request(
      "/api/v1/owner-approvals/{approval_id}/respond",
      {
        method: "POST",
        pathParams: { approval_id: input.approvalId },
        body: {
          status: input.status,
          ...(input.responseNotes !== undefined
            ? { response_notes: input.responseNotes }
            : {}),
        },
      },
    );
  }
}
