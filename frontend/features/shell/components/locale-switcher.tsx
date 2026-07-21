"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  LOCALE_COOKIE,
  SUPPORTED_LOCALES,
  type Locale,
} from "@/lib/config/constants";
import { Button } from "@/components/ui/button";

/**
 * Accessible ES/EN language control (design D13). Selecting a language updates
 * i18next, the non-sensitive locale cookie, and the document `lang` attribute.
 * The mutation runs in an effect (not during render) and the locale is never
 * stored in Zustand (design D7).
 */
export function LocaleSwitcher() {
  const { i18n, t } = useTranslation("navigation");
  const current = i18n.resolvedLanguage;
  const [requested, setRequested] = useState<Locale | null>(null);

  useEffect(() => {
    if (requested === null) {
      return;
    }
    void i18n.changeLanguage(requested);
    document.cookie = `${LOCALE_COOKIE}=${requested}; path=/; max-age=31536000; samesite=lax`;
    document.documentElement.lang = requested;
  }, [requested, i18n]);

  return (
    <div role="group" aria-label={t("localeSwitcher.label")} className="flex gap-1">
      {SUPPORTED_LOCALES.map((locale) => (
        <Button
          key={locale}
          type="button"
          size="sm"
          variant={current === locale ? "default" : "ghost"}
          aria-pressed={current === locale}
          onClick={() => setRequested(locale)}
        >
          {t(`localeSwitcher.${locale}`)}
        </Button>
      ))}
    </div>
  );
}
