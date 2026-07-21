import "server-only";

import { cookies } from "next/headers";
import { createInstance, type i18n } from "i18next";

import {
  DEFAULT_LOCALE,
  LOCALE_COOKIE,
  type Locale,
} from "@/lib/config/constants";
import { resolveLocale } from "./locale";
import { DEFAULT_NS, NAMESPACES, resources } from "./resources";

/**
 * Server-side i18n (design D13). The locale is resolved per request from the
 * non-sensitive `autohostai.locale` cookie, and a fresh i18next instance is
 * created per request so instances never leak between requests.
 */
export async function getServerLocale(): Promise<Locale> {
  const store = await cookies();
  return resolveLocale(store.get(LOCALE_COOKIE)?.value);
}

export async function createServerI18n(locale: Locale): Promise<i18n> {
  const instance = createInstance();
  await instance.init({
    lng: locale,
    fallbackLng: DEFAULT_LOCALE,
    ns: [...NAMESPACES],
    defaultNS: DEFAULT_NS,
    resources,
    interpolation: { escapeValue: false },
  });
  return instance;
}

/**
 * Convenience for Server Components: resolves the request locale and returns a
 * fixed `t` that expects namespaced keys (e.g. `t("navigation:skipToContent")`).
 * Lets shell chrome resolve its static text on the server instead of shipping a
 * client i18n hook for it (design D9/D13).
 */
export async function getServerT() {
  const locale = await getServerLocale();
  const instance = await createServerI18n(locale);
  return instance.getFixedT(locale, null);
}
