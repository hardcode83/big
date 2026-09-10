import type { ShellProfile } from "@/features/shell";

/**
 * Where a notification row links to, per shell profile (R6.1, R6.2, R6.4, design D15).
 *
 * **One table, and the profile is a dimension of it rather than an `if`.** That is what makes
 * R6.4 true: the day `cleaner-app` ships its task detail, adding the destination is filling in
 * a cell here, not searching through components.
 *
 * `workspace` and `technician` are the populated rows: `/incidents/[id]`, `/conversations/[id]`
 * and `/reservations/[id]` are real pages for `workspace`, and `/tech/incidents/[id]` is a real
 * page for `technician` (R5.2). `cleaner` is declared and deliberately EMPTY — its detail routes
 * are `RoutePlaceholder` until `cleaner-app` delivers them, and a link into a placeholder is
 * worse than no link (R6.2, R5.4). It is written out rather than omitted so the shape of the
 * table says what is missing.
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
  technician: {
    incident: (id) => `/tech/incidents/${id}`,
  },
  // The four shells below never mount the bell (R3.1), so they can have no destinations.
  public: {},
  guest: {},
  authenticated: {},
  // `SUPER_ADMIN`'s console (`super-admin-console` R1) uses the same bare topbar
  // composition `authenticated` does for `/welcome` — `Brand` + `UserMenu`, no bell.
  platform: {},
};

/**
 * Destinations keyed by the notification's own `type` rather than by `related_type` (R5.1,
 * design D8). `related_type`/`related_id` is a polymorphic pair pointing at the *subject* of a
 * notification (an incident, a conversation…) — but `OWNER_APPROVAL_REQUIRED` doesn't point at a
 * per-row entity, it points at the approvals queue itself, which takes no id. Hence a second
 * table, consulted first: builders here take no `id` argument.
 *
 * `workspace` is the only populated row today. `cleaner` and `technician` are declared and
 * EMPTY: a type-keyed override is not needed for either yet, and — per the module docstring —
 * the row is written out so a missing shell is a typecheck failure, not a silent gap.
 */
export type NotificationTypeDestinations = Record<
  ShellProfile,
  Partial<Record<string, () => string>>
>;

export const NOTIFICATION_TYPE_DESTINATIONS: NotificationTypeDestinations = {
  workspace: {
    OWNER_APPROVAL_REQUIRED: () => "/approvals",
  },
  cleaner: {},
  technician: {},
  public: {},
  guest: {},
  authenticated: {},
  platform: {},
};

/**
 * The href for one row, or `null` when there is nowhere to go (R5.1, R5.3, R6.1, R6.3).
 *
 * Consults `NOTIFICATION_TYPE_DESTINATIONS[profile]` (keyed by `type`) before falling through to
 * `NOTIFICATION_DESTINATIONS[profile]` (keyed by `related_type`) — a type with an override wins
 * outright and never needs `related_type`/`related_id`. Returns `null` — rather than a `#` or
 * the id — for every case that is not a live destination: no override and (no `related_type`, no
 * `related_id`, a `related_type` the table does not carry, or a profile whose pages do not exist
 * yet). The caller renders plain text, and the UUID never reaches the screen.
 */
export function notificationHref(
  type: string,
  profile: ShellProfile,
  relatedType: string | null,
  relatedId: string | null,
): string | null {
  const typeTable = NOTIFICATION_TYPE_DESTINATIONS[profile];
  // Same guard as the `related_type` table below, and for the same reason: `type` is free text
  // off the wire too, and a plain object literal answers for its PROTOTYPE.
  if (Object.hasOwn(typeTable, type)) {
    const buildFromType = typeTable[type];
    if (typeof buildFromType === "function") {
      const typeHref = buildFromType();
      if (typeof typeHref === "string" && typeHref.startsWith("/")) {
        return typeHref;
      }
    }
  }

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
