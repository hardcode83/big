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

export function buildPublicRuntimeConfig(): PublicRuntimeConfig {
  return {
    appEnv: process.env.NEXT_PUBLIC_APP_ENV ?? "development",
    defaultLocale: DEFAULT_LOCALE,
    featureFlags: Object.freeze({}),
    // Read here and nowhere else, so the whole application takes the build identity
    // from the same allowlisted boundary as every other public value. Baked at image
    // build time, which is what makes them unable to lie about which image is running
    // — a value injected by Compose at runtime reports what Compose believes instead.
    appVersion: process.env.NEXT_PUBLIC_APP_VERSION ?? "",
    buildCommitShort: process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT ?? "",
  };
}
