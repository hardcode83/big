/**
 * Mapping of `trigger × blocking_state → ActionKind | null`
 * (proposal `blocked-transitions-web` D3, R2.2, R2.3).
 *
 * The matrix is the single declaration of "what action a row can offer". It
 * lives here so:
 *
 *   - the closed `ClockTrigger` union below is the only place those literals
 *     are transcribed in the feature — a backend change that adds a fourth
 *     trigger must show up in the union, and the compile-time guard turns
 *     the omission into a typecheck error;
 *
 *   - the component renders an action button only when this map says the
 *     row has one — proposal R1.5 forbids the `if (state === …)` style
 *     that a per-row guard would invite;
 *
 *   - the permission that runs each action (`MANAGE_CLEANING_TASKS` /
 *     `EXECUTE_INCIDENTS`) is enforced at the call site (the row component),
 *     not here — this map knows nothing about roles, by design: the
 *     permission is the card's concern, the action kind is the data's.
 *
 * The runtime default is `null` (informative without action), so the
 * `Record<…, Record<…, ActionKind | null>>` type admits the few non-`null`
 * cells explicitly and lets everything else fall back at the call site.
 */

import type { PropertyOperationalState } from "@/components/property-state-badge";

/** The three clock triggers the calendar emits (PRD §8). */
export type ClockTrigger =
  | "CHECKIN_WINDOW_OPENED"
  | "CHECKIN_TIME_REACHED"
  | "CHECKOUT_TIME_REACHED";

/** The two action kinds the card can offer on a blocked-transition row. */
export type ActionKind = "cancel-cleaning" | "resolve-incident";

/**
 * The action matrix. Each cell is either the action the row offers or `null`
 * (informative without action). The two active cells match design D3's
 * "exactly two":
 *
 *   - `cancel-cleaning` when the clock says "the guest is here, but the
 *     cleaning hasn't moved" — so a trigger in
 *     {CHECKIN_WINDOW_OPENED, CHECKIN_TIME_REACHED} and a blocking state in
 *     {AWAITING_CLEANING, CLEANING_IN_PROGRESS, CLEANING_SCHEDULED};
 *
 *   - `resolve-incident` when the clock says "the guest is here, but the
 *     property is not in a state that admits them" — so any trigger and a
 *     blocking state in {MAINTENANCE_REQUIRED, CRITICAL_INCIDENT}.
 *
 * Cells that are absent from the table resolve to `null` at the call site:
 * adding a state to the matrix that has no action is meaningless, and the
 * matrix only enumerates the cells that do.
 */
const ACTION_MATRIX = {
  CHECKIN_WINDOW_OPENED: {
    AWAITING_CLEANING: "cancel-cleaning",
    CLEANING_IN_PROGRESS: "cancel-cleaning",
    CLEANING_SCHEDULED: "cancel-cleaning",
    MAINTENANCE_REQUIRED: "resolve-incident",
    CRITICAL_INCIDENT: "resolve-incident",
  },
  CHECKIN_TIME_REACHED: {
    AWAITING_CLEANING: "cancel-cleaning",
    CLEANING_IN_PROGRESS: "cancel-cleaning",
    CLEANING_SCHEDULED: "cancel-cleaning",
    MAINTENANCE_REQUIRED: "resolve-incident",
    CRITICAL_INCIDENT: "resolve-incident",
  },
  CHECKOUT_TIME_REACHED: {
    MAINTENANCE_REQUIRED: "resolve-incident",
    CRITICAL_INCIDENT: "resolve-incident",
  },
} as const satisfies Record<
  ClockTrigger,
  Partial<Record<PropertyOperationalState, ActionKind>>
>;

/**
 * Compile-time guard: every `ClockTrigger` must have a column in the matrix.
 * Adding a fourth trigger without an entry is a typecheck error, just like
 * the exhaustiveness guard on `TIMELINE_EVENT_TYPES`
 * (`dashboard-web-frontend.md` §Timeline).
 *
 * States, by contrast, are not exhaustively required — `null` is a valid
 * answer for "this state does not admit any action from this trigger", and
 * that is exactly what the absent cells mean.
 */
type _TriggerColumns = Exclude<ClockTrigger, keyof typeof ACTION_MATRIX>;
type _TriggerColumnsAreNever = [
  _TriggerColumns,
] extends [never]
  ? true
  : "ERROR: a ClockTrigger is missing from ACTION_MATRIX";
const _triggerCoverage: _TriggerColumnsAreNever = true;

/**
 * Resolves a row to its action kind, or `null` when no action fits.
 *
 * The runtime default is `null` (any cell not enumerated above), so a new
 * `trigger`/`blocking_state` combination shows as informative without ever
 * offering a button that the matrix did not authorise. R1.5 names the
 * per-cell test; this function is the one place that interprets the table.
 */
export function actionMapFor(
  trigger: string,
  blockingState: string,
): ActionKind | null {
  const triggerColumn = (
    ACTION_MATRIX as Record<string, Record<string, ActionKind>>
  )[trigger];
  if (!triggerColumn) {
    return null;
  }
  return triggerColumn[blockingState] ?? null;
}