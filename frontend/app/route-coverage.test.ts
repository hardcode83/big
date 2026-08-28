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
// property-detail; cleaning-manager-view: cleaning; properties-web: properties;
// timeline-web: timeline; pricing-web: pricing).
//
// The bare `page.tsx` is the root at `/`, which the `landing-public` change
// promoted from the `(workspace)` group — it now wires the `landing` route.
// It MUST stay LAST: `Object.entries` iterates in insertion order and the
// matching is `endsWith(suffix)`, so the generic `"page.tsx"` would swallow
// every other entry first.
const REAL_PAGE_ROUTE_IDS: Record<string, string> = {
  "(workspace)/cleaning/page.tsx": "cleaning",
  "(workspace)/dashboard/page.tsx": "dashboard",
  "(workspace)/properties/page.tsx": "properties",
  "(workspace)/properties/[id]/page.tsx": "property-detail",
  "(workspace)/timeline/page.tsx": "timeline",
  "(workspace)/reservations/page.tsx": "reservations",
  "(workspace)/reservations/[id]/page.tsx": "reservation-detail",
  "(workspace)/incidents/page.tsx": "incidents",
  "(workspace)/incidents/[id]/page.tsx": "incident-detail",
"(workspace)/conversations/page.tsx": "conversations",
  "(workspace)/conversations/[id]/page.tsx": "conversation-detail",
  "(workspace)/pricing/page.tsx": "pricing",
  "(public)/login/page.tsx": "login",
  "(guest)/guest/[token]/page.tsx": "guest",
  "(authenticated)/welcome/page.tsx": "welcome",
  "page.tsx": "landing",
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
    // Every page file covers a routeId — the (workspace) root redirect was
    // promoted to a real landing page in `landing-public`.
    const uncovered = pageFiles.filter(
      (file) => routeIdOf(file) === undefined,
    );
    expect(uncovered.length).toBe(0);
  });
});
