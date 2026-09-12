import type {
  CreateReviewInput,
  PropertySummary,
  RespondInput,
  Review,
  ReviewDraft,
  ReviewFilters,
  ReviewsPage,
} from "./dto";

/**
 * The reviews screen's data-access boundary. Components and hooks depend ONLY on
 * this interface, never on a concrete implementation, which is what lets the
 * component tests inject a double without touching `lib/api`. The single runtime
 * implementation is `HttpReviewsSource`; there is no mock source, because the
 * backend has existed since the `revenue-reviews` change and there is nothing to
 * stand in for (design D1).
 *
 * `tenantId` is explicit at the boundary so the tenant-scoped query keys stay
 * honest; it comes from the session context. The backend remains the authority
 * for tenant isolation.
 *
 * **There is no `listSummary` method**, and that is the enforcement of the
 * «/reviews summary endpoint is dashboard-only» decision in the proposal:
 * `GET /properties/{id}/reviews/summary` is consumed by the dashboard
 * `dashboard-activity-feed` change, not here. **There is no `regenerateDraft`
 * method** either, also out of scope for this UI: the regeneration runs on the
 * 5-minute Celery cycle, and the user waits.
 *
 * Every method rejects with `ApiError` (`lib/api`) on failure — including the §23
 * `403`/`404`/`409`/`422` envelopes that `respondToReview` and `createReview` can
 * produce.
 */
export interface ReviewsDataSource {
  /** One page of the tenant's reviews, filtered server-side (R2.1, R5.1). */
  listReviews(
    tenantId: string,
    filters: ReviewFilters,
    page: number,
  ): Promise<ReviewsPage<Review>>;

  /** One review, by id (R6.1). */
  getReview(tenantId: string, reviewId: string): Promise<Review>;

  /** The draft of one review's response (R6.1). `404` if `IGNORED`. */
  getDraft(tenantId: string, reviewId: string): Promise<ReviewDraft>;

  /** Manual create from the dialog (R5.3). */
  createReview(
    tenantId: string,
    input: CreateReviewInput,
  ): Promise<Review>;

  /** One of the four legal moves (R3.1, R3.2, R3.3, R4.3). */
  respondToReview(tenantId: string, input: RespondInput): Promise<Review>;

  /** The tenant's property catalog, for R2.8 / R5.3 readable identity. */
  listProperties(tenantId: string): Promise<PropertySummary[]>;
}