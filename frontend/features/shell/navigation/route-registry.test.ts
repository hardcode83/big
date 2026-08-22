import { describe, expect, it } from "vitest";

import {
  getRouteById,
  routeRegistry,
  type ShellRouteDescriptor,
} from "@/features/shell/navigation/route-registry";

/** The exact surfaces defined by PRD §24 (independent list for coverage). */
const PRD_24_SURFACES = [
  "/login",
  "/forgot-password",
  "/dashboard",
  "/properties",
  "/properties/[id]",
  "/timeline",
  "/reservations",
  "/reservations/[id]",
  "/cleaning",
  "/incidents",
  "/incidents/[id]",
  "/conversations",
  "/conversations/[id]",
  "/pricing",
  "/statements",
  "/reviews",
  "/approvals",
  "/settings",
  "/settings/integrations",
  "/cleaner",
  "/cleaner/tasks/[id]",
  "/tech",
  "/tech/incidents/[id]",
  "/guest/[token]",
].sort();

const ALLOWED_KEYS = new Set<keyof ShellRouteDescriptor>([
  "id",
  "pattern",
  "href",
  "titleKey",
  "descriptionKey",
  "metadataTitleKey",
  "metadataDescriptionKey",
  "breadcrumbKeys",
  "icon",
  "profile",
  "match",
  "navigationGroup",
  "order",
]);

const VALID_PROFILES = new Set([
  "workspace",
  "cleaner",
  "technician",
  "public",
  "guest",
]);

describe("route registry (D4 / PRD §24)", () => {
  it("covers exactly the PRD §24 surfaces (no more, no less)", () => {
    const patterns = routeRegistry.map((r) => r.pattern).sort();
    expect(patterns).toEqual(PRD_24_SURFACES);
  });

  it("has unique route ids", () => {
    const ids = routeRegistry.map((r) => r.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("has unique hrefs among navigable routes", () => {
    const hrefs = routeRegistry
      .map((r) => r.href)
      .filter((h): h is string => h !== undefined);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it("assigns every route a valid shell profile", () => {
    for (const route of routeRegistry) {
      expect(VALID_PROFILES.has(route.profile)).toBe(true);
    }
  });

  it("keeps `/tech` as a public slug while using the technician profile", () => {
    const tech = getRouteById("tech");
    expect(tech?.pattern).toBe("/tech");
    expect(tech?.href).toBe("/tech");
    expect(tech?.profile).toBe("technician");
  });

  it("never navigates to the guest token route (no href) and matches by prefix", () => {
    const guest = getRouteById("guest");
    expect(guest?.href).toBeUndefined();
    expect(guest?.pattern).toBe("/guest/[token]");
    expect(guest?.match).toBe("prefix");
  });

  it("gives dynamic routes no href and static navigable routes a static href", () => {
    for (const route of routeRegistry) {
      const isDynamic = route.pattern.includes("[");
      if (isDynamic) {
        expect(route.href).toBeUndefined();
      }
      if (route.href !== undefined) {
        expect(route.href).not.toContain("[");
      }
    }
  });

  it("carries only shell metadata — no roles/endpoints/data fields", () => {
    for (const route of routeRegistry) {
      for (const key of Object.keys(route)) {
        expect(ALLOWED_KEYS.has(key as keyof ShellRouteDescriptor)).toBe(true);
      }
    }
  });

  // F7: per-property assertions for `reservation-detail` (R1.2). The generic
  // "gives dynamic routes no href" test only covers the no-href invariant;
  // it does not catch the regression of putting `reservation-detail` in
  // the sidebar (which would add `navigationGroup`) or of breaking the
  // exact-match breadcrumb link (which would change `breadcrumbKeys`).
  it("reservation-detail mirrors the property-detail descriptor shape (R1.2)", () => {
    const detail = getRouteById("reservation-detail");
    expect(detail?.pattern).toBe("/reservations/[id]");
    expect(detail?.match).toBe("exact");
    expect(detail?.href).toBeUndefined();
    expect(detail?.navigationGroup).toBeUndefined();
    // breadcrumbKeys are `navigation:routes.<id>.title` strings; the
    // shape is the same as `property-detail` (`crumbs("reservations",
    // "reservation-detail")`) — the regression this guards against is
    // changing the order, the count, or losing the root `reservations`
    // crumb.
    expect(detail?.breadcrumbKeys).toEqual([
      "navigation:routes.reservations.title",
      "navigation:routes.reservation-detail.title",
    ]);
  });
});
