import { DEFAULT_LOCALE, isLocale, type Locale } from "@/lib/config/constants";

/**
 * Resolves a raw cookie value to a supported locale, falling back to the product
 * default (`es`) for anything missing or invalid (design D13). Isomorphic: no
 * Next.js or browser dependency, so it is unit-testable in isolation.
 */
export function resolveLocale(value: string | undefined | null): Locale {
  return isLocale(value) ? value : DEFAULT_LOCALE;
}
