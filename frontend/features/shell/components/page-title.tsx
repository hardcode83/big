"use client";

import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";

import { matchRoute } from "../navigation/match-route";
import type { ShellProfile } from "../navigation/route-registry";

/** Compact current-page title for the mobile topbar (design D5). */
export function PageTitle({ profile }: { profile: ShellProfile }) {
  const pathname = usePathname() ?? "/";
  const { t } = useTranslation("navigation");
  const route = matchRoute(pathname, profile);

  if (!route) {
    return null;
  }
  return (
    <span className="truncate text-sm font-semibold text-foreground">
      {t(route.titleKey)}
    </span>
  );
}
