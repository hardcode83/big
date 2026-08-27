"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Monitor, Moon, Sun } from "lucide-react";

import { THEME_COOKIE, type Theme } from "@/lib/config/constants";
import { THEME_ATTRIBUTE } from "@/lib/theme/theme";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

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
 *
 * **Icons rather than words**, decided 2026-08-24 after seeing it in a browser:
 * three text pills beside the language control read as five competing buttons in
 * the topbar. The icon is decorative (`aria-hidden`) and the accessible name
 * comes from the translated `aria-label`, so what a screen reader announces is
 * unchanged from the text version. A tooltip carries the same word for sighted
 * users, because an icon alone does not distinguish «light» from «system`.
 */

/** The three choices offered. «system» is the absence of a persisted theme. */
type Choice = Theme | "system";

const CHOICES = [
  { value: "light", Icon: Sun },
  { value: "dark", Icon: Moon },
  { value: "system", Icon: Monitor },
] as const satisfies readonly { value: Choice; Icon: unknown }[];

function choiceOf(theme: Theme | null): Choice {
  return theme ?? "system";
}

export function ThemeSwitcher({ initial }: { initial: Theme | null }) {
  const { t } = useTranslation("navigation");
  const [requested, setRequested] = useState<Choice | null>(null);

  /*
   * Derived, not a second piece of state. Holding both `choice` and `requested`
   * meant calling `setChoice` inside the effect, which
   * `react-hooks/set-state-in-effect` rejects — and rightly: it is a second
   * render for a value that is already a pure function of what the server sent
   * and what the user last clicked.
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
    <TooltipProvider>
      <div
        role="group"
        aria-label={t("themeSwitcher.label")}
        className="flex items-center gap-0.5"
      >
        {CHOICES.map(({ value, Icon }) => {
          const label = t(`themeSwitcher.${value}`);
          return (
            <Tooltip key={value}>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  size="icon"
                  // `size="icon"` is already `h-11 w-11` (44px), but `tap-target`
                  // states the R3.5 guarantee explicitly so it survives a change
                  // to the primitive's icon size.
                  className="tap-target"
                  variant={choice === value ? "default" : "ghost"}
                  aria-pressed={choice === value}
                  aria-label={label}
                  onClick={() => setRequested(value)}
                >
                  <Icon aria-hidden="true" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{label}</TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </TooltipProvider>
  );
}
