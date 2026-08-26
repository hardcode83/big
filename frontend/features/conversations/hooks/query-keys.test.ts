import { describe, expect, it } from "vitest";

import { conversationsKeys } from "./query-keys";

/**
 * Tenant-isolation guarantees for the conversations query keys (R6.6,
 * `sdd/steering/security.md` rule 1, `sdd/specs/messaging-ai.md` R1).
 *
 * The implementation already uses `tenantScopedKey` for every key; these
 * tests pin the contract so a regression that drops the `tenantId` prefix,
 * flips it to a different resource, or lets an empty tenant through, fails
 * red instead of silently polluting a neighbour's cache.
 */
describe("conversationsKeys — tenant isolation (R6.6)", () => {
  it("list keys for two different tenants never collide", () => {
    const a = conversationsKeys.list("tenant-a", { status: "OPEN" });
    const b = conversationsKeys.list("tenant-b", { status: "OPEN" });
    expect(a).not.toEqual(b);
    expect(a).toContain("tenant-a");
    expect(b).toContain("tenant-b");
    // The very first segment must be the literal "tenant" — that is what
    // `tenantScopedKey` enforces and what guarantees a cross-tenant lookup
    // cannot match.
    expect(a[0]).toBe("tenant");
    expect(b[0]).toBe("tenant");
  });

  it("detail keys for two different tenants never collide", () => {
    expect(conversationsKeys.detail("tenant-a", "c1")).not.toEqual(
      conversationsKeys.detail("tenant-b", "c1"),
    );
  });

  it("messages keys for two different tenants never collide", () => {
    expect(conversationsKeys.messages("tenant-a", "c1", 1)).not.toEqual(
      conversationsKeys.messages("tenant-b", "c1", 1),
    );
  });

  it("listPrefix / messagesPrefix carry the tenantId", () => {
    expect(conversationsKeys.listPrefix("tenant-a")[0]).toBe("tenant");
    expect(conversationsKeys.listPrefix("tenant-a")).toContain("tenant-a");
    expect(conversationsKeys.messagesPrefix("tenant-a", "c1")).toContain("tenant-a");
    expect(conversationsKeys.messagesPrefix("tenant-a", "c1")).toContain("c1");
  });

  it("tenantScopedKey rejects an empty tenantId", () => {
    expect(() => conversationsKeys.list("", {})).toThrow(/tenant/i);
    expect(() => conversationsKeys.detail("", "c1")).toThrow(/tenant/i);
    expect(() => conversationsKeys.messages("", "c1", 1)).toThrow(/tenant/i);
  });

  it("two equivalent filter objects produce the same list key (cache stability)", () => {
    const filtersA = { status: "OPEN" as const, page: 1, perPage: 20 };
    const filtersB = { status: "OPEN" as const, page: 1, perPage: 20 };
    // TanStack Query uses deep equality on the query key, so the object
    // identity does not have to match — but the structural key does.
    expect(conversationsKeys.list("t", filtersA)).toEqual(
      conversationsKeys.list("t", filtersB),
    );
  });

  it("different filters produce different list keys (no false cache hits)", () => {
    const a = conversationsKeys.list("t", { status: "OPEN" });
    const b = conversationsKeys.list("t", { status: "RESOLVED" });
    expect(a).not.toEqual(b);
  });

  it("no JSON.stringify is involved in the key shape", () => {
    // The fix is structural: passing the object directly means two renders
    // with equivalent filters produce a structurally identical key. There
    // should be no string serialization in the produced key.
    const key = conversationsKeys.list("t", { status: "OPEN" });
    expect(key.some((segment) => typeof segment === "string" && segment.startsWith("{"))).toBe(
      false,
    );
  });
});
