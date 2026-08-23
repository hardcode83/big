import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type { PropertyFilters, PropertyList, PropertySummaryDto } from "../dto";

type PropertyListItemResponse =
  components["schemas"]["PropertyListItemResponse"];

/**
 * Map one list-row API response to `PropertySummaryDto`.
 *
 * Only the fields `PropertyListItemResponse` actually carries. It deliberately
 * does NOT reach for `access_notes`, `cleaning_notes` or `emergency_notes` —
 * the list response does not contain them (exception 6 of rule 11 in
 * `steering/security.md`), and this feature must not fetch them per row
 * (proposal R5.1, R5.2).
 */
function mapPropertySummary(
  value: PropertyListItemResponse,
): PropertySummaryDto {
  return {
    id: value.id,
    name: value.name,
    internalCode: value.internal_code,
    pmsProvider: value.pms_provider,
    pmsExternalId: value.pms_external_id,
    addressLine1: value.address_line1,
    addressLine2: value.address_line2,
    city: value.city,
    province: value.province,
    postalCode: value.postal_code,
    country: value.country,
    timezone: value.timezone,
    maxGuests: value.max_guests,
    bedrooms: value.bedrooms,
    bathrooms: value.bathrooms,
    currentOperationalState: value.current_operational_state,
    defaultCheckInTime: value.default_check_in_time,
    defaultCheckOutTime: value.default_check_out_time,
    wifiName: value.wifi_name,
    hasWifiPassword: value.has_wifi_password,
    status: value.status,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
  };
}

/**
 * The HTTP source for the properties feature. It owns the v1 contract for the
 * list endpoint and maps the snake_case payload into the camelCase UI DTO.
 *
 * Constructed with the authenticated `ApiClient` by the composition point
 * (`features/properties/data/index.ts`, design D4). UI and hooks depend ONLY on
 * this class's methods, never on the OpenAPI types.
 *
 * There is no mock source: unlike the dashboard, whose UI shipped before its
 * backend, this feature's endpoint has been archived since 2026-08-08, so the
 * `Mock*Source` indirection would be a layer without the problem that justified
 * it (design D4).
 */
export class HttpPropertiesSource {
  constructor(private readonly client: ApiClient) {}

  /**
   * List the tenant's properties, paginated and filterable (proposal R1, R2).
   * `tenantId` is explicit at the boundary so the source stays honest about
   * tenant scoping; the backend remains the authority for tenant isolation.
   *
   * A filter that is `undefined` means "all" and is omitted from the query
   * string rather than sent empty. The wire name of the status filter is
   * `status`: the Python parameter is called `status_filter` but declares
   * `alias="status"`, so `status` is what travels.
   *
   * Only the four keys the v1 contract admits are ever emitted. There is no
   * text search, ordering or city filter to add here (R2.4).
   */
  async listProperties(
    _tenantId: string,
    filters: PropertyFilters = {},
  ): Promise<PropertyList> {
    const query = {
      ...(filters.status !== undefined ? { status: filters.status } : {}),
      ...(filters.currentOperationalState !== undefined
        ? { current_operational_state: filters.currentOperationalState }
        : {}),
      ...(filters.page !== undefined ? { page: filters.page } : {}),
      ...(filters.perPage !== undefined ? { per_page: filters.perPage } : {}),
    };
    const response = await this.client.request("/api/v1/properties", { query });
    const page = response as {
      data: PropertyListItemResponse[];
      page: number;
      per_page: number;
      total: number;
      total_pages: number;
    };
    return {
      data: page.data.map(mapPropertySummary),
      page: page.page,
      perPage: page.per_page,
      total: page.total,
      totalPages: page.total_pages,
    };
  }
}
