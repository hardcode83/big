import { describe, expect, it } from "vitest";

import { buildBreadcrumbs } from "@/features/shell/navigation/breadcrumbs";

describe("buildBreadcrumbs (D5)", () => {
  it("returns a single crumb for a top-level route", () => {
    expect(buildBreadcrumbs("/dashboard", "workspace")).toEqual([
      "navigation:routes.dashboard.title",
    ]);
  });

  it("returns the explicit chain for a detail route (generic label, no id)", () => {
    expect(buildBreadcrumbs("/properties/123", "workspace")).toEqual([
      "navigation:routes.properties.title",
      "navigation:routes.property-detail.title",
    ]);
  });

  it("returns an empty trail for an unknown path", () => {
    expect(buildBreadcrumbs("/nope", "workspace")).toEqual([]);
  });
});
