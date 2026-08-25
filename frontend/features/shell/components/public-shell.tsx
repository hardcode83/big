import type { ReactNode } from "react";

import { getServerT } from "@/lib/i18n/server";
import { Brand } from "./brand";
import { ShellFrame } from "./shell-frame";
import { ShellFooter } from "./shell-footer";
import { SkipLink } from "./skip-link";
import { Topbar } from "./topbar";

/**
 * Public Application Shell (design D3): minimal chrome for `/login` and
 * `/forgot-password`. A Server Component with no private/module navigation and
 * no private navigation and no auth guard; `/login` is the public entry point.
 * Only the locale switcher is a client island.
 */
export async function PublicShell({ children }: { children: ReactNode }) {
  const t = await getServerT();
  return (
    <ShellFrame
      skipLink={<SkipLink label={t("navigation:skipToContent")} />}
      topbar={await Topbar({ start: <Brand label={t("common:appName")} /> })}
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
