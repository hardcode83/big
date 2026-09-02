import type { ReactNode } from "react";

import { getServerT } from "@/lib/i18n/server";
import { getServerTheme } from "@/lib/theme/server";
import { AuthenticatedTopbarActions } from "./authenticated-topbar-actions";
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

  /*
   * `end` overrides the Topbar default — design D2: UserMenu replaces nothing in
   * the default slot, it ADDS to it. The default carries the theme and locale
   * controls; this extends them with the bell and the user menu so the logged-in
   * user can always sign out.
   *
   * The five controls used to be written out here, and identically in
   * `cleaner-shell.tsx` and `technician-shell.tsx`. `shell-topbar-overflow-360`
   * (D3) collapsed the three copies into `AuthenticatedTopbarActions`, which is
   * now the single place the composition that
   * `sdd/specs/frontend-foundation.md:25` fixes is written.
   */
  const theme = await getServerTheme();
  const end = <AuthenticatedTopbarActions profile={PROFILE} theme={theme} />;

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
