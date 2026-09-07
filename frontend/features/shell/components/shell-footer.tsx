import { VersionBadge, type VersionBadgeLabels } from "./version-badge";
import { ProvenancePanel } from "@/features/provenance";

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
  showProvenance = false,
}: {
  versionLabels: VersionBadgeLabels;
  showProvenance?: boolean;
}) {
  return (
    <footer className="flex shrink-0 items-center border-t border-border bg-surface/80 px-4 py-2 backdrop-blur-md">
      <VersionBadge labels={versionLabels} />
      {showProvenance && <div className="ml-auto"><ProvenancePanel /></div>}
    </footer>
  );
}
