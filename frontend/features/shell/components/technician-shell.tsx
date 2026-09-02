import type { ReactNode } from "react";

import { getServerT } from "@/lib/i18n/server";
import { getServerTheme } from "@/lib/theme/server";
import { AuthenticatedTopbarActions } from "./authenticated-topbar-actions";
import { Brand } from "./brand";
import { PageTitle } from "./page-title";
import { ShellFrame } from "./shell-frame";
import { ShellFooter } from "./shell-footer";
import { SkipLink } from "./skip-link";
import { Topbar } from "./topbar";

/**
 * Technician Application Shell (design D3/D6): an independent, mobile-first chrome
 * for the `technician` profile (public slug `/tech`). A Server Component; `/tech`
 * is its only navigable destination, so it renders no bottom navigation or
 * sidebar — just a topbar (task 6.6). There is deliberately no MaintenanceShell.
 */
export async function TechnicianShell({ children }: { children: ReactNode }) {
  const t = await getServerT();
  const theme = await getServerTheme();
  const start = (
    <>
      <Brand label={t("common:appName")} />
      <PageTitle profile="technician" />
    </>
  );
  /*
   * The five controls used to be written out here, identically in the other two
   * authenticated shells. `shell-topbar-overflow-360` (D3) collapsed the three
   * copies into `AuthenticatedTopbarActions`, which also selects the narrow
   * layout below `sm` so this shell stops overflowing at 360px (R1.1).
   */
  const end = (
    <AuthenticatedTopbarActions profile={"technician"} theme={theme} />
  );
  return (
    <ShellFrame
      skipLink={<SkipLink label={t("navigation:skipToContent")} />}
      topbar={await Topbar({ start, end })}
      footer={
        <ShellFooter
          versionLabels={{
            label: t("common:version.label"),
            unknown: t("common:version.unknown"),
          }}
        />
      }
    >
      {children}
    </ShellFrame>
  );
}
