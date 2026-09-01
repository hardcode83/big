import { describe, expect, it } from "vitest";

import { incidentsKeys } from "./query-keys";

/**
 * The tenant-isolation test `sdd/steering/security.md` rule 1 requires of every
 * new module ("Tests automáticos que demuestran que un tenant no accede a datos
 * de otro — obligatorios en cada módulo nuevo").
 *
 * For a frontend-only change the isolation surface is the **cache identity**,
 * not SQL: `context`, `photos` and `listPrefix` are new here, and a key that
 * forgot its tenant discriminator would survive a session switch and serve one
 * tenant's access notes and signed photo URLs to the next. The precedent is
 * `features/cleaning/hooks/query-keys.test.ts`.
 */
describe("incidentsKeys tenant isolation (steering security rule 1, R1.3)", () => {
  const A = "tenant-a";
  const B = "tenant-b";

  const forTenant = (tenantId: string) => ({
    list: incidentsKeys.list(tenantId, { status: "ASSIGNED" }),
    listUnfiltered: incidentsKeys.list(tenantId),
    detail: incidentsKeys.detail(tenantId, "i1"),
    context: incidentsKeys.context(tenantId, "i1"),
    photos: incidentsKeys.photos(tenantId, "i1"),
    listPrefix: incidentsKeys.listPrefix(tenantId),
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
    // `listPrefix` invalidation walks by prefix, so a tenant id that prefixed
    // another's would let one invalidation reach across the boundary.
    const a = incidentsKeys.listPrefix(A);
    const b = incidentsKeys.listPrefix(B);
    expect(b.slice(0, a.length)).not.toEqual(a);
    expect(a.slice(0, b.length)).not.toEqual(b);
  });

  it("gives the four resources distinct keys within one tenant", () => {
    const { list, detail, context, photos } = forTenant(A);
    expect(
      new Set([list, detail, context, photos].map((k) => JSON.stringify(k))).size,
    ).toBe(4);
  });

  it("shares one key between the row and the detail context (R1.3)", () => {
    expect(incidentsKeys.context(A, "i1")).toEqual(incidentsKeys.context(A, "i1"));
    expect(incidentsKeys.context(A, "i1")).not.toEqual(
      incidentsKeys.context(A, "i2"),
    );
  });

  it("makes listPrefix a prefix of every list key in the same tenant", () => {
    const prefix = incidentsKeys.listPrefix(A);
    for (const key of [
      incidentsKeys.list(A),
      incidentsKeys.list(A, { status: "ASSIGNED" }),
      incidentsKeys.list(A, { status: "RESOLVED", page: 2 }),
    ]) {
      expect(key.slice(0, prefix.length)).toEqual(prefix);
    }
  });
});
