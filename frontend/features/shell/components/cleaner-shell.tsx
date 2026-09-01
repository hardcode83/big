import type { ReactNode } from "react";

import { UserMenu } from "@/features/auth";
import { NotificationBell } from "@/features/notifications";
import { Separator } from "@/components/ui/separator";
import { getServerT } from "@/lib/i18n/server";
import { getServerTheme } from "@/lib/theme/server";
import { Brand } from "./brand";
import { LocaleSwitcher } from "./locale-switcher";
import { PageTitle } from "./page-title";
import { ShellFrame } from "./shell-frame";
import { ShellFooter } from "./shell-footer";
import { SkipLink } from "./skip-link";
import { ThemeSwitcher } from "./theme-switcher";
import { Topbar } from "./topbar";

/**
 * Cleaner Application Shell (design D3/D6): an independent, mobile-first chrome
 * for the `cleaner` profile. A Server Component; `/cleaner` is its only
 * navigable destination, so it renders no bottom navigation or sidebar — just a
 * topbar (task 6.5). Only PageTitle and the locale switcher are client islands.
 */
export async function CleanerShell({ children }: { children: ReactNode }) {
  const t = await getServerT();
  const theme = await getServerTheme();
  const start = (
    <>
      <Brand label={t("common:appName")} />
      <PageTitle profile="cleaner" />
    </>
  );
  const end = (
    <>
      <ThemeSwitcher initial={theme} />
      <Separator orientation="vertical" className="mx-1 h-6" />
      <LocaleSwitcher />
      <NotificationBell profile={"cleaner"} />
      <UserMenu />
    </>
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
