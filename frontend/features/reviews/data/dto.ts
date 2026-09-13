import type { components } from "@/lib/api/generated/openapi";

/**
 * DTOs for the reviews screen (PRD §18, §7.20-7.21). Success shapes only:
 * failures travel as the §23 error envelope, which `lib/api` turns into a thrown
 * `ApiError`. Types only — no runtime code.
 *
 * Two things here are deliberately unlike the rest of the tree, and both are the
 * point (design D2, D3):
 *
 *  - The page envelope is `ReviewsPage`, **not** `PricingPage` and **not** `PaginatedResponse`.
 *    Reviews answers `{items, page, per_page, total}` with no `total_pages`, while
 *    §23's envelope is `{data, …, total_pages}`. A boundary copied from `pricing`
 *    compiles against `data` and fails at runtime; a name lifted from `cleaning`
 *    does the same. The type carries a different name to make the asymmetry
 *    visible where it has to be seen.
 *  - What must not be painted **does not cross the boundary**. No
 *    `classification_attempts`, no `created_at`/`updated_at`, no `reservation_id`,
 *    no `approved_by`/`approved_at` — the corresponding fields in `ReviewDraftResponse`
 *    (`approved_at`, `approved_by`, `created_at`, `edits_count`) are dropped the
 *    same way. R2.5, R6.5 stop being discipline for whoever writes the component
 *    and become unrepresentable.
 */

/**
 * Reviews' page envelope, normalized at the boundary with `totalPages` computed
 * there (design D2). `totalPages` is `0` when `total` is `0`, so «page 1 of 0» is
 * not representable and the view resolves the empty state before paginating (R2.3).
 */
export interface ReviewsPage<T> {
  items: T[];
  total: number;
  page: number;
  perPage: number;
  totalPages: number;
}

/**
 * Alias of the generated union, never a hand-written copy: a sixth status in the
 * backend must break the build here as soon as the contract is regenerated. That
 * guarantee is compile-time only — `lib/review-actions.ts` carries the runtime
 * fallback for the deploy-skew window.
 */
export type ReviewStatus = components["schemas"]["ReviewStatus"];
export type ReviewSentiment = components["schemas"]["ReviewSentiment"];
export type ReviewChannel = components["schemas"]["ReviewChannel"];
export type RecurringIssueTag = components["schemas"]["RecurringIssueTag"];

/**
 * The four actions the operator may send (design D4). Taking this rather than
 * the full union means sending anything else does not compile, and a rename in
 * the backend breaks the build on regeneration instead of producing a `422` at
 * runtime.
 */
export type ReviewAction = Extract<
  components["schemas"]["ReviewResponseActionRequest"]["action"],
  "APPROVE" | "IGNORE" | "MARK_POSTED" | "EDIT"
>;

/**
 * One review row (PRD §7.20).
 *
 * `classification_attempts`, `created_at`, `updated_at` and `reservation_id` are
 * absent on purpose (design D3): the first is a job-internal counter, the second
 * two would be the only timestamps on screen when the DTO publishes no decision
 * instant, and the fourth has no UI consumer (no route to a reservation detail
 * from here). `approved_by`/`approved_at` are also absent — `ReviewResponse` does
 * not publish them.
 *
 * `content` and `aiSummary` cross the boundary because R6.2 paints them, but the
 * mapper leaves `content` as `string | null` literal —prosa del huésped, regla 11
 * exception 4— and `draftContent` as required `string` because the published DTO
 * (`ReviewDraftResponse.draft_content`, `openapi.d.ts:4480`) is non-nullable.
 * The UI paints both as text, never as HTML (R3.8, D11).
 */
export interface Review {
  id: string;
  propertyId: string;
  reviewerName: string | null;
  /** Decimal as a string; converted to a number only to format it (R8.3). */
  rating: string | null;
  content: string | null;
  sentiment: ReviewSentiment | null;
  aiSummary: string | null;
  recurringIssues: RecurringIssueTag[];
  status: ReviewStatus;
  publishedAt: string | null;
  channel: ReviewChannel;
  language: string | null;
}

/**
 * The draft of a review's response (PRD §7.21).
 *
 * `aiGenerated`, `approvedAt`, `approvedBy`, `createdAt`, `editsCount` are absent
 * on purpose (design D3): none is painted. `aiGenerated` is bitácora de origen
 * (R3.5), not state, and the rest are job/audit detail without a UI consumer.
 */
export interface ReviewDraft {
  reviewId: string;
  draftContent: string;
  language: string;
}

/** A property from the tenant's catalog, for the readable identity (R5.3 / R2.8). */
export interface PropertySummary {
  id: string;
  internalCode: string;
  name: string;
}

/** Server-side filters for the review list (R2.1, R5.1); never applied client-side.
 *  `ratingMin`/`ratingMax` are `number` because the backend's `Query(alias=...)`
 *  declares them as such (`openapi.d.ts:10203` `rating_min?: number | null`).
 *  The UI collects them as numbers from the rating selector. */
export interface ReviewFilters {
  propertyId?: string;
  channel?: ReviewChannel;
  sentiment?: ReviewSentiment | null;
  status?: ReviewStatus;
  ratingMin?: number;
  ratingMax?: number;
  dateFrom?: string;
  dateTo?: string;
}

/** Body of `POST /api/v1/reviews` (R5.1). */
export interface CreateReviewInput {
  propertyId: string;
  channel: ReviewChannel;
  reviewerName?: string;
  /** The backend accepts `number | string | null`; the UI always sends a number. */
  rating: number;
  content?: string;
  language?: string;
}

/**
 * Body of `PATCH /api/v1/reviews/{id}/response` discriminated by `action`
 * (design D4). `EDIT` carries `draftContent`; the other three do not.
 */
export type RespondInput =
  | { reviewId: string; action: "APPROVE" }
  | { reviewId: string; action: "IGNORE" }
  | { reviewId: string; action: "MARK_POSTED" }
  | { reviewId: string; action: "EDIT"; draftContent: string };