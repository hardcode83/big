import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  COLOR_PREFIX,
  DARK_VARIANT,
  NON_COLOR,
  RAW_SCALE,
  STYLE_COLOR,
  applyDirectives,
  arbitraryIsColor,
  arbitraryUtility,
  colorUtility,
  namesAColorToken,
  stripCode,
  styleValueIsHardCodedColor,
} from "./color-tokens";
import { declarationsOf, readCss, stripComments } from "./css-tokens";

/**
 * The guard of design D12 and R6.6, and the third check D13 added.
 *
 * R6.6: «THE SYSTEM SHALL dejar el árbol de `frontend/` sin ninguna referencia a
 * una escala numérica de color de Tailwind … en código no de test para color de
 * superficie, texto o borde, y esto SHALL ser verificable con un grep cuyo
 * resultado quede registrado.» R1.5 adds that no consumer should need a `dark:`
 * variant to express its colour.
 *
 * D12 chose a test over an ESLint rule because `no-restricted-syntax` on class
 * literals is brittle with `cva` and `cn()`, and because R6.6 asks for a COUNT —
 * which this file prints. It follows `test/eslint-boundaries.test.ts`, already
 * the precedent for enforcing a repo rule with a test.
 *
 * Five checks, and the third is not a variation of the others:
 *
 *   1. a raw numeric Tailwind colour scale (`bg-emerald-100`, `text-gray-700`);
 *   2. a theme variant that follows the OS (`dark:`, or the same media query
 *      written as an arbitrary variant);
 *   3. a colour utility naming a token `globals.css` does not declare;
 *   4. a colour that bypasses the token layer (`bg-[#e11d48]`, `bg-(--brand)`);
 *   5. a hard-coded colour in an inline style or a JSX attribute.
 *
 * All but the third look for what should not be there. The third looks for what
 * is MISSING, and only it could have caught `bg-card` — six shipped card
 * surfaces painting nothing at all, because `--color-card` was never declared
 * (design D13). A guard that only checks for surplus reads a tree with six
 * invisible surfaces as clean.
 *
 * Checks 4 and 5 arrived with the section-8 panel; the count above says five
 * because saying three is what let two reviews read the list as exhaustive.
 */

const FRONTEND = join(__dirname, "..");

/**
 * Directories that hold no shipped UI code, pinned so a NEW one is scanned by
 * default rather than silently skipped.
 *
 * D12 named four roots — `app/`, `components/`, `features/`, `lib/` — but R6.6
 * scopes the obligation to «el árbol de `frontend/`», and a hard-coded list
 * cannot tell the difference between "this directory has no colours" and "this
 * directory did not exist when the list was written". Someone adding `hooks/` or
 * `widgets/` would get no coverage and no warning, and `FILES.length` would not
 * move enough to notice. So the roots are derived and the EXCLUSIONS are what
 * gets reviewed.
 */
const NOT_UI = new Set([
  "node_modules", // dependencies
  ".next", // build output
  "coverage", // test output
  "public", // static assets, no TS
  "locales", // JSON catalogues, no TS
  "devops", // Dockerfile and friends
  "scripts", // build tooling, never rendered
  /*
   * Test infrastructure, and the one entry that needs a reason rather than a
   * label.
   *
   * R6.6 scopes the obligation to «código **no de test**», and D12 names four
   * roots — so excluding `test/` is the design, not a gap. Deriving the roots
   * briefly pulled it in, and that surfaced why it must not be: this guard's own
   * pattern module lives in `test/color-tokens.ts`, and its `NON_COLOR` table
   * contains strings like `from-font` (a text-decoration keyword) that read as
   * colour utilities when regex source is scanned as if it were markup. The
   * guard flagged itself.
   *
   * What this gives up is small and worth naming: a test helper that hard-codes
   * a colour is not caught. Helpers do not ship, and `*.test.*` files were
   * already exempt by D12 for the same reason.
   */
  "test",
]);

function uiRoots(): string[] {
  return readdirSync(FRONTEND)
    .filter((entry) => !entry.startsWith("."))
    .filter((entry) => !NOT_UI.has(entry))
    .filter((entry) => statSync(join(FRONTEND, entry)).isDirectory())
    .sort();
}

const ROOTS = uiRoots();

/**
 * The scannable files that sit loose in `frontend/` rather than under a root.
 *
 * `uiRoots()` keeps only directories, so these are not walked — which is right
 * (every one is build configuration, the same category as `scripts/` and
 * `devops/`) but was silent, and silence is how the review of 2026-08-24 found
 * it. Deriving and pinning the list applies this file's own rule to the last
 * place it did not: a NEW loose file is a deliberate edit to the assertion
 * below, where someone decides whether it ships UI.
 */
function looseRootFiles(): string[] {
  return readdirSync(FRONTEND)
    .filter((entry) => !entry.startsWith("."))
    .filter((entry) => SCANNED_EXTENSION.test(entry))
    .filter((entry) => !statSync(join(FRONTEND, entry)).isDirectory())
    .sort();
}

/**
 * The three exceptions of D12, declared and reasoned rather than pattern-matched.
 *
 * Keyed by the exact file, so the exemption cannot spread: a second
 * `bg-black/50` in another component is a failure, which is the point.
 */
const EXCEPTIONS: Record<string, readonly string[]> = {
  // A scrim: identical in both themes by design, and not a numeric scale.
  "components/ui/sheet.tsx": ["bg-black/50"],
  // Replaces the `layout.tsx` that imports `globals.css`, so it literally has no
  // tokens available — the same reason it carries its i18n catalogue inline.
  // The needles are the whole declared values, because check 5 now reports what
  // it read rather than just the hex it found inside a shorthand.
  "app/global-error.tsx": ["#555", "1px solid #ccc"],
  // Renders standalone HTML via `next/og` for the Open Graph image. The
  // generated PNG ships as a static asset and never reaches the runtime CSS
  // tree, so the same no-tokens-available argument applies — the colours
  // are inlined in the JSX `style` prop.
  "app/opengraph-image.tsx": ["#006b5f", "#ffffff"],
};

/*
 * The patterns live in `./color-tokens`, driven from a table by
 * `color-tokens.patterns.test.ts`.
 *
 * They were inline here until the section-8 panel found ten holes in two
 * successive versions — every one invisible to the tree-level assertions below,
 * which are green whenever the tree does not happen to exercise the break. This
 * file now answers «is the tree clean»; that one answers «do the patterns work».
 */

/**
 * Every extension that can carry a utility class.
 *
 * `.tsx?` alone was the whole scan until the review of 2026-08-24: a new
 * `app/print.css` with `@apply bg-red-500 dark:bg-blue-900`, or any `.mjs`/`.jsx`
 * component, was simply never opened — the patterns caught the string fine, the
 * walk never handed it to them. Stylesheets are read through `applyDirectives`
 * rather than whole (see there for why); everything else is read as source.
 */
const SCANNED_EXTENSION = /\.([cm]?jsx?|tsx?|css)$/;

/** The text a file contributes to the scan: `@apply` lists for CSS, code otherwise. */
function scannable(file: string): string {
  const source = readFileSync(file, "utf8");
  return file.endsWith(".css")
    ? applyDirectives(stripComments(source))
    : stripCode(source);
}

function sourceFiles(): string[] {
  const found: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) {
        if (entry === "node_modules" || entry === "generated") continue;
        walk(full);
        continue;
      }
      if (!SCANNED_EXTENSION.test(entry)) continue;
      // D12 exempts tests: they may name classes, and pinning a class string is
      // exactly what `property-state-badge.test.tsx` exists to do.
      // Anchored to the extension, not a substring anywhere in the name: a
      // helper called `checkout.test.helpers.tsx` is not a test and must not
      // exempt itself from the guard by how it is named.
      // Every extension `SCANNED_EXTENSION` accepts, or the two lists disagree:
      // a `foo.test.mjs` would be scanned as production code and its pinned class
      // strings would count as violations.
      if (/\.test\.[cm]?[jt]sx?$/.test(entry)) continue;
      found.push(full);
    }
  };
  for (const root of ROOTS) walk(join(FRONTEND, root));
  return found;
}

function relative(file: string): string {
  return file.slice(FRONTEND.length + 1);
}

function allowed(file: string, needle: string): boolean {
  return (EXCEPTIONS[relative(file)] ?? []).includes(needle);
}

const GLOBALS = readCss(join(FRONTEND, "app/globals.css"));

/** The colour tokens `@theme inline` exposes to Tailwind, as utility names. */
const DECLARED_TOKENS = new Set(
  Object.keys(declarationsOf(GLOBALS, "@theme inline"))
    .filter((name) => name.startsWith("--color-"))
    .map((name) => name.slice("--color-".length)),
);

/**
 * The typographic roles of design D10, read from the PLAIN `@theme` block.
 *
 * `text-display-2xl` is a font size, not a colour, and check 3 has to know that
 * from the same file the roles are declared in — otherwise the ten roles this
 * change introduces fail the guard the moment a screen uses one. Modifier keys
 * (`--text-body-lg--line-height`) are not roles, so they are dropped.
 */
const DECLARED_TEXT_ROLES = new Set(
  Object.keys(declarationsOf(GLOBALS, "@theme"))
    .filter((name) => name.startsWith("--text-"))
    .map((name) => name.slice("--text-".length))
    .filter((role) => !role.includes("--")),
);

const FILES = sourceFiles();

type Violation = { file: string; found: string };

function scan(
  pattern: RegExp,
  pick: (match: RegExpMatchArray) => string | null,
): Violation[] {
  const violations: Violation[] = [];
  for (const file of FILES) {
    const source = scannable(file);
    for (const match of source.matchAll(pattern)) {
      const found = pick(match);
      if (found === null || allowed(file, found)) continue;
      violations.push({ file: relative(file), found });
    }
  }
  return violations;
}

function format(violations: Violation[]): string[] {
  return violations.map(({ file, found }) => `${file}: ${found}`);
}

describe("colour tokens (R6.6, R1.5, design D12 + D13)", () => {
  it("has no raw Tailwind colour scale in shipped code", () => {
    // The count R6.6 asks to have registered. Section 1 measured 44 in three
    // files (`lib/ui/status-tone.ts` 24, and 10 in each of the two incidents
    // components); section 7 took all three to zero.
    const violations = scan(RAW_SCALE, (match) => match[0]);
    expect(format(violations)).toEqual([]);
  });

  it("has no `dark:` variant in shipped code (R1.5)", () => {
    /*
     * Not a style rule — a correctness one. Tailwind's `dark:` follows
     * `prefers-color-scheme`, never our `data-theme` attribute, so on a page
     * forced dark over a light system a `dark:` utility silently does not fire.
     * That was the measured R6.5 defect. D12 rejected redefining the variant to
     * follow the attribute, because it would then stop firing in «no cookie,
     * dark system» — the most common case of all.
     */
    const violations = scan(DARK_VARIANT, (match) => match[0]);
    expect(format(violations)).toEqual([]);
  });

  it("names only colour tokens globals.css actually declares (D13)", () => {
    /*
     * The check that would have caught `bg-card`: a utility whose token does not
     * exist emits no CSS at all, so the surface paints nothing and every other
     * check stays green.
     *
     * Failing here means one of two things, and the message says which applies:
     * the token should be declared in `@theme inline`, or the value is a
     * non-colour Tailwind keyword that belongs in `NON_COLOR` above.
     */
    const violations = scan(colorUtility(), (match) => {
      const [utility, prefix, name] = match;
      if (!namesAColorToken(prefix, name, DECLARED_TEXT_ROLES)) return null;
      if (DECLARED_TOKENS.has(name)) return null;
      // The WHOLE utility, opacity modifier included, so D12's `bg-black/50`
      // exemption matches what it declares and reads as what it exempts.
      return utility;
    });
    expect(format(violations)).toEqual([]);
  });

  it("has no colour that bypasses the token layer entirely (R1.5)", () => {
    /*
     * Arbitrary values and CSS-variable shorthand. `bg-[#e11d48]` satisfies
     * R6.6's literal text — it is not a numeric Tailwind scale — while breaking
     * R1.5 outright: a hard-coded colour cannot depend on the resolved theme.
     * Both were invisible to every other check here.
     */
    const violations = scan(arbitraryUtility(), (match) =>
      arbitraryIsColor(match[1] ?? match[2] ?? "") ? match[0] : null,
    );
    expect(format(violations)).toEqual([]);
  });

  it("has no colour hex in an inline style outside the declared exception", () => {
    /*
     * This is what makes the `#555`/`#ccc` entry in `EXCEPTIONS` mean something.
     * Until this check existed no needle was ever a hex, so that entry gated
     * nothing while the assertion below claimed the list was bounded.
     *
     * `app/global-error.tsx` keeps its exemption on the merits: it substitutes
     * for the `layout.tsx` that imports `globals.css`, so it has no tokens to
     * name — the same reason it carries its i18n catalogue inline.
     */
    const violations = scan(STYLE_COLOR, (match) => {
      const value = match[2] ?? match[3] ?? match[4] ?? "";
      return styleValueIsHardCodedColor(match[1], value) ? value.trim() : null;
    });
    expect(format(violations)).toEqual([]);
  });

  it("keeps the exception list to D12's three, so none can be smuggled in", () => {
    // An exception nobody re-reads becomes a hole. Pinning the list means adding
    // one is a deliberate edit to this assertion, with a reviewer attached.
    expect(EXCEPTIONS).toEqual({
      "components/ui/sheet.tsx": ["bg-black/50"],
      "app/global-error.tsx": ["#555", "1px solid #ccc"],
      "app/opengraph-image.tsx": ["#006b5f", "#ffffff"],
    });
  });

  it("scans a tree that is actually there, so a broken walk cannot pass empty", () => {
    // Every assertion above is «found nothing». If `sourceFiles()` returned an
    // empty list — a renamed directory, a bad join — all of them would pass.
    expect(FILES.length).toBeGreaterThan(100);
    expect(DECLARED_TOKENS.size).toBe(25);
    // The ten typographic roles of D10, which check 3 must not read as colours.
    expect(DECLARED_TEXT_ROLES.size).toBe(10);

    /*
     * The roots are DERIVED from the `frontend/` listing, so what needs pinning
     * is the exclusion list — the only place a directory can now disappear from
     * the scan. A new `hooks/` or `widgets/` is scanned the day it appears; a
     * new exclusion is a deliberate edit to this assertion.
     */
    expect([...NOT_UI].sort()).toEqual([
      ".next",
      "coverage",
      "devops",
      "locales",
      "node_modules",
      "public",
      "scripts",
      "test",
    ]);
    // Exactly D12's four today — and a NEW directory joins them by default,
    // which is the point of deriving rather than listing.
    expect(ROOTS).toEqual(["app", "components", "features", "lib"]);

    // Build configuration, every one of them, and none renders anything. Pinned
    // so a loose `.tsx` dropped in the root has to be looked at rather than
    // skipped by the same `isDirectory` filter that skips these.
    expect(looseRootFiles()).toEqual([
      "eslint.config.mjs",
      "next-env.d.ts",
      "next.config.ts",
      "postcss.config.mjs",
      "vitest.config.ts",
    ]);
  });
});
