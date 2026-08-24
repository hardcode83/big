import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import "./globals.css";
import { buildPublicRuntimeConfig } from "@/lib/config/public";
import { getServerLocale } from "@/lib/i18n/server";
import { getServerTheme } from "@/lib/theme/server";
import { createRootMetadata } from "@/lib/metadata/create-route-metadata";
import { AppProviders } from "./providers";

/**
 * The two families of the design export, self-hosted (design D8, R4.1).
 *
 * `next/font/google` downloads the files at BUILD time and serves them from
 * `/_next/static`, so at runtime there is not one request to
 * `fonts.googleapis.com` — which is the point: a third party in the critical path
 * of an app that serves tenant data is what R4.1 forbids.
 *
 * The cost is a network dependency in `npm run build`, and the failure mode is a
 * broken build — loud, not silent (`next build`, unlike `next dev`, treats a
 * `next/font/google` fetch failure as fatal). WHICH builds run it is enumerated
 * once, in design D8 §«Dónde corre ese build», and deliberately not repeated
 * here: this comment carried two different counts at the same time because each
 * correction was appended instead of applied.
 *
 * `variable` (not `className` alone) because `@theme inline` maps `--font-sans`
 * and `--font-mono` onto these, so every Tailwind font utility resolves through
 * the token rather than through a class on one element.
 *
 * `subsets: ["latin"]` does NOT restrict what the build emits — measured, not
 * assumed: the output carries cyrillic, greek and vietnamese `unicode-range`
 * blocks too. It costs image size only, because `unicode-range` is what gates
 * the browser's fetch, so no user downloads a face they cannot read.
 */
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

const jetBrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-jetbrains-mono",
});

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
  const theme = await getServerTheme();
  const config = buildPublicRuntimeConfig();

  return (
    /*
     * The theme is resolved on the SERVER and painted into the first HTML, next
     * to the `lang` that already worked this way (design D4, R3.2).
     *
     * `theme ?? undefined` is load-bearing: React omits an attribute whose value
     * is `undefined`, and that ABSENCE is the third state — it is what lets the
     * `prefers-color-scheme` media query in `globals.css` decide. Writing `""`
     * or `"system"` here would match no rule and pin every visitor to light.
     */
    <html
      lang={locale}
      data-theme={theme ?? undefined}
      className={`${inter.variable} ${jetBrainsMono.variable}`}
    >
      <body>
        <AppProviders config={config} locale={locale}>
          {children}
        </AppProviders>
      </body>
    </html>
  );
}
