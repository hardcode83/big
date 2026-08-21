import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * R7.3 / design D4: the inbox has exactly one implementation of its data source
 * (HTTP), and only `data/index.ts` is allowed to name it. Test fixtures live in
 * the test files that use them, so no runtime module may import a fixture module
 * or a second implementation.
 *
 * Vitest runs with the frontend package as cwd, so sources are read relative to
 * it — no Vite-only APIs, which keeps `tsc --noEmit` green.
 */
const featureDir = join(process.cwd(), "features/conversations");
const ALLOWED_TO_IMPORT_THE_IMPLEMENTATION = new Set(["data/index.ts"]);

function runtimeSourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      return runtimeSourceFiles(full);
    }
    if (!/\.(ts|tsx)$/.test(entry.name) || /\.test\.(ts|tsx)$/.test(entry.name)) {
      return [];
    }
    return [full];
  });
}

describe("conversations feature data boundary (R7.3, D4)", () => {
  it("has no mock or fixture module in the tree", () => {
    expect(existsSync(join(featureDir, "data/mock"))).toBe(false);
    const fixtures = runtimeSourceFiles(featureDir).filter((file) =>
      /(^|\/)(fixtures|mock|mocks|stubs)\.(ts|tsx)$/.test(file),
    );
    expect(fixtures).toEqual([]);
  });

  it("no runtime module imports a fixture or a second implementation", () => {
    const files = runtimeSourceFiles(featureDir);
    expect(files.length).toBeGreaterThan(0);

    for (const file of files) {
      const src = readFileSync(file, "utf8");
      const rel = relative(featureDir, file);

      expect(src, `${rel} must not import from a mock/fixture path`).not.toMatch(
        /from\s+["'][^"']*\/(mock|mocks|fixtures|stubs)(\/|["'])/,
      );
      expect(src, `${rel} must not import a test file`).not.toMatch(
        /from\s+["'][^"']*\.test["']/,
      );

      if (!ALLOWED_TO_IMPORT_THE_IMPLEMENTATION.has(rel)) {
        expect(
          src,
          `${rel} must depend on ConversationsDataSource, not import the HTTP implementation`,
        ).not.toMatch(/import\b[^;]*HttpConversationsSource/);
      }
    }
  });

  it("only the composition point constructs the data source", () => {
    const composedIn = runtimeSourceFiles(featureDir).filter((file) =>
      /createAuthenticatedClients|createApiClient/.test(
        readFileSync(file, "utf8"),
      ),
    );
    expect(composedIn.map((file) => relative(featureDir, file))).toEqual([
      "data/index.ts",
    ]);
  });
});
