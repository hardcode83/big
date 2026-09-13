<!-- Markers, read by /sdd:run and the lifecycle gates (HTML comments, invisible
     when rendered). On a section heading: "hard" makes that section's
     implementer run on the stronger model; "panel: PASS <date> receipt:<id>"
     is written by the panel gate (reviewer_panel.py) when the section's review
     panel passes — never by hand; "panel: skipped — <reason>" records a
     deliberate skip (scaffolding, docs, config). On a task line:
     "manual" marks a task only a human can perform — run leaves it to you and
     it may travel with the PR as a deferred entry; it may sit on any line of
     the task item, not only the checkbox line. -->

# Tasks: guest-scheduled-comms

## 1. Check-in reminders (24h and 2h)

- [ ] 1.1 Add `render_checkin_reminder_email(language, property_name, check_in_date, check_in_time_local) -> tuple[str, str]` to new `backend/app/reservations/domain/notifications.py`, following `guests/domain/notifications.py`'s `"es"`/`"en"` fallback convention (design D6) — fixed template plus property name and dates only, never guest- or operator-authored text. Unit tests in new `backend/tests/reservations/test_notifications.py` covering both languages and the unknown-language fallback. [R1, R5]
- [ ] 1.2 Add `SendCheckinRemindersUseCase` to `backend/app/reservations/application/use_cases.py`: per-tenant candidate query of `CONFIRMED` reservations bounded to `check_in_date` within ±1 day of `now` (design D4); for each candidate, `properties.domain.clock_triggers.effective_bounds(property, reservation)` + the threshold-crossing check of design D3 (`checkin_instant - lead <= now < checkin_instant`) for both `CHECKIN_REMINDER_24H` (24h lead) and `CHECKIN_REMINDER_2H` (2h lead); resolve the guest's email (skip-and-count the candidate if blank, design D5); `exists_for(tenant_id, related_type="reservation", related_id=reservation.id, notification_type=...)` dedup per type (design D8) before building; write one `PENDING` `NotificationLog` row per due type via `render_checkin_reminder_email`, `channel=EMAIL`, `sla_deadline_at=None` (design D11/D12). Catch `IncompatibleTransitionContextError` per candidate and skip-and-count rather than aborting the tenant's sweep. [R1, R4, R5]
- [ ] 1.3 Unit tests for `SendCheckinRemindersUseCase` with in-memory fakes for its ports (per `backend-architecture.md`'s `application/` testing convention — no real DB, no SQLAlchemy mocks): each window fires exactly once, a second run does not duplicate either type, a reservation with no guest email is skipped and counted, a property with a DST-invalid local time is skipped and counted rather than raising out of the sweep. [R1, R4]
- [ ] 1.4 Register `send_checkin_reminders` in `CADENCES` (`backend/app/scheduler/schedule.py`, `timedelta(minutes=15)`, design D2) and add its `@celery_app.task` in `backend/app/scheduler/tasks.py`, wiring `SendCheckinRemindersUseCase` through the existing `_guarded`/`run_for_every_tenant` shape (design D1) — mirror `check_checkin_windows`'s wiring at `tasks.py:461-467`. [R1]
- [ ] 1.5 In `backend/tests/notifications/test_writer_census.py`: move `CHECKIN_REMINDER_24H` and `CHECKIN_REMINDER_2H` from `WITHOUT_WRITER` to `WITH_WRITER`; add `reservations/domain/notifications.py` and `reservations/application/use_cases.py` to `CONSTRUCTION_SITES` (only if not already present). In `backend/tests/scheduler/test_schedule.py`: register `send_checkin_reminders` in the "every registered task is in exactly one of the three tables" assertion and the "calendar is PRD §8.3 plus exactly the declared additions" assertion. [R1, R5]

## 2. Checkout reminder

- [ ] 2.1 Add `render_checkout_reminder_email(language, property_name, check_out_date, check_out_time_local) -> tuple[str, str]` to `backend/app/reservations/domain/notifications.py` (same file as 1.1). Unit tests alongside 1.1's in `backend/tests/reservations/test_notifications.py`. [R2, R5]
- [ ] 2.2 Add `SendCheckoutRemindersUseCase` to `backend/app/reservations/application/use_cases.py`: same shape as `SendCheckinRemindersUseCase` (1.2) but against `effective_bounds`'s `end` instant and `check_out_date`, a 2h lead time (design D3 — reused from `CHECKIN_REMINDER_2H` rather than inventing a new number), and `notification_type=CHECKOUT_REMINDER`. Same skip-and-count rules for missing email and DST-invalid times. [R2, R4, R5]
- [ ] 2.3 Unit tests for `SendCheckoutRemindersUseCase`, same coverage shape as 1.3 (fires once, dedup on repeat run, missing-email skip, DST-invalid skip). [R2, R4]
- [ ] 2.4 Register `send_checkout_reminders` in `CADENCES` (15 min) and its `@celery_app.task`, same wiring shape as 1.4. [R2]
- [ ] 2.5 In `test_writer_census.py`: move `CHECKOUT_REMINDER` from `WITHOUT_WRITER` to `WITH_WRITER` (the module is already in `CONSTRUCTION_SITES` from 1.5). In `test_schedule.py`: register `send_checkout_reminders` in both assertions from 1.5. [R2, R5]

## 3. Automatic access-instructions delivery

- [ ] 3.1 Add `ACCESS_INSTRUCTIONS_SENT = "ACCESS_INSTRUCTIONS_SENT"` to `NotificationType` in `backend/app/notifications/domain/enums.py`, commented as a declared divergence from PRD §14's sixteen (design D10), the same way `GUEST_PORTAL_LINK_DELIVERED`/`PASSWORD_RESET_REQUESTED` are already commented. [R3, R5]
- [ ] 3.2 Add `render_access_instructions_email(language, code_masked) -> tuple[str, str]` to new `backend/app/access/domain/notifications.py` — fixed template plus `code_masked` only (rule 11 exception 1), never `access_records.notes` or any other free text. Unit tests in new `backend/tests/access/test_notifications.py` covering both languages, the fallback, and that only the masked form appears in the rendered output. [R3, R5]
- [ ] 3.3 Add `DeliverAccessInstructionsUseCase` to `backend/app/access/application/use_cases.py`: per-tenant candidate query over `AccessRecord`s with `status` in `{MANUAL_ADDED, CREATED_EXTERNAL}` and a non-null `code_masked`; resolve the linked reservation's guest email (skip-and-count if blank, design D5); `exists_for(tenant_id, related_type="access_record", related_id=record.id, notification_type=ACCESS_INSTRUCTIONS_SENT)` dedup (design D8); write one `PENDING` row via `render_access_instructions_email`, `channel=EMAIL`, `sla_deadline_at=None`; MUST NOT call `mark_delivered` or otherwise mutate `AccessRecord.status` (design D9, proposal R3.4 — this stays the operator's own independent confirmation). [R3, R4, R5]
- [ ] 3.4 Unit tests for `DeliverAccessInstructionsUseCase`: fires exactly once per record, a second run does not duplicate, missing-email skip, and an explicit assertion that `AccessRecord.status`/`mark_delivered` is untouched by this use case. [R3, R4]
- [ ] 3.5 Register `deliver_access_instructions` in `CADENCES` (15 min, design D9) and its `@celery_app.task`, wiring `DeliverAccessInstructionsUseCase` through the same `_guarded` shape — mirror `provision_access_records`'s wiring at `tasks.py:666-684`. [R3]
- [ ] 3.6 In `test_writer_census.py`: add `ACCESS_INSTRUCTIONS_SENT` to `WITH_WRITER`; add `access/domain/notifications.py` and `access/application/use_cases.py` to `CONSTRUCTION_SITES`; update `test_exactly_four_types_have_no_writer` (retitle if needed) so `WITHOUT_WRITER` now asserts exactly `{"LOCK_ALERT"}`, since all three reminder types moved out in sections 1-2. In `test_schedule.py`: register `deliver_access_instructions` in both assertions. [R3, R5]

## 4. Verification

- [ ] 4.1 Full backend test suite passes: `docker compose exec backend uv run pytest` (or `docker compose run --rm backend uv run pytest` with the stack down).
- [ ] 4.2 Static tooling passes: from `backend`, `uv sync --frozen` then `uv run pyright .`.
- [ ] 4.3 `make check-rule11-ownership` passes (host, `python3`, no Docker, no stack) — this change is the first living writer of rule 11's exception 1 and touches backend docstrings that reference it.
- [ ] 4.4 Manual: with the dev stack up and seed/demo data giving a reservation inside each of the 24h/2h/checkout windows and an `AccessRecord` with a masked code, trigger each of the three new Celery tasks (or wait a tick) and confirm a real email arrives via the dev SMTP relay, each `NotificationLog` row lands `SENT` with the expected template/language and, for the access-instructions email, the masked code and nothing else; confirm a second tick does not send any of them twice. <!-- manual -->

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->
