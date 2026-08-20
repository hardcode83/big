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

// Real (non-placeholder) pages that cover a registered route without a
// `routeId` prop. As modules graduate from placeholder to implemented, they are
// listed here by path suffix → route id (dashboard-web-frontend: dashboard,
// property-detail).
const REAL_PAGE_ROUTE_IDS: Record<string, string> = {
  "(workspace)/dashboard/page.tsx": "dashboard",
  "(workspace)/properties/[id]/page.tsx": "property-detail",
  "(workspace)/reservations/page.tsx": "reservations",
  "(workspace)/reservations/[id]/page.tsx": "reservation-detail",
  "(public)/login/page.tsx": "login",
  "(guest)/guest/[token]/page.tsx": "guest",
};

function routeIdOf(file: string): string | undefined {
  const match = readFileSync(file, "utf8").match(/routeId="([^"]+)"/);
  if (match) {
    return match[1];
  }
  const real = Object.entries(REAL_PAGE_ROUTE_IDS).find(([suffix]) =>
    file.endsWith(suffix),
  );
  return real?.[1];
}

describe("App Router coverage (tasks 7.2–7.6)", () => {
  const pageFiles = findPageFiles(appDir);
  const wiredRouteIds = pageFiles
    .map(routeIdOf)
    .filter((id): id is string => id !== undefined);

  it("wires exactly one page (placeholder or real) per registered route", () => {
    expect(new Set(wiredRouteIds)).toEqual(
      new Set(routeRegistry.map((route) => route.id)),
    );
    expect(wiredRouteIds.length).toBe(routeRegistry.length);
  });

  it("has a page for every PRD §24 surface with no orphan pages", () => {
    // Every page file either covers a routeId (placeholder or real) or is the
    // (workspace) root redirect.
    const uncovered = pageFiles.filter(
      (file) => routeIdOf(file) === undefined,
    );
    expect(uncovered.length).toBe(1); // only the (workspace) root redirect
  });
});
