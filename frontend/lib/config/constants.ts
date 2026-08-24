/**
 * Non-sensitive product defaults. Safe to import from Server or Client
 * Components. Anything private or environment-injected lives in `server.ts`
 * (server-only), and only the allowlisted subset in `public.ts` reaches the
 * browser (design D15).
 */

export const SUPPORTED_LOCALES = ["es", "en"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];

/** Product fallback locale (design D13). */
export const DEFAULT_LOCALE: Locale = "es";

/** Non-sensitive cookie that carries the resolved UI locale (design D13). */
export const LOCALE_COOKIE = "autohostai.locale";

export function isLocale(value: unknown): value is Locale {
  return (
    typeof value === "string" &&
    (SUPPORTED_LOCALES as readonly string[]).includes(value)
  );
}

/**
 * The two persisted themes (design D4). There is deliberately no `"system"`
 * value: the third state is the **absence** of the cookie, which is what hands
 * control back to `prefers-color-scheme`. Persisting `"system"` would be a
 * second way to say the same thing, and the CSS in `globals.css` keys off the
 * attribute being absent, not off a value.
 */
export const SUPPORTED_THEMES = ["light", "dark"] as const;
export type Theme = (typeof SUPPORTED_THEMES)[number];

/**
 * Non-sensitive cookie carrying the resolved UI theme (design D4). Same posture
 * as `LOCALE_COOKIE`: `path=/`, `samesite=lax`, a one-year `max-age`, and no
 * personal data — it holds one of two literal words.
 */
export const THEME_COOKIE = "autohostai.theme";

export function isTheme(value: unknown): value is Theme {
  return (
    typeof value === "string" &&
    (SUPPORTED_THEMES as readonly string[]).includes(value)
  );
}
