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
 * The one metadata shape the badge renders verbatim: a build date and a short commit, as in
 * `2026-07-31.5872022`.
 *
 * The component distrusts its producer on purpose, for the same reason the empty-base guard
 * below exists — it must not depend on its caller being careful. Until this change the
 * metadata was DISCARDED and replaced by the short SHA, so whatever the CD composed, only
 * seven characters could ever reach the screen. Showing it whole removes that structural
 * limit, and the badge is painted on ANONYMOUS surfaces: a later edit to the provenance step
 * — dropping `:0:7` from `${GITHUB_SHA:0:7}`, or appending `.${GITHUB_RUN_ID}` — would
 * publish the full SHA or the Actions run id in the footer of `/login`. Those are precisely
 * the values the capability forbids in the frontend snapshot (R2.4 in
 * `sdd/specs/app-version-visibility.md`), so the badge enforces it here rather than trusting
 * the pipeline to keep being careful. Off-shape metadata degrades to the short form: the
 * badge shows LESS than expected, never more. Found by the security panel of this change.
 *
 * The 7-12 bound on the commit is what rejects a 40-character full SHA while still tolerating
 * a pipeline that widens the abbreviation. If the canonical schema ever changes — a time
 * component, say — this pattern changes with it, or the badge silently falls back.
 */
const CANONICAL_METADATA = /^\d{4}-\d{2}-\d{2}\.[0-9a-f]{7,12}$/;

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

  // `rest.join("+")` instead of `rest[0]`, so the shape check sees the WHOLE metadata.
  // Taking only the first segment would let a smuggled suffix — `2026-07-31.5872022+dirty` —
  // be truncated into something that matches the canonical shape, and the badge would then
  // pass a modified build off as a clean one.
  const metadata = rest.join("+").trim();
  if (CANONICAL_METADATA.test(metadata)) return `${base}+${metadata}`;

  // No usable metadata: either the string never had any (the `local` of dev), or it had a
  // `+` carrying nothing (`"0.1.0+"`, `"0.1.0++"` — the mirror image of the empty-base guard
  // above), or it carried something off-shape. Either way the short SHA is the only identity
  // left, so it is still worth appending when the image baked one.
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
