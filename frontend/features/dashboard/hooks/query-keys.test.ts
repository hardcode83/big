import { describe, expect, it } from "vitest";

import { dashboardKeys } from "./query-keys";

describe("dashboardKeys (R4, D11)", () => {
  it("prefixes every key with tenant + tenantId", () => {
    expect(dashboardKeys.cards("t1")).toEqual([
      "tenant",
      "t1",
      "dashboard-cards",
    ]);
    expect(dashboardKeys.propertyDetail("t1", "redes11")).toEqual([
      "tenant",
      "t1",
      "property-detail",
      "redes11",
    ]);
  });

  it("includes the filters in the timeline key so cache entries stay distinct", () => {
    expect(
      dashboardKeys.propertyTimeline("t1", "redes11", { actorType: "GUEST" }),
    ).toEqual([
      "tenant",
      "t1",
      "property-timeline",
      "redes11",
      { actorType: "GUEST" },
    ]);
  });

  it("refuses to build a key without a tenantId", () => {
    expect(() => dashboardKeys.cards("")).toThrow(/tenantId/);
  });
});
