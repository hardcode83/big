import { describe, expect, it } from "vitest";

import type { PricingRuleFilters, RecommendationFilters } from "../data";
import {
  normalizeRecommendationFilters,
  normalizeRuleFilters,
  pricingKeys,
} from "./query-keys";

describe("pricingKeys — tenant scoping (steering/security.md rule 1)", () => {
  it("begins every key with ['tenant', tenantId, …]", () => {
    expect(pricingKeys.recommendations("t-1", {}, 1).slice(0, 3)).toEqual([
      "tenant",
      "t-1",
      "pricing-recommendations",
    ]);
    expect(pricingKeys.rules("t-1", {}, 1).slice(0, 3)).toEqual([
      "tenant",
      "t-1",
      "pricing-rules",
    ]);
    expect(pricingKeys.properties("t-1")).toEqual([
      "tenant",
      "t-1",
      "pricing-properties",
    ]);
  });

  it("refuses to build a key without a tenant, rather than caching globally", () => {
    expect(() => pricingKeys.recommendations("", {}, 1)).toThrow();
    expect(() => pricingKeys.properties("")).toThrow();
  });

  it("gives two tenants different keys for the same filters", () => {
    expect(pricingKeys.recommendations("t-1", {}, 1)).not.toEqual(
      pricingKeys.recommendations("t-2", {}, 1),
    );
  });

  it("uses resource names of its own, distinct from cleaning's", () => {
    // `cleaning` uses `cleaning-properties` for the same catalog; the two caches
    // are deliberately separate copies (design D6).
    const names = [
      pricingKeys.recommendations("t-1", {}, 1)[2],
      pricingKeys.rules("t-1", {}, 1)[2],
      pricingKeys.properties("t-1")[2],
    ];
    expect(new Set(names).size).toBe(3);
    for (const name of names) {
      expect(name).toMatch(/^pricing-/);
    }
  });
});

describe("normalizeRecommendationFilters (R2.1, design D6)", () => {
  it("gives the same key for equivalent filters built in a different order", () => {
    // TanStack Query hashes the key structurally, so two orders would otherwise
    // be two cache entries for one request.
    const a: RecommendationFilters = {
      status: "APPROVED",
      propertyId: "p-1",
      dateFrom: "2026-09-01",
    };
    const b: RecommendationFilters = {
      dateFrom: "2026-09-01",
      propertyId: "p-1",
      status: "APPROVED",
    };
    expect(JSON.stringify(normalizeRecommendationFilters(a, 2))).toBe(
      JSON.stringify(normalizeRecommendationFilters(b, 2)),
    );
    expect(JSON.stringify(pricingKeys.recommendations("t-1", a, 2))).toBe(
      JSON.stringify(pricingKeys.recommendations("t-1", b, 2)),
    );
  });

  it("omits an absent filter instead of writing it as undefined", () => {
    expect(Object.keys(normalizeRecommendationFilters({}, 1))).toEqual(["page"]);
  });

  it("canonicalizes an absent page to 1", () => {
    // «No page» and «page 1» are one request: the backend defaults `page` to 1.
    expect(normalizeRecommendationFilters({})).toEqual({ page: 1 });
    expect(JSON.stringify(pricingKeys.recommendations("t-1", {}, 1))).toBe(
      JSON.stringify(pricingKeys.recommendations("t-1", {}, 1)),
    );
  });

  it("distinguishes «no status» from any chosen status", () => {
    expect(pricingKeys.recommendations("t-1", {}, 1)).not.toEqual(
      pricingKeys.recommendations("t-1", { status: "DRAFT" }, 1),
    );
  });
});

describe("normalizeRuleFilters (R5.1)", () => {
  it("keeps `active: false` — it is a chosen filter, not an absent one", () => {
    expect(normalizeRuleFilters({ active: false }, 1)).toEqual({
      active: false,
      page: 1,
    });
    expect(pricingKeys.rules("t-1", { active: false }, 1)).not.toEqual(
      pricingKeys.rules("t-1", {}, 1),
    );
  });

  it("gives different keys for active true and false", () => {
    expect(pricingKeys.rules("t-1", { active: true }, 1)).not.toEqual(
      pricingKeys.rules("t-1", { active: false }, 1),
    );
  });

  it("emits a fixed key order regardless of how the object was built", () => {
    expect(
      JSON.stringify(normalizeRuleFilters({ propertyId: "p", active: true }, 3)),
    ).toBe(
      JSON.stringify(normalizeRuleFilters({ active: true, propertyId: "p" }, 3)),
    );
  });
});

describe("recommendationsPrefix (R3.4, R3.5, design D7)", () => {
  it("is a prefix of every recommendation key, for any filter and page", () => {
    // This is the property the invalidation depends on: one prefix reaches every
    // filter/page combination without enumerating them.
    const prefix = pricingKeys.recommendationsPrefix("t-1");
    const filterSets: RecommendationFilters[] = [
      {},
      { status: "RECOMMENDED" },
      { propertyId: "p-1", dateFrom: "2026-09-01", dateTo: "2026-09-30" },
      { status: "APPLIED_EXTERNAL", propertyId: "p-2" },
    ];
    for (const filters of filterSets) {
      for (const page of [1, 2, 37]) {
        const key = pricingKeys.recommendations("t-1", filters, page);
        expect(key.slice(0, prefix.length)).toEqual([...prefix]);
      }
    }
  });

  it("is NOT a prefix of the rules key, so invalidating it never refetches rules", () => {
    // R3.5: neither deciding nor regenerating writes a rule.
    const prefix = pricingKeys.recommendationsPrefix("t-1");
    const rulesKey = pricingKeys.rules("t-1", {}, 1);
    expect(rulesKey.slice(0, prefix.length)).not.toEqual([...prefix]);
  });

  it("is NOT a prefix of another tenant's recommendation key", () => {
    const prefix = pricingKeys.recommendationsPrefix("t-1");
    const otherTenant = pricingKeys.recommendations("t-2", {}, 1);
    expect(otherTenant.slice(0, prefix.length)).not.toEqual([...prefix]);
  });

  it("does not reach the property catalog, which no mutation invalidates", () => {
    const prefix = pricingKeys.recommendationsPrefix("t-1");
    const properties = pricingKeys.properties("t-1");
    expect(properties.slice(0, prefix.length)).not.toEqual([...prefix]);
  });
});

describe("filters are typed apart, so a rule filter cannot key a recommendation", () => {
  it("normalizes only the fields its own filter type declares", () => {
    const ruleFilters: PricingRuleFilters = { propertyId: "p-1", active: true };
    expect(Object.keys(normalizeRuleFilters(ruleFilters, 1)).sort()).toEqual([
      "active",
      "page",
      "propertyId",
    ]);
    expect(
      Object.keys(
        normalizeRecommendationFilters(
          { propertyId: "p-1", status: "DRAFT" },
          1,
        ),
      ).sort(),
    ).toEqual(["page", "propertyId", "status"]);
  });
});
