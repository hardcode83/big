import { describe, expect, it, vi } from "vitest";

import { ApiError, type ApiClient } from "@/lib/api";

import type { CreateReservationInput, UpdateReservationInput } from "../dto";
import { HttpReservationsSource } from "./http-reservations-source";

function sourceWith(response: unknown): {
  source: HttpReservationsSource;
  request: ReturnType<typeof vi.fn>;
} {
  const request = vi.fn().mockResolvedValue(response);
  const client = { request } as unknown as ApiClient;
  return { source: new HttpReservationsSource(client), request };
}

const TENANT = "tenant-1";

describe("HttpReservationsSource — listReservations", () => {
  it("maps the §23 page envelope from snake_case to camelCase and preserves its keys", async () => {
    const { source, request } = sourceWith({
      data: [
        {
          id: "reservation-1",
          property_id: "property-1",
          status: "PENDING",
          check_in_date: "2026-08-12",
          check_out_date: "2026-08-15",
          check_in_time: null,
          check_out_time: null,
          nights: 3,
          total_guests: 2,
          guest_id: null,
          channel: "BOOKING",
          currency: "EUR",
          gross_amount: "612.50",
          ota_commission: null,
          net_amount: null,
          payment_status: "PENDING",
          cleaning_required: false,
          access_status: "PENDING",
          external_channel_id: null,
          external_pms_id: null,
          internal_notes: null,
          special_requests: null,
          legal_registration_status: "PENDING",
          created_at: "2026-08-01T09:00:00Z",
          updated_at: "2026-08-01T09:00:00Z",
          property_name: "Hotel Sol",
          property_internal_code: "HS-01",
          guest_full_name: "Laura Gómez",
        },
      ],
      page: 1,
      per_page: 20,
      total: 1,
      total_pages: 1,
    });

    await expect(source.listReservations(TENANT)).resolves.toEqual({
      data: [
        {
          id: "reservation-1",
          propertyId: "property-1",
          status: "PENDING",
          checkInDate: "2026-08-12",
          checkOutDate: "2026-08-15",
          nights: 3,
          totalGuests: 2,
          guestId: null,
          channel: "BOOKING",
          currency: "EUR",
          grossAmount: "612.50",
          paymentStatus: "PENDING",
          propertyName: "Hotel Sol",
          propertyInternalCode: "HS-01",
          guestFullName: "Laura Gómez",
        },
      ],
      page: 1,
      perPage: 20,
      total: 1,
      totalPages: 1,
    });
    expect(request).toHaveBeenCalledWith("/api/v1/reservations", { query: {} });
  });

  it("maps property_name/property_internal_code/guest_full_name to null when null or absent from the row (R1.3)", async () => {
    const { source } = sourceWith({
      data: [
        {
          id: "reservation-2",
          property_id: "property-1",
          status: "PENDING",
          check_in_date: "2026-08-12",
          check_out_date: "2026-08-15",
          check_in_time: null,
          check_out_time: null,
          nights: 3,
          total_guests: 2,
          guest_id: null,
          channel: "BOOKING",
          currency: "EUR",
          gross_amount: "612.50",
          ota_commission: null,
          net_amount: null,
          payment_status: "PENDING",
          cleaning_required: false,
          access_status: "PENDING",
          external_channel_id: null,
          external_pms_id: null,
          internal_notes: null,
          special_requests: null,
          legal_registration_status: "PENDING",
          created_at: "2026-08-01T09:00:00Z",
          updated_at: "2026-08-01T09:00:00Z",
          property_name: null,
          // property_internal_code and guest_full_name absent entirely.
        },
      ],
      page: 1,
      per_page: 20,
      total: 1,
      total_pages: 1,
    });

    const result = await source.listReservations(TENANT);
    expect(result.data[0]?.propertyName).toBeNull();
    expect(result.data[0]?.propertyInternalCode).toBeNull();
    expect(result.data[0]?.guestFullName).toBeNull();
  });

  it("serializes v1 filters exactly and never adds property_id (D4)", async () => {
    const { source, request } = sourceWith({
      data: [],
      page: 2,
      per_page: 20,
      total: 0,
      total_pages: 0,
    });

    await source.listReservations(TENANT, {
      status: "PENDING",
      dateFrom: "2026-08-01",
      page: 2,
    });

    // Object equality — no objectContaining, no toMatchObject — so any extra key
    // (including `property_id`) makes the test fail in red.
    expect(request).toHaveBeenCalledWith("/api/v1/reservations", {
      query: { status: "PENDING", date_from: "2026-08-01", page: 2 },
    });
    // Redundant, explicit assertion of the v1 invariant: `property_id` is NOT
    // sent in v1 (design D4). The equality check above already catches it, but
    // the next line names the invariant for the next reader.
    expect(request.mock.calls[0][1].query).not.toHaveProperty("property_id");
  });

  it("emits only the provided dateTo key and nothing else", async () => {
    const { source, request } = sourceWith({
      data: [],
      page: 1,
      per_page: 20,
      total: 0,
      total_pages: 0,
    });

    await source.listReservations(TENANT, { dateTo: "2026-08-31" });

    expect(request).toHaveBeenCalledWith("/api/v1/reservations", {
      query: { date_to: "2026-08-31" },
    });
  });
});

describe("HttpReservationsSource — getReservation", () => {
  it("maps the detail response with a non-null guest block", async () => {
    const { source, request } = sourceWith({
      id: "reservation-1",
      property_id: "property-1",
      status: "CONFIRMED",
      check_in_date: "2026-08-12",
      check_out_date: "2026-08-15",
      check_in_time: "15:00",
      check_out_time: "11:00",
      nights: 3,
      total_guests: 2,
      guest_id: "guest-1",
      channel: "DIRECT",
      currency: "EUR",
      gross_amount: "612.50",
      ota_commission: null,
      net_amount: "612.50",
      payment_status: "PAID",
      cleaning_required: true,
      access_status: "DELIVERED",
      external_channel_id: null,
      external_pms_id: null,
      internal_notes: "Allergic to feathers",
      special_requests: "Late check-in",
      legal_registration_status: "REGISTERED",
      created_at: "2026-08-01T09:00:00Z",
      updated_at: "2026-08-10T09:00:00Z",
      adults: 2,
      children: 0,
      property_name: "Hotel Sol",
      property_internal_code: "HS-01",
      guest_full_name: "Laura Gómez",
      guest: {
        id: "guest-1",
        full_name: "Laura Gómez",
        email: "laura@example.com",
        phone: "+34 600 000 000",
        preferred_language: "es",
        document_status: "VERIFIED",
        legal_registration_status: "REGISTERED",
      },
    });

    await expect(
      source.getReservation(TENANT, "reservation-1"),
    ).resolves.toEqual({
      id: "reservation-1",
      propertyId: "property-1",
      status: "CONFIRMED",
      checkInDate: "2026-08-12",
      checkOutDate: "2026-08-15",
      nights: 3,
      totalGuests: 2,
      guestId: "guest-1",
      channel: "DIRECT",
      currency: "EUR",
      grossAmount: "612.50",
      paymentStatus: "PAID",
      propertyName: "Hotel Sol",
      propertyInternalCode: "HS-01",
      guestFullName: "Laura Gómez",
      checkInTime: "15:00",
      checkOutTime: "11:00",
      adults: 2,
      children: 0,
      otaCommission: null,
      netAmount: "612.50",
      cleaningRequired: true,
      accessStatus: "DELIVERED",
      externalChannelId: null,
      externalPmsId: null,
      internalNotes: "Allergic to feathers",
      specialRequests: "Late check-in",
      createdAt: "2026-08-01T09:00:00Z",
      updatedAt: "2026-08-10T09:00:00Z",
      guest: {
        id: "guest-1",
        fullName: "Laura Gómez",
        email: "laura@example.com",
        phone: "+34 600 000 000",
        preferredLanguage: "es",
        documentStatus: "VERIFIED",
        legalRegistrationStatus: "REGISTERED",
      },
    });
    expect(request).toHaveBeenCalledWith(
      "/api/v1/reservations/{reservation_id}",
      { pathParams: { reservation_id: "reservation-1" } },
    );
  });

  it("maps the detail response with guest: null", async () => {
    const { source } = sourceWith({
      id: "reservation-2",
      property_id: "property-1",
      status: "PENDING",
      check_in_date: "2026-08-12",
      check_out_date: "2026-08-15",
      check_in_time: null,
      check_out_time: null,
      nights: 3,
      total_guests: 2,
      guest_id: null,
      channel: "MANUAL",
      currency: "EUR",
      gross_amount: null,
      ota_commission: null,
      net_amount: null,
      payment_status: "PENDING",
      cleaning_required: false,
      access_status: "PENDING",
      external_channel_id: null,
      external_pms_id: null,
      internal_notes: null,
      special_requests: null,
      legal_registration_status: "PENDING",
      created_at: "2026-08-01T09:00:00Z",
      updated_at: "2026-08-01T09:00:00Z",
      adults: 0,
      children: 0,
      property_name: null,
      // property_internal_code and guest_full_name absent entirely.
      guest: null,
    });

    await expect(
      source.getReservation(TENANT, "reservation-2"),
    ).resolves.toMatchObject({
      guest: null,
      propertyName: null,
      propertyInternalCode: null,
      guestFullName: null,
    });
  });
});

describe("HttpReservationsSource — reservation mutations (R1, R2, R3, D4)", () => {
  const response = {
    id: "reservation-created",
    property_id: "property-1",
    status: "PENDING",
    check_in_date: "2026-09-12",
    check_out_date: "2026-09-15",
    nights: 3,
    total_guests: 2,
    guest_id: "guest-resolved",
    channel: "MANUAL",
    currency: "EUR",
    gross_amount: null,
    payment_status: "PENDING",
    property_name: "Hotel Sol",
    property_internal_code: "HS-01",
    guest_full_name: "Laura Gómez",
  };

  it("posts the generated create shape, omits blank optionals, and never creates guest_id", async () => {
    const { source, request } = sourceWith(response);
    const input: CreateReservationInput = {
      property_id: "property-1",
      check_in_date: "2026-09-12",
      check_out_date: "2026-09-15",
      channel: "MANUAL",
      check_in_time: "",
      check_out_time: undefined,
      internal_notes: "",
      guest: { full_name: "Laura Gómez", email: "laura@example.com" },
    };

    await expect(source.createReservation(TENANT, input)).resolves.toMatchObject({
      id: "reservation-created",
      guestId: "guest-resolved",
    });
    expect(request).toHaveBeenCalledWith("/api/v1/reservations", {
      method: "POST",
      body: {
        property_id: "property-1",
        check_in_date: "2026-09-12",
        check_out_date: "2026-09-15",
        channel: "MANUAL",
        guest: { full_name: "Laura Gómez", email: "laura@example.com" },
      },
    });
    expect(request.mock.calls[0][1].body).not.toHaveProperty("guest_id");
  });

  it("patches the exact reservation path and preserves explicit nullable values", async () => {
    const { source, request } = sourceWith(response);
    const input: UpdateReservationInput = {
      check_out_date: "2026-09-16",
      internal_notes: null,
      special_requests: "",
    };

    await source.updateReservation(TENANT, "reservation-1", input);
    expect(request).toHaveBeenCalledWith(
      "/api/v1/reservations/{reservation_id}",
      {
        method: "PATCH",
        pathParams: { reservation_id: "reservation-1" },
        body: { check_out_date: "2026-09-16", internal_notes: null },
      },
    );
    expect(request.mock.calls[0][1].body).not.toHaveProperty("guest_id");
  });

  it("maps backend recalculation of nights and total guests after PATCH", async () => {
    const { source, request } = sourceWith({ ...response, nights: 4, total_guests: 5 });

    await expect(source.updateReservation(TENANT, "reservation-1", {
      check_out_date: "2026-09-16",
      adults: 4,
      children: 1,
    })).resolves.toMatchObject({ nights: 4, totalGuests: 5 });
    expect(request).toHaveBeenCalledWith(
      "/api/v1/reservations/{reservation_id}",
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("allowlists runtime mutation keys and nested guest fields", async () => {
    const { source, request } = sourceWith(response);
    await source.createReservation(TENANT, {
      property_id: "property-1",
      check_in_date: "2026-09-15",
      check_out_date: "2026-09-16",
      guest: {
        full_name: "Guest",
        email: "guest@example.com",
        // Runtime callers can bypass TypeScript; these keys must not cross the boundary.
        guest_id: "forbidden",
        document_number: "123",
      },
      guest_id: "forbidden",
      unexpected: "forbidden",
    } as never);

    expect(request.mock.calls[0][1].body).toEqual({
      property_id: "property-1",
      check_in_date: "2026-09-15",
      check_out_date: "2026-09-16",
      guest: { full_name: "Guest", email: "guest@example.com" },
    });
  });

  it("omits blank guest fields and null values disallowed by OpenAPI", async () => {
    const { source, request } = sourceWith(response);
    await source.createReservation(TENANT, {
      property_id: "property-1",
      check_in_date: "2026-09-15",
      check_out_date: "2026-09-16",
      guest: {
        full_name: "Guest",
        email: "",
        phone: "",
        preferred_language: null,
      },
    } as never);

    expect(request.mock.calls[0][1].body).toMatchObject({
      guest: { full_name: "Guest" },
    });
    expect(request.mock.calls[0][1].body.guest).not.toHaveProperty("email");
    expect(request.mock.calls[0][1].body.guest).not.toHaveProperty("phone");
  });

  it("omits a guest block that has no accepted values", async () => {
    const { source, request } = sourceWith(response);
    await source.createReservation(TENANT, {
      property_id: "property-1",
      check_in_date: "2026-09-15",
      check_out_date: "2026-09-16",
      guest: { email: "", document_number: "123" },
    } as never);

    expect(request.mock.calls[0][1].body).not.toHaveProperty("guest");
  });

  it("deletes the exact reservation path without a body and resolves void", async () => {
    const { source, request } = sourceWith(undefined);

    await expect(
      source.cancelReservation(TENANT, "reservation-1"),
    ).resolves.toBeUndefined();
    expect(request).toHaveBeenCalledWith(
      "/api/v1/reservations/{reservation_id}",
      { method: "DELETE", pathParams: { reservation_id: "reservation-1" } },
    );
    expect(request.mock.calls[0][1]).not.toHaveProperty("body");
  });
});

describe("HttpReservationsSource — guest access token (R1, R2, R3, D7)", () => {
  it("maps the live status response to camelCase", async () => {
    const { source, request } = sourceWith({
      is_live: true,
      issued_at: "2026-09-01T09:00:00Z",
    });

    await expect(
      source.getGuestAccessTokenStatus(TENANT, "reservation-1"),
    ).resolves.toEqual({ isLive: true, issuedAt: "2026-09-01T09:00:00Z" });
    expect(request).toHaveBeenCalledWith(
      "/api/v1/reservations/{reservation_id}/guest-access-token",
      { pathParams: { reservation_id: "reservation-1" } },
    );
  });

  it("maps the no-token status response with issuedAt null", async () => {
    const { source } = sourceWith({ is_live: false, issued_at: null });

    await expect(
      source.getGuestAccessTokenStatus(TENANT, "reservation-1"),
    ).resolves.toEqual({ isLive: false, issuedAt: null });
  });

  it("issues a fresh token and returns the cleartext value once", async () => {
    const { source, request } = sourceWith({ token: "clear-token-abc" });

    await expect(
      source.issueGuestAccessToken(TENANT, "reservation-1"),
    ).resolves.toBe("clear-token-abc");
    expect(request).toHaveBeenCalledWith(
      "/api/v1/reservations/{reservation_id}/guest-access-token",
      { method: "POST", pathParams: { reservation_id: "reservation-1" } },
    );
  });

  it("revokes the live token with a DELETE and resolves with no value", async () => {
    const { source, request } = sourceWith(undefined);

    await expect(
      source.revokeGuestAccessToken(TENANT, "reservation-1"),
    ).resolves.toBeUndefined();
    expect(request).toHaveBeenCalledWith(
      "/api/v1/reservations/{reservation_id}/guest-access-token",
      { method: "DELETE", pathParams: { reservation_id: "reservation-1" } },
    );
  });

  it("sends the guest link email and surfaces delivered: true", async () => {
    const { source, request } = sourceWith({ delivered: true });

    await expect(
      source.sendGuestAccessTokenEmail(TENANT, "reservation-1"),
    ).resolves.toBe(true);
    expect(request).toHaveBeenCalledWith(
      "/api/v1/reservations/{reservation_id}/guest-access-token/send",
      { method: "POST", pathParams: { reservation_id: "reservation-1" } },
    );
  });

  it("surfaces delivered: false distinctly from a thrown error (R3.5)", async () => {
    const { source } = sourceWith({ delivered: false });

    await expect(
      source.sendGuestAccessTokenEmail(TENANT, "reservation-1"),
    ).resolves.toBe(false);
  });
});

describe("HttpReservationsSource — error propagation", () => {
  it.each([
    [401, "UNAUTHORIZED"],
    [403, "FORBIDDEN"],
    [404, "NOT_FOUND"],
    [422, "VALIDATION_ERROR"],
    [500, "INTERNAL_SERVER_ERROR"],
  ] as const)(
    "propagates ApiError status %s without wrapping or retrying",
    async (status, code) => {
      const error = new ApiError({ code, message: `API error ${status}`, status });
      const request = vi.fn().mockRejectedValue(error);
      const source = new HttpReservationsSource({
        request,
      } as unknown as ApiClient);

      await expect(source.getReservation(TENANT, "x")).rejects.toBe(error);
      expect(request).toHaveBeenCalledTimes(1);
    },
  );
});
