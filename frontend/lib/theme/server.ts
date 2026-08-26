import "server-only";

import { cookies } from "next/headers";

import { THEME_COOKIE, type Theme } from "@/lib/config/constants";
import { resolveTheme } from "./theme";

/**
 * Server-side theme resolution (design D4), the mirror of `getServerLocale`.
 *
 * Resolving here rather than on the client is the whole point: the store hydrates
 * *after* the first paint, so a client-resolved theme flashes the wrong one on
 * every load. Reading the cookie per request lets `app/layout.tsx` put the
 * attribute into the very first HTML it sends (R3.2, R3.3).
 *
 * `null` means «no persisted preference» and must reach the markup as an ABSENT
 * attribute, not as an empty or `"system"` one — that absence is what lets the
 * `prefers-color-scheme` media query win.
 */
export async function getServerTheme(): Promise<Theme | null> {
  const store = await cookies();
  return resolveTheme(store.get(THEME_COOKIE)?.value);
}
