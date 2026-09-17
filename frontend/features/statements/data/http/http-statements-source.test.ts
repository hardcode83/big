import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api";

import { HttpStatementsSource } from "./http-statements-source";

const SUMMARY = {
  id: "statement-1",
  property_id: "property-1",
  period_start: "2026-08-01",
  period_end: "2026-08-31",
  status: "READY",
  gross_revenue: "2000.00",
  ota_commissions: "200.00",
  net_revenue: "1800.00",
  cleaning_costs: "100.00",
  laundry_costs: "20.00",
  amenities_costs: "30.00",
  maintenance_costs: "40.00",
  specialist_costs: "50.00",
  other_costs: "60.00",
  platform_fee: "180.00",
  net_owner_result: "1320.00",
  notes: null,
  created_at: "2026-09-01T02:00:00Z",
  updated_at: "2026-09-02T10:00:00Z",
};

function makeClient(overrides: Partial<ApiClient>): ApiClient {
  return {
    request: vi.fn(),
    requestBinary: vi.fn(),
    ...overrides,
  } as unknown as ApiClient;
}

describe("HttpStatementsSource", () => {
  it("lists with only contractual filters and preserves the page envelope", async () => {
    const request = vi.fn().mockResolvedValue({
      items: [SUMMARY],
      total: 41,
      page: 2,
      per_page: 20,
    });
    const source = new HttpStatementsSource(makeClient({ request } as never));

    const result = await source.listStatements(
      "tenant-must-not-travel",
      {
        propertyId: "property-1",
        periodStartFrom: "2026-01-01",
        periodStartTo: "2026-08-01",
        status: "READY",
      },
      2,
    );

    expect(request).toHaveBeenCalledWith("/api/v1/owner-statements", {
      query: {
        page: 2,
        per_page: 20,
        property_id: "property-1",
        period_start_from: "2026-01-01",
        period_start_to: "2026-08-01",
        status: "READY",
      },
    });
    expect(JSON.stringify(request.mock.calls)).not.toContain("tenant-must-not-travel");
    expect(result).toMatchObject({ total: 41, page: 2, perPage: 20 });
    expect(result).not.toHaveProperty("totalPages");
    expect(result.items[0]).toMatchObject({
      id: "statement-1",
      propertyId: "property-1",
      netOwnerResult: "1320.00",
    });
  });

  it("omits unselected filters instead of sending empty values", async () => {
    const request = vi.fn().mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      per_page: 20,
    });
    const source = new HttpStatementsSource(makeClient({ request } as never));

    await source.listStatements("tenant-1", {}, 1);

    expect(request).toHaveBeenCalledWith("/api/v1/owner-statements", {
      query: { page: 1, per_page: 20 },
    });
  });

  it("gets detail by statement_id and maps both breakdowns", async () => {
    const request = vi.fn().mockResolvedValue({
      ...SUMMARY,
      reservations: [
        {
          id: "reservation-1",
          check_in_date: "2026-08-10",
          nights: 3,
          gross_amount: null,
          ota_commission: "20.00",
          net_amount: "180.00",
          currency: "EUR",
        },
      ],
      expenses: [
        {
          id: "expense-1",
          category: "CLEANING",
          description: "Turnover",
          amount: "100.00",
          currency: "EUR",
          date: "2026-08-13",
        },
      ],
    });
    const source = new HttpStatementsSource(makeClient({ request } as never));

    const result = await source.getStatement("tenant-1", "statement-1");

    expect(request).toHaveBeenCalledWith(
      "/api/v1/owner-statements/{statement_id}",
      { method: "GET", pathParams: { statement_id: "statement-1" } },
    );
    expect(result.reservations[0].grossAmount).toBeNull();
    expect(result.expenses[0]).toMatchObject({
      id: "expense-1",
      amount: "100.00",
      currency: "EUR",
    });
  });

  it.each([
    ["CSV", "exportCsv", "/api/v1/owner-statements/{statement_id}/export.csv", "text/csv"],
    ["PDF", "exportPdf", "/api/v1/owner-statements/{statement_id}/export.pdf", "application/pdf"],
  ] as const)("keeps %s bytes and all headers opaque", async (_label, method, path, contentType) => {
    const bytes = new Uint8Array([0, 255, 1, 128]);
    const headers = new Headers({
      "Content-Type": contentType,
      "Content-Disposition": 'attachment; filename="opaque.bin"',
      "X-Report-Version": "7",
    });
    const requestBinary = vi.fn().mockResolvedValue({ bytes, headers, status: 200 });
    const source = new HttpStatementsSource(
      makeClient({ requestBinary } as never),
    );

    const result = await source[method]("tenant-1", "statement-1");

    expect(requestBinary).toHaveBeenCalledWith(path, {
      pathParams: { statement_id: "statement-1" },
    });
    expect(result.bytes).toBe(bytes);
    expect(result.headers).toBe(headers);
    expect(result.headers.get("X-Report-Version")).toBe("7");
  });

  it("propagates a download error without creating a payload", async () => {
    const error = new Error("download failed");
    const requestBinary = vi.fn().mockRejectedValue(error);
    const source = new HttpStatementsSource(
      makeClient({ requestBinary } as never),
    );

    await expect(source.exportPdf("tenant-1", "statement-1")).rejects.toBe(
      error,
    );
  });
});
