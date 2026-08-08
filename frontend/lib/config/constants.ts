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
