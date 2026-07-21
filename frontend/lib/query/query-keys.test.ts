import { describe, expect, it } from "vitest";

import { tenantScopedKey } from "@/lib/query/query-keys";

describe("tenantScopedKey (D11)", () => {
  it("prefixes every key with tenant + tenantId + resource", () => {
    expect(tenantScopedKey("t1", "properties")).toEqual([
      "tenant",
      "t1",
      "properties",
    ]);
  });

  it("appends an arbitrary scope after the resource", () => {
    expect(tenantScopedKey("t1", "properties", "p9", { page: 2 })).toEqual([
      "tenant",
      "t1",
      "properties",
      "p9",
      { page: 2 },
    ]);
  });

  it("refuses to build a key without a tenantId", () => {
    expect(() => tenantScopedKey("", "properties")).toThrow(/tenantId/);
  });

  it("refuses to build a key without a resource", () => {
    expect(() => tenantScopedKey("t1", "")).toThrow(/resource/);
  });
});
