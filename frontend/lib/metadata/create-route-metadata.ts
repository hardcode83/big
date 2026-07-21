import type { Metadata } from "next";

import { createServerI18n, getServerLocale } from "@/lib/i18n/server";

/**
 * Localized App Router metadata (design D19). This module lives in the shared
 * `lib` layer, so it does NOT import the route registry (a shell-feature concern,
 * design D2); callers pass the localized metadata keys instead — see
 * `features/shell` `routeMetadata()`.
 *
 * Every surface is `noindex, nofollow`; Open Graph is generic
 * (name/title/description) with no canonical URL, images, or business data.
 * `metadataBase` is intentionally omitted — no public URL is authorized here.
 */
async function translator() {
  const locale = await getServerLocale();
  const i18n = await createServerI18n(locale);
  return i18n.getFixedT(locale, null);
}

export async function createRootMetadata(): Promise<Metadata> {
  const t = await translator();
  const appName = t("common:appName");
  const description = t("common:appDescription");
  return {
    title: { default: appName, template: `%s | ${appName}` },
    description,
    robots: { index: false, follow: false },
    openGraph: {
      siteName: appName,
      title: appName,
      description,
      type: "website",
    },
  };
}

export async function createMetadataFromKeys(keys?: {
  titleKey: string;
  descriptionKey: string;
}): Promise<Metadata> {
  if (!keys) {
    return { robots: { index: false, follow: false } };
  }
  const t = await translator();
  const title = t(keys.titleKey);
  const description = t(keys.descriptionKey);
  return {
    title,
    description,
    robots: { index: false, follow: false },
    openGraph: {
      siteName: t("common:appName"),
      title,
      description,
      type: "website",
    },
  };
}
