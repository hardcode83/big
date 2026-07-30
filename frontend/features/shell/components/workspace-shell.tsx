import type { ReactNode } from "react";

import { buildPublicRuntimeConfig } from "@/lib/config/public";
import { getServerConfig } from "@/lib/config/server";
import { getServerT } from "@/lib/i18n/server";
import { BottomNavigation } from "./bottom-navigation";
import { Breadcrumbs } from "./breadcrumbs";
import { PageTitle } from "./page-title";
import { resolveProvenance } from "./provenance";
import { ProvenancePanel } from "./provenance-panel";
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
          // The provenance panel hangs off THIS shell only (R4.3): its links name the
          // private repository and the Pull Request, and pairing a screen with a PR is an
          // operator action. The other shells pass no `end`, so they get the badge alone.
          end={
            <ProvenancePanel
              labels={{
                trigger: t("common:provenance.trigger"),
                title: t("common:provenance.title"),
                closeLabel: t("common:provenance.closeLabel"),
                commit: t("common:provenance.commit"),
                pullRequest: t("common:provenance.pullRequest"),
                prPrefix: t("common:provenance.prPrefix"),
                noPullRequest: t("common:provenance.noPullRequest"),
                builtAt: t("common:provenance.builtAt"),
                runId: t("common:provenance.runId"),
                ref: t("common:provenance.ref"),
                unknown: t("common:provenance.unknown"),
                frontendVersion: t("common:provenance.frontendVersion"),
                backendVersion: t("common:provenance.backendVersion"),
                driftWarning: t("common:provenance.driftWarning"),
                checking: t("common:provenance.checking"),
              }}
              provenance={resolveProvenance(getServerConfig().buildProvenance)}
              // Through the config boundary, never `process.env` directly: the spec of
              // `frontend-foundation` requires application code to read configuration
              // only through `lib/config`.
              frontendVersion={buildPublicRuntimeConfig().appVersion || null}
            />
          }
        />
      }
      bottomNavigation={<BottomNavigation profile={PROFILE} />}
    >
      {children}
    </ShellFrame>
  );
}
