import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Feature-wide R3 swap boundary (task 7.1): no component, hook, store, or lib in
 * the dashboard feature may import the mock implementation or its fixtures. The
 * ONLY places allowed to know about the mock are the composition point
 * (`data/index.ts`) and the mock module itself (`data/mock/`). This is what lets
 * `HttpDashboardSource` replace `MockDashboardSource` by editing one file.
 *
 * Vitest runs with the frontend package as cwd, so sources are read relative to
 * it — no Vite-only APIs, so `tsc --noEmit` stays green.
 */
const featureDir = join(process.cwd(), "features/dashboard");
const ALLOWED = new Set(["data/index.ts"]);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      // The mock module is the one place allowed to define/reference the mock.
      return entry.name === "mock" ? [] : sourceFiles(full);
    }
    if (!/\.(ts|tsx)$/.test(entry.name) || /\.test\.(ts|tsx)$/.test(entry.name)) {
      return [];
    }
    return [full];
  });
}

describe("dashboard feature import boundary (R3)", () => {
  it("no component/hook/store/lib imports the mock source or fixtures", () => {
    const files = sourceFiles(featureDir).filter(
      (f) => !ALLOWED.has(relative(featureDir, f)),
    );
    expect(files.length).toBeGreaterThan(0);

    for (const file of files) {
      const src = readFileSync(file, "utf8");
      const rel = relative(featureDir, file);
      // Import *from* a mock path, or import the mock symbol — not comment mentions.
      expect(src, `${rel} must not import from a /mock/ path`).not.toMatch(
        /from\s+["'][^"']*\/mock\//,
      );
      expect(src, `${rel} must not import MockDashboardSource`).not.toMatch(
        /import\b[^;]*MockDashboardSource/,
      );
    }
  });
});
