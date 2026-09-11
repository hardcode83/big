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

/** A complete `PropertyResponse`, every field the full-detail contract declares. */
const DETAIL_RESPONSE = {
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
  access_notes: "código de la caja fuerte: 1234",
  cleaning_notes: "ojo con la lavadora",
  emergency_notes: "llamar al 600000000",
  status: "ACTIVE",
  created_at: "2026-08-01T09:00:00Z",
  updated_at: "2026-08-02T09:00:00Z",
} as const;

describe("HttpPropertiesSource — getProperty (R1.2, R2.2, design D7)", () => {
  it("calls GET /api/v1/properties/{property_id} with the id as a path param", async () => {
    const { source, request } = sourceWith(DETAIL_RESPONSE);

    await source.getProperty(TENANT, "property-1");

    expect(request).toHaveBeenCalledWith("/api/v1/properties/{property_id}", {
      pathParams: { property_id: "property-1" },
    });
  });

  it("maps the full response to PropertyDetailDto, including the three notes", async () => {
    const { source } = sourceWith(DETAIL_RESPONSE);

    const detail = await source.getProperty(TENANT, "property-1");

    expect(detail).toEqual({
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
      accessNotes: "código de la caja fuerte: 1234",
      cleaningNotes: "ojo con la lavadora",
      emergencyNotes: "llamar al 600000000",
      status: "ACTIVE",
      createdAt: "2026-08-01T09:00:00Z",
      updatedAt: "2026-08-02T09:00:00Z",
    });
  });

  it("never reads a wifi_password field from the response (rule 5.2)", async () => {
    // `PropertyResponse` has no such field, but if a future backend
    // regression ever put one on the wire, this mapping must not surface it.
    const { source } = sourceWith({ ...DETAIL_RESPONSE, wifi_password: "supersecret" });

    const detail = await source.getProperty(TENANT, "property-1");

    expect(detail).not.toHaveProperty("wifiPassword");
    expect(JSON.stringify(detail)).not.toContain("supersecret");
  });
});

describe("HttpPropertiesSource — createProperty (R1.2, R1.4)", () => {
  it("POSTs the required fields only when nothing else is given", async () => {
    const { source, request } = sourceWith(DETAIL_RESPONSE);

    await source.createProperty(TENANT, {
      name: "Redes 11",
      internalCode: "REDES11",
    });

    expect(request).toHaveBeenCalledWith("/api/v1/properties", {
      method: "POST",
      body: { name: "Redes 11", internal_code: "REDES11" },
    });
  });

  it("sends every optional field the caller supplies, snake_cased", async () => {
    const { source, request } = sourceWith(DETAIL_RESPONSE);

    await source.createProperty(TENANT, {
      name: "Redes 11",
      internalCode: "REDES11",
      pmsExternalId: "ext-1",
      addressLine1: "Calle Redes 11",
      addressLine2: "3ºB",
      city: "Madrid",
      province: "Madrid",
      postalCode: "28000",
      country: "ES",
      timezone: "Europe/Madrid",
      maxGuests: 4,
      bedrooms: 2,
      bathrooms: 1,
      defaultCheckInTime: "16:00:00",
      defaultCheckOutTime: "11:00:00",
      wifiName: "REDES11-WIFI",
      wifiPassword: "s3cr3t",
      accessNotes: "código: 1234",
      cleaningNotes: "ojo con la lavadora",
      emergencyNotes: "llamar al 600000000",
    });

    expect(request).toHaveBeenCalledWith("/api/v1/properties", {
      method: "POST",
      body: {
        name: "Redes 11",
        internal_code: "REDES11",
        pms_external_id: "ext-1",
        address_line1: "Calle Redes 11",
        address_line2: "3ºB",
        city: "Madrid",
        province: "Madrid",
        postal_code: "28000",
        country: "ES",
        timezone: "Europe/Madrid",
        max_guests: 4,
        bedrooms: 2,
        bathrooms: 1,
        default_check_in_time: "16:00:00",
        default_check_out_time: "11:00:00",
        wifi_name: "REDES11-WIFI",
        wifi_password: "s3cr3t",
        access_notes: "código: 1234",
        cleaning_notes: "ojo con la lavadora",
        emergency_notes: "llamar al 600000000",
      },
    });
  });

  it("never sends pms_provider or status (R1.2)", async () => {
    const { source, request } = sourceWith(DETAIL_RESPONSE);

    await source.createProperty(TENANT, {
      name: "Redes 11",
      internalCode: "REDES11",
    });

    const [, options] = request.mock.calls[0] as [string, { body: object }];
    expect(options.body).not.toHaveProperty("pms_provider");
    expect(options.body).not.toHaveProperty("status");
  });

  it("maps the 201 response to PropertyDetailDto", async () => {
    const { source } = sourceWith(DETAIL_RESPONSE);

    const created = await source.createProperty(TENANT, {
      name: "Redes 11",
      internalCode: "REDES11",
    });

    expect(created.id).toBe("property-1");
    expect(created.accessNotes).toBe("código de la caja fuerte: 1234");
  });

  it("never reads a wifi_password field from the response (rule 5.2)", async () => {
    const { source } = sourceWith({ ...DETAIL_RESPONSE, wifi_password: "supersecret" });

    const created = await source.createProperty(TENANT, {
      name: "Redes 11",
      internalCode: "REDES11",
    });

    expect(created).not.toHaveProperty("wifiPassword");
    expect(JSON.stringify(created)).not.toContain("supersecret");
  });
});

describe("HttpPropertiesSource — updateProperty (R2.2, R2.5, R2.6, design D8, D9)", () => {
  it("PATCHes only the keys present on input, verbatim", async () => {
    const { source, request } = sourceWith(DETAIL_RESPONSE);

    await source.updateProperty(TENANT, "property-1", { name: "Redes 12" });

    expect(request).toHaveBeenCalledWith("/api/v1/properties/{property_id}", {
      method: "PATCH",
      pathParams: { property_id: "property-1" },
      body: { name: "Redes 12" },
    });
  });

  it("sends null for an explicit clear of a nullable field", async () => {
    const { source, request } = sourceWith(DETAIL_RESPONSE);

    await source.updateProperty(TENANT, "property-1", { addressLine2: null });

    expect(request).toHaveBeenCalledWith("/api/v1/properties/{property_id}", {
      method: "PATCH",
      pathParams: { property_id: "property-1" },
      body: { address_line2: null },
    });
  });

  it("does not filter — an empty input sends an empty body", async () => {
    const { source, request } = sourceWith(DETAIL_RESPONSE);

    await source.updateProperty(TENANT, "property-1", {});

    expect(request).toHaveBeenCalledWith("/api/v1/properties/{property_id}", {
      method: "PATCH",
      pathParams: { property_id: "property-1" },
      body: {},
    });
  });

  it("forwards wifi_password verbatim, including null for an explicit clear", async () => {
    const { source, request } = sourceWith(DETAIL_RESPONSE);

    await source.updateProperty(TENANT, "property-1", { wifiPassword: "new-pass" });
    expect(request).toHaveBeenLastCalledWith(
      "/api/v1/properties/{property_id}",
      expect.objectContaining({ body: { wifi_password: "new-pass" } }),
    );

    await source.updateProperty(TENANT, "property-1", { wifiPassword: null });
    expect(request).toHaveBeenLastCalledWith(
      "/api/v1/properties/{property_id}",
      expect.objectContaining({ body: { wifi_password: null } }),
    );
  });

  it("sends exactly { status: 'INACTIVE' } for the retire path, nothing else (R2.6)", async () => {
    const { source, request } = sourceWith(DETAIL_RESPONSE);

    await source.updateProperty(TENANT, "property-1", { status: "INACTIVE" });

    expect(request).toHaveBeenCalledWith("/api/v1/properties/{property_id}", {
      method: "PATCH",
      pathParams: { property_id: "property-1" },
      body: { status: "INACTIVE" },
    });
  });

  it("never sends pms_provider or current_operational_state (R2.3)", async () => {
    const { source, request } = sourceWith(DETAIL_RESPONSE);

    await source.updateProperty(TENANT, "property-1", { name: "Redes 12" });

    const [, options] = request.mock.calls[0] as [string, { body: object }];
    expect(options.body).not.toHaveProperty("pms_provider");
    expect(options.body).not.toHaveProperty("current_operational_state");
  });

  it("maps the response to PropertyDetailDto", async () => {
    const { source } = sourceWith(DETAIL_RESPONSE);

    const updated = await source.updateProperty(TENANT, "property-1", {
      name: "Redes 12",
    });

    expect(updated.id).toBe("property-1");
    expect(updated.emergencyNotes).toBe("llamar al 600000000");
  });

  it("never reads a wifi_password field from the response (rule 5.2)", async () => {
    const { source } = sourceWith({ ...DETAIL_RESPONSE, wifi_password: "supersecret" });

    const updated = await source.updateProperty(TENANT, "property-1", {
      name: "Redes 12",
    });

    expect(updated).not.toHaveProperty("wifiPassword");
    expect(JSON.stringify(updated)).not.toContain("supersecret");
  });
});
