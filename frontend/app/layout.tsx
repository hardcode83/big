import type { Metadata } from "next";

import "./globals.css";
import { buildPublicRuntimeConfig } from "@/lib/config/public";
import { getServerLocale } from "@/lib/i18n/server";
import { createRootMetadata } from "@/lib/metadata/create-route-metadata";
import { AppProviders } from "./providers";

export function generateMetadata(): Promise<Metadata> {
  // Localized app name/description, title template, and a noindex default (D19).
  return createRootMetadata();
}

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = await getServerLocale();
  const config = buildPublicRuntimeConfig();

  return (
    <html lang={locale}>
      <body>
        <AppProviders config={config} locale={locale}>
          {children}
        </AppProviders>
      </body>
    </html>
  );
}
