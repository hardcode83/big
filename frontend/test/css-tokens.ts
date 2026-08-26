import { readFileSync } from "node:fs";

/**
 * Reading `globals.css` as data, shared by the two guards that do it:
 * `app/globals.tokens.test.ts` (the parity guard of design D1) and
 * `app/globals.contrast.test.ts` (the WCAG audit of D11/R1.6).
 *
 * Shared rather than copied because the parser has already had one real bug —
 * it counted braces inside comments and overran into the next block — and a
 * second copy is a second place for that to come back. Helpers live in `test/`
 * by this project's convention (`frontend/README.md` §testing: «helpers en
 * `test/`»).
 */

/**
 * Comments are stripped before anything parses the file.
 *
 * A brace inside a comment — someone writing «the `@theme {` rule…» in prose —
 * would make the brace matcher overrun into the following block, merging its
 * declarations into the one being read. That does not fail cleanly: it surfaces
 * as unrelated assertions failing with a message pointing nowhere near the
 * comment that caused it. Stripping deletes the failure class instead of
 * documenting it. It also stops a commented-out declaration from being read as a
 * live one, which was a real false-pass path.
 */
export function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

export function readCss(path: string): string {
  return stripComments(readFileSync(path, "utf8"));
}

/**
 * A declaration ends at `;`, at the block's `}`, or — for the last one in a
 * block — at nothing at all, because CSS makes the final semicolon optional.
 * Missing that third case is how a one-declaration override block slipped past
 * an earlier version of the occurrence count, and nothing in this project would
 * have caught it: `lint` is `eslint .`, which does not read `.css`, and there is
 * no prettier/stylelint/biome.
 */
export const DECLARATION = /(--[a-z0-9-]+)\s*:\s*([^;}]+)(?:[;}]|$)/gi;

/** Every custom-property name declared anywhere, in source order, WITH duplicates. */
export function declaredNames(css: string): string[] {
  return [...css.matchAll(DECLARATION)].map(([, name]) => name);
}

/**
 * Custom-property declarations inside the top-level rule whose selector is
 * exactly `selector`.
 *
 * Hand-written brace matching rather than a regex: the file nests
 * (`@media { :root { … } }`) and a lazy `\{([^}]*)\}` would stop at the first
 * inner brace. `startFrom` scopes the search to a region, which is how the
 * media-query block is read without matching the bare `:root` above it.
 */
export function declarationsOf(
  css: string,
  selector: string,
  startFrom = 0,
): Record<string, string> {
  const at = css.indexOf(`${selector} {`, startFrom);
  if (at === -1) {
    throw new Error(`selector not found in globals.css: ${selector}`);
  }
  let depth = 0;
  let end = -1;
  for (let i = css.indexOf("{", at); i < css.length; i += 1) {
    if (css[i] === "{") depth += 1;
    else if (css[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  const body = css.slice(css.indexOf("{", at) + 1, end);
  const declarations: Record<string, string> = {};
  for (const [, name, value] of body.matchAll(DECLARATION)) {
    declarations[name] = value.trim();
  }
  return declarations;
}

/** Where the dark media query starts — the anchor both guards scope against. */
export function darkMediaAt(css: string): number {
  return css.indexOf("@media (prefers-color-scheme: dark)");
}

/**
 * The three token-bearing blocks of design D1: light on `:root`, dark twice.
 * `:root[data-theme="light"]` carries only `color-scheme` and declares no token,
 * so it is not one of them.
 */
export function themeBlocks(css: string): {
  light: Record<string, string>;
  darkMedia: Record<string, string>;
  darkAttribute: Record<string, string>;
} {
  return {
    light: declarationsOf(css, ":root"),
    darkMedia: declarationsOf(
      css,
      ':root:not([data-theme="light"])',
      darkMediaAt(css),
    ),
    darkAttribute: declarationsOf(css, ':root[data-theme="dark"]'),
  };
}
