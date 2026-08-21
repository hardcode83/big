import type { CleaningTaskStatus } from "../data";

/**
 * Colour group and badge classes for a cleaning task's status (design D12).
 *
 * The `Record` is exhaustive over the generated `CleaningTaskStatus` union, so a
 * tenth status in the backend fails **at compile time** as soon as the contract is
 * regenerated (R1.6). That is a build-time guarantee and not a runtime one: until
 * the frontend is rebuilt against the new contract, such a status can still arrive
 * over the wire, which is what the `?? "gray"` in `statusColorGroup()` below is for.
 * The label itself comes from the `cleaning` i18n namespace; the raw enum
 * identifier is never rendered.
 *
 * ASSUMPTION: PRD §9.1 fixes colours for a **property's** operational state, not
 * for a cleaning task's. This grouping is our reading of the same palette applied
 * to the task lifecycle: amber = waiting on someone, blue = under way, green =
 * done, red = went wrong, grey = called off.
 */
export type StatusColorGroup = "green" | "blue" | "amber" | "red" | "gray";

/**
 * Declared in the canonical PRD order of R1.6, not grouped by colour: the key order
 * is what `CLEANING_TASK_STATUSES` hands to the status filter, and a dropdown that
 * lists the lifecycle out of order reads as arbitrary.
 */
const STATUS_COLOR_GROUP: Record<CleaningTaskStatus, StatusColorGroup> = {
  CREATED: "amber",
  ASSIGNED: "amber",
  ACCEPTED: "blue",
  REJECTED: "red",
  IN_PROGRESS: "blue",
  PENDING_REVIEW: "amber",
  COMPLETED: "green",
  FAILED: "red",
  CANCELLED: "gray",
};

/**
 * Copied from `STATE_BADGE_CLASS` in
 * `features/dashboard/components/property-card.tsx` — its twin. Kept duplicated
 * on purpose (design D12): extracting it to a shared module would touch a
 * delivered feature without changing its behaviour, and the extraction is worth
 * paying for when a third consumer appears.
 */
export const STATUS_BADGE_CLASS: Record<StatusColorGroup, string> = {
  green:
    "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-200 dark:border-emerald-800",
  blue: "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-950 dark:text-blue-200 dark:border-blue-800",
  amber:
    "bg-amber-100 text-amber-900 border-amber-200 dark:bg-amber-950 dark:text-amber-200 dark:border-amber-800",
  red: "bg-red-100 text-red-800 border-red-200 dark:bg-red-950 dark:text-red-200 dark:border-red-800",
  gray: "bg-muted text-muted-foreground border-border",
};

/** Grey for a status the union does not know, so a new backend status never crashes a row. */
export function statusColorGroup(status: CleaningTaskStatus): StatusColorGroup {
  return STATUS_COLOR_GROUP[status] ?? "gray";
}

/** The nine canonical values, for the status filter and for exhaustiveness tests. */
export const CLEANING_TASK_STATUSES = Object.keys(
  STATUS_COLOR_GROUP,
) as readonly CleaningTaskStatus[];
