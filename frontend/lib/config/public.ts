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
}

export function buildPublicRuntimeConfig(): PublicRuntimeConfig {
  return {
    appEnv: process.env.NEXT_PUBLIC_APP_ENV ?? "development",
    defaultLocale: DEFAULT_LOCALE,
    featureFlags: Object.freeze({}),
  };
}
