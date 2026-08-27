"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { StatePanel } from "@/components/states/state-panel";
import { roleHome } from "@/features/auth";
import { useAuth } from "@/lib/auth";

/**
 * Mini-landing shown between login and the role-specific shell for `CLEANER`
 * and `TECHNICIAN` (design D2, R2). A field user on a shared device often
 * mis-taps during the login animation, which is why a `/welcome` screen with
 * one explicit CTA is preferable to redirecting straight to the shell.
 *
 * **Branch matrix** (verbatim from R2):
 *
 * - `?role=CLEANER` or `?role=TECHNICIAN` AND `useAuth().user.role` matches →
 *   render `StatePanel` with `auth.welcome.title` / `auth.welcome.body` and
 *   a single `Button` (a `next/link`) whose `href` is `roleHome(role)` and
 *   whose `aria-label` is `auth.welcome.cta.<role>`.
 * - `?role` absent OR `?role` mismatches the authenticated user's role →
 *   `router.replace(roleHome(user.role))`. We never expose the screen for
 *   a role the visitor is not.
 * - Status not `authenticated` (loading/refreshing/expired/anonymous) → the
 *   `AuthGuard` from the layout handles the redirect; this page renders a
 *   busy panel until then.
 */
export default function WelcomePage() {
  const { t } = useTranslation("auth");
  const router = useRouter();
  const searchParams = useSearchParams();
  const { status, user } = useAuth();
  const redirecting = useRef(false);

  const roleParam = searchParams.get("role");
  const matches = !!user && roleParam === user.role;
  const isWelcomeRole =
    roleParam === "CLEANER" || roleParam === "TECHNICIAN";

  useEffect(() => {
    if (status !== "authenticated" || !user) {
      return;
    }
    if (matches) {
      return;
    }
    if (redirecting.current) {
      return;
    }
    redirecting.current = true;
    router.replace(roleHome(user.role));
  }, [matches, roleParam, router, status, user]);

  if (status === "loading" || status === "refreshing") {
    return (
      <div className="mx-auto flex min-h-[60vh] w-full max-w-md items-center px-6 py-10">
        <StatePanel
          role="status"
          aria-busy
          title={t(status === "refreshing" ? "refreshing" : "checkingSession")}
          description={t("authRequired")}
        />
      </div>
    );
  }

  if (status !== "authenticated" || !user) {
    return null;
  }

  if (!isWelcomeRole || !matches) {
    // `useEffect` will dispatch the redirect; render a busy panel instead of
    // `null` so a tampered URL doesn't leave the visitor staring at a blank
    // page for the duration of the redirect (R2 #3 / review F4).
    return (
      <div className="mx-auto flex min-h-[60vh] w-full max-w-md items-center px-6 py-10">
        <StatePanel
          role="status"
          aria-busy
          title={t("redirecting")}
          description={t("authRequired")}
        />
      </div>
    );
  }

  const href = roleHome(roleParam as "CLEANER" | "TECHNICIAN");
  const ariaLabel = t(`welcome.cta.${roleParam}`);

  return (
    <div className="mx-auto flex min-h-[60vh] w-full max-w-md flex-col justify-center gap-6 px-6 py-10">
      <StatePanel
        title={t("welcome.title")}
        description={t("welcome.body")}
      />
      <Button asChild size="default" className="tap-target w-full">
        <Link href={href} aria-label={ariaLabel}>
          {ariaLabel}
        </Link>
      </Button>
    </div>
  );
}