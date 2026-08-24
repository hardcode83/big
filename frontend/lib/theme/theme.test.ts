import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { SUPPORTED_THEMES, isTheme, THEME_COOKIE } from "@/lib/config/constants";
import { resolveTheme, THEME_ATTRIBUTE } from "./theme";

/**
 * D4's three-state table, pinned.
 *
 * The table is the whole mechanism, so it is the thing worth testing rather than
 * the two lines of code that implement it. What each row asserts is which of
 * three outcomes a cookie value produces: the light theme, the dark theme, or
 * «no opinion», where the attribute is absent and `prefers-color-scheme` decides.
 */

describe("resolveTheme (design D4, R3.1)", () => {
  it.each([
    ["light", "light"],
    ["dark", "dark"],
  ] as const)("resolves the persisted value %s", (value, expected) => {
    expect(resolveTheme(value)).toBe(expected);
  });

  it.each([
    ["absent cookie", undefined],
    ["explicitly null", null],
    ["empty string", ""],
  ])("returns null for %s, which is the follow-the-system state", (_label, value) => {
    expect(resolveTheme(value)).toBeNull();
  });

  it.each([
    ["garbage", "not-a-theme"],
    ["a persisted 'system', which is NOT a supported value", "system"],
    ["wrong case", "Dark"],
    ["whitespace-padded", " dark "],
    ["a would-be injection", '"><script>alert(1)</script>'],
    ["another theme name", "solarized"],
  ])("returns null for %s rather than trusting it", (_label, value) => {
    // A cookie is user-controlled input. Anything unrecognised has to degrade to
    // «follow the system», never to a default that pins the user, and never to
    // the raw value — this is the only thing standing between the cookie and an
    // attribute written into `<html>`.
    expect(resolveTheme(value)).toBeNull();
  });

  it("never returns a value outside the supported set", () => {
    const inputs = [
      "light",
      "dark",
      "system",
      "",
      "LIGHT",
      undefined,
      null,
      "../../etc/passwd",
    ];
    for (const input of inputs) {
      const resolved = resolveTheme(input);
      if (resolved !== null) {
        expect(SUPPORTED_THEMES).toContain(resolved);
      }
    }
  });

  it("agrees with isTheme, so validation has one definition", () => {
    // `resolveTheme` returning non-null and `isTheme` accepting must be the same
    // predicate. Two validators that can disagree is how a value gets written
    // that the CSS has no block for.
    for (const input of ["light", "dark", "system", "", "Dark", "solarized"]) {
      expect(resolveTheme(input) !== null).toBe(isTheme(input));
    }
  });
});

describe("theme constants (R3.1)", () => {
  it("offers exactly two persisted themes, with absence as the third state", () => {
    // D4: «Tres estados, sin valor "system" persistido: la ausencia *es* el
    // estado.» If a third value ever appears here, `globals.css` needs a block
    // for it and the switcher a button — so this pins the count deliberately.
    expect(SUPPORTED_THEMES).toEqual(["light", "dark"]);
    expect(SUPPORTED_THEMES).toHaveLength(2);
  });

  it("names the cookie and the attribute the CSS keys off", () => {
    // The attribute string is shared with `globals.css`; a typo here would leave
    // the switcher writing an attribute no CSS block matches, with no error.
    expect(THEME_COOKIE).toBe("autohostai.theme");
    expect(THEME_ATTRIBUTE).toBe("data-theme");
  });

  it("has a globals.css block for every theme it can write, keyed off that attribute", () => {
    /*
     * The coupling that fails silently.
     *
     * `THEME_ATTRIBUTE` and `SUPPORTED_THEMES` decide what gets written onto
     * `<html>`; `globals.css` decides what that does. Both sides are pinned
     * individually — here and in `app/globals.tokens.test.ts` — but nothing
     * linked them, so renaming the attribute, or adding a third theme, would
     * leave the app writing an attribute no rule matches. No error, no failing
     * test, just a theme that quietly does nothing.
     */
    const css = readFileSync(
      join(__dirname, "..", "..", "app", "globals.css"),
      "utf8",
    ).replace(/\/\*[\s\S]*?\*\//g, "");

    for (const theme of SUPPORTED_THEMES) {
      expect(
        css.includes(`:root[${THEME_ATTRIBUTE}="${theme}"]`),
        `globals.css has no :root[${THEME_ATTRIBUTE}="${theme}"] block`,
      ).toBe(true);
    }

    // And the media query's escape hatch has to name the same attribute and the
    // same light value, or a persisted `light` stops beating a dark OS.
    expect(
      css.includes(`:root:not([${THEME_ATTRIBUTE}="light"])`),
      "the dark media query does not exclude the persisted light theme",
    ).toBe(true);
  });
});
