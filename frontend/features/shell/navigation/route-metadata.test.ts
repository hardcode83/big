import { describe, expect, it, vi } from "vitest";

import { routeMetadata } from "@/features/shell/navigation/route-metadata";
import { routeRegistry } from "@/features/shell/navigation/route-registry";

const cookie = vi.hoisted(() => ({ value: undefined as string | undefined }));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: () => (cookie.value ? { value: cookie.value } : undefined),
  }),
}));

describe("routeMetadata (D19)", () => {
  it("resolves a localized title for a known route", async () => {
    cookie.value = undefined;
    expect((await routeMetadata("dashboard")).title).toBe("Panel");
  });

  it("marks every registered route noindex, nofollow", async () => {
    cookie.value = undefined;
    for (const route of routeRegistry) {
      const meta = await routeMetadata(route.id);
      expect(meta.robots, route.id).toEqual({ index: false, follow: false });
    }
  });

  it("never leaks an id/token/param into dynamic-route metadata", async () => {
    cookie.value = undefined;
    for (const id of [
      "property-detail",
      "cleaner-task",
      "tech-incident",
      "guest",
    ]) {
      const meta = await routeMetadata(id);
      expect(String(meta.title ?? "")).not.toMatch(/\[|\]|\d/);
    }
  });

  it("keeps the guest token out of its metadata entirely", async () => {
    cookie.value = undefined;
    const meta = await routeMetadata("guest");
    expect(JSON.stringify(meta)).not.toMatch(/token/i);
    expect(meta.title).toBe("Portal del huésped");
  });
});
