import { describe, expect, it } from "vitest";

import type { PropertySummary } from "../data";
import {
  buildPropertyDirectory,
  resolvePropertyIdentity,
} from "./property-directory";

const ATICO: PropertySummary = {
  id: "p-1",
  name: "Ático Sol",
  internalCode: "MAD-01",
};

function directory(
  entries: readonly PropertySummary[] | undefined,
  isPending = false,
) {
  return { index: buildPropertyDirectory(entries), isPending };
}

describe("resolvePropertyIdentity — the four shapes (R2.8, R5.3)", () => {
  it("resolves an id the catalog knows", () => {
    expect(resolvePropertyIdentity("p-1", directory([ATICO]))).toEqual({
      kind: "resolved",
      value: ATICO,
    });
  });

  it("reports `pending` while the catalog is in flight", () => {
    // Not `unavailable`: R2.8 requires «catálogo en vuelo» to be distinguishable
    // from «no está en el catálogo», or the loading window renders a lie.
    expect(
      resolvePropertyIdentity("p-1", directory(undefined, true)),
    ).toEqual({ kind: "pending" });
  });

  it("reports `unavailable` once the catalog settled without the id", () => {
    expect(resolvePropertyIdentity("p-9", directory([ATICO]))).toEqual({
      kind: "unavailable",
    });
  });

  it("collapses a failed catalog into `unavailable`, not into an error", () => {
    // A failed query gives `data === undefined` with `isPending === false`. The
    // row still renders; only the identity degrades (R2.8).
    expect(resolvePropertyIdentity("p-1", directory(undefined))).toEqual({
      kind: "unavailable",
    });
  });

  it("reads a null id as the whole portfolio, never as «unassigned» (R5.3)", () => {
    // The one real difference from `features/cleaning/lib/directory.ts`, where a
    // null id is an absence. Here it is a positive claim about a rule's scope,
    // and only rules can reach it — a recommendation always names a property.
    expect(resolvePropertyIdentity(null, directory([ATICO]))).toEqual({
      kind: "portfolio",
    });
  });

  it("reads a null id as portfolio even while the catalog is in flight", () => {
    // Scope does not depend on the catalog: «whole portfolio» is knowable
    // without resolving any name, so it must not flicker through `pending`.
    expect(
      resolvePropertyIdentity(null, directory(undefined, true)),
    ).toEqual({ kind: "portfolio" });
  });
});

describe("buildPropertyDirectory", () => {
  it("indexes by id", () => {
    const index = buildPropertyDirectory([ATICO]);
    expect(index.get("p-1")).toEqual(ATICO);
    expect(index.size).toBe(1);
  });

  it("gives an empty index for an absent catalog", () => {
    expect(buildPropertyDirectory(undefined).size).toBe(0);
  });
});
