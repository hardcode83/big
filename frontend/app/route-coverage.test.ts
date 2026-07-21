import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { routeRegistry } from "@/features/shell/navigation/route-registry";

// Vitest runs from the frontend package root.
const appDir = join(process.cwd(), "app");

function findPageFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = `${dir}/${entry.name}`;
    if (entry.isDirectory()) {
      return findPageFiles(full);
    }
    return entry.name === "page.tsx" ? [full] : [];
  });
}

function routeIdOf(file: string): string | undefined {
  const match = readFileSync(file, "utf8").match(/routeId="([^"]+)"/);
  return match?.[1];
}

describe("App Router placeholder coverage (tasks 7.2–7.6)", () => {
  const pageFiles = findPageFiles(appDir);
  const wiredRouteIds = pageFiles
    .map(routeIdOf)
    .filter((id): id is string => id !== undefined);

  it("wires exactly one placeholder page per registered route", () => {
    expect(new Set(wiredRouteIds)).toEqual(
      new Set(routeRegistry.map((route) => route.id)),
    );
    expect(wiredRouteIds.length).toBe(routeRegistry.length);
  });

  it("has a page for every PRD §24 surface with no orphan pages", () => {
    // Every page file either wires a routeId or is the root redirect.
    const nonPlaceholder = pageFiles.filter(
      (file) => routeIdOf(file) === undefined,
    );
    expect(nonPlaceholder.length).toBe(1); // only the (workspace) root redirect
  });
});
