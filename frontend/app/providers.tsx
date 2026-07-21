"use client";

import type { ReactNode } from "react";

import type { Locale } from "@/lib/config/constants";
import type { PublicRuntimeConfig } from "@/lib/config/public";
import { RuntimeConfigProvider } from "@/lib/config/runtime-config-provider";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { QueryProvider } from "@/lib/query/query-provider";

/**
 * Thin client boundary rendered from the RootLayout Server Component (design
 * D10). Provider order is fixed:
 *
 *   RuntimeConfigProvider → I18nProvider → [AuthProvider slot] → QueryProvider
 *
 * The future AuthProvider will sit between i18n and query (design D10/D17); it
 * does not exist in this change. No theme/analytics/flags providers are added.
 */
export function AppProviders({
  config,
  locale,
  children,
}: {
  config: PublicRuntimeConfig;
  locale: Locale;
  children: ReactNode;
}) {
  return (
    <RuntimeConfigProvider config={config}>
      <I18nProvider locale={locale}>
        {/* Future AuthProvider slot (design D10/D17) — intentionally absent. */}
        <QueryProvider>{children}</QueryProvider>
      </I18nProvider>
    </RuntimeConfigProvider>
  );
}
