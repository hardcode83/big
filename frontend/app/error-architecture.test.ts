import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const appDir = join(process.cwd(), "app");

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
}

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
 * Each entry also names the client component the boundary must wrap and the module
 * that must still call `useSearchParams()`. Both are asserted below, so an
 * exemption cannot outlive the reason it was granted for: if the boundary stops
 * wrapping the consumer, or the consumer stops reading the search params, the test
 * fails and the entry has to be re-argued or removed.
 *
 * On what the boundary does **not** buy us, so nobody re-derives a stronger claim
 * from this list: `useSearchParams()` without a boundary makes Next bail out of
 * prerendering, and an earlier version of this comment (and of design D5) said that
 * therefore `next build` fails. In this app it does not, and it was verified not to:
 * every page awaits `getServerT()`, which reads `cookies()`, so all routes are
 * already dynamic and there is no static path left for the build to reject. The
 * boundary is still required — it is what keeps the bail-out scoped to the subtree
 * instead of the route, and it is the only reason the route survives the day server
 * i18n stops being a per-request dependency — but `next build` is not the mechanism
 * that would catch its removal. These assertions are.
 */
const PAGES_NEEDING_SUSPENSE = new Map([
  [
    "(workspace)/conversations/page.tsx",
    {
      // Change `conversations-inbox`, design D5 / R7.5.
      boundaryChild: "ConversationsView",
      consumer: join(
        process.cwd(),
        "features",
        "conversations",
        "components",
        "conversations-view.tsx",
      ),
    },
  ],
]);

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
          ![...PAGES_NEEDING_SUSPENSE.keys()].some((suffix) =>
            f.endsWith(suffix),
          ),
      );
    expect(pages.length).toBeGreaterThan(0);
    for (const page of pages) {
      const source = readFileSync(page, "utf8");
      expect(source, page).not.toContain("Suspense");
      expect(source, page).not.toContain("LoadingState");
    }
  });

  it("keeps the exemption honest: the boundary really wraps the search-params consumer", () => {
    for (const [suffix, { boundaryChild }] of PAGES_NEEDING_SUSPENSE) {
      const page = files.find((f) => f.endsWith(suffix));
      expect(page, suffix).toBeDefined();
      // Comments are stripped first: these pages document the boundary in prose that
      // itself contains `<Suspense>`, and matching that would let a page satisfy the
      // exemption by talking about a boundary it does not render.
      const source = stripComments(readFileSync(page!, "utf8"));

      const open = source.indexOf("<Suspense");
      const close = source.indexOf("</Suspense>");
      expect(open, `${suffix}: renders no <Suspense> boundary`).toBeGreaterThan(-1);
      expect(close, `${suffix}: opens a boundary it never closes`).toBeGreaterThan(open);

      // A boundary with no fallback streams nothing and is decoration by any measure.
      const openTag = source.slice(open, source.indexOf(">", open));
      expect(openTag, `${suffix}: <Suspense> without a fallback`).toContain("fallback");

      // The point of the exemption: the boundary must enclose the client component,
      // not merely appear somewhere in the same file.
      const wrapped = source.slice(open, close);
      expect(
        wrapped,
        `${suffix}: <Suspense> does not wrap <${boundaryChild}>`,
      ).toContain(`<${boundaryChild}`);
    }
  });

  it("keeps the exemption honest: the exempt page's consumer still reads the search params", () => {
    for (const [suffix, { consumer }] of PAGES_NEEDING_SUSPENSE) {
      expect(existsSync(consumer), `${suffix}: ${consumer} is gone`).toBe(true);
      const source = stripComments(readFileSync(consumer, "utf8"));
      expect(
        source,
        `${suffix}: ${consumer} no longer calls useSearchParams(), so the exemption has no reason left`,
      ).toContain("useSearchParams(");
    }
  });
});
