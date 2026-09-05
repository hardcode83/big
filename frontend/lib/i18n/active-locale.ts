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
 * Before any provider has mounted (first paint, before hydration) this holds
 * `DEFAULT_LOCALE` — the same value the server would have resolved.
 */
let activeLocale: Locale = DEFAULT_LOCALE;

export function getActiveLocale(): Locale {
  return activeLocale;
}

export function setActiveLocale(locale: Locale): void {
  activeLocale = locale;
}
