import { TONE_BADGE_CLASS, type Tone } from "@/lib/ui/status-tone";

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
export type StatusColorGroup = Tone;

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
 * Design D12 kept this duplicated «until a third consumer appears», and
 * `features/pricing` is it: `pricing-web` (design D22) extracted the strings to
 * `lib/ui/status-tone.ts`. The name stays so `cleaning-task-row.tsx` and
 * `task-status.test.ts` compile untouched, which is how the move proves it
 * changed no behaviour.
 *
 * Its twin was never in `features/dashboard/components/property-card.tsx`,
 * where this comment used to point: `properties-web` (design D2) had already
 * moved it to `components/property-state-badge.tsx`.
 */
export const STATUS_BADGE_CLASS: Record<StatusColorGroup, string> =
  TONE_BADGE_CLASS;

/** Grey for a status the union does not know, so a new backend status never crashes a row. */
export function statusColorGroup(status: CleaningTaskStatus): StatusColorGroup {
  return STATUS_COLOR_GROUP[status] ?? "gray";
}

/** The nine canonical values, for the status filter and for exhaustiveness tests. */
export const CLEANING_TASK_STATUSES = Object.keys(
  STATUS_COLOR_GROUP,
) as readonly CleaningTaskStatus[];
