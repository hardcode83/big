import { describe, expect, it } from "vitest";

import {
  mapOwnerStatementDetailResponse,
  mapOwnerStatementResponse,
} from "./http/http-statements-source";

const SUMMARY = {
  id: "statement-1",
  property_id: "property-1",
  period_start: "2026-08-01",
  period_end: "2026-08-31",
  status: "READY" as const,
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

describe("statement DTO mapping", () => {
  it("maps the list response to a camel-case flat summary only", () => {
    const statement = mapOwnerStatementResponse(
      {
        ...SUMMARY,
        reservations: [{ id: "must-not-cross" }],
        tenant_id: "must-not-cross",
        currency: "must-not-cross",
      } as unknown as Parameters<typeof mapOwnerStatementResponse>[0],
    );

    expect(statement).toEqual({
      id: "statement-1",
      propertyId: "property-1",
      periodStart: "2026-08-01",
      periodEnd: "2026-08-31",
      status: "READY",
      grossRevenue: "2000.00",
      otaCommissions: "200.00",
      netRevenue: "1800.00",
      cleaningCosts: "100.00",
      laundryCosts: "20.00",
      amenitiesCosts: "30.00",
      maintenanceCosts: "40.00",
      specialistCosts: "50.00",
      otherCosts: "60.00",
      platformFee: "180.00",
      netOwnerResult: "1320.00",
      notes: null,
      createdAt: "2026-09-01T02:00:00Z",
      updatedAt: "2026-09-02T10:00:00Z",
    });
    expect(statement).not.toHaveProperty("reservations");
    expect(statement).not.toHaveProperty("tenantId");
    expect(statement).not.toHaveProperty("currency");
  });

  it("keeps detail flat and preserves nullable amounts, notes and row currencies", () => {
    const detail = mapOwnerStatementDetailResponse({
      ...SUMMARY,
      reservations: [
        {
          id: "reservation-1",
          check_in_date: "2026-08-10",
          nights: 3,
          gross_amount: null,
          ota_commission: null,
          net_amount: null,
          currency: "USD",
        },
      ],
      expenses: [
        {
          id: "expense-1",
          category: "MAINTENANCE",
          description: "Repair",
          amount: "40.00",
          currency: "EUR",
          date: "2026-08-12",
        },
      ],
    });

    expect(detail.notes).toBeNull();
    expect(detail).not.toHaveProperty("summary");
    expect(detail.reservations[0]).toEqual({
      id: "reservation-1",
      checkInDate: "2026-08-10",
      nights: 3,
      grossAmount: null,
      otaCommission: null,
      netAmount: null,
      currency: "USD",
    });
    expect(detail.expenses[0]).toEqual({
      id: "expense-1",
      category: "MAINTENANCE",
      description: "Repair",
      amount: "40.00",
      currency: "EUR",
      date: "2026-08-12",
    });
    expect(detail).not.toHaveProperty("currency");
    expect(detail).not.toHaveProperty("subtotal");
    expect(detail).not.toHaveProperty("total");
  });
});
