"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Monitor, Moon, Sun } from "lucide-react";

import { THEME_COOKIE, type Theme } from "@/lib/config/constants";
import { THEME_ATTRIBUTE } from "@/lib/theme/theme";
import {
  useThemePreference,
  type ThemeChoice,
} from "@/lib/theme/use-theme-preference";
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
 * It reaches `aria-pressed` through `useThemePreference`, which hands back
 * `initial` for the server snapshot and the `data-theme` attribute of `<html>`
 * thereafter (`shell-topbar-overflow-360` D9/R4.4). Both come from the same
 * cookie, so the first paint is unchanged; what it buys is that any number of
 * mounted instances agree, which they did not when this was per-instance state.
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
type Choice = ThemeChoice;

const CHOICES = [
  { value: "light", Icon: Sun },
  { value: "dark", Icon: Moon },
  { value: "system", Icon: Monitor },
] as const satisfies readonly { value: Choice; Icon: unknown }[];

export function ThemeSwitcher({ initial }: { initial: Theme | null }) {
  const { t } = useTranslation("navigation");
  /*
   * Wrapped in an object, and that is load-bearing rather than style. Once
   * `choice` stopped being derived from this state (below), holding the bare
   * `Choice` made a click a no-op whenever the value had not changed since this
   * instance's last click — and with two instances mounted that is reachable:
   * pick «dark» here, pick «light» in the other one, pick «dark» here again, and
   * `setRequested("dark")` would find the same value, skip the render and never
   * run the effect, leaving the document on «light» after a click that said
   * otherwise. A fresh object every click makes the state change every click,
   * which is what «`requested` is only the trigger» has to mean.
   */
  const [requested, setRequested] = useState<{ choice: Choice } | null>(null);

  /*
   * Which button is pressed comes from the `data-theme` attribute of `<html>`,
   * not from `requested` — design D9 of `shell-topbar-overflow-360`, R4.4.
   *
   * The reason is that this control is now mounted TWICE on narrow viewports
   * (the wide topbar branch and the overflow sheet, selected by a media query),
   * and `requested` is per-instance: a click in the sheet left the wide branch
   * showing the button it had been server-rendered with until the next server
   * render. The attribute is the one place the current preference already
   * lives — `app/layout.tsx` seeds it on the server and the effect below is
   * what moves it — so every mounted instance reading it makes them agree by
   * construction rather than by synchronisation.
   */
  const choice: Choice = useThemePreference(initial);

  useEffect(() => {
    if (requested === null) {
      return;
    }

    const root = document.documentElement;

    if (requested.choice === "system") {
      // R3.6: forget the preference and obey the OS again. Expiring the cookie
      // and removing the attribute have to happen together — leaving either one
      // behind would keep the old theme pinned on the next navigation.
      document.cookie = `${THEME_COOKIE}=; path=/; max-age=0; samesite=lax`;
      delete root.dataset.theme;
    } else {
      // The same posture as the locale cookie, which R3.1 requires: `path=/`,
      // `samesite=lax`, a one-year `max-age`, and no personal data.
      document.cookie = `${THEME_COOKIE}=${requested.choice}; path=/; max-age=31536000; samesite=lax`;
      root.setAttribute(THEME_ATTRIBUTE, requested.choice);
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
                  onClick={() => setRequested({ choice: value })}
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
