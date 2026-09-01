/**
 * DTOs for the dashboard card's blocked-transitions section
 * (proposal `blocked-transitions-web` R1.2).
 *
 * `BlockedTransitionSummary` mirrors the backend's
 * `BlockedTransitionResponse` field-by-field (`openapi.d.ts:970`). Six fields
 * today, six fields tomorrow: the alias is set up so that when the backend
 * extends it with `cleaning_task_id`/`incident_id` (design OQ1) the page
 * consumes the new shape automatically, and the field-by-field equality is
 * preserved because the alias re-exports the generated type verbatim.
 *
 * Fields not present in the response are **not** synthesized — the proposal R4.3
 * explicitly forbids a parallel catalogue: `trigger` and `blocking_state` are
 * the canonical literals the backend emits, and the page renders them as such.
 * `cleaning-stall-blocks-next-stay` R2.2 documents why.
 */

import type { components } from "@/lib/api/generated/openapi";

import type { PaginatedResponse } from "../../data/dto";

/**
 * One blocked transition as exposed by the dashboard card (proposal R1.2).
 *
 * The alias exists so the page depends on a *named* type — a future change that
 * enriches the response will still satisfy every consumer that typed against
 * `BlockedTransitionSummary`, because both names point at the same generated
 * type.
 */
export type BlockedTransitionSummary =
  components["schemas"]["BlockedTransitionResponse"];

/**
 * The §23 pagination envelope over `BlockedTransitionSummary`. Re-imported from
 * the parent feature so this feature does not invent a parallel shape — the
 * proposal is explicit that the page rides on the same envelope the rest of the
 * dashboard already uses (design D1).
 */
export type BlockedTransitionPage = PaginatedResponse<BlockedTransitionSummary>;