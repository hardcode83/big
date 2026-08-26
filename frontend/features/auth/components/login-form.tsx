"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";

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

export function LoginForm() {
  const { t } = useTranslation("auth");
  const { login, status } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      await login(email, password);
      const returnTo = new URLSearchParams(window.location.search).get("returnTo");
      router.replace(safeReturnTo(returnTo));
    } catch (cause) {
      setError(cause instanceof ApiError && cause.code === "INVALID_CREDENTIALS"
        ? t("invalidCredentials")
        : t("genericError"));
    }
  }

  const submitting = status === "loading";

  return (
    <form
      className="mx-auto flex w-full max-w-md flex-col gap-5 px-6 py-10"
      onSubmit={handleSubmit}
      noValidate
    >
      <h1 className="text-2xl font-semibold text-foreground">{t("title")}</h1>
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
    </form>
  );
}
