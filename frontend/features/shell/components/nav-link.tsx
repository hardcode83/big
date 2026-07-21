"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { isRouteActive } from "../navigation/match-route";
import type { ShellRouteDescriptor } from "../navigation/route-registry";
import { navigationIcons } from "./icon-map";

/**
 * A single navigation link (design D4/D5). Marks itself with `aria-current="page"`
 * when active. When `collapsed`, the label is kept as the accessible name only.
 */
export function NavLink({
  route,
  onNavigate,
  collapsed = false,
}: {
  route: ShellRouteDescriptor;
  onNavigate?: () => void;
  collapsed?: boolean;
}) {
  const pathname = usePathname() ?? "/";
  const { t } = useTranslation("navigation");
  const active = isRouteActive(route, pathname);
  const Icon = navigationIcons[route.icon];
  const label = t(route.titleKey);

  return (
    <Link
      href={route.href ?? "#"}
      aria-current={active ? "page" : undefined}
      aria-label={collapsed ? label : undefined}
      onClick={onNavigate}
      className={cn(
        "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
        active
          ? "bg-accent font-medium text-accent-foreground"
          : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
      )}
    >
      <Icon className="size-4 shrink-0" aria-hidden="true" />
      <span className={cn(collapsed && "sr-only")}>{label}</span>
    </Link>
  );
}
