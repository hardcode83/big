"use client";

import { type ReactNode, useState } from "react";
import { createInstance } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";

import { DEFAULT_LOCALE, type Locale } from "@/lib/config/constants";
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
  return instance;
}

/**
 * Client i18n provider (design D13). Receives the server-resolved locale and
 * builds an isolated i18next instance once (never re-created on re-render), so
 * SSR and client render agree and there is no hydration mismatch.
 */
export function I18nProvider({
  locale,
  children,
}: {
  locale: Locale;
  children: ReactNode;
}) {
  const [instance] = useState(() => createClientI18n(locale));
  return <I18nextProvider i18n={instance}>{children}</I18nextProvider>;
}
