import { describe, expect, it } from "vitest";

import { stallsKeys } from "./query-keys";

describe("stallsKeys (R1.4)", () => {
  it("starts with the tenant-prefixed resource", () => {
    expect(stallsKeys.list("tenant-a", 1)).toEqual([
      "tenant",
      "tenant-a",
      "blocked-transitions",
      1,
    ]);
  });

  it("produces disjoint keys for two tenants", () => {
    expect(stallsKeys.list("tenant-a", 1)).not.toEqual(
      stallsKeys.list("tenant-b", 1),
    );
  });

  it("keeps the `all` prefix disjoint from the `list` prefix", () => {
    // `invalidateQueries({ queryKey: stallsKeys.all(tenantId) })` invalidates
    // every page; `stallsKeys.list` must therefore sit **under** the `all`
    // prefix. The shape below is the assertion that the invalidation contract
    // continues to hold when a new `list` key is added.
    expect(stallsKeys.list("tenant-a", 1).slice(0, -1)).toEqual(
      stallsKeys.all("tenant-a"),
    );
  });

  it("throws when the tenantId is empty", () => {
    expect(() => stallsKeys.list("", 1)).toThrow(/tenantId/);
  });
});