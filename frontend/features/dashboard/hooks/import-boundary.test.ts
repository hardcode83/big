import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Enforces the R3 swap boundary at the hooks layer: hooks must depend only on the
 * `DashboardDataSource` interface and the composition point, never on the mock
 * implementation or its fixtures. (task 7.1 broadens this to the whole feature.)
 *
 * Vitest runs with the frontend package as cwd, so the sources are read relative
 * to it — no Vite-only APIs, so `tsc --noEmit` (R6.2) stays green.
 */
const hooksDir = join(process.cwd(), "features/dashboard/hooks");

function sourceFiles(): string[] {
  return readdirSync(hooksDir).filter(
    (f) =>
      (f.endsWith(".ts") || f.endsWith(".tsx")) &&
      !f.endsWith(".test.ts") &&
      !f.endsWith(".test.tsx"),
  );
}

describe("hooks import boundary (R3)", () => {
  it("no hook imports the mock source or its fixtures", () => {
    const files = sourceFiles();
    expect(files.length).toBeGreaterThan(0);

    for (const file of files) {
      const src = readFileSync(join(hooksDir, file), "utf8");
      expect(src, `${file} must not import from a /mock/ path`).not.toMatch(
        /from\s+["'][^"']*\/mock\//,
      );
      expect(src, `${file} must not reference MockDashboardSource`).not.toMatch(
        /MockDashboardSource/,
      );
    }
  });
});
