import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  darkMediaAt,
  declaredNames as namesIn,
  declarationsOf as declarationsIn,
  readCss,
  stripComments,
} from "@/test/css-tokens";

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
 * Parsed by the shared helper in `test/css-tokens.ts` rather than a local copy:
 * this parser already had one real bug (it counted braces inside comments and
 * overran into the next block), and `app/globals.contrast.test.ts` needs the
 * same three blocks. Two copies would be two places for that to come back.
 */
const CSS = readCss(join(__dirname, "globals.css"));

const declarationsOf = (selector: string, startFrom = 0) =>
  declarationsIn(CSS, selector, startFrom);

const MEDIA_DARK_AT = darkMediaAt(CSS);

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
const declaredNames = namesIn(CSS);

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

/**
 * The literal half of the token layer: typography, ritmo and radii, in a plain
 * `@theme` block because they do not vary by theme (design D10).
 *
 * Pinned by NAME and by COUNT, not by containment — the failure R4.3/R5.1 guard
 * against is a partial port, where a role or a step is quietly missing and every
 * consumer silently falls back to Tailwind's numeric scale.
 */
const THEME_LITERAL = declarationsOf("@theme");

/** The ten roles of DESIGN.md §typography, in the export's own order. */
const TYPE_ROLES = [
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
] as const;

/** Size, line-height, letter-spacing and weight, straight from the export. */
const TYPE_EXPECTED: Record<
  string,
  { size: string; lineHeight: string; tracking: string; weight: string }
> = {
  "display-2xl": {
    size: "3.5rem",
    lineHeight: "4rem",
    tracking: "-0.03em",
    weight: "800",
  },
  "display-xl": {
    size: "2.75rem",
    lineHeight: "3.25rem",
    tracking: "-0.025em",
    weight: "800",
  },
  "display-lg-mobile": {
    size: "2.25rem",
    lineHeight: "2.75rem",
    tracking: "-0.02em",
    weight: "800",
  },
  "headline-lg": {
    size: "2rem",
    lineHeight: "2.5rem",
    tracking: "-0.02em",
    weight: "700",
  },
  "headline-md": {
    size: "1.5rem",
    lineHeight: "2rem",
    tracking: "-0.015em",
    weight: "600",
  },
  "body-lg": {
    size: "1rem",
    lineHeight: "1.5rem",
    tracking: "-0.005em",
    weight: "400",
  },
  "body-medium": {
    size: "0.875rem",
    lineHeight: "1.25rem",
    tracking: "0em",
    weight: "500",
  },
  "body-base": {
    size: "0.875rem",
    lineHeight: "1.25rem",
    tracking: "0em",
    weight: "400",
  },
  "data-mono": {
    size: "0.8125rem",
    lineHeight: "1.125rem",
    tracking: "-0.01em",
    weight: "500",
  },
  "label-caps": {
    size: "0.6875rem",
    lineHeight: "0.875rem",
    tracking: "0.06em",
    weight: "700",
  },
};

/**
 * The named ritmo steps, after the 2026-08-24 amendment to R5.1.
 *
 * Only three, and the eight t-shirt sizes are deliberately absent: naming them
 * `--spacing-{sm,md,lg,…}` shadowed Tailwind v4's t-shirt namespace and made
 * `max-w-md` compile to `max-width: var(--spacing-md)`. The export's eight steps
 * are Tailwind's numeric scale exactly (p-1/2/3/4/6/8/12/16), so the aliases
 * bought naming and cost layout.
 */
const SPACING_EXPECTED: Record<string, string> = {
  "--spacing-gutter": "1rem",
  "--spacing-margin-mobile": "1rem",
  "--spacing-margin-desktop": "2rem",
};

/**
 * Names that must NEVER appear in the `--spacing-*` namespace, because Tailwind
 * resolves `max-w-*`, `min-w-*` and friends against it when the key exists — so
 * declaring one silently rewrites a layout utility.
 */
const FORBIDDEN_SPACING_NAMES = [
  "xs",
  "sm",
  "md",
  "lg",
  "xl",
  "2xl",
  "3xl",
  "4xl",
  "5xl",
  "6xl",
  "7xl",
] as const;

/**
 * DESIGN.md §rounded, minus `DEFAULT` and `full` — see the assertion below for
 * why both are absent, which is the same reason twice.
 */
const RADIUS_EXPECTED: Record<string, string> = {
  "--radius-sm": "0.125rem",
  "--radius-md": "0.375rem",
  "--radius-lg": "0.5rem",
  "--radius-xl": "0.75rem",
};

describe("typography, ritmo and radii (design D10, R4.2-R4.4, R5.1)", () => {
  it("declares all TEN typographic roles, with all four properties each", () => {
    expect(TYPE_ROLES).toHaveLength(10);
    for (const role of TYPE_ROLES) {
      const expected = TYPE_EXPECTED[role];
      expect(THEME_LITERAL[`--text-${role}`], role).toBe(expected.size);
      expect(THEME_LITERAL[`--text-${role}--line-height`], role).toBe(
        expected.lineHeight,
      );
      expect(THEME_LITERAL[`--text-${role}--letter-spacing`], role).toBe(
        expected.tracking,
      );
      expect(THEME_LITERAL[`--text-${role}--font-weight`], role).toBe(
        expected.weight,
      );
    }
  });

  it("declares no role beyond the export's ten, so the set is the export's", () => {
    // A count, so an invented eleventh role is a failure rather than a surprise.
    const declared = Object.keys(THEME_LITERAL)
      .filter((name) => name.startsWith("--text-"))
      .filter((name) => !name.includes("--", 2));
    expect(new Set(declared)).toEqual(
      new Set(TYPE_ROLES.map((role) => `--text-${role}`)),
    );
  });

  it("keeps Tailwind's numeric text scale available, since Badge and Button use it", () => {
    // D10: the roles are additive. Overriding `--text-sm` here would silently
    // resize every existing component, which is out of this change's scope.
    for (const name of ["--text-xs", "--text-sm", "--text-base", "--text-lg"]) {
      expect(THEME_LITERAL[name], `${name} must NOT be redefined`).toBeUndefined();
    }
  });

  it("never declares a t-shirt-sized --spacing-* name, which would break max-w-*", () => {
    /*
     * The regression this exists to prevent, found by loading the app rather than
     * by any assertion: with `--spacing-md` declared, Tailwind compiled
     * `.max-w-md { max-width: var(--spacing-md) }` — 12px instead of 28rem — and
     * every container using it collapsed. Eight call sites across four files, and
     * nothing went red, because the token WAS declared exactly as the design
     * asked; the defect was in what declaring it did somewhere else.
     *
     * So this asserts an absence. `gutter` and the margins are fine precisely
     * because no Tailwind utility is named after them.
     */
    for (const name of FORBIDDEN_SPACING_NAMES) {
      expect(
        THEME_LITERAL[`--spacing-${name}`],
        `--spacing-${name} shadows Tailwind's t-shirt namespace and rewrites max-w-${name}`,
      ).toBeUndefined();
    }
  });

  it("declares the three named ritmo steps that collide with nothing", () => {
    expect(Object.keys(SPACING_EXPECTED)).toHaveLength(3);
    expect(THEME_LITERAL["--spacing"], "the baseline unit").toBe("0.25rem");
    for (const [name, value] of Object.entries(SPACING_EXPECTED)) {
      expect(THEME_LITERAL[name], name).toBe(value);
    }
    // Every step is a whole multiple of the 4px unit — that is what «ritmo» means.
    for (const [name, value] of Object.entries(SPACING_EXPECTED)) {
      const px = Number.parseFloat(value) * 16;
      expect(px % 4, `${name} = ${px}px is not a multiple of 4`).toBe(0);
    }
  });

  it("declares the radius scale and drops the old --radius with its calc() chain", () => {
    for (const [name, value] of Object.entries(RADIUS_EXPECTED)) {
      expect(THEME_LITERAL[name], name).toBe(value);
    }
    // R5.1: the single `--radius` and the three values derived from it are gone,
    // and nothing is left referring to it.
    expect(CSS).not.toMatch(/--radius\s*:/);
    expect(CSS).not.toContain("calc(var(--radius)");
  });

  it("declares neither DEFAULT nor full, because Tailwind already delivers both", () => {
    // One reason applied twice, and both halves verified by compiling Tailwind
    // rather than assumed (task 3.5):
    //   · `rounded` emits `border-radius: 0.25rem` as a hardcoded literal, which
    //     IS the export's `DEFAULT: 0.25rem`.
    //   · `rounded-full` emits `border-radius: calc(infinity * 1px)`, which
    //     rounds the corner fully exactly as the export's `9999px` intends — and
    //     it does not read `var(--radius-full)`, so a token could not reach it.
    // Declaring either would be a token no utility and no component consumes,
    // which is the anti-pattern design D2 names. R5.1 originally enumerated
    // `full`; amended 2026-08-24 after the section-3 panel raised the conflict.
    expect(THEME_LITERAL["--radius-DEFAULT"]).toBeUndefined();
    expect(THEME_LITERAL["--radius-default"]).toBeUndefined();
    expect(THEME_LITERAL["--radius-full"]).toBeUndefined();
  });

  it("declares exactly the four radius steps that have a consumer", () => {
    const declared = Object.keys(THEME_LITERAL).filter((name) =>
      name.startsWith("--radius-"),
    );
    expect(new Set(declared)).toEqual(new Set(Object.keys(RADIUS_EXPECTED)));
  });

  it("maps --font-sans and --font-mono onto the next/font variables, each with a fallback stack", () => {
    // R4.2. The `var(--font-*)` reference is what ties the token to the
    // self-hosted face; the rest of the stack is what renders before it arrives.
    expect(THEME_INLINE["--font-sans"]).toContain("var(--font-inter)");
    expect(THEME_INLINE["--font-sans"]).toContain("system-ui");
    expect(THEME_INLINE["--font-sans"]).toContain("sans-serif");
    expect(THEME_INLINE["--font-mono"]).toContain(
      "var(--font-jetbrains-mono)",
    );
    expect(THEME_INLINE["--font-mono"]).toContain("ui-monospace");
    expect(THEME_INLINE["--font-mono"]).toContain("monospace");
  });
});

/**
 * R4.1 has two halves and only one of them was pinned.
 *
 * "SHALL cargar Inter y JetBrains Mono a través de `next/font`" is covered by the
 * font-token assertion above. "SHALL NOT cargar ninguna fuente desde
 * `fonts.googleapis.com` ni desde ningún otro CDN" was covered by nothing: an
 * `@import url("https://fonts.googleapis.com/…")` at the top of `globals.css`
 * used to pass the whole suite and every CI job green.
 *
 * That is not a hypothetical. The copy-paste source is IN this repository:
 * `docs/design/2026-08-23-stitch-export/*​/code.html` carries
 * `preconnect` pairs to `fonts.googleapis.com`/`fonts.gstatic.com` in seven
 * files and loads `Material Symbols Outlined` from Google Fonts, and this change
 * ships no self-hosted counterpart for those icons. The first task that touches
 * icons is the moment someone pastes one of those lines.
 *
 * Scoped by an explicit FILE LIST and by exact FORM rather than by a tree-wide
 * grep for the domain, for two reasons: a tree-wide grep would trip on
 * `docs/design/` (which is a design artefact and must keep its markup), and a
 * name-based grep is trivially sidestepped — `assetPrefix` moves all thirteen
 * self-hosted faces off-origin without any of these strings appearing, because
 * every emitted `src` is relative.
 */
const FONT_SOURCE_FILES = ["globals.css", "layout.tsx"] as const;

/** Source with comments removed, so prose ABOUT a CDN is not mistaken for a use of one. */
function sourceWithoutComments(file: string): string {
  return readFileSync(join(__dirname, file), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

describe("R4.1 — no font may be loaded from a CDN", () => {
  it.each(FONT_SOURCE_FILES)(
    "%s names no third-party font host outside a comment",
    (file) => {
      const source = sourceWithoutComments(file);
      expect(source).not.toMatch(/fonts\.googleapis\.com/);
      expect(source).not.toMatch(/fonts\.gstatic\.com/);
      // Any absolute or protocol-relative URL at all — the prohibition is
      // «ni desde ningún otro CDN», so a different host is not a loophole.
      expect(source).not.toMatch(/https?:\/\//);
      expect(source).not.toMatch(/url\(\s*['"]?\/\//);
    },
  );

  it("globals.css imports nothing but tailwindcss, and never through url()", () => {
    const imports = [
      ...sourceWithoutComments("globals.css").matchAll(/@import\s+([^;]+);/g),
    ].map(([, spec]) => spec.trim());
    expect(imports).toEqual(['"tailwindcss"']);
  });

  it("globals.css declares no @font-face of its own", () => {
    // `next/font` emits the `@font-face` rules at build time, pointing at
    // `/_next/static/media`. A hand-written one here is the other way a remote
    // `src` could enter.
    expect(sourceWithoutComments("globals.css")).not.toMatch(/@font-face/i);
  });

  it("layout.tsx adds no link/preconnect/preload element", () => {
    // `next/font` needs none of these; their only use here would be reaching a
    // third party. Checked as a form, so a host this test does not know about
    // is caught too.
    const source = sourceWithoutComments("layout.tsx");
    expect(source).not.toMatch(/<link\b/i);
    expect(source).not.toMatch(/rel=["'](preconnect|preload|stylesheet)["']/i);
  });

  it("loads both families through next/font, not through a stylesheet", () => {
    const source = sourceWithoutComments("layout.tsx");
    expect(source).toMatch(
      /from\s+["']next\/font\/(google|local)["']/,
    );
    expect(source).toMatch(/\bInter\s*\(/);
    expect(source).toMatch(/\bJetBrains_Mono\s*\(/);
  });

  it("next.config declares no assetPrefix, which would move every face off-origin", () => {
    // The bypass a name-based guard cannot see: all thirteen emitted `src`
    // values are relative, so one `assetPrefix` key sends them to a CDN without
    // any font host appearing in the source. There is no CSP in this repo to
    // catch it at runtime either.
    const config = readFileSync(
      join(__dirname, "..", "next.config.ts"),
      "utf8",
    ).replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    expect(config).not.toMatch(/assetPrefix/);
  });
});

/**
 * Every file under `frontend/`, so an absence can be asserted about the TREE and
 * not just about one directory. Build output and dependencies are skipped.
 */
function everyFile(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === ".next") continue;
    if (entry.name === "coverage" || entry.name === ".git") continue;
    const full = join(dir, entry.name);
    if (entry.isDirectory()) everyFile(full, found);
    else found.push(full);
  }
  return found;
}

const FRONTEND_ROOT = join(__dirname, "..");
const ALL_FILES = everyFile(FRONTEND_ROOT).map((f) =>
  f.slice(FRONTEND_ROOT.length + 1),
);

describe("R1.1 — the token layer is the CSS, so there is no Tailwind config", () => {
  /*
   * R1.1: «THE SYSTEM SHALL NOT reintroducir `tailwind.config.js|ts`». The
   * absence is a decision of `frontend-foundation` — `components.json` carries
   * `"tailwind": {"config": ""}` — and until section 11 nothing named the file,
   * so bringing it back would have failed nothing at all. Contrast R5.1, whose
   * absence has been guarded since section 3.
   *
   * It matters because a config is a SECOND home for the token layer: v4 still
   * reads one when `@config` points at it, and a `theme.extend.colors` there
   * would define tokens `globals.css` knows nothing about — every parity and
   * contrast guard in this file reads the CSS, so they would all stay green.
   *
   * Both assertions scan the whole tree, and that is the fix rather than a
   * flourish: the first version checked only `frontend/tailwind.config.*` and
   * only `globals.css`, and the section-11 QA reviewer walked straight through
   * it with `lib/vendor/tailwind.config.js` plus an `app/print.css` carrying
   * `@config "../lib/vendor/tailwind.config.js";` — 40 tests green, second token
   * home installed. A guard against a file has to look where files can be.
   */
  const CONFIG_NAME = /(^|\/)tailwind\.config\.[cm]?[jt]s$/;

  it("has no tailwind.config file anywhere in the tree, under any extension", () => {
    const offenders = ALL_FILES.filter((file) => CONFIG_NAME.test(file));
    expect(offenders, "R1.1 forbids a second home for the token layer").toEqual(
      [],
    );
  });

  it("no stylesheet anywhere points Tailwind at a config with @config", () => {
    // `@config "./whatever.js"` loads a config under ANY name, so guarding the
    // conventional filenames alone is not enough — and it need not be
    // `globals.css` that does the pointing.
    const offenders = ALL_FILES.filter((file) => file.endsWith(".css")).filter(
      (file) =>
        /@config\b/.test(
          stripComments(readFileSync(join(FRONTEND_ROOT, file), "utf8")),
        ),
    );
    expect(offenders).toEqual([]);
  });

  it("scans a tree that is actually there, so the two absences mean something", () => {
    // Both assertions above are «found nothing». A broken walk would satisfy
    // them silently, which is the failure mode this whole change is about.
    expect(ALL_FILES.length).toBeGreaterThan(200);
    expect(ALL_FILES).toContain("app/globals.css");
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
