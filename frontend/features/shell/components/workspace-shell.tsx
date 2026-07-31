import type { ReactNode } from "react";

import { getServerT } from "@/lib/i18n/server";
import { BottomNavigation } from "./bottom-navigation";
import { Breadcrumbs } from "./breadcrumbs";
import { PageTitle } from "./page-title";
import { ShellFrame } from "./shell-frame";
import { Sidebar } from "./sidebar";
import { ShellFooter } from "./shell-footer";
import { SkipLink } from "./skip-link";
import { TabletNavTrigger } from "./tablet-nav-trigger";
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

  return (
    <ShellFrame
      skipLink={<SkipLink label={t("navigation:skipToContent")} />}
      sidebar={<Sidebar profile={PROFILE} />}
      topbar={<Topbar start={start} />}
      footer={
        <ShellFooter
          versionLabels={{
            label: t("common:version.label"),
            unknown: t("common:version.unknown"),
          }}
        />
      }
      bottomNavigation={<BottomNavigation profile={PROFILE} />}
    >
      {children}
    </ShellFrame>
  );
}
