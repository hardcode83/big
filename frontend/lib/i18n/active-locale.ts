import { DEFAULT_LOCALE, type Locale } from "@/lib/config/constants";

/**
 * Module-level publication of the active i18next locale (design D6).
 *
 * The i18next instance itself is local to `I18nProvider` (`client-provider.tsx`
 * builds it with `createInstance()` inside a `useState` initializer, on purpose
 * so SSR and client render agree — see D13), so there is no module singleton
 * that code outside React (the nine per-feature `data/index.ts` clients,
 * `authenticated-client.ts`) can import directly. This module is that
 * publication point: `I18nProvider` is the only writer, calling
 * `setActiveLocale` synchronously when it creates the instance and again on
 * every `languageChanged` event; everything else only reads via
 * `getActiveLocale`.
 *
 * `setActiveLocale` is a no-op outside the browser (security review, round 12):
 * `useState`'s lazy initializer — where `client-provider.tsx` calls it — also
 * runs during the server render of a Client Component, and `activeLocale` is a
 * plain module `let` in one Node process shared by every concurrent request.
 * Without the guard, one visitor's SSR pass could momentarily overwrite the
 * value another concurrent request's server-side code would read. No such
 * read exists today (auth tokens live only in browser memory, so no
 * authenticated fetch — the only reader of `getActiveLocale` — happens during
 * SSR), but the guard costs nothing and removes the shared-state hazard
 * outright rather than relying on that absence staying true.
 */
let activeLocale: Locale = DEFAULT_LOCALE;

export function getActiveLocale(): Locale {
  return activeLocale;
}

export function setActiveLocale(locale: Locale): void {
  if (typeof window === "undefined") return;
  activeLocale = locale;
}
