import { isTheme, type Theme } from "@/lib/config/constants";

/**
 * The attribute the two runtime-override blocks of `globals.css` key off
 * (design D1/D4). Declared here so the CSS selector and the code that writes it
 * cannot drift apart in a string literal.
 */
export const THEME_ATTRIBUTE = "data-theme";

/**
 * Resolves a raw cookie value to a persisted theme, or `null` for «follow the
 * system».
 *
 * Deliberately NOT the shape of `resolveLocale`, which it otherwise mirrors:
 * that one falls back to a product default (`es`) because a page must render in
 * some language, whereas here `null` is a real, distinct third state rather than
 * a failure. Returning `"light"` for a missing cookie would silently pin every
 * new visitor to the light theme and make `prefers-color-scheme` unreachable —
 * which is the behaviour R3.6 exists to provide.
 *
 * Isomorphic: no Next.js or browser dependency, so the switcher and the server
 * resolver share one definition of what a valid value is.
 */
export function resolveTheme(value: string | undefined | null): Theme | null {
  return isTheme(value) ? value : null;
}
