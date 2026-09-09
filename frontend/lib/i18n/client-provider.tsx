"use client";

import { type ReactNode, useEffect, useState } from "react";
import { createInstance } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";

import { DEFAULT_LOCALE, type Locale } from "@/lib/config/constants";
import { setActiveLocale } from "./active-locale";
import { DEFAULT_NS, NAMESPACES, resources } from "./resources";

function createClientI18n(locale: Locale) {
  const instance = createInstance();
  instance.use(initReactI18next).init({
    lng: locale,
    fallbackLng: DEFAULT_LOCALE,
    ns: [...NAMESPACES],
    defaultNS: DEFAULT_NS,
    resources,
    interpolation: { escapeValue: false },
    react: { useSuspense: false },
  });
  // Publish synchronously (design D6): `init` above resolves synchronously
  // (resources are passed in-line, no async backend), so `resolvedLanguage`
  // is already set here. Publishing inside the `useState` initializer — not
  // in an effect — means a query that fires on the very first render already
  // carries the right locale.
  setActiveLocale((instance.resolvedLanguage ?? locale) as Locale);
  return instance;
}

/**
 * Client i18n provider (design D13). Receives the server-resolved locale and
 * builds an isolated i18next instance once (never re-created on re-render), so
 * SSR and client render agree and there is no hydration mismatch.
 *
 * Also the sole writer of the active-locale publication (design D6): the
 * i18next instance is local to this component, so `lib/i18n/active-locale.ts`
 * is what `getHeaders` in `authenticated-client.ts` and query-key builders read
 * instead. The locale is published synchronously above at instance creation,
 * and republished here on every `languageChanged` event (fired by
 * `LocaleSwitcher`'s `i18n.changeLanguage` call) so later switches stay in
 * sync too.
 */
export function I18nProvider({
  locale,
  children,
}: {
  locale: Locale;
  children: ReactNode;
}) {
  const [instance] = useState(() => createClientI18n(locale));

  useEffect(() => {
    const handleLanguageChanged = () => {
      setActiveLocale((instance.resolvedLanguage ?? instance.language) as Locale);
    };
    instance.on("languageChanged", handleLanguageChanged);
    return () => {
      instance.off("languageChanged", handleLanguageChanged);
    };
  }, [instance]);

  return <I18nextProvider i18n={instance}>{children}</I18nextProvider>;
}
