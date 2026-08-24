"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { THEME_COOKIE, type Theme } from "@/lib/config/constants";
import { THEME_ATTRIBUTE } from "@/lib/theme/theme";
import { Button } from "@/components/ui/button";

/**
 * The three-state theme control (design D5, R3.4-R3.6).
 *
 * «System» is not a persisted value — it is the ABSENCE of the cookie, which is
 * what returns control to `prefers-color-scheme`. So the three choices map to two
 * writes and one delete, and `aria-pressed` tracks the chosen PREFERENCE rather
 * than the resolved theme: with «System» selected on a dark OS, the page is dark
 * but the pressed button is «System», because that is what the user chose.
 *
 * `initial` comes from the server (`Topbar` passes `getServerTheme()`'s result),
 * so the correct button is pressed in the FIRST paint. Reading the cookie on
 * mount instead would leave the buttons briefly wrong even though the page
 * colours were already right — the theme would not flash, but the control would.
 *
 * The mutation runs in an effect with the `requested === null` guard borrowed
 * from `LocaleSwitcher`, so nothing mutates during render (R3.4) and the initial
 * server value is not written back as a side effect on mount.
 */

/** The three choices offered. `null` is «follow the system». */
type Choice = Theme | "system";

const CHOICES: readonly Choice[] = ["light", "dark", "system"] as const;

function choiceOf(theme: Theme | null): Choice {
  return theme ?? "system";
}

export function ThemeSwitcher({ initial }: { initial: Theme | null }) {
  const { t } = useTranslation("navigation");
  const [requested, setRequested] = useState<Choice | null>(null);

  /*
   * Derived, not a second piece of state. Holding both `choice` and `requested`
   * meant calling `setChoice` inside the effect, which `react-hooks/set-state-in-effect`
   * rejects — and rightly: it is a second render for a value that is already a
   * pure function of what the server sent and what the user last clicked.
   */
  const choice: Choice = requested ?? choiceOf(initial);

  useEffect(() => {
    if (requested === null) {
      return;
    }

    const root = document.documentElement;

    if (requested === "system") {
      // R3.6: forget the preference and obey the OS again. Expiring the cookie
      // and removing the attribute have to happen together — leaving either one
      // behind would keep the old theme pinned on the next navigation.
      document.cookie = `${THEME_COOKIE}=; path=/; max-age=0; samesite=lax`;
      delete root.dataset.theme;
    } else {
      // The same posture as the locale cookie, which R3.1 requires: `path=/`,
      // `samesite=lax`, a one-year `max-age`, and no personal data.
      document.cookie = `${THEME_COOKIE}=${requested}; path=/; max-age=31536000; samesite=lax`;
      root.setAttribute(THEME_ATTRIBUTE, requested);
    }
  }, [requested]);

  return (
    <div
      role="group"
      aria-label={t("themeSwitcher.label")}
      className="flex gap-1"
    >
      {CHOICES.map((option) => (
        <Button
          key={option}
          type="button"
          size="sm"
          // `Button size="sm"` is `h-9` (36px), under the 44 the requirement
          // asks for, so `tap-target` from `globals.css` raises it (R3.5).
          className="tap-target"
          variant={choice === option ? "default" : "ghost"}
          aria-pressed={choice === option}
          onClick={() => setRequested(option)}
        >
          {t(`themeSwitcher.${option}`)}
        </Button>
      ))}
    </div>
  );
}
