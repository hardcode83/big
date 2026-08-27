"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/errors";
import { clearSessionPresent, useAuth } from "@/lib/auth";
import { roleHome } from "../lib/role-home";

function safeReturnTo(value: string | null): string {
  if (
    !value ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    /%2f|%5c/i.test(value)
  ) {
    return "/dashboard";
  }

  try {
    const target = new URL(value, window.location.origin);
    return target.origin === window.location.origin
      ? `${target.pathname}${target.search}${target.hash}`
      : "/dashboard";
  } catch {
    return "/dashboard";
  }
}

/**
 * R5 — the «Volver a la landing» control is a `<button type="button">` and not
 * an `<a>` because the order `clearSessionPresent() → router.replace("/") →
 * router.refresh()` must run BEFORE the browser commits to the navigation; an
 * `<a href="/">` would let the native click handler race the React onClick and
 * the cookie would still be set when `RootPage` re-evaluates, sending the user
 * right back into the `/login → / → /dashboard → /login` loop (R5 #2).
 *
 * R1 #5 — when the visitor was bounced out of an AuthGuard-protected segment
 * (`AuthGuard` redirected here with `?denied=role`), they are still
 * authenticated. The page surfaces `auth.deniedRole` for one render and then
 * resolves the correct shell via `roleHome(user.role)` — the visitor does not
 * need to log in again.
 */
export function LoginForm() {
  const { t } = useTranslation("auth");
  const { login, status, user } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const returnTo = searchParams.get("returnTo");
  const deniedRole = searchParams.get("denied") === "role";

  useEffect(() => {
    if (!deniedRole) {
      return;
    }
    if (status !== "authenticated" || !user) {
      return;
    }
    router.replace(roleHome(user.role));
  }, [deniedRole, router, status, user]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      await login(email, password);
      const next = returnTo
        ? safeReturnTo(returnTo)
        : (user?.role === "CLEANER" || user?.role === "TECHNICIAN")
          ? `/welcome?role=${user.role}`
          : roleHome(user?.role);
      router.replace(next);
    } catch (cause) {
      setError(cause instanceof ApiError && cause.code === "INVALID_CREDENTIALS"
        ? t("invalidCredentials")
        : t("genericError"));
    }
  }

  function handleBackToLanding() {
    clearSessionPresent();
    router.replace("/");
    router.refresh();
  }

  const submitting = status === "loading";
  const showDeniedMessage =
    deniedRole && status === "authenticated" && user !== null;

  return (
    <form
      className="mx-auto flex w-full max-w-md flex-col gap-5 px-6 py-10"
      onSubmit={handleSubmit}
      noValidate
    >
      <h1 className="text-2xl font-semibold text-foreground">{t("title")}</h1>
      {showDeniedMessage ? (
        <p
          role="alert"
          className="rounded-md border border-state-warning-border bg-state-warning-bg p-3 text-sm text-state-warning-text"
        >
          {t("deniedRole")}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-state-error-text">
          {error}
        </p>
      ) : null}
      <label className="flex flex-col gap-2 text-sm font-medium" htmlFor="email">
        {t("email")}
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="h-10 rounded-md border border-input bg-background px-3 font-normal outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      </label>
      <label className="flex flex-col gap-2 text-sm font-medium" htmlFor="password">
        {t("password")}
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="h-10 rounded-md border border-input bg-background px-3 font-normal outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      </label>
      <Button type="submit" disabled={submitting}>
        {submitting ? t("loading") : t("submit")}
      </Button>
      <button
        type="button"
        role="link"
        aria-label={t("backToLanding")}
        onClick={handleBackToLanding}
        className="tap-target self-start text-left text-sm font-medium text-muted-foreground hover:text-foreground"
      >
        {t("backToLanding")}
      </button>
    </form>
  );
}