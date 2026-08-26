import type { ReactNode } from "react";

import { getServerT } from "@/lib/i18n/server";
import { Brand } from "./brand";
import { ShellFrame } from "./shell-frame";
import { ShellFooter } from "./shell-footer";
import { SkipLink } from "./skip-link";
import { Topbar } from "./topbar";

/**
 * Public Application Shell (design D3): minimal chrome for the public surfaces
 * `/`, `/login` and `/forgot-password`. A Server Component with no private
 * navigation, no auth guard; the only client islands are the locale and theme
 * switchers in the topbar.
 *
 * The optional `marketingNav` slot is consumed only by the landing page at
 * `/` — it renders inside the topbar's center slot, between `Brand` and the
 * locale/theme switchers. `/login` and `/forgot-password` do not pass it, so
 * their chrome is byte-equivalent to today and the snapshot pinned by the
 * `public-shell` test below stays green.
 */
export async function PublicShell({
  marketingNav,
  children,
}: {
  marketingNav?: ReactNode;
  children: ReactNode;
}) {
  const t = await getServerT();
  return (
    <ShellFrame
      skipLink={<SkipLink label={t("navigation:skipToContent")} />}
      topbar={await Topbar({
        start: <Brand label={t("common:appName")} />,
        center: marketingNav,
      })}
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
