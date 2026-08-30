import type { ReactNode } from "react";

import { UserMenu } from "@/features/auth";
import { NotificationBell } from "@/features/notifications";
import { Separator } from "@/components/ui/separator";
import { getServerT } from "@/lib/i18n/server";
import { getServerTheme } from "@/lib/theme/server";
import { BottomNavigation } from "./bottom-navigation";
import { Breadcrumbs } from "./breadcrumbs";
import { LocaleSwitcher } from "./locale-switcher";
import { PageTitle } from "./page-title";
import { ShellFrame } from "./shell-frame";
import { Sidebar } from "./sidebar";
import { ShellFooter } from "./shell-footer";
import { SkipLink } from "./skip-link";
import { TabletNavTrigger } from "./tablet-nav-trigger";
import { ThemeSwitcher } from "./theme-switcher";
import { Topbar } from "./topbar";

const PROFILE = "workspace" as const;

/**
 * Workspace Application Shell (design D3/D6). A Server Component: static chrome
 * (skip link, frame, topbar container) is server-rendered; only the interactive
 * pieces are client islands — the tablet nav trigger and sidebar (Zustand),
 * breadcrumbs/page-title/bottom navigation (client navigation), and the locale
 * switcher. This keeps the shell from being one big client boundary (D9).
 */
export async function WorkspaceShell({ children }: { children: ReactNode }) {
  const t = await getServerT();

  const start = (
    <>
      <TabletNavTrigger />
      <div className="hidden md:block">
        <Breadcrumbs profile={PROFILE} />
      </div>
      <div className="md:hidden">
        <PageTitle profile={PROFILE} />
      </div>
    </>
  );

  // `end` overrides the Topbar default — design D2: UserMenu replaces nothing in
  // the default slot, it ADDS to it. The default already carries
  // ThemeSwitcher + Separator + LocaleSwitcher; we extend with UserMenu so the
  // logged-in user can always sign out.
  const theme = await getServerTheme();
  const end = (
    <>
      <ThemeSwitcher initial={theme} />
      <Separator orientation="vertical" className="mx-1 h-6" />
      <LocaleSwitcher />
      <NotificationBell profile={PROFILE} />
      <UserMenu />
    </>
  );

  return (
    <ShellFrame
      skipLink={<SkipLink label={t("navigation:skipToContent")} />}
      sidebar={<Sidebar profile={PROFILE} />}
      topbar={await Topbar({ start, end })}
      footer={
        <ShellFooter
          versionLabels={{
            label: t("common:version.label"),
            unknown: t("common:version.unknown"),
          }}
          showProvenance
        />
      }
      bottomNavigation={<BottomNavigation profile={PROFILE} />}
    >
      {children}
    </ShellFrame>
  );
}
