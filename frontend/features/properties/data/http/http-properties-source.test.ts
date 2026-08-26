import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api";

import { HttpPropertiesSource } from "./http-properties-source";

function sourceWith(response: unknown): {
  source: HttpPropertiesSource;
  request: ReturnType<typeof vi.fn>;
} {
  const request = vi.fn().mockResolvedValue(response);
  const client = { request } as unknown as ApiClient;
  return { source: new HttpPropertiesSource(client), request };
}

const TENANT = "tenant-1";

/** A complete `PropertyListItemResponse`, every field the contract declares. */
const ROW = {
  id: "property-1",
  name: "Redes 11",
  internal_code: "REDES11",
  pms_provider: "BEDS24",
  pms_external_id: "ext-1",
  address_line1: "Calle Redes 11",
  address_line2: null,
  city: "Madrid",
  province: "Madrid",
  postal_code: "28000",
  country: "ES",
  timezone: "Europe/Madrid",
  max_guests: 4,
  bedrooms: 2,
  bathrooms: 1,
  current_operational_state: "VACANT_READY",
  default_check_in_time: "16:00:00",
  default_check_out_time: "11:00:00",
  wifi_name: "REDES11-WIFI",
  has_wifi_password: true,
  status: "ACTIVE",
  created_at: "2026-08-01T09:00:00Z",
  updated_at: "2026-08-02T09:00:00Z",
} as const;

function pageOf(rows: readonly unknown[], overrides: object = {}) {
  return {
    data: rows,
    page: 1,
    per_page: 20,
    total: rows.length,
    total_pages: 1,
    ...overrides,
  };
}

describe("HttpPropertiesSource — listProperties (R1)", () => {
  it("maps the §23 page envelope from snake_case to camelCase", async () => {
    const { source } = sourceWith(pageOf([ROW]));

    await expect(source.listProperties(TENANT)).resolves.toEqual({
      data: [
        {
          id: "property-1",
          name: "Redes 11",
          internalCode: "REDES11",
          pmsProvider: "BEDS24",
          pmsExternalId: "ext-1",
          addressLine1: "Calle Redes 11",
          addressLine2: null,
          city: "Madrid",
          province: "Madrid",
          postalCode: "28000",
          country: "ES",
          timezone: "Europe/Madrid",
          maxGuests: 4,
          bedrooms: 2,
          bathrooms: 1,
          currentOperationalState: "VACANT_READY",
          defaultCheckInTime: "16:00:00",
          defaultCheckOutTime: "11:00:00",
          wifiName: "REDES11-WIFI",
          hasWifiPassword: true,
          status: "ACTIVE",
          createdAt: "2026-08-01T09:00:00Z",
          updatedAt: "2026-08-02T09:00:00Z",
        },
      ],
      page: 1,
      perPage: 20,
      total: 1,
      totalPages: 1,
    });
  });

  it("reads pagination from the flat envelope, not from a nested meta object (R1.4)", async () => {
    // The mistake this pins: assuming another module's `{data, meta: {...}}`
    // shape. `PropertyPageResponse` is flat, like reservations'.
    const { source } = sourceWith(
      pageOf([ROW], { page: 3, per_page: 5, total: 42, total_pages: 9 }),
    );

    const result = await source.listProperties(TENANT, { page: 3, perPage: 5 });

    expect(result.page).toBe(3);
    expect(result.perPage).toBe(5);
    expect(result.total).toBe(42);
    expect(result.totalPages).toBe(9);
  });

  it("renders the nullable half of the contract without inventing values", async () => {
    // `city`, `province`, `postalCode`, both address lines, `wifiName`,
    // `pmsProvider` and `pmsExternalId` are all nullable in the contract.
    const { source } = sourceWith(
      pageOf([
        {
          ...ROW,
          pms_provider: null,
          pms_external_id: null,
          address_line1: null,
          address_line2: null,
          city: null,
          province: null,
          postal_code: null,
          wifi_name: null,
          has_wifi_password: false,
        },
      ]),
    );

    const [row] = (await source.listProperties(TENANT)).data;

    expect(row.city).toBeNull();
    expect(row.province).toBeNull();
    expect(row.postalCode).toBeNull();
    expect(row.addressLine1).toBeNull();
    expect(row.wifiName).toBeNull();
    expect(row.pmsProvider).toBeNull();
    expect(row.pmsExternalId).toBeNull();
    expect(row.hasWifiPassword).toBe(false);
  });

  it("never carries the three free-text sinks or a WiFi password (R5.1, R5.3)", async () => {
    // Even if a future backend regression put them back in the list payload,
    // the mapper must not surface them: exception 6 of rule 11 removed them
    // from this endpoint on purpose, and the DTO is the boundary that holds.
    const { source } = sourceWith(
      pageOf([
        {
          ...ROW,
          access_notes: "código de la caja fuerte: 1234",
          cleaning_notes: "ojo con la lavadora",
          emergency_notes: "llamar al 600000000",
          wifi_password: "supersecret",
        },
      ]),
    );

    const [row] = (await source.listProperties(TENANT)).data;

    expect(row).not.toHaveProperty("accessNotes");
    expect(row).not.toHaveProperty("access_notes");
    expect(row).not.toHaveProperty("cleaningNotes");
    expect(row).not.toHaveProperty("emergencyNotes");
    expect(row).not.toHaveProperty("wifiPassword");
    expect(JSON.stringify(row)).not.toContain("supersecret");
    expect(JSON.stringify(row)).not.toContain("caja fuerte");
  });
});

describe("HttpPropertiesSource — query string (R2)", () => {
  it("omits both filters when neither is set", async () => {
    const { source, request } = sourceWith(pageOf([]));

    await source.listProperties(TENANT);

    expect(request).toHaveBeenCalledWith("/api/v1/properties", { query: {} });
  });

  it("sends the status filter under the wire name `status`", async () => {
    // The Python parameter is `status_filter` with `alias="status"`, so
    // `status` is what travels. Sending `status_filter` would be silently
    // ignored by the backend.
    const { source, request } = sourceWith(pageOf([]));

    await source.listProperties(TENANT, { status: "INACTIVE" });

    expect(request).toHaveBeenCalledWith("/api/v1/properties", {
      query: { status: "INACTIVE" },
    });
  });

  it("sends only the operational-state filter when that is the only one set", async () => {
    const { source, request } = sourceWith(pageOf([]));

    await source.listProperties(TENANT, {
      currentOperationalState: "AWAITING_CLEANING",
    });

    expect(request).toHaveBeenCalledWith("/api/v1/properties", {
      query: { current_operational_state: "AWAITING_CLEANING" },
    });
  });

  it("combines both filters with pagination", async () => {
    const { source, request } = sourceWith(pageOf([]));

    await source.listProperties(TENANT, {
      status: "ACTIVE",
      currentOperationalState: "CRITICAL_INCIDENT",
      page: 2,
      perPage: 50,
    });

    expect(request).toHaveBeenCalledWith("/api/v1/properties", {
      query: {
        status: "ACTIVE",
        current_operational_state: "CRITICAL_INCIDENT",
        page: 2,
        per_page: 50,
      },
    });
  });

  it("never emits a key the v1 contract does not accept (R2.4)", async () => {
    const { source, request } = sourceWith(pageOf([]));

    await source.listProperties(TENANT, {
      status: "ACTIVE",
      currentOperationalState: "VACANT_READY",
      page: 1,
      perPage: 20,
    });

    const [, options] = request.mock.calls[0] as [string, { query: object }];
    // There is no text search, no selectable ordering and no city filter.
    expect(Object.keys(options.query).sort()).toEqual([
      "current_operational_state",
      "page",
      "per_page",
      "status",
    ]);
  });

  it("calls the list endpoint and never the per-row detail endpoints (R5.2)", async () => {
    const { source, request } = sourceWith(pageOf([ROW, { ...ROW, id: "p2" }]));

    await source.listProperties(TENANT);

    expect(request).toHaveBeenCalledTimes(1);
    const paths = request.mock.calls.map((call) => call[0] as string);
    expect(paths).toEqual(["/api/v1/properties"]);
    expect(paths.some((path) => path.includes("{property_id}"))).toBe(false);
  });
});
