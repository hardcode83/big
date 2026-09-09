import { describe, expect, it } from "vitest";

import { approvalsKeys } from "./query-keys";

/**
 * The tenant-isolation test `sdd/steering/security.md` rule 1 requires of
 * every new module. The precedent is `features/incidents/hooks/query-keys.test.ts`.
 */
describe("approvalsKeys tenant isolation (steering security rule 1, R1.1)", () => {
  const A = "tenant-a";
  const B = "tenant-b";

  const forTenant = (tenantId: string) => ({
    list: approvalsKeys.list(tenantId, { status: "PENDING" }),
    listUnfiltered: approvalsKeys.list(tenantId),
    listPrefix: approvalsKeys.listPrefix(tenantId),
  });

  it("prefixes every key with its tenant", () => {
    for (const key of Object.values(forTenant(A))) {
      expect(key.slice(0, 2)).toEqual(["tenant", A]);
    }
  });

  it("keeps every key distinct between two tenants asking for the same thing", () => {
    const a = forTenant(A);
    const b = forTenant(B);
    for (const name of Object.keys(a) as (keyof typeof a)[]) {
      expect(a[name]).not.toEqual(b[name]);
    }
  });

  it("never lets one tenant's key be a prefix of another's", () => {
    const a = approvalsKeys.listPrefix(A);
    const b = approvalsKeys.listPrefix(B);
    expect(b.slice(0, a.length)).not.toEqual(a);
    expect(a.slice(0, b.length)).not.toEqual(b);
  });

  it("makes listPrefix a prefix of every list key in the same tenant", () => {
    const prefix = approvalsKeys.listPrefix(A);
    for (const key of [
      approvalsKeys.list(A),
      approvalsKeys.list(A, { status: "PENDING" }),
      approvalsKeys.list(A, { status: "APPROVED", perPage: 5 }),
      approvalsKeys.list(A, { status: "REJECTED", perPage: 5 }),
    ]) {
      expect(key.slice(0, prefix.length)).toEqual(prefix);
    }
  });

  it("gives distinct keys to distinct filters within one tenant", () => {
    const keys = [
      approvalsKeys.list(A),
      approvalsKeys.list(A, { status: "PENDING" }),
      approvalsKeys.list(A, { status: "APPROVED", perPage: 5 }),
      approvalsKeys.list(A, { status: "REJECTED", perPage: 5 }),
    ];
    expect(new Set(keys.map((k) => JSON.stringify(k))).size).toBe(keys.length);
  });
});
