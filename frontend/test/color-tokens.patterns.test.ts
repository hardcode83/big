import { describe, expect, it } from "vitest";

import {
  DARK_VARIANT,
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

/**
 * The guard's own tests.
 *
 * `color-tokens.test.ts` asserts «the tree is clean», which is the requirement —
 * but it is green whenever the tree does not happen to exercise a broken pattern.
 * Two review panels found **ten** holes in this guard that way, one after
 * another, each invisible to the tree-level assertions.
 *
 * So every hole is a row below, named after what got through. A regex change that
 * reopens one fails here with the case in the message, whether or not any file in
 * `frontend/` happens to use it.
 */

/** Declared tokens, as the real guard reads them from `@theme inline`. */
const DECLARED = new Set([
  "background",
  "foreground",
  "surface",
  "surface-high",
  "muted",
  "muted-foreground",
  "primary",
  "primary-foreground",
  "state-error",
  "state-error-text",
]);

/**
 * The ten typographic roles of D10, as the real guard reads them from the plain
 * `@theme` block. They are font sizes, so no `--color-*` will ever declare them
 * and check 3 has to be told, or every screen that uses one fails the build.
 */
const TEXT_ROLES = new Set([
  "display-2xl",
  "display-xl",
  "display-lg-mobile",
  "headline-lg",
  "headline-md",
  "body-lg",
  "body-medium",
  "body-base",
  "data-mono",
  "label-caps",
]);

/** What check 3 reports for a snippet: the utilities naming an unknown token. */
function undeclared(source: string): string[] {
  const found: string[] = [];
  for (const match of stripCode(source).matchAll(colorUtility())) {
    const [utility, prefix, name] = match;
    if (!namesAColorToken(prefix, name, TEXT_ROLES)) continue;
    if (!DECLARED.has(name)) found.push(utility);
  }
  return found;
}

/** What check 4 reports: arbitrary values that are colours. */
function arbitraryColors(source: string): string[] {
  const found: string[] = [];
  for (const match of stripCode(source).matchAll(arbitraryUtility())) {
    const value = match[1] ?? match[2] ?? "";
    if (arbitraryIsColor(value)) found.push(match[0]);
  }
  return found;
}

/** What check 5 reports: hard-coded colours in styles and JSX attributes. */
function styleColors(source: string): string[] {
  const found: string[] = [];
  for (const match of stripCode(source).matchAll(STYLE_COLOR)) {
    const property = match[1];
    const value = match[2] ?? match[3] ?? match[4] ?? "";
    if (styleValueIsHardCodedColor(property, value)) found.push(value.trim());
  }
  return found;
}

describe("check 1 — raw numeric scales", () => {
  it.each([
    ["bare", 'className="bg-emerald-100"'],
    // The section-8 panel: a variant used to hide the whole match, not just
    // from check 3 but as a class of blindness worth pinning here too.
    ["behind a variant", 'className="hover:bg-emerald-100"'],
    ["behind two variants", 'className="sm:hover:text-slate-700"'],
    ["as a gradient stop", 'className="from-rose-500"'],
  ])("catches a raw scale %s", (_name, source) => {
    expect([...source.matchAll(RAW_SCALE)].length).toBeGreaterThan(0);
  });

  it("does not fire on a token that merely ends in digits", () => {
    expect([...'className="bg-primary/90"'.matchAll(RAW_SCALE)]).toEqual([]);
  });
});

describe("check 2 — the dark: variant", () => {
  it("catches the variant in code", () => {
    expect([...'className="dark:bg-surface"'.matchAll(DARK_VARIANT)].length).toBe(
      1,
    );
  });

  it("ignores the word in a comment, so prose can explain the ban", () => {
    // The real reason this matters: `lib/ui/status-tone.ts` documents why the
    // variant was removed, and counting its prose would fail the file that fixed
    // the defect.
    const source = "/** Tailwind's dark: follows the OS. */\nexport const a = 1;";
    expect([...stripCode(source).matchAll(DARK_VARIANT)]).toEqual([]);
  });

  it("does not lose a live class after a protocol-relative URL", () => {
    // `[^:]` alone guarded `https://` but not `//cdn`, so the rest of the line —
    // including a real class — was deleted before any check ran.
    const source = 'const u = "//cdn.example/x.png"; const c = "bg-emerald-100";';
    expect([...stripCode(source).matchAll(RAW_SCALE)].length).toBe(1);
  });

  it.each([
    // The one that mattered: it compiles to the very same OS-following rule and
    // passed all five checks, so R6.5 was reopenable in a single line.
    [
      "the media query as an arbitrary variant",
      'className="[@media(prefers-color-scheme:dark)]:bg-surface"',
    ],
    [
      "the same on a declared text colour",
      'className="[@media(prefers-color-scheme:dark)]:text-primary"',
    ],
    ["the query spaced out", 'className="[@media(prefers-color-scheme: dark)]:bg-surface"'],
    /*
     * Tailwind v4 turns `_` into a space inside an arbitrary variant, so this
     * compiles to a REAL `@media (prefers-color-scheme: dark)` rule — verified
     * with `@tailwindcss/cli`, not assumed. The first version of this fix only
     * knew `\s*` and let it through all five checks, on a production component,
     * one keystroke from the case it had just closed. Found by the section-11 QA
     * reviewer; this row is why it cannot come back.
     */
    ["the underscore form Tailwind expands", 'className="[@media(prefers-color-scheme:_dark)]:bg-surface"'],
    ["the underscore form capitalised", 'className="[@media(prefers-color-scheme:_DARK)]:bg-surface"'],
    ["several underscores", 'className="[@media(prefers-color-scheme:__dark)]:text-primary"'],
    /*
     * The one that ended the arms race. `prefers-color-scheme` has exactly two
     * values, so `not (… : light)` IS dark mode — and the word `dark` appears
     * nowhere, so every pattern that matched the VALUE let it through. Compiled
     * with the project's own `@tailwindcss/postcss` and confirmed against the
     * real guard on a production component. Found by the section-11 QA reviewer
     * on the re-review, after two previous fixes had each closed only the exact
     * case the previous one missed.
     */
    ["the negated light query", 'className="[@media_not_(prefers-color-scheme:light)]:bg-surface"'],
    ["the negated light query, spaced", 'className="[@media not (prefers-color-scheme: light)]:bg-surface"'],
    ["a query that names no value at all", 'className="[@media(prefers-color-scheme)]:bg-surface"'],
    // Tailwind lowercases nothing, so this is the same utility.
    ["the keyword capitalised", 'className="DARK:bg-surface"'],
  ])("catches %s", (_name, source) => {
    expect([...stripCode(source).matchAll(DARK_VARIANT)].length).toBeGreaterThan(0);
  });

  it("does not fire on reading the OS preference from JavaScript", () => {
    // `lib/theme/` legitimately calls this; it is not a Tailwind variant, and the
    // `]:` anchor is what tells the two apart.
    const source = 'const m = window.matchMedia("(prefers-color-scheme: dark)");';
    expect([...stripCode(source).matchAll(DARK_VARIANT)]).toEqual([]);
  });
});

describe("stripCode — comments go, strings stay", () => {
  it("does not let a comment opener inside a string swallow the file", () => {
    // Unanchored `/\*[\s\S]*?\*/` deleted everything from the string to the next
    // comment close, live classes included, and reported zero violations.
    const source = [
      'const marker = "/*";',
      'const c = "bg-red-500 dark:bg-blue-900";',
      "/** doc */",
    ].join("\n");
    // Two raw scales in that class list, and the point is that neither is lost.
    expect([...stripCode(source).matchAll(RAW_SCALE)].length).toBe(2);
    expect([...stripCode(source).matchAll(DARK_VARIANT)].length).toBe(1);
  });

  it.each([
    [
      "after a letter inside an attribute",
      '<img src="a//b.png" className="dark:bg-red-500" />',
    ],
    ["inside a template literal", "const u = `${a}//${b}`; const c = \"dark:bg-red-500\";"],
    ["after a closing brace", "const x = {}//note\nconst c = \"dark:bg-red-500\";"],
    ["after a closing paren", "f()//note\nconst c = \"dark:bg-red-500\";"],
  ])("keeps the class when // follows %s", (_name, source) => {
    expect([...stripCode(source).matchAll(DARK_VARIANT)].length).toBe(1);
  });

  it("still deletes a real line comment", () => {
    expect([...stripCode('// dark:bg-red-500').matchAll(DARK_VARIANT)]).toEqual([]);
  });
});

describe("check 3 — a utility naming a token that does not exist", () => {
  it.each([
    ["bare", 'className="bg-card"', "bg-card"],
    ["behind hover:", 'className="hover:bg-card"', "hover:bg-card"],
    [
      "behind focus-visible:",
      'className="focus-visible:ring-nope"',
      "focus-visible:ring-nope",
    ],
    [
      "behind a data- variant",
      'className="data-[state=open]:bg-card"',
      "data-[state=open]:bg-card",
    ],
    ["with a leading !", 'className="!bg-card"', "!bg-card"],
    // Reported without the bang: `\b` cannot sit between `!` and `"`, so the
    // match ends at the token. Caught either way, which is what matters.
    ["with a trailing !", 'className="bg-card!"', "bg-card"],
    ["capitalised", 'className="bg-Card"', "bg-Card"],
    ["as a gradient stop", 'className="from-nope"', "from-nope"],
    ["as a coloured shadow", 'className="shadow-nope"', "shadow-nope"],
    ["with an opacity modifier", 'className="bg-card/15"', "bg-card/15"],
  ])("catches an undeclared token %s", (_name, source, expected) => {
    expect(undeclared(source)).toContain(expected);
  });

  it.each([
    ["a declared token", 'className="bg-surface"'],
    ["a declared token behind a variant", 'className="hover:bg-surface"'],
    ["a declared token with opacity", 'className="bg-state-error/15"'],
    ["a font size", 'className="text-sm"'],
    ["a border side", 'className="border-b"'],
    ["a logical border side", 'className="border-s-2"'],
    ["a shadow size", 'className="shadow-lg"'],
    // A real default utility of the pinned Tailwind 4.3.2, which the first
    // whitelist rejected because it knew `2xl` but not `2xs`.
    ["the 2xs shadow", 'className="shadow-2xs"'],
    ["a gradient direction", 'className="bg-gradient-to-r"'],
    ["an outline keyword", 'className="outline-none"'],
    ["text alignment", 'className="text-center"'],
  ])("does not fire on %s", (_name, source) => {
    expect(undeclared(source)).toEqual([]);
  });

  it.each([...TEXT_ROLES].map((role) => [role]))(
    "does not fire on the typographic role text-%s",
    (role) => {
      expect(undeclared(`className="text-${role}"`)).toEqual([]);
      expect(undeclared(`className="md:text-${role}"`)).toEqual([]);
    },
  );

  it("still catches a text- name that is neither a colour token nor a role", () => {
    // The roles are a declared set, not a licence for any `text-*` to pass.
    expect(undeclared('className="text-headline-xl"')).toContain("text-headline-xl");
  });
});

describe("check 4 — a colour that bypasses the token layer", () => {
  it.each([
    ["an arbitrary hex", 'className="bg-[#e11d48]"'],
    ["a short arbitrary hex", 'className="text-[#fff]"'],
    ["an arbitrary colour function", 'className="bg-[rgb(255_0_0)]"'],
    ["an arbitrary oklch", 'className="bg-[oklch(0.7_0.2_20)]"'],
    // Invalid Tailwind: it emits nothing, which is the silent zero this guard
    // exists to prevent, so it counts rather than being skipped.
    ["an arbitrary value with a space", 'className="bg-[oklch(0.7 0.2 20)]"'],
    ["an arbitrary named colour", 'className="bg-[rebeccapurple]"'],
    ["a typed arbitrary colour", 'className="text-[color:red]"'],
    ["a css variable shorthand", 'className="bg-(--danger)"'],
    // Tailwind v4's documented typed form. The parens branch used to require
    // `--` immediately after `(`, so any hint defeated it.
    ["a typed css variable shorthand", 'className="bg-(color:--brand)"'],
    ["behind a variant", 'className="hover:bg-[#fff]"'],
    ["an arbitrary var()", 'className="bg-[var(--danger)]"'],
  ])("catches %s", (_name, source) => {
    expect(arbitraryColors(source).length).toBeGreaterThan(0);
  });

  it.each([
    // Live in `features/shell/components/version-badge.tsx`.
    ["an arbitrary font size", 'className="text-[0.6875rem]"'],
    ["a size with a line height", 'className="text-[0.6875rem/1]"'],
    ["an arbitrary pixel size", 'className="text-[14px]"'],
    ["a border width keyword", 'className="border-[thin]"'],
    ["a computed length", 'className="text-[calc(1rem-2px)]"'],
    ["a background image", 'className="bg-[url(/x.png)]"'],
    ["a typed length", 'className="text-[length:1rem]"'],
  ])("does not fire on %s", (_name, source) => {
    expect(arbitraryColors(source)).toEqual([]);
  });
});

describe("check 5 — a hard-coded colour in a style or attribute", () => {
  it.each([
    ["a double-quoted hex", 'style={{ color: "#555" }}', "#555"],
    // Nothing in this project enforces double quotes — no prettier, no quote
    // lint rule — so the single-quoted and template forms were lint-clean and
    // invisible.
    ["a single-quoted hex", "style={{ color: '#555' }}", "#555"],
    ["a template-literal hex", "style={{ color: `#555` }}", "#555"],
    ["a hex inside a shorthand", 'style={{ border: "1px solid #ccc" }}', "1px solid #ccc"],
    // The old check keyed on `#`, so every other colour syntax walked through
    // the one channel it was meant to gate.
    ["an rgb() literal", 'style={{ color: "rgb(255,0,0)" }}', "rgb(255,0,0)"],
    ["a named colour", 'style={{ color: "rebeccapurple" }}', "rebeccapurple"],
    ["accentColor", 'style={{ accentColor: "#abc" }}', "#abc"],
    ["borderBlockColor", 'style={{ borderBlockColor: "#abc" }}', "#abc"],
    ["a gradient in backgroundImage", 'style={{ backgroundImage: "linear-gradient(#fff,#000)" }}', "linear-gradient(#fff,#000)"],
    ["a drop-shadow filter", 'style={{ filter: "drop-shadow(0 0 2px #abc)" }}', "drop-shadow(0 0 2px #abc)"],
    // The JSX attribute form, where hard-coded hexes actually arrive: inline SVG.
    ["a fill attribute", '<path fill="#abc" />', "#abc"],
    ["a stopColor attribute", '<stop stopColor="#abc" />', "#abc"],
    // A computed key is the same property to JavaScript, and the old pattern
    // required the name to be followed directly by `:` or `=`.
    ["a computed key", 'style={{ ["color"]: "#e11d48" }}', "#e11d48"],
    ["a single-quoted computed key", "style={{ ['color']: '#e11d48' }}", "#e11d48"],
  ])("catches %s", (_name, source, expected) => {
    expect(styleColors(source)).toContain(expected);
  });

  it.each([
    ["a token reference", 'style={{ color: "var(--foreground)" }}'],
    ["currentColor", 'style={{ fill: "currentColor" }}'],
    ["transparent", 'style={{ backgroundColor: "transparent" }}'],
    ["outline none", 'style={{ outline: "none" }}'],
    ["a tokenised shadow", 'style={{ boxShadow: "0 1px 2px var(--border)" }}'],
    ["a plain length", 'style={{ borderWidth: "1px" }}'],
    ["a booking reference that looks like a hex", 'const r = "Booking.com #1234";'],
  ])("does not fire on %s", (_name, source) => {
    expect(styleColors(source)).toEqual([]);
  });
});

describe("stylesheets — only what `@apply` names", () => {
  const SHEET = `
    /* a comment mentioning bg-emerald-100 */
    .card { background-color: var(--color-surface); border-color: var(--color-border); }
    @media (prefers-color-scheme: dark) { .card { color: #fff; } }
    .promo { @apply bg-red-500 dark:bg-blue-900; }
  `;

  it("catches a raw scale and a theme variant inside @apply", () => {
    const applied = applyDirectives(SHEET);
    expect([...applied.matchAll(RAW_SCALE)].length).toBe(2);
    expect([...applied.matchAll(DARK_VARIANT)].length).toBe(1);
  });

  it("ignores the stylesheet's own declarations, which are not utilities", () => {
    // `border-color: var(--color-border)` reads as the prefix `border` naming an
    // undeclared token `color`, and the media query reads as a theme variant.
    // Feeding a stylesheet to the class patterns whole is how that happens.
    expect(applyDirectives(SHEET)).not.toContain("border-color");
    expect(applyDirectives(SHEET)).not.toContain("prefers-color-scheme");
  });
});
