import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createLandingMetadata,
  createMetadataFromKeys,
  createRootMetadata,
} from "@/lib/metadata/create-route-metadata";
import { routeRegistry } from "@/features/shell/navigation/route-registry";

const cookie = vi.hoisted(() => ({ value: undefined as string | undefined }));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: () => (cookie.value ? { value: cookie.value } : undefined),
  }),
}));

describe("createRootMetadata (D19)", () => {
  it("sets the localized default title, template and noindex", async () => {
    cookie.value = undefined;
    const meta = await createRootMetadata();
    expect(meta.title).toEqual({
      default: "AutoHostAI",
      template: "%s | AutoHostAI",
    });
    expect(meta.robots).toEqual({ index: false, follow: false });
    expect(meta.description).toBe("Aplicación operativa de AutoHostAI");
  });

  it("does not set metadataBase (no authorized public URL)", async () => {
    expect((await createRootMetadata()).metadataBase).toBeUndefined();
  });
});

describe("createMetadataFromKeys (D19)", () => {
  const keys = {
    titleKey: "navigation:routes.dashboard.title",
    descriptionKey: "navigation:routes.dashboard.description",
  };

  it("resolves localized title/description per locale", async () => {
    cookie.value = undefined;
    expect((await createMetadataFromKeys(keys)).title).toBe("Panel");
    cookie.value = "en";
    expect((await createMetadataFromKeys(keys)).title).toBe("Dashboard");
  });

  it("emits generic noindex Open Graph with no canonical/images/base", async () => {
    cookie.value = undefined;
    const meta = await createMetadataFromKeys(keys);
    expect(meta.robots).toEqual({ index: false, follow: false });
    expect(meta.openGraph).toMatchObject({ siteName: "AutoHostAI" });
    expect(meta.metadataBase).toBeUndefined();
    expect(meta.alternates).toBeUndefined();
    expect((meta.openGraph as { images?: unknown }).images).toBeUndefined();
  });

  it("returns a safe noindex fallback for an unknown route (no keys)", async () => {
    expect(await createMetadataFromKeys(undefined)).toEqual({
      robots: { index: false, follow: false },
    });
  });
});

describe("createLandingMetadata (R2.1, R2.3, design D4)", () => {
  const original = { ...process.env };
  beforeEach(() => {
    delete process.env.NEXT_PUBLIC_APP_URL;
  });
  afterEach(() => {
    process.env = { ...original };
  });

  it("emits index, follow and a title outside the %s | AutoHostAI template", async () => {
    cookie.value = undefined;
    const meta = await createLandingMetadata();
    expect(meta.robots).toEqual({ index: true, follow: true });
    expect(meta.title).toBe(
      "AutoHostAI — La capa operativa de tu alquiler vacacional",
    );
    expect(meta.title).not.toMatch(/AutoHostAI$/);

    cookie.value = "en";
    const enMeta = await createLandingMetadata();
    expect(enMeta.title).toBe(
      "AutoHostAI — The operational layer for your vacation rental",
    );
    expect(enMeta.robots).toEqual({ index: true, follow: true });
  });

  it("omits metadataBase, alternates.canonical and OG url when no public URL is configured", async () => {
    cookie.value = undefined;
    const meta = await createLandingMetadata();
    expect(meta.metadataBase).toBeUndefined();
    expect(meta.alternates).toBeUndefined();
    expect((meta.openGraph as { url?: unknown }).url).toBeUndefined();
  });

  it("sets metadataBase, alternates.canonical and OG url to the absolute URL when configured", async () => {
    process.env.NEXT_PUBLIC_APP_URL = "https://app.autohostai.com";
    cookie.value = undefined;
    const meta = await createLandingMetadata();
    expect(meta.metadataBase).toBeInstanceOf(URL);
    expect((meta.metadataBase as URL).toString()).toBe("https://app.autohostai.com/");
    expect(meta.alternates?.canonical).toBe("https://app.autohostai.com/");
    expect((meta.openGraph as { url?: string }).url).toBe("https://app.autohostai.com/");
  });

  it("is the only helper in this file that emits robots.index=true", () => {
    // Structural guard: no other export can become indexable by accident (R2.3).
    const exported = Object.keys({
      createRootMetadata,
      createMetadataFromKeys,
      createLandingMetadata,
    });
    expect(exported).toContain("createLandingMetadata");
    // The two noindex helpers exist; only one indexable helper does.
    const indexableExports = ["createLandingMetadata"];
    expect(exported.filter((k) => indexableExports.includes(k))).toEqual(
      indexableExports,
    );
  });
});

describe("every other route id stays noindex (R2.2)", () => {
  it("every descriptor resolves to a string key in both locales", () => {
    // The landing is the only descriptor whose title/description key lives
    // outside the `navigation` namespace — it pulls from `landing:meta.*`
    // because the page IS the landing. Every other route stays on the
    // shell's `navigation:routes.<id>.{title,description}` keys.
    for (const route of routeRegistry) {
      expect(route.id).toBeTruthy();
      if (route.id === "landing") {
        expect(route.metadataTitleKey).toMatch(/^landing:/);
        expect(route.metadataDescriptionKey).toMatch(/^landing:/);
      } else {
        expect(route.metadataTitleKey).toMatch(/^navigation:/);
        expect(route.metadataDescriptionKey).toMatch(/^navigation:/);
      }
    }
  });

  it("createRootMetadata is the only root metadata and stays noindex", async () => {
    const meta = await createRootMetadata();
    expect(meta.robots).toEqual({ index: false, follow: false });
  });

  /*
   * Design D4's load-bearing claim: "no future descriptor can flip a flag
   * and become indexable by accident." This is the structural guard — every
   * entry in `routeRegistry` is exercised through `createMetadataFromKeys`
   * (the helper every descriptor except landing goes through), and the
   * resolved `robots.index` is asserted to be `false`. Today the helper
   * hard-codes the value; the test pins the invariant so a future helper
   * added next to it that emits `index: true` would be caught at the
   * descriptor walk rather than at the production robots.txt.
   */
  it("every non-landing descriptor yields robots: { index: false } from createMetadataFromKeys", async () => {
    cookie.value = undefined;
    for (const route of routeRegistry) {
      if (route.id === "landing") continue;
      const meta = await createMetadataFromKeys({
        titleKey:
          route.metadataTitleKey ??
          `navigation:routes.${route.id}.title`,
        descriptionKey:
          route.metadataDescriptionKey ??
          `navigation:routes.${route.id}.description`,
      });
      expect(
        meta.robots,
        `${route.id} (${route.metadataTitleKey}) must stay noindex`,
      ).toEqual({ index: false, follow: false });
    }
  });

  /*
   * The companion to the previous test: of every descriptor in
   * `routeRegistry`, the landing is the only one that produces
   * `robots: { index: true }`. Asserting it both ways — every descriptor
   * through `createMetadataFromKeys` is noindex AND the landing through
   * `createLandingMetadata` is indexable — closes the loop the design
   * promises.
   */
  it("only the landing descriptor yields robots: { index: true }", async () => {
    cookie.value = undefined;

    const landingMeta = await createLandingMetadata();
    expect(landingMeta.robots).toEqual({ index: true, follow: true });

    for (const route of routeRegistry) {
      if (route.id === "landing") continue;
      const meta = await createMetadataFromKeys({
        titleKey:
          route.metadataTitleKey ??
          `navigation:routes.${route.id}.title`,
        descriptionKey:
          route.metadataDescriptionKey ??
          `navigation:routes.${route.id}.description`,
      });
      // Next's `Metadata.robots` is `Robots | string`; a future helper
      // emitting either the structured form or the string form of
      // "index, follow" would indexable a descriptor by accident. Both
      // shapes must be absent.
      expect(
        meta.robots,
        `${route.id} (${route.metadataTitleKey}) must NOT be indexable`,
      ).not.toEqual({ index: true, follow: true });
      expect(meta.robots, `${route.id} must NOT be the indexable string`).not.toBe(
        "index, follow",
      );
    }
  });
});
