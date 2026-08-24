import type { ReactNode } from "react";

import { getServerT } from "@/lib/i18n/server";
import { Brand } from "./brand";
import { ShellFrame } from "./shell-frame";
import { SkipLink } from "./skip-link";
import { Topbar } from "./topbar";

/**
 * Guest Application Shell (design D3): isolated chrome for `/guest/[token]`. A
 * Server Component that exposes no navigation to internal surfaces and never
 * renders the token. The language control (a client island) remains available.
 */
export async function GuestShell({ children }: { children: ReactNode }) {
  const t = await getServerT();
  return (
    <ShellFrame
      skipLink={<SkipLink label={t("navigation:skipToContent")} />}
      topbar={await Topbar({ start: <Brand label={t("common:appName")} /> })}
    >
      {children}
    </ShellFrame>
  );
}
