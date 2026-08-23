import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api";

import { HttpPricingSource, countEntries } from "./http-pricing-source";

function sourceWith(response: unknown): {
  source: HttpPricingSource;
  request: ReturnType<typeof vi.fn>;
} {
  const request = vi.fn().mockResolvedValue(response);
  return {
    source: new HttpPricingSource({ request } as unknown as ApiClient),
    request,
  };
}

const recommendationResponse = {
  id: "rec-1",
  property_id: "property-1",
  pricing_rule_id: "rule-1",
  date: "2026-09-01",
  recommended_price: "142.50",
  status: "RECOMMENDED",
  explanation: "Base 120.00 · Season (High) +10.00% · capped by max_price",
  // The three fields design D3 keeps out of the DTO. They are present here
  // precisely so the mapping test can prove they do not cross the boundary.
  current_price: null,
  confidence: "1.00",
  created_at: "2026-08-23T06:00:00Z",
};

const mappedRecommendation = {
  id: "rec-1",
  propertyId: "property-1",
  pricingRuleId: "rule-1",
  date: "2026-09-01",
  recommendedPrice: "142.50",
  status: "RECOMMENDED",
  explanation: "Base 120.00 · Season (High) +10.00% · capped by max_price",
};

const ruleResponse = {
  id: "rule-1",
  property_id: "property-1",
  name: "Temporada alta",
  active: true,
  base_price: "120.00",
  min_price: "80.00",
  max_price: "300.00",
  max_daily_change_pct: "15.00",
  weekday_modifiers: { FRI: 10, SAT: 15 },
  lead_time_rules: [{ days: 7, pct: 5 }],
  occupancy_rules: [{ from: 0.8, pct: 12 }, { from: 0.9, pct: 20 }],
  seasonality_rules: [],
  event_rules: [{ name: "Feria", pct: 30 }],
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-02T00:00:00Z",
};

/** Pricing's envelope: `items`, and no `total_pages` (design D2). */
function page(items: unknown[], overrides: Record<string, number> = {}) {
  return { items, total: items.length, page: 1, per_page: 20, ...overrides };
}

describe("HttpPricingSource.listRecommendations (R2.1, R2.2, R2.5)", () => {
  it("reads the `items` envelope and computes totalPages in the client", async () => {
    const { source, request } = sourceWith(
      page([recommendationResponse], { total: 45, page: 3, per_page: 20 }),
    );

    await expect(
      source.listRecommendations("tenant-1", {}, 3),
    ).resolves.toEqual({
      items: [mappedRecommendation],
      total: 45,
      page: 3,
      perPage: 20,
      // 45/20 → 3, computed here because the response has no `total_pages`.
      totalPages: 3,
    });
    expect(request).toHaveBeenCalledWith("/api/v1/price-recommendations", {
      query: { page: 3, per_page: 20 },
    });
  });

  it("reads `items` and not `data` — the field the other envelopes use", async () => {
    // The named risk of this change: a boundary copied from `cleaning` compiles
    // against `data` and yields an empty list at runtime.
    const { source } = sourceWith({
      data: [recommendationResponse],
      items: [],
      total: 0,
      page: 1,
      per_page: 20,
    });

    const result = await source.listRecommendations("tenant-1", {}, 1);
    expect(result.items).toEqual([]);
  });

  it("gives totalPages 0 when total is 0, so «page 1 of 0» is unrepresentable (R2.3)", async () => {
    const { source } = sourceWith(page([], { total: 0, per_page: 20 }));

    await expect(source.listRecommendations("tenant-1", {}, 1)).resolves.toEqual(
      { items: [], total: 0, page: 1, perPage: 20, totalPages: 0 },
    );
  });

  it("gives totalPages 0 when per_page is 0, instead of dividing by zero", async () => {
    const { source } = sourceWith(page([], { total: 12, per_page: 0 }));

    const result = await source.listRecommendations("tenant-1", {}, 1);
    expect(result.totalPages).toBe(0);
  });

  it("sends the status filter under the query name `status`, not `status_filter`", async () => {
    // Python calls the parameter `status_filter` with `Query(alias="status")`;
    // the alias is what travels (R2.1).
    const { source, request } = sourceWith(page([]));

    await source.listRecommendations("tenant-1", { status: "APPROVED" }, 1);

    const query = request.mock.calls[0][1].query as Record<string, unknown>;
    expect(query.status).toBe("APPROVED");
    expect(Object.keys(query)).not.toContain("status_filter");
  });

  it("sends only the filters actually chosen, as snake_case query keys", async () => {
    const { source, request } = sourceWith(page([]));

    await source.listRecommendations(
      "tenant-1",
      {
        propertyId: "property-9",
        dateFrom: "2026-09-01",
        dateTo: "2026-09-30",
        status: "RECOMMENDED",
      },
      2,
    );

    expect(request).toHaveBeenCalledWith("/api/v1/price-recommendations", {
      query: {
        page: 2,
        per_page: 20,
        property_id: "property-9",
        date_from: "2026-09-01",
        date_to: "2026-09-30",
        status: "RECOMMENDED",
      },
    });
  });

  it("omits the keys of unchosen filters entirely", async () => {
    // `toHaveBeenCalledWith` ignores keys whose value is `undefined`, so the key
    // set is the real assertion.
    const { source, request } = sourceWith(page([]));

    await source.listRecommendations("tenant-1", { dateFrom: "2026-09-01" }, 1);

    expect(
      Object.keys(request.mock.calls[0][1].query).sort(),
    ).toEqual(["date_from", "page", "per_page"]);
  });

  it("does not carry current_price, confidence or created_at across the boundary (R2.5, R2.6)", async () => {
    const { source } = sourceWith(page([recommendationResponse]));

    const [item] = (await source.listRecommendations("tenant-1", {}, 1)).items;
    expect(Object.keys(item).sort()).toEqual([
      "date",
      "explanation",
      "id",
      "pricingRuleId",
      "propertyId",
      "recommendedPrice",
      "status",
    ]);
  });
});

describe("HttpPricingSource.listRules (R5.1, R5.2, R5.4)", () => {
  it("sends `active` as a boolean query parameter (design D20)", async () => {
    const { source, request } = sourceWith(page([]));

    await source.listRules("tenant-1", { propertyId: "p-1", active: true }, 1);

    expect(request).toHaveBeenCalledWith("/api/v1/pricing-rules", {
      query: { page: 1, per_page: 20, property_id: "p-1", active: true },
    });
  });

  it("keeps `active: false` — it is a chosen filter, not an absent one", async () => {
    const { source, request } = sourceWith(page([]));

    await source.listRules("tenant-1", { active: false }, 1);

    const query = request.mock.calls[0][1].query as Record<string, unknown>;
    expect(query.active).toBe(false);
  });

  it("replaces the five JSONB columns with their entry counts, reading no value", async () => {
    const { source } = sourceWith(page([ruleResponse]));

    const [rule] = (await source.listRules("tenant-1", {}, 1)).items;
    expect(rule.modifierCounts).toEqual({
      weekday: 2,
      leadTime: 1,
      occupancy: 2,
      seasonality: 0,
      event: 1,
    });
    // R5.4: nothing from inside a JSONB column reaches the DTO. Serializing the
    // whole rule and looking for a value only the fixtures carry proves it.
    const serialized = JSON.stringify(rule);
    for (const inner of ["FRI", "SAT", "Feria", "days", "pct", "from"]) {
      expect(serialized).not.toContain(inner);
    }
    expect(Object.keys(rule).sort()).toEqual([
      "active",
      "basePrice",
      "id",
      "maxDailyChangePct",
      "maxPrice",
      "minPrice",
      "modifierCounts",
      "name",
      "propertyId",
    ]);
  });

  it("keeps a null property_id as null — the whole-portfolio scope of R5.3", async () => {
    const { source } = sourceWith(
      page([{ ...ruleResponse, property_id: null }]),
    );

    const [rule] = (await source.listRules("tenant-1", {}, 1)).items;
    expect(rule.propertyId).toBeNull();
  });
});

describe("countEntries (R5.4, design D3)", () => {
  it("counts an object's keys and an array's length", () => {
    expect(countEntries({ FRI: 10, SAT: 15 })).toBe(2);
    expect(countEntries([1, 2, 3])).toBe(3);
    expect(countEntries({})).toBe(0);
    expect(countEntries([])).toBe(0);
  });

  it("gives 0 for anything the contract does not declare, instead of throwing", () => {
    // Deploy-skew window: the column arrives as something other than an object
    // or an array. A count of 0 degrades; an exception would take down the tab.
    for (const value of [null, undefined, 7, "text", true]) {
      expect(countEntries(value)).toBe(0);
    }
  });
});

describe("HttpPricingSource.listProperties (R2.8)", () => {
  it("asks for one catalog page of 100 and reads the §23 `data` envelope", async () => {
    // `/api/v1/properties` is NOT a pricing envelope: it answers `data` and
    // carries `total_pages`. The two shapes coexist in this adapter.
    const { source, request } = sourceWith({
      data: [{ id: "p-1", name: "Ático Sol", internal_code: "MAD-01" }],
      total: 1,
      page: 1,
      per_page: 100,
      total_pages: 1,
    });

    await expect(source.listProperties("tenant-1")).resolves.toEqual([
      { id: "p-1", name: "Ático Sol", internalCode: "MAD-01" },
    ]);
    expect(request).toHaveBeenCalledWith("/api/v1/properties", {
      query: { page: 1, per_page: 100 },
    });
  });
});

describe("HttpPricingSource.decideRecommendation (R3.1, R3.2)", () => {
  it("PATCHes the id with a body of exactly {status}", async () => {
    // `DecidePriceRecommendationRequest` is `extra="forbid"`: one field and no
    // more, or the backend answers 422.
    const { source, request } = sourceWith({
      ...recommendationResponse,
      status: "APPROVED",
    });

    await expect(
      source.decideRecommendation("tenant-1", "rec-1", "APPROVED"),
    ).resolves.toEqual({ ...mappedRecommendation, status: "APPROVED" });

    expect(request).toHaveBeenCalledWith(
      "/api/v1/price-recommendations/{recommendation_id}",
      {
        method: "PATCH",
        pathParams: { recommendation_id: "rec-1" },
        body: { status: "APPROVED" },
      },
    );
    expect(Object.keys(request.mock.calls[0][1].body)).toEqual(["status"]);
  });
});

describe("HttpPricingSource.generateRecommendations (R4.1, R4.2)", () => {
  it("POSTs {property_id} and returns the four counters", async () => {
    const { source, request } = sourceWith({
      created: 40,
      updated: 3,
      preserved: 2,
      skipped: 1,
    });

    await expect(
      source.generateRecommendations("tenant-1", "property-9"),
    ).resolves.toEqual({ created: 40, updated: 3, preserved: 2, skipped: 1 });

    expect(request).toHaveBeenCalledWith(
      "/api/v1/price-recommendations/generate",
      { method: "POST", body: { property_id: "property-9" } },
    );
  });

  it("sends property_id null when no property filter is active", async () => {
    const { source, request } = sourceWith({
      created: 0,
      updated: 0,
      preserved: 0,
      skipped: 0,
    });

    await source.generateRecommendations("tenant-1", null);

    expect(request.mock.calls[0][1].body).toEqual({ property_id: null });
  });
});
