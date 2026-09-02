# Reviews (`revenue-reviews`)

The reviews capability replaces the work MAGNO used to do on guest reviews:
recording what guests wrote about the property, deciding whether to respond,
drafting the response, and asking the owner to approve it before posting.

**No posting to OTAs.** PRD §18 forbids automatic posting in the MVP — the
manager copies the approved draft into Airbnb/Booking/Google by hand, then
records the result through `PATCH /reviews/{id}/response` with `action =
MARK_POSTED`. The system has no adapter that talks to an OTA about reviews
(`beds24-messaging-adapter` and any future PMS review adapter are separate
changes).

**No UI in this change.** The seven API endpoints land here; the manager-facing
screen is a future change (`[FE]` entry in the roadmap, after `hardening-release`).

## Endpoints

| Method | Path | Permission | Body |
|---|---|---|---|
| `POST` | `/api/v1/reviews` | `CREATE_REVIEW` | `CreateReviewRequest` (R5.1) |
| `GET` | `/api/v1/reviews` | `READ_REVIEWS` | `?page&per_page&property_id&channel&sentiment&status&rating_min&rating_max&date_from&date_to` |
| `GET` | `/api/v1/reviews/{id}` | `READ_REVIEWS` | — |
| `GET` | `/api/v1/reviews/{id}/response` | `READ_REVIEWS` | — (404 if `IGNORED`) |
| `POST` | `/api/v1/reviews/{id}/response` | `APPROVE_REVIEW` | regenerate draft (optional body) |
| `PATCH` | `/api/v1/reviews/{id}/response` | `APPROVE_REVIEW` / `IGNORE_REVIEW` / `MARK_REVIEW_POSTED` | `{"action": "APPROVE"\|"IGNORE"\|"MARK_POSTED"\|"EDIT", "draft_content"?}` |
| `GET` | `/api/v1/properties/{id}/reviews/summary` | `READ_REVIEWS` | `?window_days&top_n` |

`404` is the answer for "no review", "another tenant's review" and "role cannot
read" — the responses are indistinguishable, by design (R1.3).

## The flow, end-to-end

1. The manager creates a review with `POST /reviews`. The row is born `NEW`
   with empty AI fields; the timeline gets `REVIEW_CREATED`.
2. The scheduler ticks `classify_reviews` every 5 minutes. For each pending
   review (`ai_summary IS NULL AND classification_attempts < 3`), the analyser
   returns sentiment, summary and recurring-issue tags, and the draft
   generator emits the response. The timeline gets `REVIEW_RESPONSE_DRAFTED`.
   The review moves to `DRAFTED`.
3. The manager edits the draft through `PATCH /response` with `action =
   EDIT`, which increments `edits_count` and emits `REVIEW_DRAFT_EDITED`.
   Editing is locked after approval (R3.6).
4. The manager approves with `PATCH /response` with `action = APPROVE`. The
   review moves to `APPROVED`, the draft fills `approved_by` and
   `approved_at`, the timeline gets `REVIEW_RESPONSE_APPROVED`, and a
   `NotificationType.REVIEW_RESPONSE_APPROVED` row lands in the inbox of the
   tenant's managers and owner (R6.2).
5. The manager either:
   - posts the response on the OTA by hand, then `PATCH /response` with
     `action = MARK_POSTED`. The review moves to `POSTED_MANUALLY`
     (terminal). Timeline gets `REVIEW_POSTED_MANUALLY`.
   - decides the review is not worth responding to, then `PATCH /response`
     with `action = IGNORE`. The review moves to `IGNORED` (terminal).
     Timeline gets `REVIEW_IGNORED`.

A review in `IGNORED` or `POSTED_MANUALLY` admits no further transitions
(D4). The endpoints answer `409` if the action would be illegal, with the
domain exception mapped through `app/reviews/api/errors.py`.

## Confidence and reclassification

The classifier's confidence is compared against
`TenantConfig.ai_confidence_threshold` (default `0.75`). Below the threshold:

- `sentiment` is set to the verdict
- `ai_summary` is `NULL`
- `recurring_issues` is `()`
- The timeline gets `REVIEW_CLASSIFIED_LOW_CONFIDENCE` instead of
  `REVIEW_RESPONSE_DRAFTED`

The manager triages a low-confidence verdict by editing the draft
(`PATCH .../response` with `action = EDIT`); the AI's verdict stays in
`recurring_issues` and `sentiment` so the audit trail preserves the
adaptor's read.

Three consecutive analyser failures park the row for manual triage
(`classification_attempts = 3`); the next tick of `classify_reviews` no
longer picks it up.

## What the timeline shows

| Event | When | `metadata` |
|---|---|---|
| `REVIEW_CREATED` | `POST /reviews` | `review_id`, `property_id`, `channel` |
| `REVIEW_RESPONSE_DRAFTED` | `classify_reviews` succeeds | `review_id`, `property_id`, `sentiment`, `template_version` |
| `REVIEW_DRAFT_EDITED` | `PATCH .../response` with `action = EDIT` | `review_id`, `property_id`, `edits_count` |
| `REVIEW_CLASSIFIED_LOW_CONFIDENCE` | below threshold | `review_id`, `property_id`, `sentiment`, `confidence` |
| `REVIEW_RESPONSE_APPROVED` | `action = APPROVE` | `review_id`, `property_id` |
| `REVIEW_IGNORED` | `action = IGNORE` | `review_id`, `property_id` |
| `REVIEW_POSTED_MANUALLY` | `action = MARK_POSTED` | `review_id`, `property_id` |

The reviewer's body never appears in `metadata`. It is a rule-11 sink (excepción 4)
of `steering/security.md` and stays in `reviews.content` only.

## The summary endpoint

`GET /properties/{id}/reviews/summary` returns the sentiment histogram and
top-N recurring-issue counts of the property's reviews in the last 90 days
(`window_days` is `1..365`, default `90`). `top_n` defaults to the tenant's
`TenantConfig.review_recurring_issues_top_n` (1..50, default `5`).

## What this change does NOT do

- It does not import reviews from any PMS. The `external_id` column exists
  for when that adapter arrives.
- It does not post to any OTA. The transition to `POSTED_MANUALLY` is a
  record of work a person did, not a call our system made.
- It does not render a UI. The manager-facing screen of PRD §18 is the
  next change.
- It does not write the audit row for the four actions. The R1.7 audit is
  deferred to a follow-up; today the use cases wire `audit_factory=None` and
  the timeline event carries the operator's identity.
