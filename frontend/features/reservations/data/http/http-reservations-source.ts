import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type {
  GuestAccessTokenStatusDto,
  GuestSummaryDto,
  ReservationDetailDto,
  ReservationFilters,
  ReservationList,
  ReservationSummaryDto,
} from "../dto";

type ReservationResponse = components["schemas"]["ReservationResponse"];
type ReservationDetailResponse = components["schemas"]["ReservationDetailResponse"];
type GuestSummaryResponse = components["schemas"]["GuestSummaryResponse"];
type GuestAccessTokenStatusResponse =
  components["schemas"]["GuestAccessTokenStatusResponse"];
type GuestAccessTokenIssuedResponse =
  components["schemas"]["GuestAccessTokenIssuedResponse"];
type GuestAccessTokenSentResponse =
  components["schemas"]["GuestAccessTokenSentResponse"];

/** Map `GuestSummaryResponse` (snake_case, no PII) to the UI DTO (camelCase). */
function mapGuestSummary(value: GuestSummaryResponse): GuestSummaryDto {
  return {
    id: value.id,
    fullName: value.full_name,
    email: value.email,
    phone: value.phone,
    preferredLanguage: value.preferred_language,
    documentStatus: value.document_status,
    legalRegistrationStatus: value.legal_registration_status,
  };
}

/** Map one list-row API response to `ReservationSummaryDto`. */
function mapReservationSummary(value: ReservationResponse): ReservationSummaryDto {
  return {
    id: value.id,
    propertyId: value.property_id,
    status: value.status,
    checkInDate: value.check_in_date,
    checkOutDate: value.check_out_date,
    nights: value.nights,
    totalGuests: value.total_guests,
    guestId: value.guest_id,
    channel: value.channel,
    currency: value.currency,
    grossAmount: value.gross_amount,
    paymentStatus: value.payment_status,
    propertyName: value.property_name ?? null,
    propertyInternalCode: value.property_internal_code ?? null,
    guestFullName: value.guest_full_name ?? null,
  };
}

/** Map the detail endpoint response to `ReservationDetailDto`. */
function mapReservationDetail(
  value: ReservationDetailResponse,
): ReservationDetailDto {
  return {
    ...mapReservationSummary(value),
    checkInTime: value.check_in_time,
    checkOutTime: value.check_out_time,
    adults: value.adults,
    children: value.children,
    otaCommission: value.ota_commission,
    netAmount: value.net_amount,
    cleaningRequired: value.cleaning_required,
    accessStatus: value.access_status,
    externalChannelId: value.external_channel_id,
    externalPmsId: value.external_pms_id,
    internalNotes: value.internal_notes,
    specialRequests: value.special_requests,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
    guest: value.guest ? mapGuestSummary(value.guest) : null,
  };
}

/**
 * The HTTP source for the reservations feature. It owns the v1 contract for
 * the list and the detail endpoints and maps snake_case payloads into the
 * camelCase UI DTOs.
 *
 * The class is constructed with the authenticated `ApiClient` by the
 * composition point (`features/reservations/data/index.ts`). UI and hooks
 * depend ONLY on the methods of this class, not on the OpenAPI types.
 */
export class HttpReservationsSource {
  constructor(private readonly client: ApiClient) {}

  /**
   * List the tenant's reservations, paginated and filterable (proposal R2).
   * `tenantId` is explicit at the boundary so the source stays honest about
   * tenant scoping; the backend is the authority for tenant isolation.
   *
   * Only the keys admitted by the v1 contract are emitted; `property_id` is
   * NOT in v1 and is never added here (design D4). A filter that is
   * `undefined` is omitted so the wire payload matches what the test asserts
   * exactly.
   */
  async listReservations(
    _tenantId: string,
    filters: ReservationFilters = {},
  ): Promise<ReservationList> {
    const query = {
      ...(filters.status !== undefined ? { status: filters.status } : {}),
      ...(filters.dateFrom !== undefined ? { date_from: filters.dateFrom } : {}),
      ...(filters.dateTo !== undefined ? { date_to: filters.dateTo } : {}),
      ...(filters.page !== undefined ? { page: filters.page } : {}),
      ...(filters.perPage !== undefined ? { per_page: filters.perPage } : {}),
    };
    const response = await this.client.request("/api/v1/reservations", {
      query,
    });
    const page = response as {
      data: ReservationResponse[];
      page: number;
      per_page: number;
      total: number;
      total_pages: number;
    };
    return {
      data: page.data.map(mapReservationSummary),
      page: page.page,
      perPage: page.per_page,
      total: page.total,
      totalPages: page.total_pages,
    };
  }

  /**
   * Fetch a single reservation with its linked guest block (proposal R3).
   * A 404 from the backend (other tenant, or unknown id) surfaces as an
   * `ApiError` thrown by the client; the UI distinguishes the variant in
   * `useReservationsError` (section 7).
   */
  async getReservation(
    _tenantId: string,
    reservationId: string,
  ): Promise<ReservationDetailDto> {
    const response = await this.client.request(
      "/api/v1/reservations/{reservation_id}",
      { pathParams: { reservation_id: reservationId } },
    );
    return mapReservationDetail(response as ReservationDetailResponse);
  }

  /**
   * Read whether the stay currently has a live guest portal token, and since
   * when (proposal R1.1, R2). Never returns the token or its digest — only
   * presence and issuance instant, mirroring the backend response one-to-one.
   */
  async getGuestAccessTokenStatus(
    _tenantId: string,
    reservationId: string,
  ): Promise<GuestAccessTokenStatusDto> {
    const response = await this.client.request(
      "/api/v1/reservations/{reservation_id}/guest-access-token",
      { pathParams: { reservation_id: reservationId } },
    );
    const status = response as GuestAccessTokenStatusResponse;
    return { isLive: status.is_live, issuedAt: status.issued_at };
  }

  /**
   * Mint a fresh portal token for the stay (proposal R1.2). Replaces any live
   * token, same as the backend's own issuance contract. Returns the cleartext
   * value exactly once — the caller (`useIssueGuestAccessToken`) is
   * responsible for never persisting it beyond the one-time reveal.
   */
  async issueGuestAccessToken(
    _tenantId: string,
    reservationId: string,
  ): Promise<string> {
    const response = await this.client.request(
      "/api/v1/reservations/{reservation_id}/guest-access-token",
      { method: "POST", pathParams: { reservation_id: reservationId } },
    );
    return (response as GuestAccessTokenIssuedResponse).token;
  }

  /** Revoke the stay's live portal token, if any (proposal R1.3). Idempotent. */
  async revokeGuestAccessToken(
    _tenantId: string,
    reservationId: string,
  ): Promise<void> {
    await this.client.request(
      "/api/v1/reservations/{reservation_id}/guest-access-token",
      { method: "DELETE", pathParams: { reservation_id: reservationId } },
    );
  }

  /**
   * Mint a fresh token and email the portal link to the guest (proposal R3).
   * Returns `delivered` — the adapter's acceptance, never the cleartext token
   * (design D5): "copy it yourself" and "email it to the guest" stay two
   * distinct operator actions.
   */
  async sendGuestAccessTokenEmail(
    _tenantId: string,
    reservationId: string,
  ): Promise<boolean> {
    const response = await this.client.request(
      "/api/v1/reservations/{reservation_id}/guest-access-token/send",
      { method: "POST", pathParams: { reservation_id: reservationId } },
    );
    return (response as GuestAccessTokenSentResponse).delivered;
  }
}
