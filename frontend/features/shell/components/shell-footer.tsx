import { VersionBadge, type VersionBadgeLabels } from "./version-badge";

/**
 * Shell footer (change app-version-visibility, R2.1/R2.2).
 *
 * Deliberately thin: it exists so the deployed build version is visible on opening the
 * app, including on `/login` where there is no session yet — which is precisely the
 * situation where an operator most needs to know what is running and cannot look it up
 * from inside. A Server Component with no client JavaScript.
 */
export function ShellFooter({
  versionLabels,
}: {
  versionLabels: VersionBadgeLabels;
}) {
  return (
    <footer className="flex shrink-0 items-center border-t px-4 py-2">
      <VersionBadge labels={versionLabels} />
    </footer>
  );
}
