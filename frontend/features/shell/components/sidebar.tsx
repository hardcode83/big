"use client";

import Link from "next/link";
import { CircleHelp, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { selectNavigationGroups } from "../navigation/select-routes";
import { getRouteById, type ShellProfile } from "../navigation/route-registry";
import { useShellUiStore } from "../state/use-shell-ui-store";
import { Brand } from "./brand";
import { navigationIcons } from "./icon-map";
import { NavLink } from "./nav-link";

/**
 * Workspace navigation surface (design D6). Renders a persistent sidebar on
 * desktop (collapsible to an icon rail) and a drawer on tablet, both fed by the
 * same grouped registry selection. Hidden on mobile, where bottom navigation is
 * used instead.
 *
 * Composed with three non-navigational additions from the export's sidebar
 * sketch (visual-restyle-workspace R2 AC2): a brand block with a "Panel de
 * Control" subtitle, a `btn-glow`-emphasized promoted link to `dashboard` (a
 * SECOND entry point to the route that already lives inside the `operation`
 * group below — nothing is removed, merged or reordered), and a static,
 * non-interactive help row pinned to the bottom with `mt-auto`. None of the
 * three touches `route-registry.ts` or adds a route; `dashboardRoute` is read
 * from the same registry `nav()` already renders from.
 */
export function Sidebar({ profile }: { profile: ShellProfile }) {
  const { t } = useTranslation("navigation");
  const groups = selectNavigationGroups(profile);
  const dashboardRoute = getRouteById("dashboard");
  const DashboardIcon = dashboardRoute
    ? navigationIcons[dashboardRoute.icon]
    : null;
  const collapsed = useShellUiStore(
    (state) => state.sidebarCollapsedByProfile[profile] ?? false,
  );
  const toggleSidebar = useShellUiStore((state) => state.toggleSidebar);
  const tabletNavOpen = useShellUiStore((state) => state.tabletNavOpen);
  const setTabletNavOpen = useShellUiStore((state) => state.setTabletNavOpen);

  function brandBlock(showLabels: boolean) {
    if (!showLabels) {
      return null;
    }
    return (
      <div className="flex flex-col gap-0.5 px-3 pt-1">
        <Brand label={t("common:appName")} />
        <p className="text-xs text-muted-foreground">{t("brandSubtitle")}</p>
      </div>
    );
  }

  function dashboardCta(showLabels: boolean, onNavigate?: () => void) {
    if (!dashboardRoute || !DashboardIcon) {
      return null;
    }
    const label = t(dashboardRoute.titleKey);
    return (
      <Button glow asChild className="tap-target w-full justify-start gap-3">
        <Link
          href={dashboardRoute.href ?? "#"}
          aria-label={showLabels ? undefined : label}
          onClick={onNavigate}
        >
          <DashboardIcon className="size-4 shrink-0" aria-hidden="true" />
          <span className={cn(!showLabels && "sr-only")}>{label}</span>
        </Link>
      </Button>
    );
  }

  function helpRow(showLabels: boolean) {
    return (
      <div className="mt-auto flex items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground">
        <CircleHelp className="size-4 shrink-0" aria-hidden="true" />
        <span className={cn(!showLabels && "sr-only")}>{t("help")}</span>
      </div>
    );
  }

  function nav(onNavigate?: () => void, showLabels = true) {
    return (
      <nav aria-label={t("primaryNavigation")} className="flex flex-col gap-4">
        {groups.map((block) => (
          <div key={block.group}>
            {showLabels ? (
              <p className="px-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {t(`groups.${block.group}`)}
              </p>
            ) : null}
            <ul className="mt-1 flex flex-col gap-1">
              {block.routes.map((route) => (
                <li key={route.id}>
                  <NavLink
                    route={route}
                    onNavigate={onNavigate}
                    collapsed={!showLabels}
                  />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
    );
  }

  return (
    <>
      <aside
        className={cn(
          "hidden shrink-0 flex-col gap-4 border-r bg-background p-3 lg:flex",
          collapsed ? "w-16" : "w-64",
        )}
      >
        {brandBlock(!collapsed)}
        <Button
          variant="ghost"
          size="icon"
          aria-expanded={!collapsed}
          aria-label={collapsed ? t("expandSidebar") : t("collapseSidebar")}
          onClick={() => toggleSidebar(profile)}
        >
          {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
        </Button>
        {dashboardCta(!collapsed)}
        {nav(undefined, !collapsed)}
        {helpRow(!collapsed)}
      </aside>

      <Sheet open={tabletNavOpen} onOpenChange={setTabletNavOpen}>
        <SheetContent
          side="left"
          closeLabel={t("closeMenu")}
          className="w-72 lg:hidden"
        >
          <SheetTitle>{t("primaryNavigation")}</SheetTitle>
          {brandBlock(true)}
          {dashboardCta(true, () => setTabletNavOpen(false))}
          {nav(() => setTabletNavOpen(false))}
          {helpRow(true)}
        </SheetContent>
      </Sheet>
    </>
  );
}
