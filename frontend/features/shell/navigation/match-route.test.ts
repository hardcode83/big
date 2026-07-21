import { describe, expect, it } from "vitest";

import {
  isRouteActive,
  matchRoute,
  normalizePath,
} from "@/features/shell/navigation/match-route";
import { getRouteById } from "@/features/shell/navigation/route-registry";

describe("normalizePath (D5)", () => {
  it("strips query and hash", () => {
    expect(normalizePath("/dashboard?tab=1#x")).toBe("/dashboard");
  });
  it("removes a trailing slash except for root", () => {
    expect(normalizePath("/properties/")).toBe("/properties");
    expect(normalizePath("/")).toBe("/");
  });
});

describe("matchRoute (D5)", () => {
  it("matches a static route exactly", () => {
    expect(matchRoute("/dashboard", "workspace")?.id).toBe("dashboard");
  });
  it("prefers the most specific (dynamic detail over list)", () => {
    expect(matchRoute("/properties", "workspace")?.id).toBe("properties");
    expect(matchRoute("/properties/123", "workspace")?.id).toBe(
      "property-detail",
    );
  });
  it("matches nested child routes", () => {
    expect(matchRoute("/settings", "workspace")?.id).toBe("settings");
    expect(matchRoute("/settings/integrations", "workspace")?.id).toBe(
      "settings-integrations",
    );
  });
  it("matches dynamic field and guest routes", () => {
    expect(matchRoute("/cleaner/tasks/abc", "cleaner")?.id).toBe("cleaner-task");
    expect(matchRoute("/tech/incidents/9", "technician")?.id).toBe(
      "tech-incident",
    );
    expect(matchRoute("/guest/anytoken", "guest")?.id).toBe("guest");
  });
  it("ignores trailing slash and query", () => {
    expect(matchRoute("/timeline/?x=1", "workspace")?.id).toBe("timeline");
  });
  it("returns undefined for the wrong profile or unknown path", () => {
    expect(matchRoute("/dashboard", "cleaner")).toBeUndefined();
    expect(matchRoute("/nope", "workspace")).toBeUndefined();
  });
});

describe("isRouteActive (D5)", () => {
  it("keeps a prefix route active for its descendants", () => {
    const properties = getRouteById("properties")!;
    expect(isRouteActive(properties, "/properties")).toBe(true);
    expect(isRouteActive(properties, "/properties/123")).toBe(true);
    expect(isRouteActive(properties, "/property")).toBe(false);
  });
  it("keeps an exact route active only for its own path", () => {
    const dashboard = getRouteById("dashboard")!;
    expect(isRouteActive(dashboard, "/dashboard")).toBe(true);
    expect(isRouteActive(dashboard, "/dashboard/x")).toBe(false);
  });
  it("marks settings active on its integrations child", () => {
    const settings = getRouteById("settings")!;
    expect(isRouteActive(settings, "/settings/integrations")).toBe(true);
  });
});
