"use client";

import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { selectNavigationGroups } from "../navigation/select-routes";
import type { ShellProfile } from "../navigation/route-registry";
import { useShellUiStore } from "../state/use-shell-ui-store";
import { NavLink } from "./nav-link";

/**
 * Workspace navigation surface (design D6). Renders a persistent sidebar on
 * desktop (collapsible to an icon rail) and a drawer on tablet, both fed by the
 * same grouped registry selection. Hidden on mobile, where bottom navigation is
 * used instead.
 */
export function Sidebar({ profile }: { profile: ShellProfile }) {
  const { t } = useTranslation("navigation");
  const groups = selectNavigationGroups(profile);
  const collapsed = useShellUiStore(
    (state) => state.sidebarCollapsedByProfile[profile] ?? false,
  );
  const toggleSidebar = useShellUiStore((state) => state.toggleSidebar);
  const tabletNavOpen = useShellUiStore((state) => state.tabletNavOpen);
  const setTabletNavOpen = useShellUiStore((state) => state.setTabletNavOpen);

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
        <Button
          variant="ghost"
          size="icon"
          aria-expanded={!collapsed}
          aria-label={collapsed ? t("expandSidebar") : t("collapseSidebar")}
          onClick={() => toggleSidebar(profile)}
        >
          {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
        </Button>
        {nav(undefined, !collapsed)}
      </aside>

      <Sheet open={tabletNavOpen} onOpenChange={setTabletNavOpen}>
        <SheetContent
          side="left"
          closeLabel={t("closeMenu")}
          className="w-72 lg:hidden"
        >
          <SheetTitle>{t("primaryNavigation")}</SheetTitle>
          {nav(() => setTabletNavOpen(false))}
        </SheetContent>
      </Sheet>
    </>
  );
}
