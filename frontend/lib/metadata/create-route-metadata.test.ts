import { describe, expect, it, vi } from "vitest";

import {
  createMetadataFromKeys,
  createRootMetadata,
} from "@/lib/metadata/create-route-metadata";

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
