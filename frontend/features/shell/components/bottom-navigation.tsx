"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Ellipsis } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { isRouteActive } from "../navigation/match-route";
import { selectPrimaryNavigation } from "../navigation/select-routes";
import type { ShellProfile } from "../navigation/route-registry";
import { useShellUiStore } from "../state/use-shell-ui-store";
import { navigationIcons } from "./icon-map";
import { MoreMenu } from "./more-menu";

/** Direct mobile destinations for the Workspace shell (design D6). */
const WORKSPACE_BOTTOM_NAV_IDS = [
  "dashboard",
  "timeline",
  "cleaning",
  "incidents",
] as const;

/**
 * Mobile bottom navigation (design D6): up to four direct destinations plus a
 * "More" sheet for the rest. Fixed, safe-area aware, 44×44 tap targets, hidden
 * from tablet up.
 */
export function BottomNavigation({ profile }: { profile: ShellProfile }) {
  const { t } = useTranslation("navigation");
  const pathname = usePathname() ?? "/";
  const all = selectPrimaryNavigation(profile);
  const direct = WORKSPACE_BOTTOM_NAV_IDS.map((id) =>
    all.find((route) => route.id === id),
  ).filter((route): route is (typeof all)[number] => route !== undefined);
  const rest = all.filter(
    (route) =>
      !WORKSPACE_BOTTOM_NAV_IDS.includes(
        route.id as (typeof WORKSPACE_BOTTOM_NAV_IDS)[number],
      ),
  );
  const moreOpen = useShellUiStore((state) => state.mobileMoreOpen);
  const setMoreOpen = useShellUiStore((state) => state.setMobileMoreOpen);
  const activeInMore = rest.some((route) => isRouteActive(route, pathname));

  return (
    <nav
      aria-label={t("primaryNavigation")}
      className="fixed inset-x-0 bottom-0 z-40 flex border-t bg-background pb-safe md:hidden"
    >
      {direct.map((route) => {
        const Icon = navigationIcons[route.icon];
        const active = isRouteActive(route, pathname);
        return (
          <Link
            key={route.id}
            href={route.href ?? "#"}
            aria-current={active ? "page" : undefined}
            className={cn(
              "tap-target flex flex-1 flex-col items-center justify-center gap-1 py-2 text-xs",
              active ? "text-foreground" : "text-muted-foreground",
            )}
          >
            <Icon className="size-5" aria-hidden="true" />
            <span>{t(route.titleKey)}</span>
          </Link>
        );
      })}
      <MoreMenu routes={rest} open={moreOpen} onOpenChange={setMoreOpen}>
        <button
          type="button"
          aria-current={activeInMore ? "true" : undefined}
          className={cn(
            "tap-target flex flex-1 flex-col items-center justify-center gap-1 py-2 text-xs",
            activeInMore ? "text-foreground" : "text-muted-foreground",
          )}
        >
          <Ellipsis className="size-5" aria-hidden="true" />
          <span>{t("more")}</span>
        </button>
      </MoreMenu>
    </nav>
  );
}
