# Design: guest-scheduled-comms

## Context

Four independent gaps close together here, and all four are pure additions — no existing behaviour
changes shape:

- `backend/app/scheduler/schedule.py` declares `CADENCES`/`DAILY_JOBS`/`MONTHLY_JOBS` as the single
  source for Celery beat (`schedule.py:46-146`), each entry backed by a task in
  `backend/app/scheduler/tasks.py` built from `_guarded(name, cadence, work)` +
  `run_for_every_tenant` (`tasks.py:387-420`, `scheduler/runner.py:169-191`), which opens one
  tenant-marked session per active tenant and rolls back per-tenant failures without stopping the
  batch. `check_checkin_windows`/`process_checkouts` (`tasks.py:461-489`) are the closest siblings:
  same per-reservation, per-property-timezone shape, different `PropertyStateTrigger`.
- `properties/domain/clock_triggers.py:60-69` already exposes `effective_bounds(property,
  reservation) -> (start, end)`, converting `Property.timezone` + `check_in_date`/`check_in_time`
  (defaulting to `Property.default_check_in_time`) into real UTC-aware instants, DST-safe
  (`properties/domain/state_resolution.py:65-94`). This is the only place that logic exists and
  every clock job already goes through it.
- `notification_logs` gets a new row through one of exactly two AST-visible forms
  (`test_writer_census.py:7-13`), from a module in an explicit `CONSTRUCTION_SITES` allowlist
  (`test_writer_census.py:317-354`). `guests/domain/notifications.py` +
  `guests/application/portal.py:766-913` (`GUEST_PORTAL_LINK_DELIVERED`) is the only existing
  guest-facing, language-keyed, `EMAIL`-delivered writer, and the only one so far that needed a
  stored/sent text split because its content (a live URL) could never be persisted. Everything else
  — SLA escalations, `maintenance`/`cleaning`/`pricing` builders — writes one constant-plus-ids body
  straight to the row.
- Rule 11's exception 1 (`sdd/steering/security.md:184,234`) already permits the masked `****XX`
  form of an access code in `notification_logs.subject`/`body`, and has never been exercised —
  `AccessRecordModel` has no plaintext column at all (`access/domain/entities.py:75-78`), only
  `code_masked` (`access/infrastructure/models.py:33`).

## Decisions

### D1 — Two new Celery tasks, not one and not three

**Chosen:** `send_checkin_reminders` (PRD's own name, extended to evaluate both `CHECKIN_REMINDER_24H`
and `CHECKIN_REMINDER_2H` per reservation in one sweep) and a new `send_checkout_reminders`
(declared divergence, same class as `dispatch_notifications`/`classify_incidents`). Both share the
identical "confirmed reservation, property-timezone instant, threshold, dedup" shape; splitting on
the reminder's *direction* (check-in vs. checkout) rather than on its exact type keeps the beat
calendar legible — one row per real-world concern — while avoiding two near-identical tasks that
would only differ by a duration constant.

Rejected: one task for all three types — mixes checkout into a task literally named
`send_checkin_reminders`, which every future reader has to learn is not what the name says. Rejected:
three separate tasks (one per `NotificationType` member) — `CHECKIN_REMINDER_24H` and
`CHECKIN_REMINDER_2H` differ only in a lead-time constant over the exact same query and recipient
resolution; tripling the sweep buys nothing `check_checkin_windows`/`process_checkouts`'s split
buys (there, the two really do different things: one opens a window, the other transitions state
and creates a `CleaningTask`).

### D2 — 15-minute cadence for both new tasks

**Chosen:** `CADENCES["send_checkin_reminders"] = CADENCES["send_checkout_reminders"] =
timedelta(minutes=15)`, giving a 45-minute lock via `lock_ttl_for` (`scheduler/locks.py:33-39`).

Rejected: 5 minutes, matching `check_checkin_windows` — that cadence exists because
`check_checkin_windows` gates same-day operational automation (cleaning tasks, state machine); a
guest reminder tolerates a much coarser worst-case delay with no operational cost, and a faster
cadence only multiplies per-tenant query round-trips for reservations that are, by construction,
still hours away from the threshold.

### D3 — Threshold-crossing check with dedup, never an exact-window match

**Chosen:** a candidate reservation is due for `CHECKIN_REMINDER_24H` when
`checkin_instant - 24h <= now < checkin_instant` (symmetric for `_2H` and for `send_checkout_reminders`
against `checkout_instant`, with the **same 2h lead time reused for the checkout reminder** — R2 left
the exact lead open; reusing `CHECKIN_REMINDER_2H`'s value avoids inventing a third magic number with
no PRD support). The upper bound (`now < target_instant`) matters as much as the lower one: without
it, a reservation whose check-in already passed — including the entire backlog on this feature's
first deploy — would retroactively fire a stale reminder for a stay that is over. Combined with R4's
`exists_for` dedup (`notification_logs.related_type`/`related_id`/`notification_type`,
`ix_notification_logs_related_type_related_id`), a reservation that a sweep misses (worker down, lock
contention) is still caught by the next one, because "past the threshold" stays true until the upper
bound — unlike an exact-window match, which silently skips a guest forever if the one tick that
matched its window was missed.

Rejected: `instant BETWEEN threshold AND threshold + cadence` (mirrors how a naive reading of
`CADENCES` might look) — fails exactly the way described above on a missed tick, and ties correctness
to the cadence never changing.

### D4 — Bounded candidate query, one per task

**Chosen:** each sweep selects only `CONFIRMED` reservations whose `check_in_date` (respectively
`check_out_date`) falls within a narrow date window around today (today ± 1 day is enough to cover
every property's timezone offset and both reminder types' lead times) before evaluating
`effective_bounds`/the threshold in Python — the same "index-friendly date filter, then precise
check in code" shape `check_checkin_windows`'s own candidate query already uses, so the new tasks
read as siblings rather than a new pattern.

### D5 — Recipient resolution mirrors `GuestLinkDeliveryUseCase._recipient`, adapted to "skip" not "422"

**Chosen:** for each candidate, load the guest through the existing `GuestRepository`, strip
`guest.email`, and — if blank — skip the candidate and count it, exactly like
`resolve_channels` already treats a contact-less channel (`channel_resolver.py:70-91`). There is no
HTTP caller here to answer `422` to (`GuestContactMissingError` stays a portal-side concept). Return
`(email, preferred_language)`, reusing `Guest.preferred_language`'s existing `"es"`/`"en"`
fallback convention from `guests/domain/notifications.py:20-23`.

### D6 — New domain builders, one per data-owning module, not one shared "guest notifications" file

**Chosen:** `reservations/domain/notifications.py` (new file) holds
`render_checkin_reminder_email(language, property_name, check_in_date, check_in_time_local)` and
`render_checkout_reminder_email(...)` — fixed template plus property name and the reservation's own
dates, never guest- or operator-authored text. `access/domain/notifications.py` (new file) holds
`render_access_instructions_email(language, code_masked)`. Both join `CONSTRUCTION_SITES` in
`test_writer_census.py`. This follows the existing convention — `cleaning/domain/notifications.py`,
`maintenance/domain/notifications.py`, `pricing/domain/notifications.py`, `reviews/domain/
notifications.py` are each keyed to the module that **owns the row's underlying data**, not to who
receives it; `Reservation` belongs to `reservations`, `AccessRecord` to `access`.

Rejected: adding all three renderers to the existing `guests/domain/notifications.py` — that module
is guest-**identity**-scoped (portal tokens), not the owner of `Reservation` or `AccessRecord`, and
stretching "guest-facing" into a construction-site criterion would make the convention ambiguous for
the next writer.

### D7 — Reminders and access instructions write `PENDING` rows through the standard dispatcher, not a synchronous send

**Chosen:** all three writers build a row with `status=PENDING` and let the existing
`dispatch_notifications` (every minute, `tasks.py:602-612`) deliver it through the `EMAIL` adapter,
exactly like the 19 already-`WITH_WRITER` types (SLA escalations, `maintenance`/`cleaning`/`pricing`
builders). `GUEST_PORTAL_LINK_DELIVERED` needed a synchronous send (`status` already `SENT`/`FAILED`,
never `PENDING`) only because its real content — a live portal URL — could never be persisted at all;
here, the masked code (`****XX`) **is** exactly what rule 11's exception 1 allows to be persisted, so
there is no unmaskable secret forcing a same-request send, and the ordinary `PENDING` path is simpler
and reuses `dispatch_notifications`'s existing retry ceiling (`notification_max_attempts`) for free.

Rejected: synchronous send à la `guest-link-delivery` — would need its own retry logic duplicating
`dispatch_notifications`, for a body that is safe to persist as-is.

### D8 — Idempotency: `exists_for` before every write, task lock around every sweep

**Chosen:** immediately before building each row, call
`repository.exists_for(tenant_id, related_type=..., related_id=..., notification_type=...)`
(the existing port method on `notifications/domain/repositories.py`; its one production caller today
is `TriageIncidentUseCase` in `maintenance/application/use_cases.py`, deduplicating a severity-alert
write under the same index — `cancel_sla_deadline` is a different, unrelated method that clears a
deadline rather than checking existence) — `related_type="reservation"` / `reservation.id` for both
reminder types, `related_type="access_record"` / `record.id` for access instructions. Each task additionally
runs inside `_guarded(name, CADENCES[name], work)`, so two overlapping runs of the *same* task cannot
both pass the check for the same candidate before either commits (D3's note on missed ticks is about
a *different* run finding the candidate later, not about two runs racing the same candidate).

### D9 — Access-instructions delivery is its own task, not folded into `provision_access_records`

**Chosen:** a third new task, `deliver_access_instructions`, same `_guarded` shape, 15-minute cadence
(D2), sweeping `AccessRecord`s in `MANUAL_ADDED` or `CREATED_EXTERNAL` with no
`ACCESS_INSTRUCTIONS_SENT` row yet for that record.

Rejected: adding a step to `provision_access_records` — that task's own docstring and
`access-notifications` design scope it tightly to reconciliation (create/revoke/expire); folding a
guest-messaging concern into its commit would mix two responsibilities under one lock and one
cadence, where this change wants its own (independently tunable, independently testable) surface.

### D10 — New `NotificationType` member: `ACCESS_INSTRUCTIONS_SENT`

**Chosen:** add `ACCESS_INSTRUCTIONS_SENT = "ACCESS_INSTRUCTIONS_SENT"` to
`notifications/domain/enums.py`, declared the same way `GUEST_PORTAL_LINK_DELIVERED` and
`PASSWORD_RESET_REQUESTED` already are — a divergence from PRD §14's sixteen, commented as such. It
goes straight into `WITH_WRITER` — it is never a member without a writer, since this change is its
only reason to exist.

Rejected: `ACCESS_INSTRUCTIONS_DELIVERED` — deliberately avoided despite mirroring
`AccessRecordStatus.DELIVERED`/`TimelineEventType.ACCESS_CODE_DELIVERED`
(`access/application/use_cases.py:53-61`), because those two existing symbols denote the operator's
independent, out-of-band confirmation via `MarkAccessDeliveredUseCase` (R3.4 keeps that decoupled from
this change's automated email) — a near-identical name for a semantically distinct fact ("the system
emailed a masked code" vs. "an operator confirmed the guest has it by some other means") is exactly
the kind of confusion D10 exists to avoid. `_SENT` names what this notification type actually records:
an email left this system, nothing about the operator's own confirmation.

### D11 — No `sla_deadline_at`, no `escalation_for` entry, for any of the four writers

**Chosen:** all three writers pass `sla_deadline_at=None`. None of the four notification types has an
operator-facing deadline to breach — a guest reminder or an access-instructions email has nobody to
escalate to if "late," the same reasoning already recorded for `GUEST_PORTAL_LINK_DELIVERED` and the
`OWNER_APPROVAL_*` pair. Skipping this would make `check_sla_breaches` pick up rows for a policy
`escalation_for` was never asked to define.

### D12 — `EMAIL` only, no channel resolver / fan-out reuse

**Chosen:** each writer targets `NotificationChannel.EMAIL` directly and writes exactly one row per
candidate. `channel_resolver.py`'s `resolve_channels`/`dispatch_channels` fan-out
(`channel_dispatch.py:46-159`) is keyed to `User.email`/`User.phone` and always includes `IN_APP`
unconditionally — both wrong for a guest, who has no authenticated inbox and no `User` row. Reusing it
would require teaching it a second recipient shape for no benefit, since this change needs exactly one
channel.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Scheduler | `backend/app/scheduler/schedule.py` | Add `send_checkin_reminders`, `send_checkout_reminders`, `deliver_access_instructions` to `CADENCES` (15 min each, D2/D9) |
| Scheduler | `backend/app/scheduler/tasks.py` | Three new `@celery_app.task`-decorated functions, `_guarded` shape (D1, D9), wiring the three new use cases below |
| Reservations | `backend/app/reservations/application/use_cases.py` (or a new module in the same package) | New use cases: `SendCheckinRemindersUseCase`, `SendCheckoutRemindersUseCase` — per-tenant candidate query (D4), `effective_bounds` + threshold (D3), recipient resolution (D5), `exists_for` dedup (D8), row write (D6/D7/D11/D12) |
| Reservations | `backend/app/reservations/domain/notifications.py` (new) | `render_checkin_reminder_email`, `render_checkout_reminder_email` (D6) |
| Access | `backend/app/access/application/use_cases.py` | New `DeliverAccessInstructionsUseCase` — candidate query over `MANUAL_ADDED`/`CREATED_EXTERNAL`, same dedup/write shape |
| Access | `backend/app/access/domain/notifications.py` (new) | `render_access_instructions_email` (D6) |
| Notifications | `backend/app/notifications/domain/enums.py` | Add `ACCESS_INSTRUCTIONS_SENT` (D10) |
| Tests | `backend/tests/notifications/test_writer_census.py` | Move the three reminder types from `WITHOUT_WRITER` to `WITH_WRITER`; add `ACCESS_INSTRUCTIONS_SENT` to `WITH_WRITER`; add both new modules to `CONSTRUCTION_SITES`; update `test_exactly_four_types_have_no_writer` (now `LOCK_ALERT` alone — rename/retitle the test) |
| Tests | `backend/tests/scheduler/test_schedule.py` | Register the three new task names in the "exactly one of the three tables" and "calendar is PRD §8.3 plus exactly the declared additions" assertions |

## Data & interfaces

No schema changes. `notification_logs` already has every column these writers need
(`recipient_contact`, `channel`, `notification_type`, `subject`, `body`, `status`, `related_type`,
`related_id`, `sla_deadline_at`) and `AccessRecordModel`/`ReservationModel` are read-only from this
change's perspective. `NotificationType` gains one Python enum member on a `String(100)` column — no
migration, consistent with every prior addition to that enum.

## Risks & mitigations

- **First-deploy backlog.** Every already-`CONFIRMED` reservation whose check-in/checkout already
  passed, and every `AccessRecord` already `MANUAL_ADDED`/`CREATED_EXTERNAL`, exists before this
  change ships. D3's upper bound (`now < target_instant`) keeps the reminder jobs from mailing anyone
  about a stay that is already over; `deliver_access_instructions` has no equivalent upper bound
  (an access code is still useful no matter how long ago it was registered) and **will** email every
  qualifying guest the first time it runs. This is the intended behaviour — it is exactly the gap PRD
  §15 describes — but it means the first run's volume is the full backlog, not a trickle; measuring
  that count before deploy (`SELECT count(*) FROM access_records WHERE status IN
  ('MANUAL_ADDED','CREATED_EXTERNAL')`) is worth doing at implementation time, the same way
  `celery-jobs`' SLA emitter measured its own first-tick backlog.
- **Property timezone / DST edge cases.** `effective_bounds` already raises
  `IncompatibleTransitionContextError` on an invalid zone or a nonexistent/ambiguous local wall time;
  the new use cases must catch that per-candidate and skip-and-count, never let one bad property abort
  a tenant's whole sweep (mirrors how `_active_reservations` callers already treat it).
- **Test literalism.** `test_writer_census.py` and `test_schedule.py` assert exact counts and exact
  set contents by design (their own docstrings: "a number in prose is a number that rots"). This
  design's changes to both are enumerated in "Changes by area" precisely so `/sdd:tasks` can turn them
  into their own checklist items rather than discovering them as review findings.

## Open questions

None. Every decision above follows an existing, directly reusable precedent in the codebase
(`effective_bounds`, the `_guarded`/`task_lock` shape, `exists_for`, the domain-builder convention,
the `GUEST_PORTAL_LINK_DELIVERED` writer) or an explicit divergence-declaration style the project
already uses repeatedly (`dispatch_notifications`, `classify_incidents`, `GUEST_PORTAL_LINK_DELIVERED`
itself). Nothing here touches a requirement, a security exception's scope (exception 1 already covers
the one rule-3 value in play), or an irreversible action.
