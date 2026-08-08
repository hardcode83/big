import { DEFAULT_LOCALE, type Locale } from "./constants";
import identityContract from "./build-identity-contract.json";

/**
 * The public runtime configuration is the ONLY configuration object allowed to
 * cross to the browser (design D15). It is assembled from an explicit allowlist
 * of non-sensitive sources — never by spreading `process.env`. Adding a field
 * here is a deliberate act, which is what keeps server-only values (e.g.
 * `BACKEND_INTERNAL_URL`) and secrets out of the client bundle.
 */
export interface PublicRuntimeConfig {
  /** Same-origin API base; the route handler forwards `/api/` server-side. */
  apiBaseUrl: string;
  /** Deployment environment label (from NEXT_PUBLIC_APP_ENV). Non-sensitive. */
  appEnv: string;
  /** Product default locale. */
  defaultLocale: Locale;
  /**
   * Server-evaluated, allowlisted boolean feature flags. Empty in this change:
   * the boundary exists, but no flags are defined or activated yet (design D15).
   */
  featureFlags: Readonly<Record<string, boolean>>;
  /**
   * Canonical build version baked at image build time (`<base>+<date>.<sha>`), or
   * `""` when the image carries no identity (a local `npm run dev`, an image built
   * without build-args). Change `app-version-visibility`, D3.
   */
  appVersion: string;
  /**
   * Short commit SHA baked at build time, or `""`.
   *
   * These two are the ONLY build identity this snapshot carries. The full SHA, the Pull
   * Request number, the Actions run id and the repository URL do not enter the frontend
   * snapshot or bundle — the full SHA remains available only in the OCI revision label, while
   * the other provenance fields live in the `app-version-provenance` roadmap entry, blocked
   * until the frontend has authentication. This snapshot reaches the browser on EVERY surface,
   * including `/login` and the guest portal
   * (app-version-visibility D3, R2.4).
   */
  buildCommitShort: string;
}

/**
 * The only two shapes the build identity may have to enter this snapshot.
 *
 * This is a **disclosure boundary**, not a formatting nicety, and it has to live here
 * rather than in the badge that displays it. React serializes this whole object as a prop
 * into the RSC payload of the root layout, so it is embedded in the server-rendered HTML of
 * **every** surface — `/login` and `/guest/<token>` included — no matter which components
 * read it. Validating in `VersionBadge` only cleans the pixels the operator sees; the raw
 * value still travels in the page source of the guest portal, which the capability spec
 * singles out as the one surface that must not receive it (`sdd/specs/app-version-visibility.md`,
 * "Alcance de la divulgación, aceptado", and the prohibition at lines 67-70 on the full SHA,
 * the Pull Request number, the `run_id` and the `ref`).
 *
 * So anything off-shape is dropped to `""` HERE, where every present and future consumer of
 * the snapshot is covered at once. `""` is already the "no identity baked" case the badge
 * renders as a localized "unknown", so dropping degrades safely.
 *
 * Everything is pinned to what the pipeline actually guarantees, never to a character class
 * plus a length cap — a cap only limits how much of a secret leaks, it does not stop one:
 *
 * - The base is `X.Y.Z`, which the CD validates before composing anything
 *   (`grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'` on `VERSION`), or the literal `local` that
 *   `docker-compose.yml` defaults to for a dev image. An earlier version of this pattern
 *   allowed any 32 alphanumerics/dots/hyphens, and the security panel showed that
 *   `0.1.0-30618352968+2026-07-31.5872022` — a run id in the base, a common CI versioning
 *   pattern — sailed through into the HTML of `/guest/<token>`, as did a 32-character hex
 *   prefix that `git rev-parse` resolves to a commit.
 * - The commit is exactly 7 hex characters, which is what the CD composes
 *   (`${GITHUB_SHA:0:7}`). Deliberately NOT a range: decimal digits are a subset of hex, so a
 *   lenient `{7,12}` accepts an Actions `run_id` — 11 decimal digits — as if it were a commit.
 * - The date's month and day are bounded to real calendar dates, not just to two digits each.
 *   A bare `\d{4}-\d{2}-\d{2}` is eight FREE decimal digits, and `0.1.0+3061-83-52.9680000`
 *   sailed through it — the same mistake as the base, one slot further along. The pipeline
 *   guarantees `date -u`, which means a real date, so that is what gets required.
 *
 * If either shape ever changes upstream, change it here in the same commit, on purpose. The
 * badge degrades to "unknown" rather than showing something unvetted, and the
 * `frontend-tests` Pull Request check verifies that the CD producer and this boundary stay
 * congruent.
 *
 * All of this came out of the security and architecture panels of the `app-version-badge-date`
 * change, across three iterations: the first put the check in the badge (wrong layer — the
 * value reaches the page source regardless), the second bounded the commit too loosely, and
 * the third left the base unpinned.
 */
const BAKED_VERSION = new RegExp(
  `^(?:${identityContract.basePattern}(?:\\+${identityContract.datePattern}\\.${identityContract.commitShortPattern})?|${identityContract.localVersion})$`,
);
const BAKED_COMMIT_SHORT = new RegExp(
  `^${identityContract.commitShortPattern}$`,
);
const BAKED_DATE = new RegExp(
  `\\+(${identityContract.datePattern})\\.${identityContract.commitShortPattern}$`,
);

function isRealCalendarDate(yearText: string, monthText: string, dayText: string): boolean {
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  if (!Number.isSafeInteger(year)) return false;

  const daysInMonth = [
    31,
    year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ][month - 1];
  return day <= daysInMonth;
}

function allowlistedVersion(raw: string | undefined): string {
  const value = (raw ?? "").trim();
  if (!BAKED_VERSION.test(value)) return "";

  const dateMatch = value.match(BAKED_DATE);
  if (!dateMatch) return value;

  const [, date] = dateMatch;
  const [year, month, day] = date.split("-");
  return isRealCalendarDate(year, month, day) ? value : "";
}

function allowlistedShape(raw: string | undefined, shape: RegExp): string {
  const value = (raw ?? "").trim();
  return shape.test(value) ? value : "";
}

export function buildPublicRuntimeConfig(): PublicRuntimeConfig {
  return {
    apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "",
    appEnv: process.env.NEXT_PUBLIC_APP_ENV ?? "development",
    defaultLocale: DEFAULT_LOCALE,
    featureFlags: Object.freeze({}),
    // Read here and nowhere else, so the whole application takes the build identity
    // from the same allowlisted boundary as every other public value. Baked at image
    // build time, which is what makes them unable to lie about which image is running
    // — a value injected by Compose at runtime reports what Compose believes instead.
    appVersion: allowlistedVersion(process.env.NEXT_PUBLIC_APP_VERSION),
    buildCommitShort: allowlistedShape(
      process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT,
      BAKED_COMMIT_SHORT,
    ),
  };
}
