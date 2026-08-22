import { describe, expect, expectTypeOf, it } from "vitest";

import type { components } from "@/lib/api/generated/openapi";

import { HttpPropertiesSource } from "./http/http-properties-source";
import type {
  PropertyFilters,
  PropertyOperationalState,
  PropertyStatus,
  PropertySummaryDto,
} from "./dto";
import type { ApiClient } from "@/lib/api";
import { vi } from "vitest";

/**
 * Boundary test for the properties DTOs (design D5).
 *
 * Two things are pinned here that no other test covers:
 *
 *  1. The DTO's field set is EXACTLY the contract's field set — neither short
 *     (a field silently dropped in the mapper) nor long (a field invented, or
 *     worse, one of the three free-text sinks leaking back in).
 *  2. The re-exported unions are the generated ones, not hand-written copies
 *     that can drift from `backend/app/properties/domain/enums.py`.
 */

/** Exactly the 23 fields `PropertyListItemResponse` declares, in camelCase. */
const EXPECTED_DTO_KEYS = [
  "addressLine1",
  "addressLine2",
  "bathrooms",
  "bedrooms",
  "city",
  "country",
  "createdAt",
  "currentOperationalState",
  "defaultCheckInTime",
  "defaultCheckOutTime",
  "hasWifiPassword",
  "id",
  "internalCode",
  "maxGuests",
  "name",
  "pmsExternalId",
  "pmsProvider",
  "postalCode",
  "province",
  "status",
  "timezone",
  "updatedAt",
  "wifiName",
] as const;

const CONTRACT_ROW = {
  id: "p1",
  name: "Redes 11",
  internal_code: "REDES11",
  pms_provider: "BEDS24",
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
  current_operational_state: "VACANT_READY",
  default_check_in_time: "16:00:00",
  default_check_out_time: "11:00:00",
  wifi_name: "REDES11-WIFI",
  has_wifi_password: true,
  status: "ACTIVE",
  created_at: "2026-08-01T09:00:00Z",
  updated_at: "2026-08-02T09:00:00Z",
};

async function mapOneRow(): Promise<PropertySummaryDto> {
  const request = vi.fn().mockResolvedValue({
    data: [CONTRACT_ROW],
    page: 1,
    per_page: 20,
    total: 1,
    total_pages: 1,
  });
  const source = new HttpPropertiesSource({ request } as unknown as ApiClient);
  const [row] = (await source.listProperties("tenant-1")).data;
  return row;
}

describe("PropertySummaryDto — the contract boundary", () => {
  it("carries exactly the contract's fields, no more and no fewer", async () => {
    const row = await mapOneRow();
    expect(Object.keys(row).sort()).toEqual([...EXPECTED_DTO_KEYS]);
  });

  it("has no field whose name suggests a free-text sink or a secret", async () => {
    // Exception 6 of rule 11 (`steering/security.md`) took `access_notes`,
    // `cleaning_notes` and `emergency_notes` out of this endpoint. If a backend
    // change ever puts them back, this list is where it shows up first.
    //
    // `hasWifiPassword` is the one allowed name containing "password": it is
    // the boolean signal R5.3 designates as the ONLY thing the contract offers
    // about WiFi credentials. It is allowed by name and constrained by type
    // below, so it cannot quietly start carrying the secret itself.
    const row = await mapOneRow();
    const forbidden = ["notes", "password", "secret", "token"];
    const allowed = new Set(["hasWifiPassword"]);
    const offenders = Object.keys(row).filter(
      (key) =>
        !allowed.has(key) &&
        forbidden.some((needle) => key.toLowerCase().includes(needle)),
    );
    expect(offenders).toEqual([]);
  });

  it("exposes WiFi only as a boolean flag, never as a value (R5.3)", async () => {
    const row = await mapOneRow();
    expect(typeof row.hasWifiPassword).toBe("boolean");
    expectTypeOf<PropertySummaryDto["hasWifiPassword"]>().toEqualTypeOf<boolean>();
    // The name of the credential is public (it is the SSID); the credential is not.
    expect(Object.keys(row)).not.toContain("wifiPassword");
  });
});

describe("Re-exported unions come from the generated contract (design D5)", () => {
  it("PropertyStatus is the generated union", () => {
    expectTypeOf<PropertyStatus>().toEqualTypeOf<
      components["schemas"]["PropertyStatus"]
    >();
  });

  it("PropertyOperationalState is the generated union", () => {
    expectTypeOf<PropertyOperationalState>().toEqualTypeOf<
      components["schemas"]["PropertyOperationalState"]
    >();
  });
});

describe("PropertyFilters — only what the v1 contract accepts (R2.4)", () => {
  it("has no key for text search, ordering or city", () => {
    // A compile-time guard: adding `search`, `orderBy` or `city` to the filters
    // type would break this assignment, which is the point — those need new
    // backend, not a new frontend field.
    expectTypeOf<keyof PropertyFilters>().toEqualTypeOf<
      "status" | "currentOperationalState" | "page" | "perPage"
    >();
  });
});
