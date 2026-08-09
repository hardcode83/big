"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import { StatePanel } from "@/components/states/state-panel";
import { useAuth } from "@/lib/auth";

export function AuthGuard({ children }: { children: ReactNode }) {
  const { t } = useTranslation("auth");
  const { status } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const redirecting = useRef(false);

  useEffect(() => {
    if (status === "authenticated") {
      redirecting.current = false;
    } else if ((status === "anonymous" || status === "expired") && !redirecting.current) {
      redirecting.current = true;
      const returnTo = pathname.startsWith("/")
        ? `${pathname}${window.location.search}${window.location.hash}`
        : "/dashboard";
      router.replace(`/login?returnTo=${encodeURIComponent(returnTo)}`);
    }
  }, [pathname, router, status]);

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

  return <>{children}</>;
}
