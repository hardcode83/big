import { describe, expect, it } from "vitest";

import {
  selectNavigationGroups,
  selectPrimaryNavigation,
  selectRoutesForProfile,
} from "@/features/shell/navigation/select-routes";

describe("route selection per profile (D4)", () => {
  it("returns only a profile's own routes", () => {
    for (const profile of ["workspace", "cleaner", "technician", "public", "guest"] as const) {
      const routes = selectRoutesForProfile(profile);
      expect(routes.length).toBeGreaterThan(0);
      expect(routes.every((r) => r.profile === profile)).toBe(true);
    }
  });

  it("excludes Cleaner and Technician from Workspace navigation", () => {
    const ids = selectPrimaryNavigation("workspace").map((r) => r.id);
    expect(ids).not.toContain("cleaner");
    expect(ids).not.toContain("tech");
    expect(ids).not.toContain("cleaner-task");
    expect(ids).not.toContain("tech-incident");
  });

  it("excludes dynamic and child routes from primary navigation", () => {
    const ids = selectPrimaryNavigation("workspace").map((r) => r.id);
    expect(ids).not.toContain("property-detail");
    // settings/integrations is a child route (no order) — not a primary link.
    expect(ids).not.toContain("settings-integrations");
    expect(ids).toContain("settings");
  });

  it("orders Workspace navigation by group then order", () => {
    const groups = selectNavigationGroups("workspace");
    expect(groups.map((g) => g.group)).toEqual([
      "operation",
      "work",
      "revenue",
      "administration",
    ]);
    expect(groups[0].routes.map((r) => r.id)).toEqual([
      "dashboard",
      "timeline",
      "properties",
    ]);
    expect(groups[1].routes.map((r) => r.id)).toEqual([
      "reservations",
      "cleaning",
      "incidents",
      "conversations",
      "approvals",
    ]);
  });

  it("gives Cleaner and Technician only their own single navigable destination", () => {
    expect(selectPrimaryNavigation("cleaner").map((r) => r.id)).toEqual([
      "cleaner",
    ]);
    expect(selectPrimaryNavigation("technician").map((r) => r.id)).toEqual([
      "tech",
    ]);
    // No navigation groups for field shells.
    expect(selectNavigationGroups("cleaner")).toEqual([]);
    expect(selectNavigationGroups("technician")).toEqual([]);
  });

  it("gives Public and Guest no primary module navigation", () => {
    expect(selectPrimaryNavigation("public")).toEqual([]);
    expect(selectPrimaryNavigation("guest")).toEqual([]);
  });
});
