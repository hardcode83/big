import { describe, expect, it } from "vitest";

import { NAMESPACES, resources } from "@/lib/i18n/resources";
import { routeRegistry } from "@/features/shell/navigation/route-registry";

type Json = string | number | boolean | null | { [k: string]: Json } | Json[];

function keyPaths(value: Json, prefix = ""): string[] {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return [prefix];
  }
  return Object.entries(value).flatMap(([k, v]) =>
    keyPaths(v as Json, prefix ? `${prefix}.${k}` : k),
  );
}

function resolveKey(locale: "es" | "en", namespacedKey: string): unknown {
  const [ns, path] = namespacedKey.includes(":")
    ? namespacedKey.split(":")
    : ["common", namespacedKey];
  const table = (resources[locale] as Record<string, Json>)[ns];
  return path
    .split(".")
    .reduce<unknown>(
      (acc, segment) =>
        acc && typeof acc === "object"
          ? (acc as Record<string, unknown>)[segment]
          : undefined,
      table,
    );
}

describe("catalog parity ES/EN (D13)", () => {
  for (const ns of NAMESPACES) {
    it(`has identical key sets in both locales for "${ns}"`, () => {
      const es = keyPaths(resources.es[ns] as Json).sort();
      const en = keyPaths(resources.en[ns] as Json).sort();
      expect(en).toEqual(es);
    });
  }

  it("resolves every route descriptor key in both locales", () => {
    for (const route of routeRegistry) {
      const keys = [
        route.titleKey,
        route.descriptionKey,
        route.metadataTitleKey,
        route.metadataDescriptionKey,
        ...route.breadcrumbKeys,
      ];
      for (const key of keys) {
        expect(typeof resolveKey("es", key), `es ${key}`).toBe("string");
        expect(typeof resolveKey("en", key), `en ${key}`).toBe("string");
      }
    }
  });
});
