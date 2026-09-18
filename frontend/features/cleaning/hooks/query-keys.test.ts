import { describe, expect, it } from "vitest";

import { cleaningKeys } from "./query-keys";

describe("cleaningKeys (R1, R2.5, R3)", () => {
  it("scopes every key to the tenant", () => {
    const keys = [
      cleaningKeys.tasks("tenant-1", {}, 1),
      cleaningKeys.tasksPrefix("tenant-1"),
      cleaningKeys.task("tenant-1", "task-9"),
      cleaningKeys.cleaners("tenant-1"),
      cleaningKeys.properties("tenant-1"),
    ];
    for (const key of keys) {
      expect(key.slice(0, 2)).toEqual(["tenant", "tenant-1"]);
    }
  });

  it("gives the three resources distinct keys", () => {
    expect(new Set([
      JSON.stringify(cleaningKeys.tasks("tenant-1", {}, 1)),
      JSON.stringify(cleaningKeys.cleaners("tenant-1")),
      JSON.stringify(cleaningKeys.properties("tenant-1")),
    ]).size).toBe(3);
  });

  it("caches each filter/page combination apart", () => {
    const combinations = [
      cleaningKeys.tasks("tenant-1", {}, 1),
      cleaningKeys.tasks("tenant-1", {}, 2),
      cleaningKeys.tasks("tenant-1", { propertyId: "property-1" }, 1),
      cleaningKeys.tasks("tenant-1", { status: "CREATED" }, 1),
      cleaningKeys.tasks(
        "tenant-1",
        { propertyId: "property-1", status: "CREATED" },
        1,
      ),
    ].map((key) => JSON.stringify(key));

    expect(new Set(combinations).size).toBe(combinations.length);
  });

  it("keeps a different tenant's task key distinct for the same filters", () => {
    expect(cleaningKeys.tasks("tenant-1", {}, 1)).not.toEqual(
      cleaningKeys.tasks("tenant-2", {}, 1),
    );
  });

  it("makes tasksPrefix a prefix of every task key (design D9)", () => {
    const prefix = cleaningKeys.tasksPrefix("tenant-1");
    const keys = [
      cleaningKeys.tasks("tenant-1", {}, 1),
      cleaningKeys.tasks("tenant-1", { propertyId: "property-1" }, 4),
      cleaningKeys.tasks("tenant-1", { status: "COMPLETED" }, 7),
    ];

    for (const key of keys) {
      expect(key.slice(0, prefix.length)).toEqual(prefix);
      expect(key.length).toBeGreaterThan(prefix.length);
    }
  });

  it("does not reach the catalogs from the task prefix", () => {
    const prefix = cleaningKeys.tasksPrefix("tenant-1");
    for (const key of [
      cleaningKeys.cleaners("tenant-1"),
      cleaningKeys.properties("tenant-1"),
    ]) {
      expect(key.slice(0, prefix.length)).not.toEqual(prefix);
    }
  });

  it("details a task under the ['tenant', tenantId, 'cleaning-task'] prefix (design D4, R1.1)", () => {
    const key = cleaningKeys.task("tenant-1", "task-9");
    expect(key.slice(0, 3)).toEqual(["tenant", "tenant-1", "cleaning-task"]);
  });

  it("scopes a task's photos under ['tenant', tenantId, 'cleaning-photos', taskId] (R2.1)", () => {
    const key = cleaningKeys.photos("tenant-1", "task-9");
    expect(key.slice(0, 3)).toEqual(["tenant", "tenant-1", "cleaning-photos"]);
    expect(key).toContain("task-9");
  });

  it("keeps a different task's photos key distinct, same tenant (R2.1)", () => {
    expect(cleaningKeys.photos("tenant-1", "task-9")).not.toEqual(
      cleaningKeys.photos("tenant-1", "task-10"),
    );
  });

  it("keeps a different tenant's photos key distinct for the same task (R2.1)", () => {
    expect(cleaningKeys.photos("tenant-1", "task-9")).not.toEqual(
      cleaningKeys.photos("tenant-2", "task-9"),
    );
  });
});
