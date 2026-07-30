import type { ReactNode } from "react";

import { VersionBadge, type VersionBadgeLabels } from "./version-badge";

/**
 * Shell footer (change app-version-visibility, R3.1/R3.2).
 *
 * Deliberately thin: it exists so the deployed build version is visible on opening the
 * app, including on `/login` where there is no session yet — which is precisely the
 * situation where an operator most needs to know what is running and cannot look it up
 * from inside. A Server Component with no client JavaScript.
 *
 * `end` is the extension point the workspace uses to add the provenance panel; the other
 * shells pass nothing, so they get the badge alone.
 */
export function ShellFooter({
  versionLabels,
  end,
}: {
  versionLabels: VersionBadgeLabels;
  end?: ReactNode;
}) {
  return (
    <footer className="flex shrink-0 items-center justify-between gap-3 border-t px-4 py-2">
      <VersionBadge labels={versionLabels} />
      {end ? <div className="flex items-center gap-2">{end}</div> : null}
    </footer>
  );
}
