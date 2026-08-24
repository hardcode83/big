import { beforeEach, describe, expect, it } from "vitest";

import { usePricingUiStore } from "./use-pricing-ui-store";

function store() {
  return usePricingUiStore.getState();
}

beforeEach(() => {
  // Module-level singleton: without this every test inherits the previous one's
  // filters and the file becomes order-dependent.
  store().reset();
});

describe("initial state (R1.1)", () => {
  it("opens on the Recommendations tab", () => {
    expect(store().activeTab).toBe("recommendations");
  });

  it("starts both slices on page 1 with no filters", () => {
    expect(store().recommendations).toEqual({
      propertyId: undefined,
      dateFrom: undefined,
      dateTo: undefined,
      status: undefined,
      page: 1,
    });
    expect(store().rules).toEqual({
      propertyId: undefined,
      active: undefined,
      page: 1,
    });
  });
});

describe("every setter resets its own slice to page 1 (R1.3)", () => {
  it("does so for each recommendation filter", () => {
    const setters = [
      () => store().setRecommendationPropertyId("p-1"),
      () => store().setRecommendationDateFrom("2026-09-01"),
      () => store().setRecommendationDateTo("2026-09-30"),
      () => store().setRecommendationStatus("APPROVED"),
    ];
    for (const applyFilter of setters) {
      store().setRecommendationPage(4);
      expect(store().recommendations.page).toBe(4);
      applyFilter();
      // The invariant lives in the setter, so no caller has to remember it.
      expect(store().recommendations.page).toBe(1);
    }
  });

  it("does so for each rule filter", () => {
    for (const applyFilter of [
      () => store().setRulePropertyId("p-1"),
      () => store().setRuleActive(true),
    ]) {
      store().setRulePage(3);
      expect(store().rules.page).toBe(3);
      applyFilter();
      expect(store().rules.page).toBe(1);
    }
  });

  it("lets the page setter move the page without clearing anything", () => {
    store().setRecommendationStatus("RECOMMENDED");
    store().setRecommendationPage(2);
    expect(store().recommendations).toMatchObject({
      status: "RECOMMENDED",
      page: 2,
    });
  });
});

describe("the two slices are independent (design D11)", () => {
  it("does not share propertyId", () => {
    // The subtle one R4.1 depends on: a `property_id` set from the Rules tab must
    // never become the scope that «Regenerate now» sweeps.
    store().setRulePropertyId("rule-scope");
    expect(store().recommendations.propertyId).toBeUndefined();

    store().setRecommendationPropertyId("queue-scope");
    expect(store().rules.propertyId).toBe("rule-scope");
    expect(store().recommendations.propertyId).toBe("queue-scope");
  });

  it("does not share the page", () => {
    store().setRecommendationPage(5);
    expect(store().rules.page).toBe(1);

    store().setRulePage(2);
    expect(store().recommendations.page).toBe(5);
  });

  it("keeps a rule filter out of the recommendation slice entirely", () => {
    store().setRuleActive(false);
    expect(store().recommendations).not.toHaveProperty("active");
  });
});

describe("setActiveTab (R1.1, R1.3)", () => {
  it("switches the tab without touching either slice", () => {
    store().setRecommendationPropertyId("p-1");
    store().setRecommendationPage(3);
    store().setRulePropertyId("p-2");
    store().setRulePage(7);

    store().setActiveTab("rules");
    expect(store().activeTab).toBe("rules");

    store().setActiveTab("recommendations");
    expect(store().recommendations).toMatchObject({
      propertyId: "p-1",
      page: 3,
    });
    expect(store().rules).toMatchObject({ propertyId: "p-2", page: 7 });
  });
});

describe("adoptTenant (steering/security.md rule 1, frontend side)", () => {
  it("records the tenant on first adoption", () => {
    store().adoptTenant("tenant-1");
    expect(store().tenantId).toBe("tenant-1");
  });

  it("keeps the filters while the tenant is unchanged", () => {
    store().adoptTenant("tenant-1");
    store().setRecommendationPropertyId("p-1");
    store().adoptTenant("tenant-1");
    expect(store().recommendations.propertyId).toBe("p-1");
  });

  it("discards another tenant's propertyId when the tenant changes", () => {
    // One tenant's opaque identifier must not travel into another's request.
    store().adoptTenant("tenant-1");
    store().setRecommendationPropertyId("tenant-1-property");
    store().setRulePropertyId("tenant-1-rule-property");
    store().setActiveTab("rules");

    store().adoptTenant("tenant-2");

    expect(store().tenantId).toBe("tenant-2");
    expect(store().recommendations.propertyId).toBeUndefined();
    expect(store().rules.propertyId).toBeUndefined();
    expect(store().recommendations.page).toBe(1);
    expect(store().rules.page).toBe(1);
    expect(store().activeTab).toBe("recommendations");
  });

  it("clears the filters on logout, when the tenant becomes undefined", () => {
    store().adoptTenant("tenant-1");
    store().setRecommendationPropertyId("p-1");

    store().adoptTenant(undefined);

    expect(store().tenantId).toBeUndefined();
    expect(store().recommendations.propertyId).toBeUndefined();
  });
});

describe("reset", () => {
  it("returns the whole store to its initial state, tenant included", () => {
    store().adoptTenant("tenant-1");
    store().setRecommendationStatus("REJECTED");
    store().setRuleActive(true);
    store().setActiveTab("rules");

    store().reset();

    expect(store().tenantId).toBeUndefined();
    expect(store().activeTab).toBe("recommendations");
    expect(store().recommendations.status).toBeUndefined();
    expect(store().rules.active).toBeUndefined();
  });
});
