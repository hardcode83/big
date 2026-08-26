"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { Languages } from "lucide-react";

import {
  LOCALE_COOKIE,
  SUPPORTED_LOCALES,
  type Locale,
} from "@/lib/config/constants";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

/**
 * Accessible ES/EN language control (design D13). Selecting a language updates
 * i18next, the non-sensitive locale cookie, and the document `lang` attribute.
 * The mutation runs in an effect (not during render) and the locale is never
 * stored in Zustand (design D7).
 *
 * **One button rather than two**, changed 2026-08-24 alongside the new theme
 * control: three theme pills plus two language pills read as five competing
 * buttons in the topbar. With exactly two locales, the second button was never
 * carrying information the first did not — so this shows the ACTIVE locale and
 * switches to the other one.
 *
 * That changes the accessible semantics deliberately, and this is the reasoning
 * rather than an oversight: two buttons were a set of choices, so `aria-pressed`
 * described which was current. One button is an ACTION, so `aria-pressed` would
 * be meaningless — pressed relative to what? — and the accessible name has to say
 * what the press will do («Cambiar idioma a English»), not what the label reads.
 * The visible text stays the current locale, which is what a sighted user needs
 * to orient.
 *
 * `sdd/specs/frontend-foundation.md:43` requires «an accessible topbar control
 * switches ES/EN, updating i18next, the cookie, and `lang`» — checked before
 * changing this: the spec fixes the behaviour, not the number of buttons, so a
 * single control still satisfies it.
 */
export function LocaleSwitcher() {
  const { i18n, t } = useTranslation("navigation");
  const router = useRouter();
  const current = (i18n.resolvedLanguage ?? SUPPORTED_LOCALES[0]) as Locale;
  const next = SUPPORTED_LOCALES.find((locale) => locale !== current) as Locale;
  const [requested, setRequested] = useState<Locale | null>(null);

  // Hold `i18n` and `router` behind refs so the effect's only dep that triggers
  // a re-run is `requested`. `useTranslation` returns a new `i18n` reference
  // after `changeLanguage` fires (the hook re-subscribes to languageChanged),
  // and putting that in the deps would queue `router.refresh()` twice per click.
  const i18nRef = useRef(i18n);
  const routerRef = useRef(router);
  useEffect(() => {
    i18nRef.current = i18n;
    routerRef.current = router;
  });

  useEffect(() => {
    if (requested === null) {
      return;
    }
    void i18nRef.current.changeLanguage(requested);
    document.cookie = `${LOCALE_COOKIE}=${requested}; path=/; max-age=31536000; samesite=lax`;
    document.documentElement.lang = requested;
    // Re-fetch the current segment so Server Components of the landing
    // (LandingView, Hero, MarketingNav, FeaturesGrid, StatsBand, FinalCta,
    // LandingFooter) re-execute with the new locale cookie. The cookie write
    // above is synchronous, so the refresh's request carries it in its
    // headers. See proposal R1 + design D1.
    routerRef.current.refresh();
  }, [requested]);

  // «Cambiar idioma a English» — names the destination, not the current state,
  // because pressing it is what it does.
  const label = t("localeSwitcher.switchTo", {
    language: t(`localeSwitcher.${next}`),
  });

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="tap-target gap-1 text-xs font-semibold uppercase"
            aria-label={label}
            onClick={() => setRequested(next)}
          >
            <Languages aria-hidden="true" />
            <span aria-hidden="true">{current}</span>
          </Button>
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
