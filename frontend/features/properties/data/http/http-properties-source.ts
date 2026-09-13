import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type {
  CreatePropertyInput,
  PropertyDetailDto,
  PropertyFilters,
  PropertyList,
  PropertySummaryDto,
  UpdatePropertyInput,
} from "../dto";

type PropertyListItemResponse =
  components["schemas"]["PropertyListItemResponse"];
type PropertyResponse = components["schemas"]["PropertyResponse"];

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
 * Map one full-detail API response to `PropertyDetailDto` (design D7).
 *
 * Unlike `mapPropertySummary`, this one DOES read `access_notes`,
 * `cleaning_notes` and `emergency_notes` — `PropertyResponse` (unlike
 * `PropertyListItemResponse`) carries them. It never reads a `wifi_password`
 * field: `PropertyResponse` has no such field to read (rule 5.2 of
 * `steering/security.md`), only the derived `has_wifi_password` boolean.
 */
function mapPropertyDetail(value: PropertyResponse): PropertyDetailDto {
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
    accessNotes: value.access_notes,
    cleaningNotes: value.cleaning_notes,
    emergencyNotes: value.emergency_notes,
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

  /**
   * Fetch a single property in full (proposal R2.2, design D7). A 404 from
   * the backend (other tenant, or unknown id) surfaces as an `ApiError`
   * thrown by the client.
   */
  async getProperty(
    _tenantId: string,
    id: string,
  ): Promise<PropertyDetailDto> {
    const response = await this.client.request(
      "/api/v1/properties/{property_id}",
      { pathParams: { property_id: id } },
    );
    return mapPropertyDetail(response as PropertyResponse);
  }

  /**
   * Create a property (proposal R1.2, R1.4). Only the keys `input` actually
   * sets are sent — an absent optional key lets the backend apply its own
   * default, exactly as an unset field does on `CreatePropertyRequest`.
   * Neither `pms_provider` nor `status` is ever sent (R1.2): `input`'s type
   * has no such fields to forward.
   */
  async createProperty(
    _tenantId: string,
    input: CreatePropertyInput,
  ): Promise<PropertyDetailDto> {
    const response = await this.client.request("/api/v1/properties", {
      method: "POST",
      body: {
        name: input.name,
        internal_code: input.internalCode,
        ...(input.pmsExternalId !== undefined
          ? { pms_external_id: input.pmsExternalId }
          : {}),
        ...(input.addressLine1 !== undefined
          ? { address_line1: input.addressLine1 }
          : {}),
        ...(input.addressLine2 !== undefined
          ? { address_line2: input.addressLine2 }
          : {}),
        ...(input.city !== undefined ? { city: input.city } : {}),
        ...(input.province !== undefined ? { province: input.province } : {}),
        ...(input.postalCode !== undefined
          ? { postal_code: input.postalCode }
          : {}),
        ...(input.country !== undefined ? { country: input.country } : {}),
        ...(input.timezone !== undefined ? { timezone: input.timezone } : {}),
        ...(input.maxGuests !== undefined
          ? { max_guests: input.maxGuests }
          : {}),
        ...(input.bedrooms !== undefined ? { bedrooms: input.bedrooms } : {}),
        ...(input.bathrooms !== undefined
          ? { bathrooms: input.bathrooms }
          : {}),
        ...(input.defaultCheckInTime !== undefined
          ? { default_check_in_time: input.defaultCheckInTime }
          : {}),
        ...(input.defaultCheckOutTime !== undefined
          ? { default_check_out_time: input.defaultCheckOutTime }
          : {}),
        ...(input.wifiName !== undefined ? { wifi_name: input.wifiName } : {}),
        ...(input.wifiPassword !== undefined
          ? { wifi_password: input.wifiPassword }
          : {}),
        ...(input.accessNotes !== undefined
          ? { access_notes: input.accessNotes }
          : {}),
        ...(input.cleaningNotes !== undefined
          ? { cleaning_notes: input.cleaningNotes }
          : {}),
        ...(input.emergencyNotes !== undefined
          ? { emergency_notes: input.emergencyNotes }
          : {}),
      },
    });
    return mapPropertyDetail(response as PropertyResponse);
  }

  /**
   * Update a property partially (proposal R2.2, R2.5, R2.6, design D8, D9).
   *
   * Sends only the keys present on `input`, exactly as given — the caller
   * (`EditPropertyForm`'s diffing, or the retire confirmation's
   * `{ status: "INACTIVE" }`) is responsible for deciding which fields belong
   * in the body, including `null` for an explicit clear. This method does
   * not filter or reinterpret that decision.
   */
  async updateProperty(
    _tenantId: string,
    id: string,
    input: UpdatePropertyInput,
  ): Promise<PropertyDetailDto> {
    const response = await this.client.request(
      "/api/v1/properties/{property_id}",
      {
        method: "PATCH",
        pathParams: { property_id: id },
        body: {
          ...(input.name !== undefined ? { name: input.name } : {}),
          ...(input.internalCode !== undefined
            ? { internal_code: input.internalCode }
            : {}),
          ...(input.pmsExternalId !== undefined
            ? { pms_external_id: input.pmsExternalId }
            : {}),
          ...(input.addressLine1 !== undefined
            ? { address_line1: input.addressLine1 }
            : {}),
          ...(input.addressLine2 !== undefined
            ? { address_line2: input.addressLine2 }
            : {}),
          ...(input.city !== undefined ? { city: input.city } : {}),
          ...(input.province !== undefined
            ? { province: input.province }
            : {}),
          ...(input.postalCode !== undefined
            ? { postal_code: input.postalCode }
            : {}),
          ...(input.country !== undefined ? { country: input.country } : {}),
          ...(input.timezone !== undefined
            ? { timezone: input.timezone }
            : {}),
          ...(input.maxGuests !== undefined
            ? { max_guests: input.maxGuests }
            : {}),
          ...(input.bedrooms !== undefined
            ? { bedrooms: input.bedrooms }
            : {}),
          ...(input.bathrooms !== undefined
            ? { bathrooms: input.bathrooms }
            : {}),
          ...(input.defaultCheckInTime !== undefined
            ? { default_check_in_time: input.defaultCheckInTime }
            : {}),
          ...(input.defaultCheckOutTime !== undefined
            ? { default_check_out_time: input.defaultCheckOutTime }
            : {}),
          ...(input.wifiName !== undefined
            ? { wifi_name: input.wifiName }
            : {}),
          ...(input.wifiPassword !== undefined
            ? { wifi_password: input.wifiPassword }
            : {}),
          ...(input.accessNotes !== undefined
            ? { access_notes: input.accessNotes }
            : {}),
          ...(input.cleaningNotes !== undefined
            ? { cleaning_notes: input.cleaningNotes }
            : {}),
          ...(input.emergencyNotes !== undefined
            ? { emergency_notes: input.emergencyNotes }
            : {}),
          ...(input.status !== undefined ? { status: input.status } : {}),
        },
      },
    );
    return mapPropertyDetail(response as PropertyResponse);
  }
}
