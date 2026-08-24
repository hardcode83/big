import { readdirSync, readFileSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * R3.3 is a prohibition, and a prohibition needs a guard rather than a grep —
 * the lesson this change learned when R4.1's «SHALL NOT cargar ninguna fuente
 * desde un CDN» turned out to be pinned by nothing at all.
 *
 * R3.3: «THE SYSTEM SHALL NOT guardar el tema en Zustand ni en ningún store de
 * cliente, ni leerlo solo en el cliente: el store se hidrata después del primer
 * pintado y la página parpadearía del tema equivocado al bueno en cada carga.»
 *
 * It lives in `test/` rather than beside the theme code because it walks the
 * whole tree, which is the shape of the guards already here —
 * `test/eslint-boundaries.test.ts` today, `test/color-tokens.test.ts` from
 * section 8. The unit tests for the theme mechanism itself stay in `lib/theme/`.
 *
 * The first version of this guard was escapable three ways, all of them the
 * natural thing someone would actually write. Each is now closed and named
 * below, because a guard's holes are worth more written down than fixed
 * silently.
 */

const FRONTEND_ROOT = join(__dirname, "..");
const SKIP_DIRS = new Set(["node_modules", ".next", ".git", "coverage"]);

/** Every `.ts`/`.tsx` file in the tree, repo-relative with forward slashes. */
function sourceFiles(): string[] {
  const found: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (SKIP_DIRS.has(entry.name)) continue;
      const full = join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.tsx?$/.test(entry.name)) {
        found.push(relative(FRONTEND_ROOT, full).split(sep).join("/"));
      }
    }
  };
  walk(FRONTEND_ROOT);
  return found;
}

function read(relativePath: string): string {
  return readFileSync(join(FRONTEND_ROOT, relativePath), "utf8");
}

/** Source with comments removed, so prose about the theme is not read as code. */
function code(relativePath: string): string {
  return read(relativePath)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

/**
 * Anything that names the theme, however it is spelled.
 *
 * NOT `/\btheme\b/i`, which was the first version: `\b` requires a non-word
 * character on each side, so `themeMode`, `colorTheme` and `themeState` all
 * slipped through — and those are precisely the names this state would be given.
 */
const NAMES_THEME = /theme|colou?r-?mode|dark-?mode/i;

/**
 * Files exempt from the theme-naming check, with the reason each is exempt.
 * A whitelist, so a new file cannot become exempt by accident.
 */
const MAY_NAME_THEME = new Set([
  // The mechanism itself.
  "lib/theme/theme.ts",
  "lib/theme/server.ts",
  "lib/config/constants.ts",
  "app/layout.tsx",
  /*
   * The switcher, and the one entry that needs justifying rather than listing.
   *
   * It holds the chosen PREFERENCE in `useState` and mutates the document in an
   * effect, which is what the broad net below is looking for — but it is not what
   * R3.3 forbids. R3.3 forbids the THEME being client state: read on the client,
   * hydrated after the first paint, flashing. The switcher never reads the theme;
   * it receives it from the server as `initial` and only writes. The distinction
   * is enforced by its own assertion further down, not lost by this exemption.
   */
  "features/shell/components/theme-switcher.tsx",
  "features/shell/components/theme-switcher.test.tsx",
  /*
   * `Topbar` names the theme because it is where the server value is fetched and
   * handed to the switcher. It is a Server Component with no `"use client"`, so
   * it cannot be client state by construction — the check below asserts that
   * rather than assuming it.
   */
  "features/shell/components/topbar.tsx",
  // Its tests.
  "lib/theme/theme.test.ts",
  "lib/theme/server.test.ts",
  "app/layout.test.tsx",
  "test/theme-client-state.test.ts",
  // The token layer and its guards.
  "app/globals.tokens.test.ts",
  "app/globals.contrast.test.ts",
  "test/css-tokens.ts",
  "test/wcag-contrast.ts",
]);

describe("R3.3 — the theme is never client state", () => {
  it("no Zustand store anywhere names the theme", () => {
    /*
     * Matches the `zustand` package by PREFIX, not by exact specifier.
     * `/from\s+["']zustand["']/` was the first version and it missed
     * `zustand/react` and `zustand/vanilla`, both real v5 entry points — a store
     * written against either was invisible to this walk while the
     * «cannot be outgrown» assertion below still passed.
     */
    const stores = sourceFiles().filter((file) =>
      /from\s+["']zustand(\/[^"']*)?["']/.test(read(file)),
    );

    // Sanity: the walk must actually be finding stores. An empty list here would
    // make the assertion below vacuously true, which is how this class of guard
    // usually dies.
    expect(stores.length).toBeGreaterThan(0);

    const offenders = stores.filter((file) => NAMES_THEME.test(code(file)));
    expect(offenders).toEqual([]);
  });

  it("no client component holds the theme in local or persisted client state", () => {
    /*
     * R3.3 says «ningún store de cliente», not «ningún store de Zustand». The
     * first version of this guard only knew about Zustand, so a `"use client"`
     * component doing `localStorage.getItem` plus `useState`, or a React context
     * provider, was client state that flashed on every load and was matched by
     * nothing.
     */
    const clientStateForms =
      /\b(useState|useReducer|createContext|localStorage|sessionStorage|indexedDB)\b/;

    const offenders = sourceFiles()
      .filter((file) => !MAY_NAME_THEME.has(file))
      .filter((file) => !/\.test\.tsx?$/.test(file))
      .filter((file) => {
        const source = code(file);
        return (
          /^\s*["']use client["']/m.test(source) &&
          clientStateForms.test(source) &&
          NAMES_THEME.test(source)
        );
      });

    expect(offenders).toEqual([]);
  });

  it("nothing outside the theme mechanism names the theme at all", () => {
    /*
     * The broad net. Anything naming the theme outside the whitelist is either
     * client state R3.3 forbids, or a second home for a decision that has one —
     * both worth failing on so the choice is made deliberately.
     */
    const offenders = sourceFiles()
      .filter((file) => !MAY_NAME_THEME.has(file))
      .filter((file) => NAMES_THEME.test(code(file)));
    expect(offenders).toEqual([]);
  });

  it("every whitelisted file exists, so the exemption list cannot rot", () => {
    // An entry for a deleted or renamed file would silently widen the net's
    // blind spot while looking like tightened scope.
    const present = new Set(sourceFiles());
    for (const file of MAY_NAME_THEME) {
      expect(present.has(file), `whitelisted file no longer exists: ${file}`).toBe(
        true,
      );
    }
  });

  it("layout.tsx resolves the theme on the server, not in the client", () => {
    /*
     * The other half of R3.3: «ni leerlo solo en el cliente». The resolver must be
     * CALLED and awaited, not merely imported — asserting the symbol appeared
     * anywhere in the file passed when the call was replaced by `const theme =
     * null;`, because the import line matched.
     */
    const layout = read("app/layout.tsx");
    expect(layout).toMatch(/const\s+theme\s*=\s*await\s+getServerTheme\(\)/);
    expect(layout).toMatch(/data-theme=\{theme \?\? undefined\}/);
    expect(layout).not.toMatch(/^\s*["']use client["']/m);
  });

  it("the switcher receives the theme from the server and never reads it on the client", () => {
    /*
     * What the whitelist above gives up, asserted directly.
     *
     * The switcher is exempt from the broad net because it legitimately holds the
     * chosen preference in client state. What it must NOT do is source the theme
     * from the client — reading the cookie on mount, or `matchMedia`, or
     * `localStorage` — because that is the flash R3.3 exists to prevent: the
     * colours would already be right from the server-rendered attribute while the
     * control corrected itself a tick later.
     */
    // `Topbar` is what hands it over, and it must stay on the server to do so.
    const topbar = code("features/shell/components/topbar.tsx");
    expect(topbar).not.toMatch(/^\s*["']use client["']/m);
    expect(topbar).toMatch(/await\s+getServerTheme\(\)/);
    expect(topbar).toMatch(/<ThemeSwitcher\s+initial=\{theme\}/);

    const source = code("features/shell/components/theme-switcher.tsx");

    // It takes the value as a prop.
    expect(source).toMatch(/initial\s*:\s*Theme \| null/);
    // And never sources it from the client.
    expect(source).not.toMatch(/document\.cookie\s*\.\s*match/);
    expect(source).not.toMatch(/\bmatchMedia\b/);
    expect(source).not.toMatch(/\blocalStorage\b|\bsessionStorage\b/);
    // Reading `document.cookie` at all would mean sourcing rather than writing;
    // the only permitted contact is assignment.
    expect(source).not.toMatch(/=\s*document\.cookie/);
  });

  it("no inline anti-flash script interpolates the cookie into JavaScript", () => {
    /*
     * Forward-looking, and the reason it is here rather than in a later section:
     * the ABSENCE of an inline theme bootstrap is currently load-bearing for
     * security. Resolving on the server is what makes the usual
     * `<script>document.documentElement.dataset.theme = …</script>` unnecessary
     * (design D4 rejects `next-themes` for exactly that reason).
     *
     * If one is ever added, the cookie stops being an HTML attribute value —
     * where React's escaping plus `resolveTheme`'s validation make it inert — and
     * becomes a JavaScript string, a different context with different escaping
     * rules. This fails before that can happen quietly.
     */
    const offenders = sourceFiles()
      // Excluding tests and the mechanism's own files, exactly as the checks
      // above do. Without it this test flags ITSELF — the forbidden string
      // appears in the regex literal on the next line, which is a fair catch and
      // the wrong answer.
      .filter((file) => !MAY_NAME_THEME.has(file))
      .filter((file) => !/\.test\.tsx?$/.test(file))
      .filter((file) => {
        const source = code(file);
        return (
          /dangerouslySetInnerHTML/.test(source) && NAMES_THEME.test(source)
        );
      });
    expect(offenders).toEqual([]);
  });
});
