import { matchRoute } from "./match-route";
import type { ShellProfile } from "./route-registry";

/**
 * Breadcrumb trail for a pathname (design D5). Built from the matched
 * descriptor's explicit `breadcrumbKeys` chain — never from raw path segments —
 * so IDs and tokens are never revealed and every label is a localized key.
 * Dynamic segments already resolve to a generic localized label in the registry.
 */
export function buildBreadcrumbs(
  pathname: string,
  profile: ShellProfile,
): readonly string[] {
  return matchRoute(pathname, profile)?.breadcrumbKeys ?? [];
}
