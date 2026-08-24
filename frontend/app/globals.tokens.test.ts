import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The guard that makes design D1's duplication safe instead of fragile.
 *
 * D1 declares the dark palette TWICE — once inside
 * `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])` and once
 * in `:root[data-theme="dark"]` — because the two selectors tie at specificity
 * (0,2,0) and file order is what lets the runtime attribute beat the OS
 * preference in both directions. Nothing in CSS notices when those two copies
 * drift, so this test does: same token names across all three token-bearing
 * blocks (R1.2), identical values between the two dark ones.
 *
 * It also pins the utilities and guarantees R5.3 protects, which a rewrite of
 * this file could silently drop.
 */

/**
 * Comments are stripped before anything else parses this file.
 *
 * `declarationsOf` counts raw `{`/`}` characters, so a brace living inside a
 * comment — someone writing «the `@theme {` rule…» in prose — would make the
 * matcher overrun into the next block. The overrun does not fail cleanly: it
 * merges a later block's declarations into the one being read, which shows up as
 * three unrelated assertions failing with a message that points nowhere near the
 * comment that caused it. Removing comments first deletes the whole failure
 * class instead of documenting it.
 */
const CSS = readFileSync(join(__dirname, "globals.css"), "utf8").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
);

/**
 * Custom-property declarations inside the top-level rule whose selector is
 * exactly `selector`.
 *
 * Hand-written brace matching rather than a regex: the file nests
 * (`@media { :root { … } }`) and a lazy `\{([^}]*)\}` would stop at the first
 * inner brace. `startFrom` lets the caller scope the search to a region, which
 * is how the media-query block is read without matching the bare `:root` above
 * it.
 */
function declarationsOf(
  selector: string,
  startFrom = 0,
): Record<string, string> {
  const at = CSS.indexOf(`${selector} {`, startFrom);
  if (at === -1) {
    throw new Error(`selector not found in globals.css: ${selector}`);
  }
  let depth = 0;
  let end = -1;
  for (let i = CSS.indexOf("{", at); i < CSS.length; i += 1) {
    if (CSS[i] === "{") depth += 1;
    else if (CSS[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  const body = CSS.slice(CSS.indexOf("{", at) + 1, end);
  const declarations: Record<string, string> = {};
  // A declaration ends at `;`, at the block's `}`, or — for the last one in a
  // block — at nothing at all, because CSS makes the final semicolon optional.
  // `body` excludes the closing brace, so `$` is what covers that third case.
  for (const [, name, value] of body.matchAll(
    /(--[a-z0-9-]+)\s*:\s*([^;}]+)(?:[;}]|$)/gi,
  )) {
    declarations[name] = value.trim();
  }
  return declarations;
}

const MEDIA_DARK_AT = CSS.indexOf("@media (prefers-color-scheme: dark)");

const LIGHT = declarationsOf(":root");
const DARK_MEDIA = declarationsOf(
  ':root:not([data-theme="light"])',
  MEDIA_DARK_AT,
);
const DARK_ATTRIBUTE = declarationsOf(':root[data-theme="dark"]');

/** `--color-*` aliases exposed to Tailwind, from `@theme inline`. */
const THEME_INLINE = declarationsOf("@theme inline");

/**
 * Every custom-property name declared anywhere in the file, in source order and
 * WITH duplicates — the occurrence counts are the point. Selector-anchored
 * lookups cannot see a block they were not told about; this can.
 */
const declaredNames = [
  ...CSS.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;}]+)[;}]/gi),
].map(([, name]) => name);

const CORE_TOKENS = [
  "--background",
  "--foreground",
  "--surface",
  "--surface-high",
  "--muted",
  "--muted-foreground",
  "--accent",
  "--accent-foreground",
  "--primary",
  "--primary-foreground",
  "--secondary",
  "--secondary-foreground",
  "--border",
  "--input",
  "--ring",
] as const;

const STATE_TOKENS = [
  "--state-success",
  "--state-warning",
  "--state-error",
  "--state-info",
  "--state-neutral",
  "--state-success-text",
  "--state-warning-text",
  "--state-error-text",
  "--state-info-text",
  "--state-neutral-text",
] as const;

const COLOUR_TOKENS = [...CORE_TOKENS, ...STATE_TOKENS];

/**
 * The approved palette of design.md §Paleta, transcribed. This is what makes the
 * guard prove R2.1/R2.2 — that the values came from a palette *written and
 * approved in design.md* — rather than merely prove the file is
 * self-consistent.
 *
 * Without it the guard has a blind spot with a name: a value changed to the same
 * wrong hex in BOTH dark blocks is not drift *between the copies*, so every
 * name-set and dark-parity assertion still passes. Same for a typo in a light
 * value that stays valid hex and stays different from its dark counterpart.
 * Both were found by review; this table is what closes them.
 *
 * `E` in design.md means the value is a literal from the Stitch export, `N` that
 * it is new to the approved proposal. That provenance is design.md's to carry —
 * here only the resolved value matters.
 */
const APPROVED: Record<string, { light: string; dark: string }> = {
  "--background": { light: "#eef1f7", dark: "#0f131c" },
  "--foreground": { light: "#2c303a", dark: "#F8FAFC" },
  "--surface": { light: "#f8fafd", dark: "#181b25" },
  "--surface-high": { light: "#ffffff", dark: "#1c2029" },
  "--muted": { light: "#e2e7f1", dark: "#262a34" },
  "--muted-foreground": { light: "#525b6b", dark: "#94A3B8" },
  "--accent": { light: "#e2e7f1", dark: "#262a34" },
  "--accent-foreground": { light: "#2c303a", dark: "#F8FAFC" },
  // D3: the canonical primary per theme. `#00897b` — the value DESIGN.md's prose
  // names — is deliberately NOT here: white on it measures 4.32:1 and fails AA.
  "--primary": { light: "#006b5f", dark: "#70d8c8" },
  "--primary-foreground": { light: "#ffffff", dark: "#003731" },
  "--secondary": { light: "#dfe2ef", dark: "#3e495d" },
  "--secondary-foreground": { light: "#2c303a", dark: "#aeb9d0" },
  // D9: `border` and `input` stop being the same value. `border` is the
  // export's decorative hairline; `input` is a control boundary and owes 3:1.
  "--border": { light: "#d5dbe8", dark: "#262a34" },
  "--input": { light: "#6b7688", dark: "#879390" },
  "--ring": { light: "#006b5f", dark: "#70d8c8" },
  "--state-success": { light: "#0f7a58", dark: "#10B981" },
  "--state-warning": { light: "#a4600a", dark: "#F59E0B" },
  "--state-error": { light: "#c92a2a", dark: "#EF4444" },
  "--state-info": { light: "#0a72ad", dark: "#38BDF8" },
  // R6.1: the grey family of PRD §9.1, which DESIGN.md does not define.
  "--state-neutral": { light: "#64748B", dark: "#94A3B8" },
  "--state-success-text": { light: "#065f46", dark: "#6EE7B7" },
  "--state-warning-text": { light: "#7c4a04", dark: "#FCD34D" },
  "--state-error-text": { light: "#991b1b", dark: "#FCA5A5" },
  "--state-info-text": { light: "#0b5177", dark: "#7DD3FC" },
  "--state-neutral-text": { light: "#3f4a5a", dark: "#CBD5E1" },
};

describe("token blocks (design D1, R1.2)", () => {
  it("declares the 25 tokens of design §Paleta — 15 core + 10 state", () => {
    expect(CORE_TOKENS).toHaveLength(15);
    expect(STATE_TOKENS).toHaveLength(10);
    expect(COLOUR_TOKENS).toHaveLength(25);
    // Exact set, not mere containment: an extra unlisted token in `:root` would
    // escape the parity comparison below on the light side only. `:root` holds
    // ONLY theme-dependent colour, which is what makes a whole-block comparison
    // meaningful — the radii, ritmo and type scale live in `@theme`.
    expect(new Set(Object.keys(LIGHT))).toEqual(new Set(COLOUR_TOKENS));
  });

  it("declares the SAME set of token names in the three token-bearing blocks", () => {
    const light = new Set(Object.keys(LIGHT));
    const darkMedia = new Set(Object.keys(DARK_MEDIA));
    const darkAttribute = new Set(Object.keys(DARK_ATTRIBUTE));

    expect(darkMedia).toEqual(light);
    expect(darkAttribute).toEqual(light);
    expect(light).toEqual(new Set(COLOUR_TOKENS));
  });

  it("declares IDENTICAL values in the two dark blocks", () => {
    // The whole reason this file exists: CSS cannot tell that these two copies
    // are meant to agree.
    expect(DARK_ATTRIBUTE).toEqual(DARK_MEDIA);
  });

  it("gives every token a different value in light than in dark", () => {
    // Catches a copy-paste that left a light block holding dark values (or the
    // reverse), which the parity assertions above cannot see. `--state-neutral`
    // is the one legitimate near-miss and still differs (#64748B vs #94A3B8).
    const shared = COLOUR_TOKENS.filter(
      (token) => LIGHT[token] === DARK_MEDIA[token],
    );
    expect(shared).toEqual([]);
  });

  it("declares every token as a literal hex, never as a var() indirection", () => {
    // The contrast audit parses these values; an indirection would make it
    // measure nothing while still passing.
    for (const block of [LIGHT, DARK_MEDIA, DARK_ATTRIBUTE]) {
      for (const token of COLOUR_TOKENS) {
        expect(block[token], token).toMatch(/^#[0-9a-f]{6}$/i);
      }
    }
  });

  it("sets color-scheme on every block so native controls follow the theme", () => {
    expect(declarationsOf(":root")).toBeDefined();
    expect(CSS).toMatch(/:root\s*\{\s*color-scheme: light;/);
    expect(CSS).toMatch(
      /:root:not\(\[data-theme="light"\]\)\s*\{\s*color-scheme: dark;/,
    );
    expect(CSS).toMatch(
      /:root\[data-theme="light"\]\s*\{\s*color-scheme: light;\s*\}/,
    );
    expect(CSS).toMatch(/:root\[data-theme="dark"\]\s*\{\s*color-scheme: dark;/);
  });

  it("puts the attribute override AFTER the media query, which is what makes it win", () => {
    // Same specificity (0,2,0) on both selectors, so this ordering is not
    // cosmetic: reversing it would break R1.4 in the dark-on-light direction
    // and no other test would notice.
    expect(MEDIA_DARK_AT).toBeGreaterThan(-1);
    expect(CSS.indexOf(':root[data-theme="dark"] {')).toBeGreaterThan(
      MEDIA_DARK_AT,
    );
    expect(CSS.indexOf(':root[data-theme="light"] {')).toBeGreaterThan(
      MEDIA_DARK_AT,
    );
  });

  it("declares exactly the approved values of design.md §Paleta (R2.1, R2.2)", () => {
    // Absolute fidelity, not internal consistency: catches a value changed to
    // the same wrong hex in BOTH dark blocks, and a typo in a light value that
    // stays valid hex — neither of which is «drift between the copies», so no
    // other assertion here can see them.
    expect(Object.keys(APPROVED).sort()).toEqual([...COLOUR_TOKENS].sort());
    for (const token of COLOUR_TOKENS) {
      expect(LIGHT[token], `${token} (light)`).toBe(APPROVED[token].light);
      expect(DARK_MEDIA[token], `${token} (dark, media)`).toBe(
        APPROVED[token].dark,
      );
      expect(DARK_ATTRIBUTE[token], `${token} (dark, attribute)`).toBe(
        APPROVED[token].dark,
      );
    }
  });

  it("declares each token exactly three times in the whole file — no fourth block", () => {
    // Every other assertion here is anchored on a named selector, so a rule
    // added AFTER the attribute blocks — a `.dark` class, an
    // `@media (prefers-color-scheme: light)` — could redeclare `--background`,
    // win on order, and leave the guard green. This counts instead of looking up.
    //
    // The terminator is `[;}]`, not `;`: CSS lets the LAST declaration of a
    // block omit its semicolon, and nothing in this project would catch that —
    // `lint` is `eslint .`, which does not read `.css`, and there is no
    // prettier/stylelint/biome. A one-declaration override block written without
    // the optional semicolon used to slip past this count entirely.
    for (const token of COLOUR_TOKENS) {
      const times = declaredNames.filter((name) => name === token).length;
      expect(times, `${token} declared ${times}× (expected 3)`).toBe(3);
    }
  });

  it("declares each --color-* alias exactly once, in exactly one @theme inline", () => {
    // Consumers read the ALIAS, never the raw token — this file's own R5.3
    // assertions use `var(--color-ring)`, `var(--color-border)`,
    // `var(--color-background)`. So the palette can be repainted one layer above
    // every assertion above: a later `:root { --color-background: #ff0000 }`
    // leaves all 25 raw tokens pristine and approved, and changes the colour the
    // app actually paints. `THEME_INLINE` reads the FIRST `@theme inline` block,
    // so the block count is part of the same hole.
    const themeBlocks = [...CSS.matchAll(/@theme\s+inline\s*\{/g)].length;
    expect(themeBlocks, "@theme inline blocks").toBe(1);

    for (const token of COLOUR_TOKENS) {
      const alias = token.replace(/^--/, "--color-");
      const times = declaredNames.filter((name) => name === alias).length;
      expect(times, `${alias} declared ${times}× (expected 1)`).toBe(1);
    }
  });

  it("exposes every colour token to Tailwind as --color-* via @theme inline", () => {
    for (const token of COLOUR_TOKENS) {
      const alias = token.replace(/^--/, "--color-");
      expect(THEME_INLINE[alias], alias).toBe(`var(${token})`);
    }
  });
});

describe("preserved guarantees (R5.3)", () => {
  it("keeps the visible focus indicator in @layer base", () => {
    expect(CSS).toContain("@layer base");
    expect(CSS).toMatch(
      /:focus-visible\s*\{[^}]*outline: 2px solid var\(--color-ring\);/,
    );
    expect(CSS).toMatch(/:focus-visible\s*\{[^}]*outline-offset: 2px;/);
  });

  it("keeps the border-colour and body base rules", () => {
    expect(CSS).toMatch(/\*\s*\{\s*border-color: var\(--color-border\);/);
    expect(CSS).toMatch(/background-color: var\(--color-background\);/);
    expect(CSS).toMatch(/color: var\(--color-foreground\);/);
    expect(CSS).toContain("min-height: 100dvh;");
  });

  it("keeps the prefers-reduced-motion block that kills animation", () => {
    const at = CSS.indexOf("@media (prefers-reduced-motion: reduce)");
    expect(at).toBeGreaterThan(-1);
    const block = CSS.slice(at, CSS.indexOf("@utility", at));
    expect(block).toContain("animation-duration: 0.01ms !important;");
    expect(block).toContain("animation-iteration-count: 1 !important;");
    expect(block).toContain("transition-duration: 0.01ms !important;");
    expect(block).toContain("scroll-behavior: auto !important;");
  });

  it("keeps tap-target at 44×44 and pb-safe on the safe-area inset", () => {
    expect(CSS).toMatch(
      /@utility tap-target\s*\{\s*min-height: 44px;\s*min-width: 44px;\s*\}/,
    );
    expect(CSS).toMatch(
      /@utility pb-safe\s*\{\s*padding-bottom: env\(safe-area-inset-bottom\);\s*\}/,
    );
  });
});
