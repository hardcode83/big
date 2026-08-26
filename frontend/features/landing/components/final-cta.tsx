import Link from "next/link";

import { Button } from "@/components/ui/button";
import { getServerT } from "@/lib/i18n/server";

/**
 * Final CTA section (R3). Server Component. The button label and href both
 * come from the landing catalogue — currently `/login`, the same destination
 * as the marketing nav's `Login` link. The `href` resolves through the
 * catalogue rather than being hardcoded so a future i18n variant that points
 * elsewhere does not require a code change.
 */
export async function FinalCta() {
  const t = await getServerT();
  const href = t("landing:cta.buttonHref");

  return (
    <section className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 md:py-24 lg:px-8">
      <div className="flex flex-col items-start gap-6 rounded-lg border border-border bg-surface p-8 md:flex-row md:items-center md:justify-between md:p-12">
        <h2 className="text-headline-lg font-bold tracking-tight md:text-display-xl">
          {t("landing:cta.title")}
        </h2>
        <Button asChild size="default" className="tap-target">
          <Link href={href}>{t("landing:cta.buttonLabel")}</Link>
        </Button>
      </div>
    </section>
  );
}
