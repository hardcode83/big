import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { SESSION_PRESENT_COOKIE } from "@/lib/config/constants";
import { createLandingMetadata } from "@/lib/metadata/create-route-metadata";
import { LandingView, MarketingNav } from "@/features/landing";
import { PublicShell } from "@/features/shell/components/public-shell";

import type { Metadata } from "next";

/**
 * The root of the app at `/` (design D2, R1, R2).
 *
 * Server Component that resolves the anonymous/authenticated decision from
 * the non-sensitive `autohostai.session.present` cookie (design D1):
 *
 * - present and equal to `"1"` → `redirect("/dashboard", 307)` — the
 *   anonymous visitor never sees the landing, the authenticated user keeps
 *   the same path they have today.
 * - absent or any other value → render the landing inside `PublicShell` with
 *   `MarketingNav` filling the topbar center slot.
 *
 * `307 Temporary Redirect` (not `301`) so a stale cookie that races a logout
 * self-corrects on the next request, and so we never permanently commit a
 * visitor to a route they may no longer want.
 *
 * The `generateMetadata` call wires the indexable landing metadata (R2.1,
 * design D4) — `robots: { index: true, follow: true }` plus the absolute
 * URL pieces when `NEXT_PUBLIC_APP_URL` is configured.
 */
export function generateMetadata(): Promise<Metadata> {
  return createLandingMetadata();
}

export default async function RootPage() {
  const store = await cookies();
  const present = store.get(SESSION_PRESENT_COOKIE)?.value === "1";

  if (present) {
    redirect("/dashboard", "replace");
  }

  return (
    <PublicShell marketingNav={<MarketingNav />}>
      <LandingView />
    </PublicShell>
  );
}
