import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { ApiError } from "@/lib/api/errors";
import { serverFetch } from "@/lib/api/server-client";
import { SESSION_PRESENT_COOKIE } from "@/lib/config/constants";
import { createLandingMetadata } from "@/lib/metadata/create-route-metadata";
import { LandingView, MarketingNav } from "@/features/landing";
import { PublicShell } from "@/features/shell/components/public-shell";

import type { Metadata } from "next";

/**
 * The root of the app at `/` (design D2, R4).
 *
 * Server Component that resolves the anonymous/authenticated decision:
 *
 * - `autohostai.session.present` absent → render the landing inside
 *   `PublicShell` with `MarketingNav` filling the topbar center slot. No
 *   network call (R4 #1) — the prior behaviour and the cheapest path for the
 *   anonymous visitor.
 *
 * - Cookie present → ask the backend `GET /api/v1/auth/me` from this Server
 *   Component, forwarding the inbound cookies so the session-presence cookie
 *   reaches the backend (R4 #2). The call has a 2 s timeout
 *   (`AbortSignal.timeout(2000)`, R4 #6).
 *   - 2xx → `redirect("/dashboard", "replace")` (R4 #3, prior behaviour).
 *   - 401 → `cookies().delete(SESSION_PRESENT_COOKIE)` and render the
 *     landing (R4 #4). The cookie is stale: the browser had it but its
 *     in-memory JWT is gone (tab closed, runtime restarted, refresh-token
 *     rotation invalidated it). The server cannot tell from the cookie
 *     alone — only the backend can — so its `401` is the source of truth.
 *   - `>=500` / timeout / non-`ApiError` failure → `redirect("/dashboard",
 *     "replace")` without touching the cookie (R4 #5). A backend outage is
 *     not a logout; if the cookie was set by a real login it stays valid for
 *     the next attempt.
 *
 * **Issue recorded as OQ1 in `design.md` "Decisiones del gate"**: the JWT
 * lives in browser memory, so the Server Component cannot forward it as an
 * `Authorization` header. The backend will always reject a session-check
 * without a bearer, which means the `2xx` branch (R4 #3) is structurally
 * unreachable for a Server Component. The gate accepted this regression:
 * an authenticated user with a fresh cookie who opens `/` now lands on the
 * landing instead of `/dashboard`. Their session is still alive client-side
 * and they can navigate to `/dashboard` by URL, sidebar or a link.
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
    try {
      await serverFetch("/api/v1/auth/me", {
        forwardCookies: true,
        timeoutMs: 2000,
      });
      redirect("/dashboard", "replace");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        try {
          store.delete(SESSION_PRESENT_COOKIE);
        } catch {
          // Cookie store is best-effort on this branch; if deletion fails the
          // next request will simply re-encounter the same stale cookie and
          // re-take the 401 path.
        }
      } else {
        // 5xx, timeout, network — a backend hiccup is not a logout. Re-route
        // to `/dashboard` and let the AuthProvider's own session-expired path
        // correct the state if the failure persists.
        redirect("/dashboard", "replace");
      }
    }
  }

  return (
    <PublicShell marketingNav={<MarketingNav />}>
      <LandingView />
    </PublicShell>
  );
}