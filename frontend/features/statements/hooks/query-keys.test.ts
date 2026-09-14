import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import type { OwnerStatementFilters } from "../data";
import { normalizeStatementFilters, statementsKeys } from "./query-keys";

describe("statementsKeys tenant isolation", () => {
  const tenantA = "tenant-a";
  const tenantB = "tenant-b";

  it("scopes list, detail, and properties keys by tenant", () => {
    for (const key of [
      statementsKeys.list(tenantA, {}, 1),
      statementsKeys.detail(tenantA, "statement-1"),
      statementsKeys.properties(tenantA),
    ]) {
      expect(key.slice(0, 2)).toEqual(["tenant", tenantA]);
    }
  });

  it("refuses to create a globally scoped key", () => {
    expect(() => statementsKeys.list("", {}, 1)).toThrow();
    expect(() => statementsKeys.detail("", "statement-1")).toThrow();
    expect(() => statementsKeys.properties("")).toThrow();
  });

  it("keeps cache entries and their data separate when the tenant changes", () => {
    const queryClient = new QueryClient();
    const keyA = statementsKeys.list(tenantA, { status: "READY" }, 1);
    const keyB = statementsKeys.list(tenantB, { status: "READY" }, 1);

    queryClient.setQueryData(keyA, { items: ["tenant-a-data"] });

    expect(keyA).not.toEqual(keyB);
    expect(queryClient.getQueryData(keyA)).toEqual({
      items: ["tenant-a-data"],
    });
    expect(queryClient.getQueryData(keyB)).toBeUndefined();
  });
});

describe("normalizeStatementFilters", () => {
  it("uses a fixed filter order regardless of input construction order", () => {
    const a: OwnerStatementFilters = {
      status: "READY",
      periodStartTo: "2026-09-30",
      propertyId: "property-1",
      periodStartFrom: "2026-09-01",
    };
    const b: OwnerStatementFilters = {
      periodStartFrom: "2026-09-01",
      propertyId: "property-1",
      periodStartTo: "2026-09-30",
      status: "READY",
    };

    expect(normalizeStatementFilters(a, 2)).toEqual(
      normalizeStatementFilters(b, 2),
    );
    expect(JSON.stringify(statementsKeys.list("tenant-a", a, 2))).toBe(
      JSON.stringify(statementsKeys.list("tenant-a", b, 2)),
    );
  });

  it("omits undefined filters and canonicalizes an absent page to 1", () => {
    expect(normalizeStatementFilters({})).toEqual({ page: 1 });
    expect(statementsKeys.list("tenant-a", {})).toEqual(
      statementsKeys.list("tenant-a", {}, 1),
    );
  });

  it("keeps distinct filters and pages distinct", () => {
    expect(statementsKeys.list("tenant-a", {})).not.toEqual(
      statementsKeys.list("tenant-a", { propertyId: "property-1" }),
    );
    expect(statementsKeys.list("tenant-a", {}, 1)).not.toEqual(
      statementsKeys.list("tenant-a", {}, 2),
    );
  });
});

describe("statementsKeys prefixes", () => {
  it("makes listPrefix a prefix only for the same tenant's list keys", () => {
    const prefix = statementsKeys.listPrefix("tenant-a");
    const list = statementsKeys.list("tenant-a", { status: "SENT" }, 3);
    const otherTenantList = statementsKeys.list(
      "tenant-b",
      { status: "SENT" },
      3,
    );

    expect(list.slice(0, prefix.length)).toEqual(prefix);
    expect(otherTenantList.slice(0, prefix.length)).not.toEqual(prefix);
  });
});
