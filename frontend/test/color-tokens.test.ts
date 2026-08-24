import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { declarationsOf, readCss } from "./css-tokens";

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
 * Three checks, and the third is not a variation of the first two:
 *
 *   1. a raw numeric Tailwind colour scale (`bg-emerald-100`, `text-gray-700`);
 *   2. a `dark:` variant;
 *   3. a colour utility naming a token `globals.css` does not declare.
 *
 * The first two look for what should not be there. The third looks for what is
 * MISSING, and only it could have caught `bg-card` — six shipped card surfaces
 * painting nothing at all, because `--color-card` was never declared (design
 * D13). A guard that only checks for surplus reads a tree with six invisible
 * surfaces as clean.
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
  "app/global-error.tsx": ["#555", "#ccc"],
};

/** Every numeric colour scale Tailwind ships, as the utilities that name one. */
const RAW_SCALE =
  /\b(bg|text|border|ring|fill|stroke|outline|divide|decoration|shadow|accent|caret|placeholder|from|via|to)-(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b/g;

/** The Tailwind variant, not the word. See `stripCode` for why that matters. */
const DARK_VARIANT = /\bdark:/g;

/** Every prefix that can carry a colour. Shared by checks 3 and 4. */
const COLOR_PREFIX =
  "bg|text|border|ring|fill|stroke|outline|divide|decoration|accent|caret|placeholder|from|via|to|shadow";

/**
 * An optional variant chain: `hover:`, `focus-visible:`, `sm:`, `group-hover:`,
 * and any stack of them.
 *
 * This exists because the first version of `COLOR_UTILITY` opened with
 * `(?<![\w:/-])`, and that lookbehind does not STRIP a variant — it excludes the
 * match entirely. At the `b` of `hover:bg-card` the preceding character is `:`,
 * the lookbehind fails, and nothing is reported. Nineteen live utilities in this
 * tree were invisible to check 3 for that reason, and `hover:text-destructive`
 * — one keystroke from the bug D13 exists to catch — produced zero violations.
 * Found by the section-8 security and QA reviewers.
 */
const VARIANT = "(?:[a-z][a-z0-9-]*:)*";

/**
 * A colour utility and the token it names, e.g. `hover:bg-surface` → `surface`.
 *
 * The opacity modifier (`/15`) and the variant chain are outside the captured
 * name — matched and discarded, not excluded: `bg-state-error/15` names
 * `state-error`, and so does `hover:bg-state-error/15`.
 */
const COLOR_UTILITY = new RegExp(
  `(?<![\\w/-])${VARIANT}(${COLOR_PREFIX})-([a-z][a-z0-9-]*)(?:\\/\\d{1,3})?\\b`,
  "g",
);

/**
 * A colour that bypasses the token layer entirely: an arbitrary value
 * (`bg-[#e11d48]`, `text-[oklch(.7_.2_20)]`) or Tailwind v4's CSS-variable
 * shorthand (`bg-(--danger)`).
 *
 * Checks 1 and 3 are both blind to these by construction — `RAW_SCALE` needs a
 * named palette and `COLOR_UTILITY` needs `[a-z]` after the prefix, so `[` and
 * `(` never match. That left the whole arbitrary-value channel ungated while the
 * guard reported zero, which is the failure mode this file is supposed to make
 * impossible. Raised independently by the architect and security reviewers.
 */
const ARBITRARY_UTILITY = new RegExp(
  `(?<![\\w/-])${VARIANT}(?:${COLOR_PREFIX})-(?:\\[([^\\]\\s]+)\\]|\\((--[^)\\s]+)\\))`,
  "g",
);

/**
 * An arbitrary value that IS a colour: a hex, any CSS colour function, or a
 * variable reference.
 */
const ARBITRARY_IS_COLOR =
  /^(#|rgba?\(|hsla?\(|hwb\(|oklch\(|oklab\(|lab\(|lch\(|color\(|color-mix\(|var\(--|--)/i;

/**
 * An arbitrary value that is plainly NOT a colour — a length, a number, a URL,
 * a computed dimension.
 *
 * `text-[0.6875rem]` is a font size, and `bg-[url(...)]` an image. Both share
 * the prefix of a colour utility and neither breaks R1.5, so neither is a
 * violation. Everything that is neither this nor `ARBITRARY_IS_COLOR` fails, so
 * an unrecognised form still fails closed.
 */
const ARBITRARY_IS_DIMENSION =
  /^(-?[\d.]+([a-z%]{1,4})?$|calc\(|clamp\(|min\(|max\(|url\(|length:|image:)/i;

/**
 * A colour hex in an inline style, e.g. `style={{ color: "#555" }}`.
 *
 * Scoped to a CSS colour PROPERTY rather than matching bare `#abc123`, because
 * the tree contains `"Booking.com #1234"` — a booking reference that a naive
 * hex regex reads as a four-digit `#RGBA` shorthand. Anchoring on the property
 * name is what separates a colour from a number that starts with a hash.
 *
 * Without this check the `#555`/`#ccc` entry in `EXCEPTIONS` was INERT: no check
 * ever produced a hex needle, so `allowed()` was never consulted for one, and
 * the pinning assertion below advertised a bounded exemption for a channel that
 * was never gated. A second `style={{ color: "#555" }}` in any other component
 * passed silently. Found by the section-8 security reviewer.
 */
const STYLE_HEX =
  /\b(?:color|background|backgroundColor|borderColor|borderTopColor|borderRightColor|borderBottomColor|borderLeftColor|outlineColor|fill|stroke|caretColor|textDecorationColor|columnRuleColor|border|outline|boxShadow|textShadow)\s*:\s*"[^"]*?(#[0-9a-fA-F]{3,8})\b[^"]*"/g;

/**
 * What each prefix can legally name that is NOT a colour.
 *
 * A whitelist, not a blacklist, and that is the whole design: an unrecognised
 * value fails and the message tells you the two ways out — declare the token, or
 * add the keyword here. A blacklist of known non-colours would pass anything
 * new, which is exactly how `bg-card` survived.
 */
const NON_COLOR: Record<string, RegExp> = {
  bg: /^(none|inherit|current|transparent|auto|cover|contain|center|top|bottom|left|right|repeat|repeat-x|repeat-y|no-repeat|repeat-round|repeat-space|fixed|local|scroll|clip-\w+|origin-\w+|blend-[\w-]+|gradient-to-[a-z]+|linear-[\w-]+|radial-[\w-]+|conic-[\w-]+)$/,
  text: /^(inherit|current|transparent|xs|sm|base|lg|xl|\d?xl|left|center|right|justify|start|end|ellipsis|clip|wrap|nowrap|balance|pretty)$/,
  // `s`/`e` are the logical (start/end) sides, absent from the tree today but a
  // one-keystroke neighbour of `l`/`r` — flagged by the section-8 QA reviewer.
  border: /^(inherit|current|transparent|none|solid|dashed|dotted|double|hidden|collapse|separate|spacing-[\w.]+|[xytrblse](-\d+)?|\d+)$/,
  ring: /^(inherit|current|transparent|inset|offset-[\w-]+|\d+)$/,
  fill: /^(none|inherit|current|transparent)$/,
  stroke: /^(none|inherit|current|transparent|\d+)$/,
  outline: /^(none|inherit|current|transparent|solid|dashed|dotted|double|hidden|offset-[\w-]+|\d+)$/,
  divide: /^(inherit|current|transparent|solid|dashed|dotted|double|none|[xy](-reverse)?|\d+)$/,
  decoration: /^(inherit|current|transparent|slice|clone|solid|double|dotted|dashed|wavy|auto|from-font|\d+)$/,
  accent: /^(auto|inherit|current|transparent)$/,
  caret: /^(inherit|current|transparent)$/,
  placeholder: /^(inherit|current|transparent)$/,
  // Gradient stops and coloured shadows. `RAW_SCALE` already listed these four
  // prefixes, so a `from-emerald-500` failed — but `from-nonexistent-token` was
  // never checked for existence at all, because check 3 did not know the prefix.
  // Dormant today (no gradients or coloured shadows in the tree) and closed
  // anyway: the section-8 QA reviewer found it by probing.
  from: /^(inherit|current|transparent|\d{1,3}%)$/,
  via: /^(inherit|current|transparent|\d{1,3}%)$/,
  to: /^(inherit|current|transparent|\d{1,3}%)$/,
  shadow: /^(none|inner|inherit|current|transparent|xs|sm|md|lg|xl|\d?xl)$/,
};

/**
 * Comments are stripped before anything is counted, and this is load-bearing.
 *
 * `lib/ui/status-tone.ts` explains in prose why the `dark:` variant was removed,
 * so the word appears three times inside a doc comment there. Counting it would
 * make the file that FIXED R6.5 the file that fails the guard for it — and the
 * obvious workaround, rewording the comment, would delete the explanation to
 * satisfy a regex. The same class of false positive that task 10.4 hit with
 * `fonts.googleapis.com`.
 *
 * Strings are NOT stripped: a class name lives in a string literal, so that is
 * precisely where the guard has to look.
 */
function stripCode(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    // Not just `[^:]`: that guards `https://` but not a protocol-relative URL in
    // a string — `src="//cdn.example/x.png" className="bg-red-500"` would have
    // the rest of its line deleted, live class included, before any check ran.
    // Excluding a preceding quote closes it. Raised as latent by the section-8
    // security reviewer; measured at zero occurrences today, fixed anyway
    // because a stripper that eats real code fails open.
    .replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1");
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
      if (!/\.tsx?$/.test(entry)) continue;
      // D12 exempts tests: they may name classes, and pinning a class string is
      // exactly what `property-state-badge.test.tsx` exists to do.
      // Anchored to the extension, not a substring anywhere in the name: a
      // helper called `checkout.test.helpers.tsx` is not a test and must not
      // exempt itself from the guard by how it is named.
      if (/\.test\.tsx?$/.test(entry)) continue;
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

/** The colour tokens `@theme inline` exposes to Tailwind, as utility names. */
const DECLARED_TOKENS = new Set(
  Object.keys(declarationsOf(readCss(join(FRONTEND, "app/globals.css")), "@theme inline"))
    .filter((name) => name.startsWith("--color-"))
    .map((name) => name.slice("--color-".length)),
);

const FILES = sourceFiles();

type Violation = { file: string; found: string };

function scan(
  pattern: RegExp,
  pick: (match: RegExpMatchArray) => string | null,
): Violation[] {
  const violations: Violation[] = [];
  for (const file of FILES) {
    const source = stripCode(readFileSync(file, "utf8"));
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
    const violations = scan(COLOR_UTILITY, (match) => {
      const [utility, prefix, name] = match;
      if (DECLARED_TOKENS.has(name)) return null;
      if (NON_COLOR[prefix]?.test(name)) return null;
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
    const violations = scan(ARBITRARY_UTILITY, (match) => {
      const value = match[1] ?? match[2] ?? "";
      if (ARBITRARY_IS_COLOR.test(value)) return match[0];
      // A length, a number, a URL: shares the prefix, is not a colour, breaks
      // nothing. `text-[0.6875rem]` is the live example in this tree.
      if (ARBITRARY_IS_DIMENSION.test(value)) return null;
      // Neither — fail closed, as `NON_COLOR` does for the named forms.
      return match[0];
    });
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
    const violations = scan(STYLE_HEX, (match) => match[1]);
    expect(format(violations)).toEqual([]);
  });

  it("keeps the exception list to D12's three, so none can be smuggled in", () => {
    // An exception nobody re-reads becomes a hole. Pinning the list means adding
    // one is a deliberate edit to this assertion, with a reviewer attached.
    expect(EXCEPTIONS).toEqual({
      "components/ui/sheet.tsx": ["bg-black/50"],
      "app/global-error.tsx": ["#555", "#ccc"],
    });
  });

  it("scans a tree that is actually there, so a broken walk cannot pass empty", () => {
    // Every assertion above is «found nothing». If `sourceFiles()` returned an
    // empty list — a renamed directory, a bad join — all of them would pass.
    expect(FILES.length).toBeGreaterThan(100);
    expect(DECLARED_TOKENS.size).toBe(25);

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
    ]);
    // And the four D12 named are still among them, so deriving cannot narrow.
    for (const root of ["app", "components", "features", "lib"]) {
      expect(ROOTS, `${root} must be scanned`).toContain(root);
    }
  });
});
