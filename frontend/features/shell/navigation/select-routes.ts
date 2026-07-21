import {
  routeRegistry,
  type NavigationGroup,
  type ShellProfile,
  type ShellRouteDescriptor,
} from "./route-registry";

/**
 * Navigation is always selected per shell profile (design D4). There is
 * deliberately NO "all" selector for rendering: every consumer must pass a
 * concrete `ShellProfile`, so a shell can never render another profile's routes.
 */

const GROUP_ORDER: readonly NavigationGroup[] = [
  "operation",
  "work",
  "revenue",
  "administration",
];

/** Every descriptor owned by a profile (metadata scope: breadcrumbs, placeholders). */
export function selectRoutesForProfile(
  profile: ShellProfile,
): ShellRouteDescriptor[] {
  return routeRegistry.filter((route) => route.profile === profile);
}

/**
 * Primary navigation links for a profile: navigable (has `href`) and ordered
 * (`order` set). Dynamic and child routes (no href/order) are excluded.
 */
export function selectPrimaryNavigation(
  profile: ShellProfile,
): ShellRouteDescriptor[] {
  return selectRoutesForProfile(profile)
    .filter((route) => route.href !== undefined && route.order !== undefined)
    .sort(compareByGroupThenOrder);
}

export interface NavigationGroupBlock {
  group: NavigationGroup;
  routes: ShellRouteDescriptor[];
}

/**
 * Primary navigation grouped by NavigationGroup in canonical order — used by the
 * Workspace sidebar. Profiles without groups (cleaner/technician) yield no blocks.
 */
export function selectNavigationGroups(
  profile: ShellProfile,
): NavigationGroupBlock[] {
  const items = selectPrimaryNavigation(profile).filter(
    (route) => route.navigationGroup !== undefined,
  );
  const blocks: NavigationGroupBlock[] = [];
  for (const group of GROUP_ORDER) {
    const routes = items
      .filter((route) => route.navigationGroup === group)
      .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
    if (routes.length > 0) {
      blocks.push({ group, routes });
    }
  }
  return blocks;
}

function compareByGroupThenOrder(
  a: ShellRouteDescriptor,
  b: ShellRouteDescriptor,
): number {
  const groupDelta =
    groupIndex(a.navigationGroup) - groupIndex(b.navigationGroup);
  if (groupDelta !== 0) {
    return groupDelta;
  }
  return (a.order ?? 0) - (b.order ?? 0);
}

function groupIndex(group: NavigationGroup | undefined): number {
  if (group === undefined) {
    return GROUP_ORDER.length;
  }
  return GROUP_ORDER.indexOf(group);
}
