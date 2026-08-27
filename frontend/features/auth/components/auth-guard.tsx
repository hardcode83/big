"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import { StatePanel } from "@/components/states/state-panel";
import { useAuth } from "@/lib/auth";
import type { components } from "@/lib/api/generated/openapi";

/**
 * UX-only role gate (design D1, R1). The frontend is NEVER the source of RBAC
 * (`sdd/steering/security.md` rule 2; `lib/auth/permissions.ts:7-13`). A user with
 * a valid JWT for `CLEANER` can still open `/dashboard` if they know the URL —
 * the backend will refuse with `403`. The `allow` prop is a UX shield, not a
 * wall, and the backend stays authoritative.
 *
 * **Branches** (kept verbatim in the proposal; order matters because earlier
 * branches render before `children`):
 *
 * 1. `status ∈ {loading, refreshing}` → `StatePanel aria-busy`.
 * 2. `status === "expired"` → `StatePanel role="alert"` + redirect to
 *    `/login?returnTo=...`.
 * 3. `status === "anonymous"` → redirect to `/login?returnTo=...`.
 *    `allow` is **not** evaluated here — without a session there is no role to
 *    compare (R1 #3).
 * 4. `status === "authenticated"` and `allow` is defined and `user.role ∉ allow`
 *    → redirect to `/login?denied=role`. `LoginForm` reads the query param and
 *    shows `auth.deniedRole`, then resolves the final shell via `roleHome(user.role)`
 *    (R1 #5).
 * 5. `status === "authenticated"` and (`allow` absent or `user.role ∈ allow`)
 *    → render `children`.
 *
 * The single `redirecting` ref de-duplicates every branch — a guard that fires the
 * same redirect twice across re-renders strands the user on a navigation loop.
 */
export function AuthGuard({
  allow,
  children,
}: {
  /**
   * Allowed roles. When defined, an authenticated user whose role is not in the
   * list is redirected to `/login?denied=role`. When `undefined`, every
   * authenticated user passes through (the prior behavior — preserved for
   * any layout that does not pass `allow` explicitly).
   */
  allow?: readonly components["schemas"]["UserRole"][];
  children: ReactNode;
}) {
  const { t } = useTranslation("auth");
  const { status, user } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const redirecting = useRef(false);

  useEffect(() => {
    if (status === "authenticated") {
      const isDenied =
        allow !== undefined && user !== null && !allow.includes(user.role);
      if (isDenied) {
        // Only fire the redirect once — `redirecting` stays `true` until the
        // user transitions to a non-denied state (else branch). Resetting
        // unconditionally on every render (the previous implementation) made
        // the `!redirecting.current` guard always true under StrictMode, so the
        // same redirect fired twice per mount.
        if (!redirecting.current) {
          redirecting.current = true;
          const returnTo = pathname.startsWith("/")
            ? `${pathname}${window.location.search}${window.location.hash}`
            : "/dashboard";
          router.replace(
            `/login?returnTo=${encodeURIComponent(returnTo)}&denied=role`,
          );
        }
      } else {
        // Pass-through — clear the latch so a future `isDenied` flip can fire.
        redirecting.current = false;
      }
      return;
    }

    if (
      (status === "anonymous" || status === "expired") &&
      !redirecting.current
    ) {
      redirecting.current = true;
      const returnTo = pathname.startsWith("/")
        ? `${pathname}${window.location.search}${window.location.hash}`
        : "/dashboard";
      router.replace(`/login?returnTo=${encodeURIComponent(returnTo)}`);
    }
  }, [allow, pathname, router, status, user]);

  if (status === "loading" || status === "refreshing") {
    return (
      <StatePanel
        role="status"
        aria-busy
        title={t(status === "refreshing" ? "refreshing" : "checkingSession")}
        description={t("authRequired")}
      />
    );
  }

  if (status === "expired") {
    return (
      <StatePanel
        role="alert"
        title={t("expired")}
        description={t("authRequired")}
      />
    );
  }

  if (status !== "authenticated") {
    return null;
  }

  if (allow !== undefined && user !== null && !allow.includes(user.role)) {
    // `useEffect` will dispatch the redirect; while it runs, render nothing.
    return null;
  }

  return <>{children}</>;
}