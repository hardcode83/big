"use client";

import { useTranslation } from "react-i18next";

import type { Locale } from "@/lib/config/constants";

/**
 * Reactive read of the active locale (design D6, supports R2.1).
 *
 * Built over `useTranslation()` — the same pattern already used throughout the
 * app to read `i18n.language` for locale-sensitive formatting (e.g.
 * `features/dashboard/components/property-card.tsx`) — so, unlike reading
 * `getActiveLocale()` from `active-locale.ts` directly, a language change
 * re-renders the caller instead of only updating the module-level value.
 */
export function useActiveLocale(): Locale {
  const { i18n } = useTranslation();
  return i18n.language as Locale;
}
