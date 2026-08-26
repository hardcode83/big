import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

/**
 * R3.2's actual claim, checked against actual HTML.
 *
 * R3.2: «WHEN se sirve una petición, THE SYSTEM SHALL resolver el tema en el
 * servidor y pintar el atributo correspondiente en `<html>` desde
 * `app/layout.tsx` [...] de modo que el **primer pintado** ya sea el tema
 * correcto.»
 *
 * That is a claim about served markup, and the guard for it in
 * `lib/theme/theme.test.ts` is a regex over `layout.tsx`'s source text. I had
 * assumed source text was the ceiling here, because importing `layout.tsx` under
 * vitest dies on `Inter is not a function` — `next/font/google` needs Next's
 * build-time transform. A reviewer showed that assumption was wrong: mocking the
 * two font factories is enough to import the real module, and from there the
 * layout can be rendered and the markup inspected.
 *
 * Both tests are kept. This one is the one that means something; the source-text
 * one still earns its place by catching refactors that preserve rendered output
 * for the wrong reason (`?? "light"` on a request that happens to have no
 * cookie renders identically to `?? undefined` only when the cookie is absent —
 * the source pin catches the intent, this catches the behaviour).
 */

const cookie = vi.hoisted(() => ({ value: undefined as string | undefined }));

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: () => (cookie.value === undefined ? undefined : { value: cookie.value }),
  }),
}));

// `next/font/google` resolves real font files at build time; under vitest the
// factories just need to hand back the `variable` class the layout interpolates.
vi.mock("next/font/google", () => ({
  Inter: () => ({ variable: "--font-inter-mock" }),
  JetBrains_Mono: () => ({ variable: "--font-jetbrains-mono-mock" }),
}));

const RootLayout = (await import("./layout")).default;

async function markup(): Promise<string> {
  const tree = await RootLayout({ children: <main>content</main> });
  return renderToStaticMarkup(tree);
}

describe("RootLayout — the theme in the first paint (R3.2, R3.3, design D4)", () => {
  it("emits NO data-theme attribute when no preference is persisted", async () => {
    // The third state. Absence is what hands control to `prefers-color-scheme`,
    // so an attribute here — even an empty one — would break R3.6's «volver a
    // seguir a mi sistema» for every visitor who never chose.
    cookie.value = undefined;
    const html = await markup();
    expect(html).not.toContain("data-theme");
  });

  it.each(["light", "dark"] as const)(
    "emits data-theme=%s when that theme is persisted",
    async (theme) => {
      cookie.value = theme;
      expect(await markup()).toContain(`data-theme="${theme}"`);
    },
  );

  it("emits no data-theme for a garbage cookie, rather than echoing it", async () => {
    // The cookie is user input and this is where it would surface. Validation
    // lives in `resolveTheme`; this is the end-to-end proof that nothing
    // unvalidated reaches the markup.
    cookie.value = '"><script>alert(1)</script>';
    const html = await markup();
    expect(html).not.toContain("data-theme");
    expect(html).not.toContain("<script>alert(1)</script>");
  });

  it("puts the theme on the same element as lang, which is <html>", async () => {
    // D4 pins the attribute to the root element specifically: the CSS selectors
    // are `:root[data-theme=…]`, so the attribute landing on `<body>` or a
    // wrapper would match nothing and fail silently.
    cookie.value = "dark";
    const html = await markup();
    expect(html).toMatch(/<html[^>]*\bdata-theme="dark"/);
    expect(html).toMatch(/<html[^>]*\blang="/);
  });

  it("still resolves the language independently of the theme", async () => {
    // Both come from cookies through the same store. This mock returns the same
    // value for every key, so `lang` and `data-theme` reading the same cookie
    // would be invisible to the tests above — asserting `lang` is a real locale
    // while the theme cookie holds a theme keeps them distinguishable.
    cookie.value = "dark";
    const html = await markup();
    // `dark` is not a supported locale, so `resolveLocale` falls back to `es`.
    expect(html).toMatch(/<html[^>]*\blang="es"/);
  });

  it("resolves the same theme on every render, which is what survives navigation", async () => {
    /*
     * R3.7: «WHILE se navega entre rutas, THE SYSTEM SHALL conservar el tema
     * resuelto sin destello de tema incorrecto.»
     *
     * Real navigation cannot be exercised here — that needs a browser, and
     * `npx playwright test` does not exist in this project yet. What CAN be
     * asserted is the property the requirement rests on: resolution is a pure
     * function of the request's cookie, with no state carried between renders. If
     * it were stateful — a module-level cache, a memo keyed on something else —
     * the second route in a session could render a different theme from the
     * first, and that is precisely the flash R3.7 forbids.
     *
     * So this is the honest half: the mechanism is verified idempotent, and the
     * absence of a visual flash in a real browser stays unverified until an e2e
     * harness exists. Stated rather than implied, because a green test here does
     * not mean someone watched the screen.
     */
    cookie.value = "dark";
    const first = await markup();
    const second = await markup();
    const third = await markup();
    expect(second).toBe(first);
    expect(third).toBe(first);
    expect(first).toContain('data-theme="dark"');
  });

  it("follows a changed cookie rather than a remembered value", async () => {
    // The other half of statelessness: if a later request carries a different
    // preference, the render must follow it. A cache would pass the idempotence
    // check above and fail this one.
    cookie.value = "dark";
    expect(await markup()).toContain('data-theme="dark"');

    cookie.value = "light";
    expect(await markup()).toContain('data-theme="light"');

    cookie.value = undefined;
    expect(await markup()).not.toContain("data-theme");
  });

  it("renders its children inside the document body", async () => {
    cookie.value = undefined;
    const html = await markup();
    expect(html).toContain("content");
  });
});
