import { describe, expect, it } from "vitest";

import type { ApiClient } from "@/lib/api";

import { HttpReviewsSource } from "./http-reviews-source";

/**
 * The boundary mapper is what makes a copy/paste from another feature safe or
 * catastrophic: pricing's page envelope is `{items, total, page, per_page}` with
 * no `total_pages`, §23's envelope is `{data, …, total_pages}`. A boundary lifted
 * from `cleaning` compiles against `data` and fails at runtime; a copy from
 * `pricing` compiles against `items` but breaks on `total_pages`. The mapper
 * fixes both halves (design D2), so this test pins them.
 *
 * The other tests here pin what D3 declares must not cross the boundary:
 * `classification_attempts`, `created_at`, `updated_at`, `reservation_id`,
 * `approved_by`, `approved_at`, and the analogous fields on the draft DTO
 * (`ai_generated`, `created_at`, `edits_count`).
 */

function makeClient(respond: (req: unknown) => unknown): ApiClient {
  return {
    request: async <P extends string>(...args: unknown[]) => {
      // The shape of `request` is complex; we only need a stub that returns
      // whatever the test queues. The real `ApiClient` is exercised in the
      // integration tests; here we pin the mapper.
      void args;
      void (null as unknown as P);
      return respond(args);
    },
  } as unknown as ApiClient;
}

describe("HttpReviewsSource.listReviews", () => {
  it("maps the {items, page, per_page, total} envelope into ReviewsPage<T>", async () => {
    const client = makeClient(() => ({
      items: [
        {
          id: "r1",
          property_id: "p1",
          reviewer_name: "Alice",
          rating: "4.5",
          content: "Loved it",
          sentiment: "POSITIVE",
          ai_summary: "Great",
          recurring_issues: ["WIFI"],
          status: "DRAFTED",
          published_at: "2026-09-01",
          channel: "AIRBNB",
          language: "en",
          classification_attempts: 0,
          created_at: "2026-09-01",
          updated_at: "2026-09-02",
          reservation_id: "res1",
          approved_by: null,
          approved_at: null,
        },
      ],
      page: 1,
      per_page: 20,
      total: 1,
    }));
    const source = new HttpReviewsSource(client);
    const page = await source.listReviews("t1", {}, 1);
    expect(page.items).toHaveLength(1);
    expect(page.items[0]).toEqual({
      id: "r1",
      propertyId: "p1",
      reviewerName: "Alice",
      rating: "4.5",
      content: "Loved it",
      sentiment: "POSITIVE",
      aiSummary: "Great",
      recurringIssues: ["WIFI"],
      status: "DRAFTED",
      publishedAt: "2026-09-01",
      channel: "AIRBNB",
      language: "en",
    });
    // What D3 forbids does not cross.
    expect(page.items[0]).not.toHaveProperty("classificationAttempts");
    expect(page.items[0]).not.toHaveProperty("createdAt");
    expect(page.items[0]).not.toHaveProperty("updatedAt");
    expect(page.items[0]).not.toHaveProperty("reservationId");
    expect(page.items[0]).not.toHaveProperty("approvedBy");
    expect(page.items[0]).not.toHaveProperty("approvedAt");
  });

  it("computes totalPages = 0 when total is 0", async () => {
    const client = makeClient(() => ({
      items: [],
      page: 1,
      per_page: 20,
      total: 0,
    }));
    const source = new HttpReviewsSource(client);
    const page = await source.listReviews("t1", {}, 1);
    expect(page.totalPages).toBe(0);
  });

  it("computes totalPages = 0 when per_page is 0 (no division by zero)", async () => {
    const client = makeClient(() => ({
      items: [],
      page: 1,
      per_page: 0,
      total: 0,
    }));
    const source = new HttpReviewsSource(client);
    const page = await source.listReviews("t1", {}, 1);
    expect(page.totalPages).toBe(0);
  });

  it("computes totalPages = ceil(total/per_page) on the happy path", async () => {
    const client = makeClient(() => ({
      items: [],
      page: 2,
      per_page: 20,
      total: 41,
    }));
    const source = new HttpReviewsSource(client);
    const page = await source.listReviews("t1", {}, 2);
    expect(page.totalPages).toBe(3);
  });
});

describe("HttpReviewsSource.getDraft", () => {
  it("maps only review_id, draft_content and language (D3)", async () => {
    const client = makeClient(() => ({
      review_id: "r1",
      draft_content: "Thank you!",
      language: "en",
      ai_generated: true,
      approved_by: "u1",
      approved_at: "2026-09-02",
      created_at: "2026-09-01",
      edits_count: 1,
      id: "d1",
      updated_at: "2026-09-02",
    }));
    const source = new HttpReviewsSource(client);
    const draft = await source.getDraft("t1", "r1");
    expect(draft).toEqual({
      reviewId: "r1",
      draftContent: "Thank you!",
      language: "en",
    });
  });
});

describe("HttpReviewsSource.respondToReview", () => {
  it("sends {action: APPROVE} without draft_content", async () => {
    let captured: unknown = null;
    const client = makeClient((req) => {
      captured = (req as unknown[])[1];
      return {
        id: "r1",
        property_id: "p1",
        reviewer_name: null,
        rating: null,
        content: null,
        sentiment: null,
        ai_summary: null,
        recurring_issues: [],
        status: "APPROVED",
        published_at: null,
        channel: "AIRBNB",
        language: null,
      };
    });
    const source = new HttpReviewsSource(client);
    await source.respondToReview("t1", { reviewId: "r1", action: "APPROVE" });
    expect(captured).toMatchObject({
      method: "PATCH",
      pathParams: { review_id: "r1" },
      body: { action: "APPROVE" },
    });
    expect((captured as { body: Record<string, unknown> }).body).not.toHaveProperty(
      "draft_content",
    );
  });

  it("sends {action: EDIT, draft_content} for the edit case", async () => {
    let captured: unknown = null;
    const client = makeClient((req) => {
      captured = (req as unknown[])[1];
      return {
        id: "r1",
        property_id: "p1",
        reviewer_name: null,
        rating: null,
        content: null,
        sentiment: null,
        ai_summary: null,
        recurring_issues: [],
        status: "DRAFTED",
        published_at: null,
        channel: "AIRBNB",
        language: null,
      };
    });
    const source = new HttpReviewsSource(client);
    await source.respondToReview("t1", {
      reviewId: "r1",
      action: "EDIT",
      draftContent: "Custom reply",
    });
    expect(captured).toMatchObject({
      method: "PATCH",
      pathParams: { review_id: "r1" },
      body: { action: "EDIT", draft_content: "Custom reply" },
    });
  });

  it("sends {action: MARK_POSTED} without draft_content", async () => {
    let captured: unknown = null;
    const client = makeClient((req) => {
      captured = (req as unknown[])[1];
      return {
        id: "r1",
        property_id: "p1",
        reviewer_name: null,
        rating: null,
        content: null,
        sentiment: null,
        ai_summary: null,
        recurring_issues: [],
        status: "POSTED_MANUALLY",
        published_at: null,
        channel: "AIRBNB",
        language: null,
      };
    });
    const source = new HttpReviewsSource(client);
    await source.respondToReview("t1", {
      reviewId: "r1",
      action: "MARK_POSTED",
    });
    expect((captured as { body: Record<string, unknown> }).body).toEqual({
      action: "MARK_POSTED",
    });
  });
});

describe("HttpReviewsSource.createReview", () => {
  it("sends snake_case field names (property_id, reviewer_name)", async () => {
    let captured: unknown = null;
    const client = makeClient((req) => {
      captured = (req as unknown[])[1];
      return {
        id: "r1",
        property_id: "p1",
        reviewer_name: "Alice",
        rating: "4.5",
        content: "Great",
        sentiment: null,
        ai_summary: null,
        recurring_issues: [],
        status: "NEW",
        published_at: null,
        channel: "AIRBNB",
        language: null,
      };
    });
    const source = new HttpReviewsSource(client);
    await source.createReview("t1", {
      propertyId: "p1",
      channel: "AIRBNB",
      reviewerName: "Alice",
      rating: 4.5,
      content: "Great",
    });
    expect(captured).toMatchObject({
      method: "POST",
      body: {
        property_id: "p1",
        channel: "AIRBNB",
        reviewer_name: "Alice",
        rating: 4.5,
        content: "Great",
      },
    });
  });

  it("omits optional fields when not provided", async () => {
    let captured: unknown = null;
    const client = makeClient((req) => {
      captured = (req as unknown[])[1];
      return {
        id: "r1",
        property_id: "p1",
        reviewer_name: null,
        rating: "4.0",
        content: null,
        sentiment: null,
        ai_summary: null,
        recurring_issues: [],
        status: "NEW",
        published_at: null,
        channel: "BOOKING",
        language: null,
      };
    });
    const source = new HttpReviewsSource(client);
    await source.createReview("t1", {
      propertyId: "p1",
      channel: "BOOKING",
      rating: 4,
    });
    const body = (captured as { body: Record<string, unknown> }).body;
    expect(body).toEqual({
      property_id: "p1",
      channel: "BOOKING",
      rating: 4,
    });
    expect(body).not.toHaveProperty("reviewer_name");
    expect(body).not.toHaveProperty("content");
    expect(body).not.toHaveProperty("language");
  });
});