import { describe, expect, it } from "vitest";

import { dashboardKeys } from "./query-keys";

describe("dashboardKeys (R4, D11, D7)", () => {
  it.each(["es", "en"] as const)(
    "prefixes every key with tenant + tenantId and ends with the locale (%s)",
    (locale) => {
      expect(dashboardKeys.cards("t1", locale)).toEqual([
        "tenant",
        "t1",
        "dashboard-cards",
        locale,
      ]);
      expect(dashboardKeys.propertyDetail("t1", "redes11", locale)).toEqual([
        "tenant",
        "t1",
        "property-detail",
        "redes11",
        locale,
      ]);
    },
  );

  it("includes the filters in the timeline key so cache entries stay distinct, locale last", () => {
    expect(
      dashboardKeys.propertyTimeline(
        "t1",
        "redes11",
        { actorType: "GUEST" },
        "en",
      ),
    ).toEqual([
      "tenant",
      "t1",
      "property-timeline",
      "redes11",
      { actorType: "GUEST" },
      "en",
    ]);
  });

  it("refuses to build a key without a tenantId", () => {
    expect(() => dashboardKeys.cards("", "es")).toThrow(/tenantId/);
  });

  it.each(["es", "en"] as const)(
    "dashboardKeys.cards(t, %s) still starts with ['tenant', t, 'dashboard-cards'] — the hand-written prefix invalidation in use-resolve-incident.ts / use-cancel-cleaning-task.ts must keep matching",
    (locale) => {
      const key = dashboardKeys.cards("t1", locale);
      expect(key.slice(0, 3)).toEqual(["tenant", "t1", "dashboard-cards"]);
    },
  );

  it.each(["es", "en"] as const)(
    "dashboardKeys.propertyTimeline(..., %s) still starts with ['tenant', t, 'property-timeline'] — same prefix-invalidation contract",
    (locale) => {
      const key = dashboardKeys.propertyTimeline(
        "t1",
        "redes11",
        {},
        locale,
      );
      expect(key.slice(0, 3)).toEqual([
        "tenant",
        "t1",
        "property-timeline",
      ]);
    },
  );

  it("a key built without a locale (R2.4) does not match the shape the rest of the suite expects", () => {
    // Simulates the pre-D7 behaviour: a key with no locale segment at all.
    // `cards` (4 elements: tenant, tenantId, resource, locale) must NOT equal
    // the 3-element shape a locale-less caller would have produced.
    const withLocale = dashboardKeys.cards("t1", "es");
    const withoutLocale = ["tenant", "t1", "dashboard-cards"];
    expect(withLocale).not.toEqual(withoutLocale);
    expect(withLocale).toHaveLength(4);

    if (false) {
      // @ts-expect-error R2.4: locale is now a required argument on every
      // dashboard key factory — a call that omits it must fail to typecheck.
      dashboardKeys.cards("t1");
      // @ts-expect-error same for propertyDetail.
      dashboardKeys.propertyDetail("t1", "redes11");
      // @ts-expect-error same for propertyTimeline.
      dashboardKeys.propertyTimeline("t1", "redes11", {});
    }
  });
});
