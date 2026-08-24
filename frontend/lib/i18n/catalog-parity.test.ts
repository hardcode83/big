import { readdirSync } from "node:fs";
import { join } from "node:path";

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

/**
 * The catalog files actually on disk, per locale — the **filesystem**, not the
 * registry, which is the whole point of the test below.
 *
 * Read with `node:fs` rather than `import.meta.glob`: the glob is a Vite-only
 * API and this repo does not pull `vite/client` into `tsconfig.json`, so it
 * typechecks nowhere — `npm run typecheck` failed with `TS2339: Property 'glob'
 * does not exist on type 'ImportMeta'`, and that command is a CI gate
 * (`.github/workflows/frontend-tests.yml`). Vitest runs in Node, so plain
 * `readdirSync` gives the same list with types that already exist.
 */
function catalogNames(locale: "es" | "en"): string[] {
  const dir = join(process.cwd(), "locales", locale);
  return readdirSync(dir)
    .filter((file) => file.endsWith(".json"))
    .map((file) => file.replace(/\.json$/, ""))
    .sort();
}

describe("namespace registration (R6.5)", () => {
  /**
   * Guards the failure mode the loop below **cannot** see: this file iterates
   * `NAMESPACES`, so a catalog missing from that array is not checked — it is
   * silently skipped, and the suite stays green with one test fewer. Nothing
   * else catches it either: the two `import`s and the two `resources` entries
   * are enforced by `tsc`, but the `NAMESPACES` entry is just a string in a
   * list. Raised by the QA panel on `pricing-web` section 6, which removed
   * `"pricing"` from the array and watched the suite go from 12 passing tests
   * to 11 passing tests without a single failure.
   *
   * Comparing against the files on disk rather than against a hand-written list
   * means a future namespace is covered the day its catalog is added.
   */
  it("registers every catalog file in NAMESPACES, in both locales", () => {
    expect(catalogNames("es")).toEqual([...NAMESPACES].sort());
    expect(catalogNames("en")).toEqual([...NAMESPACES].sort());
  });

  it("has a resources entry for every registered namespace", () => {
    for (const ns of NAMESPACES) {
      expect(resources.es[ns], `es resources missing ${ns}`).toBeTypeOf(
        "object",
      );
      expect(resources.en[ns], `en resources missing ${ns}`).toBeTypeOf(
        "object",
      );
    }
  });
});

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
