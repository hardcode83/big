import { describe, expect, it } from "vitest";

import { normalizeReviewFilters, reviewsKeys } from "./query-keys";

describe("normalizeReviewFilters", () => {
  it("drops undefined filters and canonicalizes page to 1", () => {
    expect(normalizeReviewFilters({})).toEqual({ page: 1 });
  });

  it("preserves the explicit null on sentiment (different from absent)", () => {
    const a = normalizeReviewFilters({ sentiment: null });
    const b = normalizeReviewFilters({});
    expect(a).toEqual({ page: 1, sentiment: null });
    expect(b).toEqual({ page: 1 });
    expect(JSON.stringify(a)).not.toBe(JSON.stringify(b));
  });

  it("emits keys in a fixed order regardless of input order", () => {
    const a = normalizeReviewFilters({
      status: "DRAFTED",
      propertyId: "p1",
    });
    const b = normalizeReviewFilters({
      propertyId: "p1",
      status: "DRAFTED",
    });
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });
});

describe("reviewsKeys", () => {
  it("listPrefix is a prefix of list for any filter and page", () => {
    const tenantId = "t1";
    const a = reviewsKeys.listPrefix(tenantId);
    const b = reviewsKeys.list(tenantId, { status: "DRAFTED" }, 3);
    expect(b.slice(0, a.length)).toEqual(a);
  });

  it("two equivalent renders produce the same list key", () => {
    const tenantId = "t1";
    const a = reviewsKeys.list(
      tenantId,
      { status: "DRAFTED", propertyId: "p1" },
      1,
    );
    const b = reviewsKeys.list(
      tenantId,
      { propertyId: "p1", status: "DRAFTED" },
      1,
    );
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });

  it("detail and draft keys differ per review", () => {
    const tenantId = "t1";
    expect(reviewsKeys.detail(tenantId, "r1")).not.toEqual(
      reviewsKeys.draft(tenantId, "r1"),
    );
  });
});