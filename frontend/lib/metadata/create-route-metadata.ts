import "server-only";

import type { Metadata } from "next";

import { buildPublicRuntimeConfig } from "@/lib/config/public";
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
 *
 * The ONE exception is the public landing (`/`), produced by
 * `createLandingMetadata()` below. The exception is named by route, not by a
 * generic flag on the descriptor, so a future page cannot become indexable by
 * accident (R2.3, design D4).
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

/**
 * Metadata for the public landing page at `/` — the ONLY indexable surface of
 * the app (R2.1, design D4).
 *
 * Centralised here, and named for the route it serves, so the
 * `robots: { index: true, follow: true }` block has exactly one producer in
 * the file. No other helper in this module emits `index: true`; that is the
 * structural guard against a future descriptor accidentally becoming
 * indexable.
 *
 * The title is OUTSIDE the `%s | AutoHostAI` template that
 * `createRootMetadata` declares — the landing is its own page, no parent
 * segment to inherit. The OG `url`, `metadataBase` and
 * `alternates.canonical` are only emitted when the deployment has a public
 * origin (the `NEXT_PUBLIC_APP_URL` allowlist, design D5); without one, the
 * metadata falls back to the no-public-URL posture that
 * `createRootMetadata` already documents.
 */
export async function createLandingMetadata(): Promise<Metadata> {
  const t = await translator();
  const title = t("landing:meta.title");
  const description = t("landing:meta.description");
  const { appUrl } = buildPublicRuntimeConfig();

  const openGraph: Metadata["openGraph"] = {
    type: "website",
    siteName: t("common:appName"),
    title,
    description,
  };

  const metadata: Metadata = {
    title,
    description,
    robots: { index: true, follow: true },
    openGraph,
  };

  if (appUrl) {
    metadata.metadataBase = new URL(appUrl);
    openGraph.url = new URL("/", appUrl).toString();
    metadata.alternates = { canonical: new URL("/", appUrl).toString() };
  }

  return metadata;
}
