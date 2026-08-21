import { describe, expect, it } from "vitest";

import type { CleanerSummary, PropertySummary } from "../data";
import { buildDirectory, resolveIdentity } from "./directory";

const cleaners: CleanerSummary[] = [
  { id: "cleaner-1", name: "Marta Ruiz", isActive: true },
  { id: "cleaner-2", name: "Ana Pérez", isActive: false },
];

const properties: PropertySummary[] = [
  { id: "property-1", name: "Redes 11", internalCode: "REDES11" },
];

function settled<T extends { id: string }>(entries: readonly T[]) {
  return { index: buildDirectory(entries), isPending: false };
}

describe("buildDirectory", () => {
  it("indexes a catalog by id", () => {
    expect(buildDirectory(cleaners).get("cleaner-2")).toEqual(cleaners[1]);
  });

  it("gives an empty index for an absent catalog", () => {
    expect(buildDirectory(undefined).size).toBe(0);
  });
});

describe("resolveIdentity (R2.2, R2.3, R2.4, design D5)", () => {
  it("reports a null id as unassigned, not as a load failure (R2.3)", () => {
    expect(resolveIdentity(null, settled(cleaners))).toEqual({
      kind: "unassigned",
    });
  });

  it("reports a catalog still in flight as pending, never as unavailable", () => {
    expect(
      resolveIdentity("cleaner-1", {
        index: buildDirectory(undefined),
        isPending: true,
      }),
    ).toEqual({ kind: "pending" });
  });

  it("reports unavailable when the catalog resolved without that id (R2.4)", () => {
    expect(resolveIdentity("cleaner-99", settled(cleaners))).toEqual({
      kind: "unavailable",
    });
  });

  it("reports unavailable when the catalog failed (R2.4)", () => {
    expect(
      resolveIdentity("cleaner-1", {
        index: buildDirectory(undefined),
        isPending: false,
      }),
    ).toEqual({ kind: "unavailable" });
  });

  it("resolves a present cleaner to her full summary (R2.2)", () => {
    expect(resolveIdentity("cleaner-1", settled(cleaners))).toEqual({
      kind: "resolved",
      value: cleaners[0],
    });
  });

  it("resolves an inactive cleaner just as well (design D4)", () => {
    expect(resolveIdentity("cleaner-2", settled(cleaners))).toEqual({
      kind: "resolved",
      value: cleaners[1],
    });
  });

  it("resolves a property to its internal code and name (R2.1)", () => {
    expect(resolveIdentity("property-1", settled(properties))).toEqual({
      kind: "resolved",
      value: properties[0],
    });
  });

  it("keeps unassigned distinct from every other shape", () => {
    const kinds = new Set([
      resolveIdentity(null, settled(cleaners)).kind,
      resolveIdentity("cleaner-1", {
        index: buildDirectory(undefined),
        isPending: true,
      }).kind,
      resolveIdentity("cleaner-99", settled(cleaners)).kind,
      resolveIdentity("cleaner-1", settled(cleaners)).kind,
    ]);
    expect(kinds).toEqual(
      new Set(["unassigned", "pending", "unavailable", "resolved"]),
    );
  });
});
