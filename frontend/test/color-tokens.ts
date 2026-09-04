/**
 * The patterns behind the colour guard of design D12/D13, extracted so they can
 * be tested against synthetic strings instead of only against whatever the tree
 * happens to contain.
 *
 * The extraction is itself a review finding. The section-8 panel found **ten**
 * holes in the first two versions of this guard — variant prefixes, arbitrary
 * values, typed CSS-variable shorthand, capitalised token names, single-quoted
 * inline styles, non-hex colour literals, gradient and shadow prefixes, and two
 * legitimate utilities wrongly rejected — and every one of them was invisible to
 * a test that only asserts «the current tree is clean». As the architect put it:
 * the guard «would go green on a broken regex whenever the tree doesn't happen
 * to exercise the break».
 *
 * So the patterns live here and `color-tokens.patterns.test.ts` drives them from
 * a table. Each row of that table is a hole a reviewer found; adding a row is how
 * the next one gets closed.
 */

/** Every prefix that can carry a colour. */
export const COLOR_PREFIX =
  "bg|text|border|ring|fill|stroke|outline|divide|decoration|accent|caret|placeholder|from|via|to|shadow";

/**
 * An optional variant chain: `hover:`, `focus-visible:`, `sm:`,
 * `data-[state=open]:`, and any stack of them.
 *
 * The first version opened with `(?<![\w:/-])`, and that lookbehind does not
 * STRIP a variant — it excludes the match entirely. `hover:bg-card` produced
 * nothing, so 19 live occurrences across 10 distinct utilities were unscanned and
 * `hover:text-destructive` — one keystroke from the D13 bug — was invisible.
 */
export const VARIANT = String.raw`(?:[a-z][a-z0-9-]*(?:-\[[^\]]*\])?:)*`;

/** An optional Tailwind `!important` marker, either side of the utility. */
const BANG = String.raw`!?`;

/** Every numeric colour scale Tailwind ships, as the utilities that name one. */
export const RAW_SCALE =
  /\b(bg|text|border|ring|fill|stroke|outline|divide|decoration|shadow|accent|caret|placeholder|from|via|to)-(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b/g;

/**
 * A theme variant that follows the OS instead of our `data-theme` attribute.
 *
 * Two forms, because the literal `dark:` is not the only way to write one. An
 * arbitrary variant can embed the media query —
 * `[@media(prefers-color-scheme:dark)]:bg-surface` — and compiles to the very
 * same rule, so it reopens the measured R6.5 defect in one line while passing a
 * check that only knows the keyword. Matching is case-insensitive because
 * Tailwind lowercases nothing: `DARK:bg-surface` is the same utility.
 *
 * The bracket form is anchored on the `]:` that makes it a variant, so
 * `matchMedia("(prefers-color-scheme: dark)")` — how `lib/theme/` legitimately
 * reads the OS preference — is not a match.
 *
 * The bracket branch matches the FEATURE NAME ALONE — any arbitrary variant that
 * mentions `prefers-color-scheme`, whatever it then says about it — and that
 * generality is the whole lesson of three review rounds, not caution:
 *   · the first version required the literal `dark:`, and
 *     `[@media(prefers-color-scheme:dark)]:bg-surface` walked through it;
 *   · the second matched `…:\s*dark`, and `…:_dark` walked through it, because
 *     **Tailwind v4 expands `_` to a space inside an arbitrary value or variant**;
 *   · the third would have matched `[\s_]*dark`, and
 *     `[@media_not_(prefers-color-scheme:light)]:bg-surface` walked through THAT,
 *     because the feature has only two values, so negating `light` IS dark and
 *     the word `dark` never appears.
 * Each of those compiles to a real `@media` rule — verified with the project's
 * own `@tailwindcss/postcss`, not assumed — and each reopens the measured R6.5
 * defect. Matching the value was always going to lose that race; matching the
 * feature ends it, and costs nothing, because R1.5 forbids a consumer from
 * following the OS preference AT ALL: colour comes from the resolved theme.
 *
 * Still anchored on the `]:` that makes it a variant, so
 * `matchMedia("(prefers-color-scheme: dark)")` — how `lib/theme/` legitimately
 * reads the preference — is not a match.
 *
 * Comments are stripped before this runs.
 */
export const DARK_VARIANT =
  /\bdark:|\[[^\]]*prefers-color-scheme[^\]]*\]:/gi;

/**
 * A colour utility and the token it names, e.g. `hover:bg-surface` → `surface`.
 *
 * The name accepts capitals: Tailwind is case-sensitive, so `bg-Card` compiles
 * to nothing exactly as `bg-card` did — the D13 defect, one shift key away. The
 * old `[a-z]`-only group could not see it.
 */
export const colorUtility = (): RegExp =>
  new RegExp(
    String.raw`(?<![\w/-])${VARIANT}${BANG}(${COLOR_PREFIX})-([A-Za-z][A-Za-z0-9-]*)${BANG}(?:\/\d{1,3})?\b`,
    "g",
  );

/**
 * A colour that bypasses the token layer: an arbitrary value (`bg-[#e11d48]`) or
 * Tailwind v4's CSS-variable shorthand, with or without a type hint
 * (`bg-(--brand)`, `bg-(color:--brand)`).
 *
 * Brackets are matched as `[^\]]+`, spaces included, because `bg-[oklch(0.7 0.2
 * 20)]` is invalid Tailwind that emits nothing — a silent zero, which is the
 * failure mode this guard exists to prevent, not a thing to skip.
 */
export const arbitraryUtility = (): RegExp =>
  new RegExp(
    String.raw`(?<![\w/-])${VARIANT}${BANG}(?:${COLOR_PREFIX})-(?:\[([^\]]+)\]|\(([^)]+)\))`,
    "g",
  );

/** A Tailwind arbitrary-value type hint, e.g. the `color:` of `text-[color:red]`. */
const TYPE_HINT = /^([a-z-]+):(.*)$/;

/** Hints that declare the value is NOT a colour. */
const NON_COLOR_HINTS = new Set([
  "length",
  "image",
  "url",
  "number",
  "percentage",
  "integer",
  "family-name",
  "generic-name",
  "line-height",
  "font-weight",
  "angle",
  "ratio",
  "position",
  "size",
  "shadow",
]);

/** An arbitrary value that IS a colour. */
const IS_COLOR =
  /^(#|rgba?\(|hsla?\(|hwb\(|oklch\(|oklab\(|lab\(|lch\(|color\(|color-mix\(|light-dark\(|var\(--|--)/i;

/**
 * An arbitrary value that is plainly not a colour: a length, a number, a URL, a
 * computed dimension, or a size/line-height pair.
 *
 * `text-[0.6875rem]` is live in `features/shell/components/version-badge.tsx`,
 * and `text-[0.6875rem/1]` — the same thing with a line height — is one
 * keystroke away. Both are font sizes and neither breaks R1.5.
 */
const IS_DIMENSION =
  /^(-?[\d.]+[a-z%]{0,4}(\s*\/\s*-?[\d.]+[a-z%]{0,4})?$|calc\(|clamp\(|min\(|max\(|url\(|attr\()/i;

/**
 * Bare keywords that are legal on a colour-capable prefix without being colours.
 *
 * A whitelist, because a bare word is otherwise indistinguishable from a named
 * CSS colour: `border-[thin]` is a width and `bg-[rebeccapurple]` is a colour,
 * and only a list can tell them apart. Anything not here fails closed.
 */
const NON_COLOR_KEYWORDS = new Set([
  "thin",
  "medium",
  "thick",
  "auto",
  "none",
  "inherit",
  "initial",
  "unset",
  "revert",
]);

/**
 * Classify an arbitrary value. `true` means it is a colour bypassing the tokens,
 * so a violation.
 *
 * Fails closed: an unrecognised form is a violation, and the failure message
 * tells the reader the two ways out — use a token, or declare the form here.
 */
export function arbitraryIsColor(raw: string): boolean {
  const value = raw.trim();
  // Invalid Tailwind (a literal space) emits nothing at all. A silent zero is
  // exactly what this guard is for, so it counts.
  if (/\s/.test(value) && !IS_DIMENSION.test(value)) return true;

  const hinted = TYPE_HINT.exec(value);
  if (hinted !== null) {
    const [, hint, rest] = hinted;
    if (NON_COLOR_HINTS.has(hint)) return false;
    if (hint === "color") return true;
    return arbitraryIsColor(rest);
  }

  if (IS_COLOR.test(value)) return true;
  if (IS_DIMENSION.test(value)) return false;
  if (NON_COLOR_KEYWORDS.has(value.toLowerCase())) return false;
  return true;
}

/**
 * A CSS colour declaration in an inline style or a JSX attribute.
 *
 * Three things the first version got wrong, all found by the section-8 security
 * reviewer:
 *   · it accepted only `"` as the delimiter, and nothing in this project
 *     enforces double quotes — no prettier, no quote lint rule — so
 *     `style={{ color: '#abc' }}` was invisible;
 *   · it keyed on `#`, so `color: "rgb(255,0,0)"` and `color: "rebeccapurple"`
 *     walked straight through the one channel it was supposed to gate;
 *   · it required `:`, so the JSX attribute form `<path fill="#abc" />` — where
 *     hard-coded hexes actually arrive, in inline SVG — was never examined.
 *
 * And a fourth, found by the review of 2026-08-24: the name had to be followed
 * directly by `:` or `=`, so a computed key — `{ ["color"]: "#e11d48" }`, which
 * JavaScript treats as identical to the plain form — went through untouched.
 * Hence the optional `"]` between the name and its separator.
 */
export const STYLE_COLOR =
  /\b([A-Za-z-]*[Cc]olor|background\w*|border\w*|outline\w*|fill|stroke|box-?[Ss]hadow|text-?[Ss]hadow|filter|stop-?[Cc]olor|flood-?[Cc]olor)\s*(?:["'`]\s*\])?\s*[:=]\s*(?:"([^"]*)"|'([^']*)'|`([^`]*)`)/g;

/** Values that are legal on a colour property without hard-coding a colour. */
const STYLE_VALUE_OK =
  /^(var\(--[^)]+\)|currentColor|inherit|initial|unset|revert|transparent|none|auto|\d+)$/i;

/** A colour literal anywhere inside a shorthand value (`1px solid #ccc`). */
const COLOR_LITERAL =
  /#[0-9a-fA-F]{3,8}\b|\b(rgba?|hsla?|hwb|oklch|oklab|lab|lch|color-mix)\s*\(|\b(aliceblue|antiquewhite|aqua|aquamarine|azure|beige|bisque|black|blanchedalmond|blue|blueviolet|brown|burlywood|cadetblue|chartreuse|chocolate|coral|cornflowerblue|cornsilk|crimson|cyan|darkblue|darkcyan|darkgoldenrod|darkgray|darkgreen|darkgrey|darkkhaki|darkmagenta|darkolivegreen|darkorange|darkorchid|darkred|darksalmon|darkseagreen|darkslateblue|darkslategray|darkslategrey|darkturquoise|darkviolet|deeppink|deepskyblue|dimgray|dimgrey|dodgerblue|firebrick|floralwhite|forestgreen|fuchsia|gainsboro|ghostwhite|gold|goldenrod|gray|green|greenyellow|grey|honeydew|hotpink|indianred|indigo|ivory|khaki|lavender|lavenderblush|lawngreen|lemonchiffon|lightblue|lightcoral|lightcyan|lightgoldenrodyellow|lightgray|lightgreen|lightgrey|lightpink|lightsalmon|lightseagreen|lightskyblue|lightslategray|lightslategrey|lightsteelblue|lightyellow|lime|limegreen|linen|magenta|maroon|mediumaquamarine|mediumblue|mediumorchid|mediumpurple|mediumseagreen|mediumslateblue|mediumspringgreen|mediumturquoise|mediumvioletred|midnightblue|mintcream|mistyrose|moccasin|navajowhite|navy|oldlace|olive|olivedrab|orange|orangered|orchid|palegoldenrod|palegreen|paleturquoise|palevioletred|papayawhip|peachpuff|peru|pink|plum|powderblue|purple|rebeccapurple|red|rosybrown|royalblue|saddlebrown|salmon|sandybrown|seagreen|seashell|sienna|silver|skyblue|slateblue|slategray|slategrey|snow|springgreen|steelblue|tan|teal|thistle|tomato|turquoise|violet|wheat|white|whitesmoke|yellow|yellowgreen)\b/i;

/**
 * Does this style declaration hard-code a colour?
 *
 * A property whose name ends in `Color` (plus `fill`/`stroke`) has a value that
 * IS a colour, so anything but a token reference or a keyword is a violation. A
 * shorthand (`border`, `background`, `boxShadow`, `filter`) can legally carry
 * lengths and keywords, so there it is the presence of a colour literal that
 * decides — which is what catches `border: "1px solid #ccc"`.
 */
export function styleValueIsHardCodedColor(
  property: string,
  value: string,
): boolean {
  const trimmed = value.trim();
  if (trimmed === "") return false;
  if (STYLE_VALUE_OK.test(trimmed)) return false;

  const colorOnly = /[Cc]olor$/.test(property) || /^(fill|stroke)$/.test(property);
  if (colorOnly) {
    // `var(--x) ` or a keyword already returned above; a bare length on a colour
    // property is nonsense, so whatever is left is a hard-coded colour.
    return !/^var\(--/.test(trimmed);
  }
  return COLOR_LITERAL.test(trimmed);
}

/**
 * Comments are stripped before anything is counted.
 *
 * `lib/ui/status-tone.ts` explains in prose why the `dark:` variant was removed,
 * so the word appears three times in a doc comment there. Counting it would make
 * the file that FIXED R6.5 the file that fails the guard for it, and the obvious
 * workaround — rewording the comment — would delete the explanation to satisfy a
 * regex.
 *
 * Strings are NOT stripped: a class name lives in a string literal, so that is
 * where the guard has to look.
 *
 * A scanner rather than two `replace` calls, because a comment delimiter has no
 * meaning inside a string and a regex cannot know which it is looking at. The
 * review of 2026-08-24 demonstrated both halves of that: `const marker = "/*";`
 * made the unanchored block rule swallow everything up to the next `*` slash —
 * live classes included, reported as zero violations — and the line rule, which
 * only excluded a preceding quote or colon, deleted the rest of any line where
 * `//` followed a letter, `}` or `)`, so `<img src="a//b.png" className="…"/>`
 * lost its class. Walking the source keeps the two states apart by construction.
 *
 * Escapes are honoured outside strings too: that is what stops the `\/` of a
 * regex literal such as `/https?:\/\//` from reading as a line comment.
 */
export function stripCode(source: string): string {
  let out = "";
  let i = 0;
  while (i < source.length) {
    const char = source[i];
    if (char === '"' || char === "'" || char === "`") {
      out += char;
      i += 1;
      while (i < source.length) {
        if (source[i] === "\\") {
          out += source.slice(i, i + 2);
          i += 2;
          continue;
        }
        out += source[i];
        i += 1;
        if (source[i - 1] === char) break;
      }
      continue;
    }
    if (char === "\\") {
      out += source.slice(i, i + 2);
      i += 2;
      continue;
    }
    if (char === "/" && source[i + 1] === "*") {
      const end = source.indexOf("*/", i + 2);
      i = end === -1 ? source.length : end + 2;
      continue;
    }
    if (char === "/" && source[i + 1] === "/") {
      const end = source.indexOf("\n", i);
      i = end === -1 ? source.length : end;
      continue;
    }
    out += char;
    i += 1;
  }
  return out;
}

/**
 * The class list of every `@apply` directive in a stylesheet, and nothing else.
 *
 * This is the answer to «what does the guard do with CSS», and the reason it is
 * not «scan it like a component»: a stylesheet's own declarations are not
 * utility classes, and running the class patterns over them reports nonsense —
 * `border-color: var(--color-border)` reads as the prefix `border` naming an
 * undeclared token `color`, and `@media (prefers-color-scheme: dark)` reads as a
 * theme variant. `@apply` is the one place a stylesheet does name utilities, so
 * it is the one place the class patterns mean anything.
 *
 * No file uses `@apply` today (`app/globals.css` is the only stylesheet and has
 * none), which is precisely why this had to be written before one does.
 */
export function applyDirectives(css: string): string {
  return [...css.matchAll(/@apply\s+([^;}]+)/g)].map(([, list]) => list).join("\n");
}

/**
 * What each prefix can legally name that is NOT a colour.
 *
 * A whitelist, not a blacklist, and that is the whole design: an unrecognised
 * value fails and the message tells you the two ways out — declare the token, or
 * add the keyword here. A blacklist of known non-colours would pass anything
 * new, which is exactly how `bg-card` survived.
 */
export const NON_COLOR: Record<string, RegExp> = {
  bg: /^(none|inherit|current|transparent|auto|cover|contain|center|top|bottom|left|right|repeat|repeat-x|repeat-y|no-repeat|repeat-round|repeat-space|fixed|local|scroll|clip-\w+|origin-\w+|blend-[\w-]+|gradient-to-[a-z]+|linear-[\w-]+|radial-[\w-]+|conic-[\w-]+)$/,
  // `glow` is `@utility text-glow` (design D4) — a hand-authored text-shadow
  // effect keyed off `--color-primary`, not a `text-<color>` utility naming a
  // colour of its own.
  text: /^(inherit|current|transparent|xs|sm|base|lg|xl|\d?xl|left|center|right|justify|start|end|ellipsis|clip|wrap|nowrap|balance|pretty|glow)$/,
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
  // `2xs` is a real default utility of the pinned tailwindcss 4.3.2
  // (`theme.css`: `--shadow-2xs`). The first pattern knew `2xl` via `\d?xl` and
  // rejected `2xs`, so reaching for a first-party shadow failed the build as a
  // colour violation. Found by the section-8 QA reviewer.
  shadow: /^(none|inner|inherit|current|transparent|\d?xs|\d?sm|md|\d?lg|\d?xl)$/,
};

/**
 * Does this named utility reference a colour token at all?
 *
 * `false` for the non-colour meanings a colour-capable prefix also carries —
 * `text-sm` is a size, `border-b` a side, `shadow-lg` an elevation. Shared by the
 * tree walk and by the pattern tests, so both classify identically; keeping a
 * second copy in the test was how eight rows disagreed with the guard.
 *
 * `textRoles` is the set of typographic roles the plain `@theme` block declares
 * as `--text-*` (design D10), and it has to be passed in because `NON_COLOR.text`
 * knows only Tailwind's numeric scale: without it `text-display-2xl` — a token
 * this very change introduces — classifies as a colour utility naming an
 * undeclared colour, and the first screen to use one fails the build asking for
 * a `--color-display-2xl` that must not exist. D10 and D12 never conflicted; the
 * guard was reading the wrong `@theme` block.
 */
export function namesAColorToken(
  prefix: string,
  name: string,
  textRoles: ReadonlySet<string>,
): boolean {
  if (prefix === "text" && textRoles.has(name)) return false;
  return !(NON_COLOR[prefix]?.test(name) ?? false);
}
