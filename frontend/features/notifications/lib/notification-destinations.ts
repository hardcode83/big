import type { ShellProfile } from "@/features/shell";

/**
 * Where a notification row links to, per shell profile (R6.1, R6.2, R6.4, design D15).
 *
 * **One table, and the profile is a dimension of it rather than an `if`.** That is what makes
 * R6.4 true: the day `cleaner-app` ships its task detail, adding the destination is filling in
 * a cell here, not searching through components.
 *
 * `workspace` is the only populated row because it is the only shell whose detail pages exist:
 * `/incidents/[id]`, `/conversations/[id]` and `/reservations/[id]` are real pages today.
 * `cleaner` and `technician` are declared and deliberately EMPTY — their detail routes are
 * `RoutePlaceholder` until `cleaner-app` and `tech-app` deliver them, and a link into a
 * placeholder is worse than no link (R6.2). They are written out rather than omitted so the
 * shape of the table says what is missing.
 *
 * **`cleaning_task` is absent on purpose** (R6.2): there is no manager-facing detail page for a
 * cleaning task, so the most common notification type in the system — `CLEANING_TASK_ASSIGNED` —
 * renders without a link rather than pointing somewhere that does not exist.
 *
 * The keys are `related_type` values, which the backend writes as free text alongside the
 * polymorphic `related_id` (PRD §7.24). A type that is not in the table, or a row with either
 * half of the pair missing, yields no link — and never the raw UUID (R6.3).
 */
export type NotificationDestinations = Record<
  ShellProfile,
  Partial<Record<string, (id: string) => string>>
>;

export const NOTIFICATION_DESTINATIONS: NotificationDestinations = {
  workspace: {
    incident: (id) => `/incidents/${id}`,
    conversation: (id) => `/conversations/${id}`,
    reservation: (id) => `/reservations/${id}`,
  },
  // Empty until `cleaner-app` delivers `/cleaner/tasks/[id]`. See the module docstring.
  cleaner: {},
  // Empty until `tech-app` delivers `/tech/incidents/[id]`. Same reason.
  technician: {},
  // The three shells below never mount the bell (R3.1), so they can have no destinations.
  public: {},
  guest: {},
  authenticated: {},
};

/**
 * The href for one row, or `null` when there is nowhere to go (R6.1, R6.3).
 *
 * Returns `null` — rather than a `#` or the id — for every case that is not a live
 * destination: no `related_type`, no `related_id`, a type the table does not carry, or a
 * profile whose pages do not exist yet. The caller renders plain text, and the UUID never
 * reaches the screen.
 */
export function notificationHref(
  profile: ShellProfile,
  relatedType: string | null,
  relatedId: string | null,
): string | null {
  if (relatedType === null || relatedId === null) {
    return null;
  }
  const table = NOTIFICATION_DESTINATIONS[profile];
  // `Object.hasOwn`, not a bare index: `relatedType` is free text off the wire (`String(100)`),
  // and a plain object literal answers for its PROTOTYPE too. Measured, not feared:
  // `table["constructor"]` returns `Object` — truthy, so the row would render a link where
  // R6.3 requires none — and `table["valueOf"]` THROWS at render, inside a topbar that the
  // field shells mount above their own `AuthGuard`, which is the whole-chrome tear-down D16
  // exists to prevent. Found by the section 7-9 security panel.
  if (!Object.hasOwn(table, relatedType)) {
    return null;
  }
  const build = table[relatedType];
  if (typeof build !== "function") {
    return null;
  }
  const href = build(relatedId);
  // The table is ours, so this cannot fail today; it is here so that it still cannot fail if
  // somebody adds a cell that returns something else.
  return typeof href === "string" && href.startsWith("/") ? href : null;
}
