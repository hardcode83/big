import {
  routeRegistry,
  type ShellProfile,
  type ShellRouteDescriptor,
} from "./route-registry";

/**
 * Active-route resolution (design D5). Matching is done against the route
 * registry, normalizing trailing slash and ignoring query/hash. The most
 * specific descriptor wins: an exact match first, then the longest valid prefix.
 */

export function normalizePath(pathname: string): string {
  const withoutQueryOrHash = pathname.split(/[?#]/)[0];
  if (withoutQueryOrHash.length > 1 && withoutQueryOrHash.endsWith("/")) {
    return withoutQueryOrHash.slice(0, -1);
  }
  return withoutQueryOrHash === "" ? "/" : withoutQueryOrHash;
}

function toSegments(path: string): string[] {
  return normalizePath(path)
    .split("/")
    .filter((segment) => segment.length > 0);
}

function isDynamic(segment: string): boolean {
  return segment.startsWith("[") && segment.endsWith("]");
}

function segmentsMatch(
  patternSegments: string[],
  pathSegments: string[],
  mode: "exact" | "prefix",
): boolean {
  if (mode === "exact" && patternSegments.length !== pathSegments.length) {
    return false;
  }
  if (mode === "prefix" && patternSegments.length > pathSegments.length) {
    return false;
  }
  return patternSegments.every((segment, index) =>
    isDynamic(segment)
      ? pathSegments[index]?.length > 0
      : segment === pathSegments[index],
  );
}

/**
 * The most specific route descriptor for a pathname within a profile, used for
 * breadcrumbs and page titles. Prefers the longest pattern; ties break toward an
 * exact match.
 */
export function matchRoute(
  pathname: string,
  profile: ShellProfile,
): ShellRouteDescriptor | undefined {
  const pathSegments = toSegments(pathname);
  let best: ShellRouteDescriptor | undefined;
  let bestLength = -1;
  let bestIsExact = false;

  for (const route of routeRegistry) {
    if (route.profile !== profile) {
      continue;
    }
    const patternSegments = toSegments(route.pattern);
    const exact = segmentsMatch(patternSegments, pathSegments, "exact");
    const prefix =
      !exact &&
      route.match === "prefix" &&
      segmentsMatch(patternSegments, pathSegments, "prefix");
    if (!exact && !prefix) {
      continue;
    }
    const length = patternSegments.length;
    if (length > bestLength || (length === bestLength && exact && !bestIsExact)) {
      best = route;
      bestLength = length;
      bestIsExact = exact;
    }
  }

  return best;
}

/**
 * Whether a navigable descriptor should be marked active for the current
 * pathname. Uses the descriptor's static `href` and its `match` strategy
 * (prefix routes stay active for their descendants).
 */
export function isRouteActive(
  descriptor: ShellRouteDescriptor,
  pathname: string,
): boolean {
  if (descriptor.href === undefined) {
    return false;
  }
  const path = normalizePath(pathname);
  const target = normalizePath(descriptor.href);
  if (descriptor.match === "prefix") {
    return path === target || path.startsWith(`${target}/`);
  }
  return path === target;
}
