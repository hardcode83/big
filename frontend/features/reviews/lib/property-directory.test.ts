import { describe, expect, it } from "vitest";

import {
  buildPropertyDirectory,
  resolvePropertyIdentity,
} from "./property-directory";

describe("buildPropertyDirectory", () => {
  it("indexes entries by id", () => {
    const dir = buildPropertyDirectory([
      { id: "p1", internalCode: "A1", name: "Loft A" },
      { id: "p2", internalCode: "A2", name: "Loft B" },
    ]);
    expect(dir.size).toBe(2);
    expect(dir.get("p1")?.name).toBe("Loft A");
  });

  it("returns an empty map when the catalog is undefined", () => {
    const dir = buildPropertyDirectory(undefined);
    expect(dir.size).toBe(0);
  });
});

describe("resolvePropertyIdentity", () => {
  const catalog = [
    { id: "p1", internalCode: "A1", name: "Loft A" },
    { id: "p2", internalCode: "A2", name: "Loft B" },
  ];

  it("returns resolved when the id is in the catalog", () => {
    const directory = {
      index: buildPropertyDirectory(catalog),
      isPending: false,
    };
    expect(resolvePropertyIdentity("p1", directory)).toEqual({
      kind: "resolved",
      value: catalog[0],
    });
  });

  it("returns pending when the catalog is in flight and the id is missing", () => {
    const directory = {
      index: buildPropertyDirectory(undefined),
      isPending: true,
    };
    expect(resolvePropertyIdentity("p3", directory)).toEqual({
      kind: "pending",
    });
  });

  it("returns unavailable when the catalog settled without the id", () => {
    const directory = {
      index: buildPropertyDirectory(catalog),
      isPending: false,
    };
    expect(resolvePropertyIdentity("p3", directory)).toEqual({
      kind: "unavailable",
    });
  });
});