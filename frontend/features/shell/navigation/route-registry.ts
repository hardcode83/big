/**
 * Single source of truth for every route surface defined in PRD §24 (design D4).
 *
 * A descriptor carries ONLY shell metadata: a stable id, its route pattern, an
 * optional navigable href, i18n keys (title/description/metadata/breadcrumb), an
 * icon NAME (serializable — not a component, per D9), a shell profile, an active
 * matching strategy, and optional navigation group/order. It never carries
 * permissions, endpoints, DTOs, data, counters, or business state (D4, Data &
 * interfaces).
 */

export type ShellProfile =
  | "workspace"
  | "cleaner"
  | "technician"
  | "public"
  | "guest";

export type NavigationGroup =
  | "operation"
  | "work"
  | "revenue"
  | "administration";

/** Icon names resolved to lucide components by the shell (kept serializable). */
export type NavigationIconName =
  | "LayoutDashboard"
  | "CalendarClock"
  | "Building2"
  | "CalendarCheck"
  | "Sparkles"
  | "Wrench"
  | "MessagesSquare"
  | "BadgeCheck"
  | "Tag"
  | "Receipt"
  | "Star"
  | "Settings"
  | "Plug"
  | "LogIn"
  | "KeyRound"
  | "ClipboardList"
  | "DoorOpen";

export interface ShellRouteDescriptor {
  id: string;
  pattern: string;
  href?: string;
  titleKey: string;
  descriptionKey: string;
  metadataTitleKey: string;
  metadataDescriptionKey: string;
  breadcrumbKeys: readonly string[];
  icon: NavigationIconName;
  profile: ShellProfile;
  match: "exact" | "prefix";
  navigationGroup?: NavigationGroup;
  order?: number;
}

function keysFor(id: string) {
  return {
    titleKey: `navigation:routes.${id}.title`,
    descriptionKey: `navigation:routes.${id}.description`,
    // Metadata reuses the localized route copy (design D19); the separate keys
    // keep the option open for a route to diverge later without a schema change.
    metadataTitleKey: `navigation:routes.${id}.title`,
    metadataDescriptionKey: `navigation:routes.${id}.description`,
  };
}

function crumbs(...ids: string[]): readonly string[] {
  return ids.map((id) => `navigation:routes.${id}.title`);
}

export const routeRegistry: readonly ShellRouteDescriptor[] = [
  // ---- Workspace: Operation ----
  {
    id: "dashboard",
    pattern: "/dashboard",
    href: "/dashboard",
    ...keysFor("dashboard"),
    breadcrumbKeys: crumbs("dashboard"),
    icon: "LayoutDashboard",
    profile: "workspace",
    match: "exact",
    navigationGroup: "operation",
    order: 1,
  },
  {
    id: "timeline",
    pattern: "/timeline",
    href: "/timeline",
    ...keysFor("timeline"),
    breadcrumbKeys: crumbs("timeline"),
    icon: "CalendarClock",
    profile: "workspace",
    match: "exact",
    navigationGroup: "operation",
    order: 2,
  },
  {
    id: "properties",
    pattern: "/properties",
    href: "/properties",
    ...keysFor("properties"),
    breadcrumbKeys: crumbs("properties"),
    icon: "Building2",
    profile: "workspace",
    match: "prefix",
    navigationGroup: "operation",
    order: 3,
  },
  {
    id: "property-detail",
    pattern: "/properties/[id]",
    ...keysFor("property-detail"),
    breadcrumbKeys: crumbs("properties", "property-detail"),
    icon: "Building2",
    profile: "workspace",
    match: "exact",
  },
  // ---- Workspace: Work ----
  {
    id: "reservations",
    pattern: "/reservations",
    href: "/reservations",
    ...keysFor("reservations"),
    breadcrumbKeys: crumbs("reservations"),
    icon: "CalendarCheck",
    profile: "workspace",
    match: "exact",
    navigationGroup: "work",
    order: 1,
  },
  {
    id: "reservation-detail",
    pattern: "/reservations/[id]",
    ...keysFor("reservation-detail"),
    breadcrumbKeys: crumbs("reservations", "reservation-detail"),
    icon: "CalendarCheck",
    profile: "workspace",
    match: "exact",
  },
  {
    id: "cleaning",
    pattern: "/cleaning",
    href: "/cleaning",
    ...keysFor("cleaning"),
    breadcrumbKeys: crumbs("cleaning"),
    icon: "Sparkles",
    profile: "workspace",
    match: "exact",
    navigationGroup: "work",
    order: 2,
  },
  {
    id: "incidents",
    pattern: "/incidents",
    href: "/incidents",
    ...keysFor("incidents"),
    breadcrumbKeys: crumbs("incidents"),
    icon: "Wrench",
    profile: "workspace",
    match: "exact",
    navigationGroup: "work",
    order: 3,
  },
  {
    id: "incident-detail",
    pattern: "/incidents/[id]",
    ...keysFor("incident-detail"),
    breadcrumbKeys: crumbs("incidents", "incident-detail"),
    icon: "Wrench",
    profile: "workspace",
    match: "exact",
  },
  {
    id: "conversations",
    pattern: "/conversations",
    href: "/conversations",
    ...keysFor("conversations"),
    breadcrumbKeys: crumbs("conversations"),
    icon: "MessagesSquare",
    profile: "workspace",
    match: "exact",
    navigationGroup: "work",
    order: 4,
  },
  {
    id: "conversation-detail",
    pattern: "/conversations/[id]",
    ...keysFor("conversation-detail"),
    breadcrumbKeys: crumbs("conversations", "conversation-detail"),
    icon: "MessagesSquare",
    profile: "workspace",
    match: "exact",
  },
  {
    id: "approvals",
    pattern: "/approvals",
    href: "/approvals",
    ...keysFor("approvals"),
    breadcrumbKeys: crumbs("approvals"),
    icon: "BadgeCheck",
    profile: "workspace",
    match: "exact",
    navigationGroup: "work",
    order: 5,
  },
  // ---- Workspace: Revenue ----
  {
    id: "pricing",
    pattern: "/pricing",
    href: "/pricing",
    ...keysFor("pricing"),
    breadcrumbKeys: crumbs("pricing"),
    icon: "Tag",
    profile: "workspace",
    match: "exact",
    navigationGroup: "revenue",
    order: 1,
  },
  {
    id: "statements",
    pattern: "/statements",
    href: "/statements",
    ...keysFor("statements"),
    breadcrumbKeys: crumbs("statements"),
    icon: "Receipt",
    profile: "workspace",
    match: "exact",
    navigationGroup: "revenue",
    order: 2,
  },
  {
    id: "reviews",
    pattern: "/reviews",
    href: "/reviews",
    ...keysFor("reviews"),
    breadcrumbKeys: crumbs("reviews"),
    icon: "Star",
    profile: "workspace",
    match: "exact",
    navigationGroup: "revenue",
    order: 3,
  },
  // ---- Workspace: Administration ----
  {
    id: "settings",
    pattern: "/settings",
    href: "/settings",
    ...keysFor("settings"),
    breadcrumbKeys: crumbs("settings"),
    icon: "Settings",
    profile: "workspace",
    match: "prefix",
    navigationGroup: "administration",
    order: 1,
  },
  {
    id: "settings-integrations",
    pattern: "/settings/integrations",
    href: "/settings/integrations",
    ...keysFor("settings-integrations"),
    breadcrumbKeys: crumbs("settings", "settings-integrations"),
    icon: "Plug",
    profile: "workspace",
    match: "exact",
  },
  // ---- Public ----
  {
    id: "landing",
    pattern: "/",
    href: "/",
    titleKey: "landing:meta.title",
    descriptionKey: "landing:meta.description",
    // The shell metadata uses the same landing copy as the page body so the
    // SERP card and the page agree on what the visitor is about to read.
    metadataTitleKey: "landing:meta.title",
    metadataDescriptionKey: "landing:meta.description",
    breadcrumbKeys: crumbs("landing"),
    icon: "LogIn",
    profile: "public",
    match: "exact",
  },
  {
    id: "login",
    pattern: "/login",
    href: "/login",
    ...keysFor("login"),
    breadcrumbKeys: crumbs("login"),
    icon: "LogIn",
    profile: "public",
    match: "exact",
  },
  {
    id: "forgot-password",
    pattern: "/forgot-password",
    href: "/forgot-password",
    ...keysFor("forgot-password"),
    breadcrumbKeys: crumbs("forgot-password"),
    icon: "KeyRound",
    profile: "public",
    match: "exact",
  },
  // ---- Cleaner (mobile-first) ----
  {
    id: "cleaner",
    pattern: "/cleaner",
    href: "/cleaner",
    ...keysFor("cleaner"),
    breadcrumbKeys: crumbs("cleaner"),
    icon: "ClipboardList",
    profile: "cleaner",
    match: "prefix",
    order: 1,
  },
  {
    id: "cleaner-task",
    pattern: "/cleaner/tasks/[id]",
    ...keysFor("cleaner-task"),
    breadcrumbKeys: crumbs("cleaner", "cleaner-task"),
    icon: "ClipboardList",
    profile: "cleaner",
    match: "exact",
  },
  // ---- Technician (mobile-first). Internal profile `technician`; slug /tech. ----
  {
    id: "tech",
    pattern: "/tech",
    href: "/tech",
    ...keysFor("tech"),
    breadcrumbKeys: crumbs("tech"),
    icon: "Wrench",
    profile: "technician",
    match: "prefix",
    order: 1,
  },
  {
    id: "tech-incident",
    pattern: "/tech/incidents/[id]",
    ...keysFor("tech-incident"),
    breadcrumbKeys: crumbs("tech", "tech-incident"),
    icon: "Wrench",
    profile: "technician",
    match: "exact",
  },
  // ---- Guest (token portal). Not navigable without a token; no href. ----
  {
    id: "guest",
    pattern: "/guest/[token]",
    ...keysFor("guest"),
    breadcrumbKeys: crumbs("guest"),
    icon: "DoorOpen",
    profile: "guest",
    match: "prefix",
  },
];

const routesById = new Map(routeRegistry.map((route) => [route.id, route]));

export function getRouteById(id: string): ShellRouteDescriptor | undefined {
  return routesById.get(id);
}
