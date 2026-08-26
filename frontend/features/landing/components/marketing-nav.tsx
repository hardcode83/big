import Link from "next/link";

import { getServerT } from "@/lib/i18n/server";
import { cn } from "@/lib/utils";

/**
 * Marketing navigation rendered inside `PublicShell`'s topbar center slot
 * (design D3, R3.3). Server Component, no client JS.
 *
 * Exactly two items — the destination they point to must exist today, so
 * `Pricing`, `Portfolio`, `Team` and `Sign Up` are deliberately NOT rendered
 * until their pages land (R3.3, design D8). The `#features` link uses native
 * anchor behaviour; smooth scrolling is a CSS rule on `html`
 * (`globals.css`, design D10).
 *
 * Below 768 px only `Login` is shown — the `#features` link is hidden because
 * the maqueta's mobile chrome reduces to the same single button (OQ-2,
 * resolved 2026-08-24).
 */
export async function MarketingNav() {
  const t = await getServerT();

  return (
    <nav
      aria-label={t("navigation:routes.landing.title")}
      className="flex items-center gap-2"
    >
      <Link
        href="/login"
        className={cn(
          "tap-target rounded-md px-3 py-2 text-sm font-medium",
          "text-foreground hover:bg-accent hover:text-accent-foreground",
        )}
      >
        {t("landing:marketing.login")}
      </Link>
      {/* hidden below 768 px (OQ-2, resolved 2026-08-24). The link is an
        * anchor to the features section so native scroll-to-anchor takes
        * over; smooth-scroll is the `html { scroll-behavior: smooth }`
        * rule in `globals.css`. */}
      <a
        href="#features"
        className={cn(
          "tap-target hidden rounded-md px-3 py-2 text-sm font-medium md:inline-flex",
          "text-foreground hover:bg-accent hover:text-accent-foreground",
        )}
      >
        {t("landing:marketing.featuresAnchor")}
      </a>
    </nav>
  );
}
