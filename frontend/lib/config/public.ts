import { DEFAULT_LOCALE, type Locale } from "./constants";

/**
 * The public runtime configuration is the ONLY configuration object allowed to
 * cross to the browser (design D15). It is assembled from an explicit allowlist
 * of non-sensitive sources — never by spreading `process.env`. Adding a field
 * here is a deliberate act, which is what keeps server-only values (e.g.
 * `BACKEND_INTERNAL_URL`) and secrets out of the client bundle.
 */
export interface PublicRuntimeConfig {
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
   * These two are the ONLY build identity this change carries. The full SHA, the Pull
   * Request number, the Actions run id and the repository URL are **not baked anywhere**
   * — they were removed with the provenance scope and live in the `app-version-provenance`
   * roadmap entry, which is blocked until the frontend has authentication. Do not read
   * this as "they exist server-side and are blessed": they do not exist. This snapshot
   * reaches the browser on EVERY surface, including `/login` and the guest portal
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
 * The commit is pinned to exactly 7 hex characters because that is what the CD composes
 * (`${GITHUB_SHA:0:7}` in the `provenance` job). It is deliberately NOT a range: decimal
 * digits are a subset of hex, so a lenient `{7,12}` would happily accept an Actions
 * `run_id` — an 11-digit decimal number — as if it were a commit. If the abbreviation ever
 * widens, widen this pattern in the same commit, on purpose.
 *
 * Both patterns and the reasoning came out of the security and architecture panels of the
 * `app-version-badge-date` change; the first two attempts got the layer and the bound wrong.
 */
const BAKED_VERSION = /^[0-9A-Za-z][0-9A-Za-z.-]{0,31}(\+\d{4}-\d{2}-\d{2}\.[0-9a-f]{7})?$/;
const BAKED_COMMIT_SHORT = /^[0-9a-f]{7}$/;

function allowlistedShape(raw: string | undefined, shape: RegExp): string {
  const value = (raw ?? "").trim();
  return shape.test(value) ? value : "";
}

export function buildPublicRuntimeConfig(): PublicRuntimeConfig {
  return {
    appEnv: process.env.NEXT_PUBLIC_APP_ENV ?? "development",
    defaultLocale: DEFAULT_LOCALE,
    featureFlags: Object.freeze({}),
    // Read here and nowhere else, so the whole application takes the build identity
    // from the same allowlisted boundary as every other public value. Baked at image
    // build time, which is what makes them unable to lie about which image is running
    // — a value injected by Compose at runtime reports what Compose believes instead.
    appVersion: allowlistedShape(
      process.env.NEXT_PUBLIC_APP_VERSION,
      BAKED_VERSION,
    ),
    buildCommitShort: allowlistedShape(
      process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT,
      BAKED_COMMIT_SHORT,
    ),
  };
}
