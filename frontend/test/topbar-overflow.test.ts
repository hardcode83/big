import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The structural half of R5's guard (`shell-topbar-overflow-360`, design D6).
 *
 * **Where it lives and how it runs** (R5.2): here, in the default Vitest
 * project, so `npm test` from `frontend/` runs it with everything else. It needs
 * no browser, no built app and no container — it reads source files and walks
 * the import graph with `node:fs` alone, so it also runs unchanged in the
 * `frontend-tests` CI job.
 *
 * It measures no widths, and must not be mistaken for the guard that does.
 * jsdom performs no layout — `scrollWidth` is always 0 — and R5.2 forbids
 * passing off an assertion that measures nothing. Section 6 of this change adds
 * the measured guard, in Chromium, under its own `npm run test:layout` (design
 * D6, task 6.3); **it does not exist yet**, so the reference is forward-looking
 * rather than a statement of fact, and this file is deliberately not asserted to
 * have a counterpart. What this file does instead is pin the SHAPE of the fix —
 * the arrangement that makes the measured width come out right — so a refactor
 * which quietly undoes it fails in the fast suite too.
 *
 * **What this guard learned about itself.** Two review rounds broke it seven
 * times, and every escape had the same form: the assertion pinned a *spelling*
 * more tightly while the mechanism moved somewhere the guard did not read — an
 * inline `style`, an arbitrary property inside brackets, a mount one file away,
 * a class appended after the caller's. So each check below asks what the branch
 * *is* rather than what it must not be spelled: which element decides `display`,
 * how many mount sites exist in the whole subtree, whether anything but a class
 * can decide visibility. The holes are named at the assertion that closes each
 * one, because a guard's history is worth more written down than fixed silently.
 *
 * **The two holes that are still open, deliberately.** Both need someone to work
 * at it, neither is a shape a well-meaning refactor produces, and both are caught
 * by construction by the measured guard of section 6 — which observes the
 * rendered width at 360px rather than the spelling that produced it. They are
 * recorded rather than chased because each further round of this has closed one
 * spelling and revealed the next:
 *
 * 1. `mountSites()` counts a literal tag name. A *second alias for the same
 *    import* in a file the walk already reaches —
 *    `import { ThemeSwitcher as ThemeToggle } from "./theme-switcher"`, then
 *    mounting both — is three real mounts and two literal `<ThemeSwitcher` tags.
 *    A pure rename is caught (the count drops to zero and this goes red); an
 *    addition under a second name is not. Closing it means resolving local
 *    binding names per file from the import statements the walk already parses.
 * 2. `DISPLAY_UTILITIES` knows Tailwind's twenty-one names and `[display:…]`, not
 *    this project's own vocabulary. `app/globals.css` authors utilities
 *    (`@utility tap-target`, `@utility pb-safe`); one declaring `display` — say
 *    `@utility topbar-wide { display: flex; }`, used as `max-sm:topbar-wide` —
 *    would set the wide branch visible at 360px and pass `displayTokens`
 *    unnoticed. Closing it means harvesting every `@utility` whose body declares
 *    `display` out of the stylesheet this file already reads.
 */

const FRONTEND_ROOT = resolve(__dirname, "..");

const THEME_SWITCHER = "features/shell/components/theme-switcher.tsx";
const LOCALE_SWITCHER = "features/shell/components/locale-switcher.tsx";
const TOPBAR_PREFERENCES = "features/shell/components/topbar-preferences.tsx";
const OVERFLOW_SHEET = "features/shell/components/topbar-overflow-sheet.tsx";
const AUTHENTICATED_ACTIONS =
  "features/shell/components/authenticated-topbar-actions.tsx";
const GLOBAL_CSS = "app/globals.css";

/** The three shells that carry the five-control authenticated composition (D3). */
const AUTHENTICATED_SHELLS = [
  "features/shell/components/workspace-shell.tsx",
  "features/shell/components/cleaner-shell.tsx",
  "features/shell/components/technician-shell.tsx",
];

/**
 * Every file that composes a topbar `end` slot of its own. The fourth one is
 * the odd member and belongs here for that reason: `(authenticated)/layout.tsx`
 * overrides `end` with `UserMenu` alone and deliberately shows no preference
 * controls at all (its own comment says so), so it is exactly the place where
 * someone would later «add the theme switcher back» by hand and reintroduce the
 * fourth copy this change removed.
 */
const TOPBAR_COMPOSITIONS = [
  ...AUTHENTICATED_SHELLS,
  "app/(authenticated)/layout.tsx",
];

/** Every path this file names. Asserted to exist, so the scope cannot rot. */
const IN_SCOPE = [
  ...TOPBAR_COMPOSITIONS,
  TOPBAR_PREFERENCES,
  OVERFLOW_SHEET,
  AUTHENTICATED_ACTIONS,
  THEME_SWITCHER,
  LOCALE_SWITCHER,
  GLOBAL_CSS,
];

function read(relativePath: string): string {
  return readFileSync(join(FRONTEND_ROOT, relativePath), "utf8");
}

/** Source with comments removed, so prose ABOUT a control is not read as code. */
function code(relativePath: string): string {
  return read(relativePath)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

// ---------------------------------------------------------------------------
// Import graph
// ---------------------------------------------------------------------------

const EXTENSIONS = [".ts", ".tsx", ".js", ".jsx"];

/** Resolves an import specifier to a frontend-relative path, or null if external. */
function resolveSpecifier(specifier: string, importer: string): string | null {
  let base: string;
  if (specifier.startsWith("@/")) {
    base = join(FRONTEND_ROOT, specifier.slice(2));
  } else if (specifier.startsWith(".")) {
    base = resolve(dirname(join(FRONTEND_ROOT, importer)), specifier);
  } else {
    return null; // node_modules or a builtin — not ours to walk
  }
  const relativise = (absolute: string) =>
    absolute.slice(FRONTEND_ROOT.length + 1).split("\\").join("/");
  for (const extension of EXTENSIONS) {
    if (existsSync(`${base}${extension}`)) {
      return relativise(`${base}${extension}`);
    }
  }
  for (const extension of EXTENSIONS) {
    const candidate = join(base, `index${extension}`);
    if (existsSync(candidate)) return relativise(candidate);
  }
  return existsSync(base) ? relativise(base) : null;
}

const STATIC_IMPORT_RE =
  /(?:^|\n)\s*(?:import|export)[\s\S]*?from\s*["']([^"']+)["']/g;
const BARE_IMPORT_RE = /(?:^|\n)\s*import\s*["']([^"']+)["']/g;
/**
 * `next/dynamic` and `React.lazy` both mount through a call expression, which
 * carries no `from` clause and so produced no edge in the first version. Neither
 * appears in the tree today, but a lazily-imported switcher is a mount like any
 * other and the walk should not depend on that staying true.
 */
const DYNAMIC_IMPORT_RE = /\bimport\(\s*["']([^"']+)["']\s*\)/g;

function importsOf(relativePath: string): string[] {
  let source: string;
  try {
    // Comment-stripped: a specifier quoted inside prose is not an edge. This is
    // what keeps `(authenticated)/layout.tsx`'s «ThemeSwitcher … intentionally
    // absent» comment from being read as a mount.
    source = code(relativePath);
  } catch {
    return [];
  }
  const found: string[] = [];
  for (const pattern of [STATIC_IMPORT_RE, BARE_IMPORT_RE, DYNAMIC_IMPORT_RE]) {
    for (const match of source.matchAll(pattern)) {
      const resolved = resolveSpecifier(match[1], relativePath);
      if (resolved) found.push(resolved);
    }
  }
  return found;
}

/**
 * The import chain from `entry` to `target` that avoids every file in `blocked`,
 * or null when none exists.
 *
 * Reachability rather than a name check is what makes this rename-proof: a
 * shell that mounts `ThemeSwitcher` directly, under an alias, through a new
 * wrapper, or via a barrel re-export all show up the same way — as a path to
 * `theme-switcher.tsx` that does not pass through `topbar-preferences.tsx`.
 * Returning the chain rather than a boolean is what makes a failure actionable.
 */
function chainTo(
  entry: string,
  target: string,
  blocked: ReadonlySet<string>,
): string[] | null {
  if (blocked.has(entry)) return null;
  const seen = new Set<string>([entry]);
  const stack: { file: string; chain: string[] }[] = [
    { file: entry, chain: [entry] },
  ];
  while (stack.length > 0) {
    const { file, chain } = stack.pop()!;
    for (const next of importsOf(file)) {
      if (blocked.has(next) || seen.has(next)) continue;
      if (next === target) return [...chain, next];
      seen.add(next);
      stack.push({ file: next, chain: [...chain, next] });
    }
  }
  return null;
}

/** Every file reachable from `entry`, `entry` included. */
function reachableFrom(entry: string): string[] {
  const seen = new Set<string>([entry]);
  const stack = [entry];
  while (stack.length > 0) {
    for (const next of importsOf(stack.pop()!)) {
      if (seen.has(next)) continue;
      seen.add(next);
      stack.push(next);
    }
  }
  return [...seen].sort();
}

/** How many times `<Name` is mounted, per file, across a set of files. */
function mountSites(files: string[], component: string): { file: string; count: number }[] {
  const pattern = new RegExp(`<${component}\\b`, "g");
  return files
    .map((file) => {
      let source: string;
      try {
        source = code(file);
      } catch {
        return { file, count: 0 };
      }
      return { file, count: (source.match(pattern) ?? []).length };
    })
    .filter((entry) => entry.count > 0);
}

// ---------------------------------------------------------------------------
// JSX attributes
// ---------------------------------------------------------------------------

/**
 * Opening and closing tags, with their attribute text. Quoted strings and brace
 * expressions are consumed as units so an attribute value containing `>` or `}`
 * does not end the tag early. Fragments (`<>` / `</>`) match neither, which is
 * fine and symmetric: they carry no attributes and never unbalance the stack.
 */
const TAG_RE =
  /<(\/?)([A-Za-z][\w.]*)((?:"[^"]*"|'[^']*'|\{(?:[^{}]|\{[^{}]*\})*\}|[^>"'{}])*?)(\/?)>/g;

/** The value text of a `className` attribute — the string, or the expression. */
function classNameOf(attributes: string): string | null {
  const match = attributes.match(
    /\bclassName\s*=\s*(?:"([^"]*)"|\{((?:[^{}]|\{[^{}]*\})*)\})/,
  );
  if (!match) return null;
  return match[1] !== undefined ? match[1] : match[2];
}

/** Every class token in an attribute value, whether a literal or a `cn(…)` call. */
function classTokens(value: string | null): Set<string> {
  if (!value) return new Set();
  const literals = /["'`]/.test(value)
    ? [...value.matchAll(/["'`]([^"'`]*)["'`]/g)].map((match) => match[1])
    : [value];
  const tokens = new Set<string>();
  for (const literal of literals) {
    for (const token of literal.split(/\s+/)) if (token) tokens.add(token);
  }
  return tokens;
}

/**
 * The attributes of every ancestor element of `<Child`, innermost first.
 *
 * A depth-tracked stack, not «the last opening tag before it». That shortcut was
 * the earlier bug: wrapping the switcher in a provider —
 * `<div className="hidden sm:flex"><TooltipProvider><ThemeSwitcher/>` — made it
 * return the provider and fail with «the wide branch carries no className»,
 * which was simply untrue. A guard that fails on an innocuous edit, and lies
 * about why, is a guard that gets deleted.
 */
function ancestorsOf(source: string, child: string): string[] {
  const childAt = source.indexOf(`<${child}`);
  if (childAt === -1) return [];
  const open: string[] = [];
  for (const match of source.matchAll(TAG_RE)) {
    if (match.index! >= childAt) break;
    if (match[1] === "/") open.pop();
    else if (match[4] !== "/") open.push(match[3]);
  }
  return open.reverse();
}

/** The attributes of the first `<Name …>` element in a source. */
function elementAttributes(source: string, name: string): string | undefined {
  return [...source.matchAll(TAG_RE)].find(
    (match) => match[1] !== "/" && match[2] === name,
  )?.[3];
}

/**
 * Tailwind's `display` utilities, all twenty-one of them. The branch that does
 * not apply must stop occupying width AND stop being reachable by assistive
 * technology and by Tab, and `display: none` is the only mechanism that does
 * both — so a branch's display tokens are pinned as an EXACT SET, never as
 * «contains `hidden`».
 *
 * «Contains» let `hidden items-center gap-2 max-sm:flex sm:flex` through: both
 * expected tokens present, and the wide branch rendering at 360px anyway — the
 * overflow this change removes, plus a duplicate of each control for R4.2 to
 * trip over.
 */
const DISPLAY_UTILITIES = new Set([
  "block", "inline-block", "inline", "flex", "inline-flex", "flow-root", "grid",
  "inline-grid", "contents", "table", "inline-table", "table-caption",
  "table-cell", "table-column", "table-column-group", "table-footer-group",
  "table-header-group", "table-row-group", "table-row", "list-item", "hidden",
]);

/** An arbitrary property that sets `display` directly, e.g. `[display:flex]`. */
const ARBITRARY_DISPLAY = /^\[\s*display\s*:/i;

/**
 * The utility a token applies, with every variant prefix removed.
 *
 * Splits on `:` **at bracket depth zero only**. `lastIndexOf(":")` was the bug:
 * for `max-sm:[display:flex]` it returned `flex]`, which matched no utility, so
 * the token vanished from the set and the exact-set assertion above passed while
 * the wide branch was `display:flex` below 640px. The colon that matters is the
 * variant separator, and that one is never inside brackets.
 */
function bareUtility(token: string): string {
  let depth = 0;
  let lastSeparator = -1;
  for (let index = 0; index < token.length; index += 1) {
    const character = token[index];
    if (character === "[" || character === "(") depth += 1;
    else if (character === "]" || character === ")") depth -= 1;
    else if (character === ":" && depth === 0) lastSeparator = index;
  }
  return token.slice(lastSeparator + 1);
}

function isDisplayToken(token: string): boolean {
  const utility = bareUtility(token);
  return DISPLAY_UTILITIES.has(utility) || ARBITRARY_DISPLAY.test(utility);
}

function displayTokens(tokens: Set<string>): string[] {
  return [...tokens].filter(isDisplayToken).sort();
}

/** An inline `style`, which beats every class at every width. */
const HAS_INLINE_STYLE = /\bstyle\s*=/;

/**
 * The wide branch and what surrounds it, as one analysis both the check and its
 * fixtures call.
 *
 * The branch is identified by what it DOES — the innermost ancestor of
 * `<ThemeSwitcher>` that is `display:none` at the base width — rather than by
 * tag name or position. Ancestors *inside* it are free: they sit in a
 * `display:none` subtree, so their own display cannot matter.
 *
 * One function rather than two because the fixtures below used to select the
 * branch by «the first ancestor with any display token» while the check selected
 * by «the first ancestor that is `hidden`». They agreed on today's tree and on
 * nothing else, so the fixtures certified a paraphrase: had the real selector
 * regressed, every one of them would have stayed green.
 */
function analyseWideBranch(source: string) {
  const ancestors = ancestorsOf(source, "ThemeSwitcher").map((attributes) => ({
    attributes,
    display: displayTokens(classTokens(classNameOf(attributes))),
  }));
  const rootIndex = ancestors.findIndex((ancestor) =>
    ancestor.display.includes("hidden"),
  );
  return {
    ancestors,
    rootIndex,
    root: rootIndex >= 0 ? ancestors[rootIndex] : null,
    outerDisplay:
      rootIndex >= 0
        ? ancestors.slice(rootIndex + 1).flatMap((ancestor) => ancestor.display)
        : [],
  };
}

/**
 * Utilities that hide a branch WITHOUT removing its box from layout.
 *
 * `opacity-0` and `sr-only` leave the subtree in the accessibility tree and in
 * the tab order, which breaks R4.2: «en cualquier ancho la tecnología asistiva
 * encuentre una sola instancia de cada control». `invisible`
 * (`visibility: hidden`) does leave the a11y tree, but keeps the box — so the
 * wide branch would still claim its ~150px at 360px and R1 would fail while the
 * accessibility tree looked correct, which is the substitution most likely to
 * survive a review.
 *
 * Matched after a token boundary that includes `:`, so every Tailwind variant
 * spelling (`sm:invisible`, `max-md:opacity-0`, `[&>*]:sr-only`) is covered by
 * the same pattern rather than by enumerating prefixes.
 */
const LAYOUT_PRESERVING_HIDE =
  /(?:^|[\s:"'`])(invisible|collapse|sr-only|opacity-0)(?=$|[\s"'`])/;

// ---------------------------------------------------------------------------

describe("shell-topbar-overflow-360 — the shape of the 360px fix", () => {
  it("every file in scope exists, so this guard cannot rot into a blind spot", () => {
    for (const file of IN_SCOPE) {
      expect(
        existsSync(join(FRONTEND_ROOT, file)),
        `file in scope no longer exists: ${file}`,
      ).toBe(true);
    }
  });

  it("the walk really reaches the switchers, so the next check is not vacuous", () => {
    // The positive control. Without it a resolver that silently found nothing
    // would satisfy the assertion below while inspecting zero imports — a guard
    // that cannot fail, which is worse than no guard because it reads as
    // evidence.
    for (const entry of TOPBAR_COMPOSITIONS) {
      expect(
        chainTo(entry, THEME_SWITCHER, new Set()),
        `${entry} reaches no theme switcher at all — the import walk is broken`,
      ).not.toBeNull();
      expect(
        chainTo(entry, LOCALE_SWITCHER, new Set()),
        `${entry} reaches no locale switcher at all — the import walk is broken`,
      ).not.toBeNull();
    }
  });

  it("no topbar composition reaches a switcher except through TopbarPreferences", () => {
    /*
     * D3: the five-control fragment used to be written out identically in the
     * three authenticated shells, which is why the overflow had to be fixed
     * three times and why nothing could pin the composition. After this change
     * there is ONE place that mounts the two preference controls, and both
     * layouts are chosen there.
     */
    const onlyDoor = new Set([TOPBAR_PREFERENCES]);
    for (const entry of TOPBAR_COMPOSITIONS) {
      for (const switcher of [THEME_SWITCHER, LOCALE_SWITCHER]) {
        const bypass = chainTo(entry, switcher, onlyDoor);
        expect(
          bypass === null ? null : bypass.join("\n  → "),
          `${entry} reaches ${switcher} without going through ${TOPBAR_PREFERENCES}. ` +
            "That is a second mount of a preference control: the narrow layout " +
            "would not apply to it, and at 360px the bar overflows again.",
        ).toBeNull();
      }
    }
  });

  it("the three authenticated shells hand Topbar the shared end slot", () => {
    for (const shell of AUTHENTICATED_SHELLS) {
      const source = code(shell);
      expect(
        source,
        `${shell} must bind AuthenticatedTopbarActions to the topbar's \`end\` slot ` +
          "rather than spelling the five controls out again (D3)",
      ).toMatch(/\bend\b\s*[:=]\s*[({]?\s*<AuthenticatedTopbarActions\b/);
      /*
       * Deliberately stops before the first `<`: the value bound to `end` may be
       * a JSX element full of braces, and a pattern that had to reach the call's
       * closing `}` failed on the behaviour-identical inline form
       * `Topbar({ start, end: <AuthenticatedTopbarActions … /> })`.
       */
      expect(
        source,
        `${shell} must pass that slot to Topbar as \`end\``,
      ).toMatch(/Topbar\(\s*\{[^<>]*?\bend\b/);
    }
  });

  it("the whole TopbarPreferences subtree mounts each control exactly twice", () => {
    /*
     * Two mount sites per control, one per branch — that is what D4 buys with
     * «duplicar dos islas», and any third is a control assistive technology
     * finds twice at some width (R4.2).
     *
     * Counted across everything reachable FROM `topbar-preferences.tsx`, not in
     * that file and the sheet alone. Two-file counting was the previous hole:
     * `topbar-preferences.tsx` is the very file the reachability walk BLOCKS, so
     * a new `quick-theme.tsx` mounting a third `<ThemeSwitcher>` and imported
     * there was invisible to both mechanisms at once — the per-file counts
     * stayed at one, and every path still went through the blocked door. The
     * same walk, run forward from the door instead of stopped at it, sees it.
     */
    const subtree = reachableFrom(TOPBAR_PREFERENCES);
    expect(
      subtree.length,
      "the walk from TopbarPreferences found almost nothing — it is broken",
    ).toBeGreaterThan(3);

    for (const [control, expected] of [
      ["ThemeSwitcher", 2],
      ["LocaleSwitcher", 2],
      ["TopbarOverflowSheet", 1],
    ] as const) {
      const sites = mountSites(subtree, control);
      const total = sites.reduce((sum, site) => sum + site.count, 0);
      expect(
        total,
        `<${control}> must have exactly ${expected} mount site(s) in everything ` +
          `TopbarPreferences reaches — one per layout branch. Found ${total}:\n  ` +
          sites.map((site) => `${site.file} ×${site.count}`).join("\n  ") +
          "\nA third mount is a control assistive technology finds twice (R4.2).",
      ).toBe(expected);
    }
  });

  it("TopbarPreferences decides its two branches with display classes, and nothing else", () => {
    const preferences = code(TOPBAR_PREFERENCES);

    const branch = analyseWideBranch(preferences);
    expect(
      branch.ancestors.length,
      "<ThemeSwitcher> has no ancestor element in TopbarPreferences",
    ).toBeGreaterThan(0);
    expect(
      branch.rootIndex,
      "no ancestor of <ThemeSwitcher> is `hidden` at the base width, so the wide " +
        "branch is not display:none at 360px (R1.1, R4.2)",
    ).toBeGreaterThanOrEqual(0);
    const root = branch.root!;

    expect(
      root.display,
      "the wide branch must be display:none below the breakpoint and a flex row " +
        "from `sm` up, and carry no OTHER display utility — a second one, named " +
        "(`max-sm:flex`) or arbitrary (`max-sm:[display:flex]`), brings it back " +
        "at 360px: the overflow this change removes, plus a duplicate of each " +
        "control (R1.1, R4.2)",
    ).toEqual(["hidden", "sm:flex"]);

    /*
     * Not because an outer element could re-show the branch — `display` does not
     * cascade, and nothing an ancestor declares reveals a `display:none`
     * descendant. The earlier version of this comment said otherwise, which was
     * simply wrong, and a reader who checked it would rightly have deleted the
     * assertion. The real reasons to keep it: an outer ancestor CAN hide the whole
     * slot at a width where the bar needs it, and `display: contents` on one
     * changes which boxes the branch generates at all — both of which move the
     * layout decision off the element this test then goes on to pin.
     */
    expect(
      branch.outerDisplay,
      "no element OUTSIDE the wide branch may decide display: the branch's " +
        "visibility must be decided on the one element this guard checks, not " +
        "split across its ancestors (R4.1, R4.2)",
    ).toEqual([]);

    expect(
      HAS_INLINE_STYLE.test(root.attributes),
      "the wide branch must not carry an inline `style`: it beats every class at " +
        "every width, so `display` would no longer come from the media query " +
        "(R4.1 «mediante media queries de CSS», R4.2)",
    ).toBe(false);

    // The narrow branch: the sheet, hidden from sm upwards.
    const sheetAttributes = elementAttributes(preferences, "TopbarOverflowSheet");
    expect(
      sheetAttributes,
      "TopbarOverflowSheet is no longer mounted as a JSX element",
    ).toBeDefined();
    expect(
      displayTokens(classTokens(classNameOf(sheetAttributes!))),
      "the sheet must be display:none from `sm` up and visible below it, with no " +
        "other display utility (R4.2)",
    ).toEqual(["sm:hidden"]);
    expect(
      HAS_INLINE_STYLE.test(sheetAttributes!),
      "the sheet must not carry an inline `style` (R4.1, R4.2)",
    ).toBe(false);

    // And nothing in the file hides a branch by a means that keeps its box or
    // its tab stop. Scanned over the whole source rather than over the two class
    // lists above, so moving the utility onto an inner wrapper does not dodge it.
    expect(
      LAYOUT_PRESERVING_HIDE.exec(preferences)?.[1] ?? null,
      `${TOPBAR_PREFERENCES} hides a branch with a utility that leaves its box ` +
        "or its tab stop in place; R4.2 and R1 both need display:none",
    ).toBeNull();
  });

  it("the class helpers behave on the shapes they exist for", () => {
    // Fixtures, not the tree: a pattern is only evidence once it has been shown
    // to fire, and a tree nobody touched passes every guard.
    for (const sample of [
      '<div className="invisible sm:flex">',
      '<div className="opacity-0 sm:opacity-100">',
      '<div className="sr-only sm:not-sr-only">',
      '<div className="hidden sm:invisible">',
    ]) {
      expect(LAYOUT_PRESERVING_HIDE.test(sample), sample).toBe(true);
    }
    for (const sample of [
      '<div className="hidden items-center gap-2 sm:flex">',
      '<TopbarOverflowSheet initial={initial} className="sm:hidden" />',
    ]) {
      expect(LAYOUT_PRESERVING_HIDE.test(sample), sample).toBe(false);
    }

    // Variant stripping must split on the separator, not on the last colon.
    expect(bareUtility("sm:flex")).toBe("flex");
    expect(bareUtility("max-sm:[display:flex]")).toBe("[display:flex]");
    expect(bareUtility("[@media(prefers-color-scheme:dark)]:bg-surface")).toBe(
      "bg-surface",
    );
    expect(isDisplayToken("max-sm:[display:flex]")).toBe(true);
    expect(isDisplayToken("supports-[display:grid]:grid")).toBe(true);
    expect(isDisplayToken("[@media(prefers-color-scheme:dark)]:bg-surface")).toBe(false);
    expect(isDisplayToken("items-center")).toBe(false);

    // Ancestor resolution, and the reformattings it must survive. Calls the same
    // `analyseWideBranch` the check above uses, so these fixtures exercise the
    // production selector rather than a paraphrase of it.
    const wideOf = (source: string) => analyseWideBranch(source).root?.display ?? [];
    expect(
      wideOf('<div className="hidden items-center gap-2 sm:flex"><ThemeSwitcher />'),
    ).toEqual(["hidden", "sm:flex"]);
    expect(
      wideOf(
        '<div data-slot="prefs" className="hidden items-center gap-2 sm:flex"><ThemeSwitcher />',
      ),
      "a cosmetic extra attribute must not turn this guard red",
    ).toEqual(["hidden", "sm:flex"]);
    expect(
      wideOf('<div className={cn("hidden items-center sm:flex")}><ThemeSwitcher />'),
      "wrapping the classes in cn() must not turn this guard red",
    ).toEqual(["hidden", "sm:flex"]);
    expect(
      wideOf(
        '<div className="hidden items-center sm:flex"><TooltipProvider><ThemeSwitcher />',
      ),
      "an intermediate provider must not turn this guard red",
    ).toEqual(["hidden", "sm:flex"]);
    expect(
      wideOf('<div className="hidden items-center max-sm:[display:flex] sm:flex"><ThemeSwitcher />'),
      "an arbitrary display property must be visible to this check",
    ).toEqual(["hidden", "max-sm:[display:flex]", "sm:flex"]);
  });

  it("the overflow sheet trigger keeps its 44px tap target and the caller's media query", () => {
    /*
     * R3.1: every touch surface in the header stays at least 44x44px in the
     * narrow layout, «incluidos los controles que pasen al desplegable». The
     * trigger is the one control this change invents, so it is the one R3.1
     * does not already cover through an existing component.
     */
    const sheet = code(OVERFLOW_SHEET);
    const triggerAt = sheet.indexOf("<SheetTrigger");
    const triggerEnd = sheet.indexOf("</SheetTrigger>");
    expect(
      triggerAt >= 0 && triggerEnd > triggerAt,
      "the sheet no longer has a <SheetTrigger> block",
    ).toBe(true);

    const block = sheet.slice(triggerAt, triggerEnd);
    expect(
      (block.match(/<Button\b/g) ?? []).length,
      "the trigger must be exactly one Button, so the assertions below cannot be " +
        "satisfied by some other element in the block",
    ).toBe(1);
    expect(block).toMatch(/\basChild\b/);

    const buttonAttributes = elementAttributes(block, "Button");
    expect(buttonAttributes, "the trigger Button has no attributes").toBeDefined();
    const buttonClassName = classNameOf(buttonAttributes!);
    expect(buttonClassName, "the trigger Button carries no className").not.toBeNull();
    expect(
      classTokens(buttonClassName).has("tap-target"),
      "the trigger must carry `tap-target` explicitly, so the 44px guarantee " +
        "survives a change to the Button primitive's icon size (R3.1)",
    ).toBe(true);

    /*
     * And the caller's media query must reach that same Button, unopposed.
     * `topbar-preferences.tsx` passing `className="sm:hidden"` proves nothing on
     * its own: routing the prop to `SheetContent` would leave the trigger visible
     * at every width, and appending a display class after it —
     * `cn("tap-target", className, "sm:inline-flex")` — lets tailwind-merge
     * resolve the conflict the wrong way. Either way the trigger sits in the bar
     * at ≥640px beside the already-visible wide branch, with a second copy of
     * each control one tap away (R4.2).
     */
    expect(
      buttonClassName!,
      "the trigger Button must compose the incoming `className` prop, which is " +
        "how it receives `sm:hidden` from TopbarPreferences (D3, R4.2)",
    ).toMatch(/\bclassName\b/);
    expect(
      displayTokens(classTokens(buttonClassName)),
      "the trigger Button must contribute NO display class of its own — the only " +
        "one on that element is the `sm:hidden` arriving from the caller (R4.2)",
    ).toEqual([]);
    expect(
      HAS_INLINE_STYLE.test(buttonAttributes!),
      "the trigger must not carry an inline `style`: it would beat the caller's " +
        "media query at every width (R4.1, R4.2)",
    ).toBe(false);

    const propConsumers = [
      ...sheet.matchAll(/\bclassName\s*=\s*(?:"[^"]*"|\{(?:[^{}]|\{[^{}]*\})*\})/g),
    ].filter((match) =>
      /\bclassName\b/.test(match[0].replace(/^\s*className\s*=\s*/, "")),
    );
    expect(
      propConsumers.length,
      "exactly one element in the sheet may consume the `className` prop — the " +
        "trigger. Two would put the media query somewhere it does not belong.",
    ).toBe(1);
    const consumerAt = propConsumers[0].index!;
    expect(
      consumerAt > triggerAt && consumerAt < triggerEnd,
      "the `className` prop must land on the trigger, not on the sheet's content " +
        "or header — only the trigger is in the bar, so only the trigger needs " +
        "hiding from `sm` up (R4.2)",
    ).toBe(true);
  });

  it("the `tap-target` utility exists and really is 44px", () => {
    /*
     * The assertion above pins a class NAME. Nothing tied it to a rule, so
     * renaming or deleting `@utility tap-target` would leave the class inert —
     * the trigger silently falling back to whatever `size="icon"` gives — while
     * this guard still claimed the 44px guarantee (R3.1).
     */
    const css = read(GLOBAL_CSS);
    const declared = css.match(/@utility\s+tap-target\b/);
    expect(
      declared,
      `${GLOBAL_CSS} no longer defines \`@utility tap-target\`, so the class the ` +
        "topbar controls carry does nothing (R3.1)",
    ).not.toBeNull();

    // Brace-balanced, so a nested at-rule cannot truncate the body and make a
    // declaration after it read as absent.
    const open = css.indexOf("{", declared!.index!);
    let depth = 0;
    let close = -1;
    for (let index = open; index < css.length; index += 1) {
      if (css[index] === "{") depth += 1;
      else if (css[index] === "}") {
        depth -= 1;
        if (depth === 0) {
          close = index;
          break;
        }
      }
    }
    expect(close, "`@utility tap-target` has no balanced body").toBeGreaterThan(open);
    const body = css.slice(open + 1, close);

    for (const property of ["min-height", "min-width"]) {
      // px or rem: 2.75rem is the same 44px, and is the spelling a token layer
      // tends toward. Rejecting it would be a guard failing on an equivalent.
      const value = body.match(
        new RegExp(`${property}\\s*:\\s*(\\d+(?:\\.\\d+)?)\\s*(px|rem)`),
      );
      expect(
        value,
        `\`@utility tap-target\` must declare ${property} in px or rem (R3.1)`,
      ).not.toBeNull();
      const pixels = Number(value![1]) * (value![2] === "rem" ? 16 : 1);
      expect(
        pixels,
        `\`@utility tap-target\` must guarantee at least 44px of ${property}, ` +
          `not ${value![1]}${value![2]} (R3.1)`,
      ).toBeGreaterThanOrEqual(44);
    }
  });
});
