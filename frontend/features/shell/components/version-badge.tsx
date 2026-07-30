import { Badge } from "@/components/ui/badge";
import { buildPublicRuntimeConfig } from "@/lib/config/public";

/** Strings resolved by the shell on the server and handed down (design D9/D13). */
export interface VersionBadgeLabels {
  /** Describes what the value is, for the accessible name. */
  label: string;
  /** Shown instead of a version when the image carries no build identity. */
  unknown: string;
}

/**
 * Composes what the badge shows from the canonical build version (OQ2).
 *
 * The canonical string carries the build date — `0.1.0+2026-07-30.a2f3c1d` — because
 * that is what `/version`, the OCI labels and `docker inspect` report. The badge shows
 * the shortened form `0.1.0+a2f3c1d`: with the date it is ~24 characters and competes
 * for room in a phone's chrome, and `steering/frontend.md` is mobile-first. Nothing is
 * lost — the provenance panel shows the build timestamp as its own field.
 *
 * Exported for testing: the composition rules are the part worth pinning down.
 */
export function formatBuildVersion(
  appVersion: string,
  buildCommitShort: string,
): string | null {
  const canonical = appVersion.trim();
  if (!canonical) return null;

  // Everything before the `+` is the base; the build metadata after it is replaced by
  // the short SHA. A value with no `+` (the `local` of dev) is already the base.
  const base = canonical.split("+")[0].trim();
  // The base has to be checked on its own, not just the whole string: `"+"` and
  // `"  +abc123"` are non-empty yet have an EMPTY base, and returning `""` for them put
  // a blank badge on screen instead of the localized "unknown" — `??` in the caller only
  // catches null. The CD guards `VERSION` to `X.Y.Z` before composing, so the real
  // pipeline cannot produce this, but the function must not depend on its caller being
  // careful (found by the QA panel).
  if (!base) return null;

  const short = buildCommitShort.trim();
  return short ? `${base}+${short}` : base;
}

/**
 * Deployed build version, shown in the shell footer (R3.1-R3.3).
 *
 * Renders from the baked snapshot and makes NO network request whatsoever — so it cannot
 * fail, cannot be slow, and works with the backend down. It carries neither the
 * repository URL nor the Pull Request title (R3.6): both are server-only and never enter
 * `PublicRuntimeConfig` (design D6).
 *
 * Synchronous, and it receives its strings instead of calling `getServerT()` itself —
 * the same shape as `Brand` and `SkipLink` (design D9/D13). An async component nested
 * inside the frame would suspend the whole shell tree, which is not something the chrome
 * can afford for a decorative value.
 */
export function VersionBadge({ labels }: { labels: VersionBadgeLabels }) {
  const { appVersion, buildCommitShort } = buildPublicRuntimeConfig();
  const version = formatBuildVersion(appVersion, buildCommitShort);
  const shown = version ?? labels.unknown;

  return (
    <Badge
      variant="outline"
      className="font-mono text-[0.6875rem] font-normal text-muted-foreground"
      aria-label={`${labels.label}: ${shown}`}
      data-testid="version-badge"
    >
      {shown}
    </Badge>
  );
}
