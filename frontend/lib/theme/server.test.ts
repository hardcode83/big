import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";

import { THEME_COOKIE } from "@/lib/config/constants";

/**
 * `getServerTheme()` is the whole trust boundary of this section: the cookie is
 * user-controlled, and its value lands in an attribute on `<html>` in the first
 * byte of HTML the server sends. Everything between those two points is this one
 * function.
 *
 * It had no test. `theme.test.ts` covers `resolveTheme` thoroughly and asserts on
 * `layout.tsx`'s source text, but nothing imported this module — so nothing
 * pinned that the read goes THROUGH `resolveTheme`, or that it reads the theme
 * cookie rather than some other one. Both reviewers found that independently, and
 * one demonstrated it: changing the key to `"autohostai.locale"` left 173 tests
 * passing while the visible theme silently followed the language cookie.
 *
 * The mock shape follows the one already established for the locale in
 * `features/shell/components/route-placeholder.test.tsx` and
 * `lib/metadata/create-route-metadata.test.ts`; `vi.hoisted` is what lets the
 * per-test value be set before the module factory runs.
 */
const cookie = vi.hoisted(() => ({
  name: undefined as string | undefined,
  value: undefined as string | undefined,
}));

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => {
      // Records which cookie was asked for, so the test can assert the KEY and
      // not merely the returned value — reading the wrong cookie was the
      // demonstrated defect.
      cookie.name = name;
      return cookie.value === undefined ? undefined : { value: cookie.value };
    },
  }),
}));

const { getServerTheme } = await import("./server");

describe("getServerTheme (design D4, R3.1, R3.2)", () => {
  it.each(["light", "dark"] as const)(
    "returns the persisted %s from the cookie",
    async (value) => {
      cookie.value = value;
      await expect(getServerTheme()).resolves.toBe(value);
    },
  );

  it.each([
    ["absent", undefined],
    ["empty", ""],
  ])("returns null when the cookie is %s", async (_label, value) => {
    cookie.value = value;
    await expect(getServerTheme()).resolves.toBeNull();
  });

  it.each([
    ["garbage", "not-a-theme"],
    ["a persisted 'system'", "system"],
    ["wrong case", "Dark"],
    ["an injection attempt", '"><script>alert(1)</script>'],
    ["a padded value", " dark "],
  ])(
    "returns null for %s, so nothing unvalidated can reach the html attribute",
    async (_label, value) => {
      cookie.value = value;
      await expect(getServerTheme()).resolves.toBeNull();
    },
  );

  it("reads THEME_COOKIE, not any other cookie", async () => {
    // The demonstrated defect: reading `autohostai.locale` here made the theme
    // follow the language and no test failed. Asserting the constant rather than
    // the literal means a rename is covered too.
    cookie.value = "dark";
    await getServerTheme();
    expect(cookie.name).toBe(THEME_COOKIE);
    expect(cookie.name).toBe("autohostai.theme");
  });

  it("never resolves to a value outside the supported set", async () => {
    for (const value of [
      "light",
      "dark",
      "system",
      "",
      "LIGHT",
      "__proto__",
      "constructor",
      undefined,
    ]) {
      cookie.value = value;
      const resolved = await getServerTheme();
      expect(resolved === null || resolved === "light" || resolved === "dark").toBe(
        true,
      );
    }
  });
});

/**
 * Two properties of this module that no behavioural test can see, because the
 * test environment deliberately neutralises one of them and the other is a
 * refactor away rather than a behaviour.
 */
describe("getServerTheme — source-form guarantees", () => {
  const source = readFileSync(join(__dirname, "server.ts"), "utf8");

  it("keeps `import \"server-only\"`, which the build relies on", () => {
    /*
     * `vitest.config.ts` aliases `server-only` to `test/stubs/server-only.ts`, so
     * no test in this repo can prove the real guarantee — the throwing
     * `react-server` export condition only bites in a build. Removing the import
     * therefore passes the entire suite, which a reviewer confirmed by doing it.
     *
     * So this asserts the line is present. It is a weaker claim than «a client
     * import fails», and it is the strongest one available here.
     */
    expect(source).toMatch(/^import "server-only";/m);
  });

  it("passes the cookie THROUGH resolveTheme rather than casting it", () => {
    // `return store.get(THEME_COOKIE)?.value as Theme` type-checks and would put
    // an attacker-controlled string into the markup. The behavioural tests above
    // catch that today; this catches it even if someone also edits them, and says
    // out loud that the cast is the thing being forbidden.
    expect(source).toMatch(/resolveTheme\(\s*store\.get\(THEME_COOKIE\)\?\.value\s*\)/);
    expect(source).not.toMatch(/as\s+Theme\b/);
  });
});
