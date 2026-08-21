import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const appDir = join(process.cwd(), "app");

function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    return entry.isDirectory() ? walk(full) : [full];
  });
}

describe("error boundary hierarchy (D18, task 8.3)", () => {
  const files = walk(appDir);

  it("places a segment error.tsx beside each shell layout", () => {
    const groups = [
      "(workspace)",
      "(public)",
      join("(field)", "cleaner"),
      join("(field)", "tech"),
      join("(guest)", "guest", "[token]"),
    ];
    for (const group of groups) {
      expect(existsSync(join(appDir, group, "layout.tsx")), group).toBe(true);
      expect(existsSync(join(appDir, group, "error.tsx")), group).toBe(true);
    }
  });

  it("uses global-error only at the root (no root app/error.tsx above the shells)", () => {
    expect(existsSync(join(appDir, "global-error.tsx"))).toBe(true);
    expect(existsSync(join(appDir, "error.tsx"))).toBe(false);
  });

  it("keeps global-error self-contained (renders its own html, no ErrorState import)", () => {
    const source = readFileSync(join(appDir, "global-error.tsx"), "utf8");
    expect(source).toContain("<html");
    expect(source).not.toContain("ErrorState");
  });
});

/**
 * Pages whose suspense boundary is **required by the framework**, not ceremony.
 * Each entry needs a reason, because the rule below exists to stop decorative
 * loading states from accumulating on pages that do not need them.
 *
 * - `(workspace)/conversations/page.tsx`: `ConversationsView` reads the selected
 *   conversation with `useSearchParams()` (change `conversations-inbox`, design
 *   D5). With `output: "standalone"` and no `force-dynamic`, a prerenderable route
 *   that reads the search params without a boundary fails `next build`, which that
 *   change's R7.5 requires to pass with no backend running.
 */
const PAGES_NEEDING_SUSPENSE = new Set(["(workspace)/conversations/page.tsx"]);

describe("no ceremonial loading/Suspense on placeholders (D18, task 8.5)", () => {
  const files = walk(appDir);

  it("adds no loading.tsx anywhere in the app tree", () => {
    expect(files.filter((f) => f.endsWith("loading.tsx"))).toEqual([]);
  });

  it("has no page importing Suspense or LoadingState without needing it", () => {
    const pages = files
      .filter((f) => f.endsWith("page.tsx"))
      .filter(
        (f) =>
          ![...PAGES_NEEDING_SUSPENSE].some((suffix) => f.endsWith(suffix)),
      );
    expect(pages.length).toBeGreaterThan(0);
    for (const page of pages) {
      const source = readFileSync(page, "utf8");
      expect(source, page).not.toContain("Suspense");
      expect(source, page).not.toContain("LoadingState");
    }
  });

  it("keeps the exemption honest: every exempt page really does use the boundary", () => {
    for (const suffix of PAGES_NEEDING_SUSPENSE) {
      const page = files.find((f) => f.endsWith(suffix));
      expect(page, suffix).toBeDefined();
      const source = readFileSync(page!, "utf8");
      expect(source, suffix).toContain("Suspense");
    }
  });
});
