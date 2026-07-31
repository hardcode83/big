import { Badge } from "@/components/ui/badge";
import { buildPublicRuntimeConfig } from "@/lib/config/public";

/** Strings resolved by the shell on the server and handed down (`frontend-foundation`
 * D9/D13, and D5 of this change). */
export interface VersionBadgeLabels {
  /** Describes what the value is, for the accessible name. */
  label: string;
  /** Shown instead of a version when the image carries no build identity. */
  unknown: string;
}

/**
 * Composes what the badge shows from the canonical build version.
 *
 * Shows the canonical string WHOLE — `0.1.0+2026-07-30.a2f3c1d`, date included — which is
 * the same string the OCI labels and `docker inspect` report. It used to be shortened to
 * `0.1.0+a2f3c1d`, on the premise that the date would be visible in the provenance panel;
 * trimming the scope of `app-version-visibility` removed that panel, and with it the only
 * place in the UI where the date could be read. The date is also the only thing that tells
 * two different builds apart, because the deployment pins the MUTABLE tag `sha-<commit>`
 * rather than a digest — see the `app-version-badge-date` change.
 *
 * Exported for testing: the composition rules are the part worth pinning down.
 */
export function formatBuildVersion(
  appVersion: string,
  buildCommitShort: string,
): string | null {
  const canonical = appVersion.trim();
  if (!canonical) return null;

  // Everything before the first `+` is the base; whatever follows is the build metadata.
  const [rawBase, ...rest] = canonical.split("+");
  const base = rawBase.trim();
  // The base has to be checked on its own, not just the whole string: `"+"` and
  // `"  +abc123"` are non-empty yet have an EMPTY base, and returning `""` for them put
  // a blank badge on screen instead of the localized "unknown" — `??` in the caller only
  // catches null. The CD guards `VERSION` to `X.Y.Z` before composing, so the real
  // pipeline cannot produce this, but the function must not depend on its caller being
  // careful (found by the QA panel).
  if (!base) return null;

  // `rest.join("+")` instead of `rest[0]`: nothing is dropped if the metadata itself
  // carries a `+`. Requiring an alphanumeric is the mirror image of the empty-base guard —
  // `"0.1.0+"` and `"0.1.0++"` have a `+` that carries NOTHING, and rendering them would
  // be exactly the "half-formed version string" the degradation rules forbid.
  const metadata = rest.join("+").trim();
  if (/[0-9a-z]/i.test(metadata)) return `${base}+${metadata}`;

  // No usable metadata (the `local` of dev): the short SHA is the only identity available,
  // so it is still worth appending when the image baked one.
  const short = buildCommitShort.trim();
  return short ? `${base}+${short}` : base;
}

/**
 * Deployed build version, shown in the shell footer (R2.1-R2.3).
 *
 * Renders from the baked snapshot and makes NO network request whatsoever — so it cannot
 * fail, cannot be slow, and works with the backend down. It carries nothing beyond the two
 * allowlisted fields (R2.4); the repository identity is not part of this change at all —
 * see the `app-version-provenance` roadmap entry.
 *
 * Synchronous, and it receives its strings instead of calling `getServerT()` itself —
 * the same shape as `Brand` and `SkipLink` (`frontend-foundation` D9/D13, and D5 of this
 * change). An async component nested
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
