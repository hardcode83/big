"use client";

import { useSyncExternalStore } from "react";

import { isTheme, type Theme } from "@/lib/config/constants";
import { THEME_ATTRIBUTE } from "./theme";

/**
 * The chosen preference, read from the authority that already holds it: the
 * `data-theme` attribute of `<html>` (design D9, R4.4).
 *
 * **Why this hook exists.** `shell-topbar-overflow-360` mounts `ThemeSwitcher`
 * twice — the wide branch and the overflow sheet, selected by a media query
 * (D4) — and its `aria-pressed` used to come from a `useState` local to each
 * instance. Two mounted instances therefore disagreed: change the theme in the
 * sheet at 360 px, widen the window without navigating, and the wide branch
 * still showed the button it was server-rendered with. The page colours were
 * right (the attribute is on `<html>`); which button looked pressed was not.
 *
 * **Why the attribute and not a store.** `sdd/specs/design-system-tokens.md:23`
 * forbids the theme living in Zustand or any other client store, and `:22`
 * already designates this attribute as what `app/layout.tsx` writes on the
 * server so the first paint is correct. Subscribing to it does not invent a
 * second source of truth — it makes N mounted instances read the one that
 * exists. `theme-switcher.tsx` is already the code that writes and deletes it.
 *
 * **Why it is not «reading the theme on the client»**, which `:23` also forbids:
 * `getServerSnapshot` returns the server's `initial`, so the first paint and
 * hydration both come from the server value. `initial` is `getServerTheme()`'s
 * result, which reads the same cookie `app/layout.tsx` wrote the attribute from,
 * so the two cannot disagree and React has no mismatch to warn about.
 *
 * It lives in `lib/theme/` rather than `features/shell/` because the dependency
 * direction is `app → features → components / lib`: this is the theme mechanism,
 * not shell composition. Separate file from `lib/theme/server.ts`, which is
 * `server-only`.
 */

/** The three choices offered. `"system"` is the ABSENCE of the attribute. */
export type ThemeChoice = Theme | "system";

/** The attribute's current value as a choice. Anything invalid reads as `"system"`. */
function choiceOf(value: string | null | undefined): ThemeChoice {
  return isTheme(value) ? value : "system";
}

/**
 * `MutationObserver` scoped to the one attribute, so an unrelated mutation of
 * `<html>` (the `lang` that `LocaleSwitcher` writes, for one) wakes nobody.
 */
function subscribe(onStoreChange: () => void): () => void {
  const observer = new MutationObserver(onStoreChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: [THEME_ATTRIBUTE],
  });
  return () => observer.disconnect();
}

export function useThemePreference(initial: Theme | null): ThemeChoice {
  return useSyncExternalStore(
    subscribe,
    // Read straight from the DOM rather than from a cached copy: React calls
    // this after every notification and compares the result, so a cache here
    // would only be a second place for the value to go stale.
    () => choiceOf(document.documentElement.getAttribute(THEME_ATTRIBUTE)),
    () => choiceOf(initial),
  );
}
