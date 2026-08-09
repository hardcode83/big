"use client";

import type { ReactNode } from "react";

import type { Locale } from "@/lib/config/constants";
import type { PublicRuntimeConfig } from "@/lib/config/public";
import { RuntimeConfigProvider } from "@/lib/config/runtime-config-provider";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { AuthProvider } from "@/lib/auth";
import { QueryProvider } from "@/lib/query/query-provider";

/**
 * Thin client boundary rendered from the RootLayout Server Component (design
 * D10). Provider order is fixed:
 *
 *   RuntimeConfigProvider → I18nProvider → AuthProvider → QueryProvider
 *
 * AuthProvider owns only React-facing identity state; token storage and refresh
 * coordination live under lib/auth. No theme/analytics/flags providers are added.
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
        <AuthProvider>
          <QueryProvider>{children}</QueryProvider>
        </AuthProvider>
      </I18nProvider>
    </RuntimeConfigProvider>
  );
}
