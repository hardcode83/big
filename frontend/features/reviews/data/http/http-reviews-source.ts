import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type {
  CreateReviewInput,
  PropertySummary,
  RespondInput,
  Review,
  ReviewDraft,
  ReviewFilters,
  ReviewsPage,
} from "../dto";
import type { ReviewsDataSource } from "../reviews-source";

type ReviewPageResponse = components["schemas"]["ReviewPageResponse"];
type ReviewResponse = components["schemas"]["ReviewResponse"];
type ReviewDraftResponse = components["schemas"]["ReviewDraftResponse"];
type PropertyPageResponse = components["schemas"]["PropertyPageResponse"];
type PropertyListItemResponse =
  components["schemas"]["PropertyListItemResponse"];

/** One page per request in both tabs; `page` is what the pagination control moves. */
const ITEMS_PER_PAGE = 20;

/**
 * ASSUMPTION (design D5): the property catalog is fetched as a single page of
 * 100, which is the backend's `MAX_PER_PAGE`, exactly as `http-pricing-source.ts`
 * does. A tenant with more than 100 properties will see "identity unavailable"
 * (R2.8) from the hundredth onwards. That is the degradation R2.8 specifies
 * rather than a silent failure, and it is harmless at MVP scale (two flats) —
 * but it stops being correct as coverage and has to be redone before the SaaS
 * phase.
 */
const CATALOG_PER_PAGE = 100;

/**
 * Reviews' page envelope is `{items, page, per_page, total}` and carries **no
 * `total_pages`** — unlike the §23 `{data, …, total_pages}` of `cleaning`,
 * `properties` and `reservations`. Both halves of that asymmetry are handled
 * here, once, so no view repeats them (design D2).
 *
 * `perPage <= 0` yields `0` rather than a division by zero, and `total === 0`
 * yields `0` too — which is what makes «page 1 of 0» unrepresentable and lets the
 * view resolve the empty state first (R2.3).
 */
function mapPage<T, U>(
  page: { items: T[]; total: number; page: number; per_page: number },
  mapItem: (item: T) => U,
): ReviewsPage<U> {
  return {
    items: page.items.map(mapItem),
    total: page.total,
    page: page.page,
    perPage: page.per_page,
    totalPages: page.per_page > 0 ? Math.ceil(page.total / page.per_page) : 0,
  };
}

function mapReview(value: ReviewResponse): Review {
  // `classification_attempts`, `created_at`, `updated_at` and `reservation_id`
  // are deliberately not read (design D3): what is not mapped cannot be painted
  // (R2.5, R6.5). `approved_by`/`approved_at` are also absent — `ReviewResponse`
  // does not publish them.
  return {
    id: value.id,
    propertyId: value.property_id,
    reviewerName: value.reviewer_name,
    rating: value.rating,
    content: value.content,
    sentiment: value.sentiment,
    aiSummary: value.ai_summary,
    recurringIssues: value.recurring_issues,
    status: value.status,
    publishedAt: value.published_at,
    channel: value.channel,
    language: value.language,
  };
}

function mapDraft(value: ReviewDraftResponse): ReviewDraft {
  // `ai_generated`, `approved_at`, `approved_by`, `created_at`, `edits_count`
  // are deliberately not read (design D3): none is painted in this UI. The
  // mapper leaves `draftContent` as required `string` because the DTO
  // (`openapi.d.ts:4480`) declares it that way.
  return {
    reviewId: value.review_id,
    draftContent: value.draft_content,
    language: value.language,
  };
}

function mapProperty(value: PropertyListItemResponse): PropertySummary {
  return {
    id: value.id,
    name: value.name,
    internalCode: value.internal_code,
  };
}

export class HttpReviewsSource implements ReviewsDataSource {
  constructor(private readonly client: ApiClient) {}

  async listReviews(
    _tenantId: string,
    filters: ReviewFilters,
    page: number,
  ): Promise<ReviewsPage<Review>> {
    const response: ReviewPageResponse = await this.client.request<
      "/api/v1/reviews",
      "GET"
    >("/api/v1/reviews", {
      query: {
        page,
        per_page: ITEMS_PER_PAGE,
        // Only the filters actually chosen travel; the backend ANDs them and
        // nothing is ever filtered client-side (R2.1, R5.1). All filter names
        // match the Python query parameters exactly (snake_case on the wire).
        ...(filters.propertyId !== undefined
          ? { property_id: filters.propertyId }
          : {}),
        ...(filters.channel !== undefined ? { channel: filters.channel } : {}),
        ...(filters.sentiment !== undefined
          ? { sentiment: filters.sentiment }
          : {}),
        ...(filters.status !== undefined ? { status: filters.status } : {}),
        ...(filters.ratingMin !== undefined
          ? { rating_min: filters.ratingMin }
          : {}),
        ...(filters.ratingMax !== undefined
          ? { rating_max: filters.ratingMax }
          : {}),
        ...(filters.dateFrom !== undefined
          ? { date_from: filters.dateFrom }
          : {}),
        ...(filters.dateTo !== undefined ? { date_to: filters.dateTo } : {}),
      },
    });
    return mapPage(response, mapReview);
  }

  async getReview(
    _tenantId: string,
    reviewId: string,
  ): Promise<Review> {
    const response: ReviewResponse = await this.client.request(
      "/api/v1/reviews/{review_id}",
      {
        method: "GET",
        pathParams: { review_id: reviewId },
      },
    );
    return mapReview(response);
  }

  async getDraft(
    _tenantId: string,
    reviewId: string,
  ): Promise<ReviewDraft> {
    const response: ReviewDraftResponse = await this.client.request(
      "/api/v1/reviews/{review_id}/response",
      {
        method: "GET",
        pathParams: { review_id: reviewId },
      },
    );
    return mapDraft(response);
  }

  async createReview(
    _tenantId: string,
    input: CreateReviewInput,
  ): Promise<Review> {
    // The backend's `CreateReviewRequest` declares `rating?: number | string | null`
    // — the UI always sends a number, the contract accepts either, and the
    // schema accepts nullable on `content`/`language`. We only send the keys the
    // UI actually has values for, and let the rest default on the server.
    const response: ReviewResponse = await this.client.request(
      "/api/v1/reviews",
      {
        method: "POST",
        body: {
          property_id: input.propertyId,
          channel: input.channel,
          rating: input.rating,
          ...(input.reviewerName !== undefined
            ? { reviewer_name: input.reviewerName }
            : {}),
          ...(input.content !== undefined ? { content: input.content } : {}),
          ...(input.language !== undefined ? { language: input.language } : {}),
        },
      },
    );
    return mapReview(response);
  }

  async respondToReview(
    _tenantId: string,
    input: RespondInput,
  ): Promise<Review> {
    // Discriminated by `action` (design D4): the body shape is exactly what the
    // wire contract publishes — `{action}` for the three terminal moves and
    // `{action, draft_content}` for `EDIT`. `extra="forbid"` on the backend
    // catches any extra field as a `422`.
    const body =
      input.action === "EDIT"
        ? { action: input.action, draft_content: input.draftContent }
        : { action: input.action };
    const response: ReviewResponse = await this.client.request(
      "/api/v1/reviews/{review_id}/response",
      {
        method: "PATCH",
        pathParams: { review_id: input.reviewId },
        body,
      },
    );
    return mapReview(response);
  }

  async listProperties(_tenantId: string): Promise<PropertySummary[]> {
    const response: PropertyPageResponse = await this.client.request<
      "/api/v1/properties",
      "GET"
    >("/api/v1/properties", {
      query: { page: 1, per_page: CATALOG_PER_PAGE },
    });
    // `/api/v1/properties` is a §23 envelope and answers `data`, not `items`:
    // the two shapes live side by side in this file on purpose.
    return response.data.map(mapProperty);
  }
}