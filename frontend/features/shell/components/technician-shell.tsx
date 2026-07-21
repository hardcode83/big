import type { ReactNode } from "react";

import { getServerT } from "@/lib/i18n/server";
import { Brand } from "./brand";
import { PageTitle } from "./page-title";
import { ShellFrame } from "./shell-frame";
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
  const start = (
    <>
      <Brand label={t("common:appName")} />
      <PageTitle profile="technician" />
    </>
  );
  return (
    <ShellFrame
      skipLink={<SkipLink label={t("navigation:skipToContent")} />}
      topbar={<Topbar start={start} />}
    >
      {children}
    </ShellFrame>
  );
}
