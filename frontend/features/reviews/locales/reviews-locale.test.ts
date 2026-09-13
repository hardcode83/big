/**
 * Locale contract tests for the `reviews` i18n namespace (proposal R8.2).
 *
 * Why this file exists, and why it is not redundant with
 * `lib/i18n/catalog-parity.test.ts`: that test compares the *key sets* of the
 * ES and EN catalogs for every registered namespace, so it catches a key
 * present in one language and missing in the other. It does **not** check that
 * there is a key per enum value — an enum with twelve values and eleven labels
 * passes it, in both languages at once. This file closes that gap, taking
 * the enum values from the generated OpenAPI types rather than transcribing
 * them, exactly as `properties-locale.test.ts` does.
 *
 * What this file pins:
 *
 *  - All five `ReviewStatus` values have labels in ES and EN — including
 *    `NEW` (R8.2: «incluido NEW, que nadie produce»), so a deploy skew that
 *    ships `NEW` to a user does not get a raw enum label.
 *  - All three `ReviewSentiment` values.
 *  - All five `ReviewChannel` values (R8.2: «los cinco miembros del enum
 *    `ReviewChannel`»). A hand-written four-member fixture would let a
 *    missing fifth member pass silently.
 *  - All nine `RecurringIssueTag` values.
 *  - All four `respond.confirmQuestion.*` copies — APPROVE, IGNORE,
 *    MARK_POSTED, EDIT — so the in-line confirmation question is a real
 *    localized string for every action (D5).
 */

import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/generated/openapi";
import enReviews from "@/locales/en/reviews.json";
import esReviews from "@/locales/es/reviews.json";

type ReviewStatus = components["schemas"]["ReviewStatus"];
type ReviewSentiment = components["schemas"]["ReviewSentiment"];
type ReviewChannel = components["schemas"]["ReviewChannel"];
type RecurringIssueTag = components["schemas"]["RecurringIssueTag"];
type ReviewAction = components["schemas"]["ReviewResponseActionRequest"]["action"];

const STATUS_VALUES: readonly ReviewStatus[] = [
  "NEW",
  "DRAFTED",
  "APPROVED",
  "POSTED_MANUALLY",
  "IGNORED",
] as const;

const SENTIMENT_VALUES: readonly ReviewSentiment[] = [
  "POSITIVE",
  "NEUTRAL",
  "NEGATIVE",
] as const;

const CHANNEL_VALUES: readonly ReviewChannel[] = [
  "AIRBNB",
  "BOOKING",
  "GOOGLE",
  "MANUAL",
  "OTHER",
] as const;

const RECURRING_VALUES: readonly RecurringIssueTag[] = [
  "WIFI",
  "NOISE",
  "CLEANLINESS",
  "ACCESS",
  "COMMUNICATION",
  "LOCATION",
  "VALUE",
  "AMENITIES",
  "OTHER",
] as const;

const CONFIRM_QUESTION_ACTIONS: readonly Exclude<
  ReviewAction,
  "MARK_POSTED"
>[] = ["APPROVE", "IGNORE", "EDIT"] as const;

describe("reviews locale — ReviewStatus (R8.2)", () => {
  it("localizes all five status values in ES and EN", () => {
    for (const status of STATUS_VALUES) {
      expect(
        esReviews.status[status],
        `ES missing label for status ${status}`,
      ).toBeTypeOf("string");
      expect(
        enReviews.status[status],
        `EN missing label for status ${status}`,
      ).toBeTypeOf("string");
    }
  });

  it("has no label for a status the contract does not declare", () => {
    expect(Object.keys(esReviews.status).sort()).toEqual(
      [...STATUS_VALUES].sort(),
    );
    expect(Object.keys(enReviews.status).sort()).toEqual(
      [...STATUS_VALUES].sort(),
    );
  });
});

describe("reviews locale — ReviewSentiment (R8.2)", () => {
  it("localizes all three sentiments in ES and EN", () => {
    for (const sentiment of SENTIMENT_VALUES) {
      expect(
        esReviews.sentiment[sentiment],
        `ES missing label for sentiment ${sentiment}`,
      ).toBeTypeOf("string");
      expect(
        enReviews.sentiment[sentiment],
        `EN missing label for sentiment ${sentiment}`,
      ).toBeTypeOf("string");
    }
  });
});

describe("reviews locale — ReviewChannel (R8.2)", () => {
  it("localizes all five channels in ES and EN", () => {
    for (const channel of CHANNEL_VALUES) {
      expect(
        esReviews.channel[channel],
        `ES missing label for channel ${channel}`,
      ).toBeTypeOf("string");
      expect(
        enReviews.channel[channel],
        `EN missing label for channel ${channel}`,
      ).toBeTypeOf("string");
    }
  });

  it("has exactly five channels", () => {
    // Guards the test above against a hand-written fixture being trimmed. A
    // removed enum value fails at compile time on the backend side, not here;
    // a removed label here fails this test and points at the omission.
    expect(Object.keys(esReviews.channel)).toHaveLength(5);
    expect(Object.keys(enReviews.channel)).toHaveLength(5);
  });
});

describe("reviews locale — RecurringIssueTag (R8.2)", () => {
  it("localizes all nine tags in ES and EN", () => {
    for (const tag of RECURRING_VALUES) {
      expect(
        esReviews.recurringIssue[tag],
        `ES missing label for recurringIssue ${tag}`,
      ).toBeTypeOf("string");
      expect(
        enReviews.recurringIssue[tag],
        `EN missing label for recurringIssue ${tag}`,
      ).toBeTypeOf("string");
    }
  });
});

describe("reviews locale — respond.confirmQuestion (D5, R3.3)", () => {
  it("has a confirmation question for every legal action (APPROVE/IGNORE/EDIT)", () => {
    for (const action of CONFIRM_QUESTION_ACTIONS) {
      expect(
        esReviews.respond.confirmQuestion[action],
        `ES missing confirmQuestion for action ${action}`,
      ).toBeTypeOf("string");
      expect(
        enReviews.respond.confirmQuestion[action],
        `EN missing confirmQuestion for action ${action}`,
      ).toBeTypeOf("string");
    }
  });
});