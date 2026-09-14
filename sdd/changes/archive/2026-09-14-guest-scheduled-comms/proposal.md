# Proposal: guest-scheduled-comms

## Why

PRD §8.3 declares six scheduled jobs (not eight, correcting `sdd/roadmap/guest-scheduled-comms.md`'s
stale count — verified directly against the PRD and against `sdd/specs/celery-jobs.md`'s own "sólo un
job de PRD §8.3 sigue sin estar aquí" note). One of the six, `send_checkin_reminders`, has never been
written: `backend/app/scheduler/schedule.py:28-31` says so in its own comment — "it is a message to a
guest, so what it needs is the channel adapter and the template... the clock is the trivial half".
`backend/tests/notifications/test_writer_census.py:117-128` measures the consequence on the enum side:
`CHECKIN_REMINDER_24H`, `CHECKIN_REMINDER_2H` and `CHECKOUT_REMINDER` are three of the four
`NotificationType` members with no production writer at all (the fourth, `LOCK_ALERT`, belongs to a
different, still-open roadmap gap).

PRD §15's access-instructions delivery has the same shape of gap, one layer further along: PRD §15
architecture is a five-step pipeline — reservation → provider import → code creation → AutoHostAI
stores the reference → *"AutoHostAI comunica instrucciones al huésped"*. `access-notifications`
delivered everything up to the fourth step (`AccessRecord`, `ManualAccessAdapter`,
`code_masked` — `backend/app/access/domain/entities.py:75-78` is explicit that there is no plaintext
column to leak) but the fifth step, the actual message to the guest, does not exist:
`POST /api/v1/access-records/{id}/delivered` (`backend/app/access/api/router.py:175-199` →
`MarkAccessDeliveredUseCase`, `backend/app/access/application/use_cases.py:268-291`) only records that
an operator *confirms* the guest already has it by some out-of-band means — it sends nothing.

Both gaps share one root cause and one unblock: `sdd/steering/security.md:184` records that rule 11's
**exception 1** — the masked `****XX` form of an access code in `notification_logs.subject`/`body` —
"sigue concedida y nadie la ejerce todavía" (granted, never exercised). What made both gaps closeable
is `notification-channel-routing` + `smtp-delivery-adapter`: the guest now has a working `EMAIL`
delivery path, proven end-to-end by `guest-link-delivery`'s `GUEST_PORTAL_LINK_DELIVERED` writer
(`backend/app/guests/application/portal.py:766-913`, `backend/app/guests/domain/notifications.py`),
which is also the closest existing precedent for a guest-facing, language-keyed, `EMAIL`-delivered
`NotificationLog` writer.

## What changes

Three scheduled jobs (24h check-in reminder, 2h check-in reminder, checkout reminder) start writing
`notification_logs` rows addressed to the guest's email, in the guest's `preferred_language`, at most
once per reservation and per type. A fourth mechanism delivers the access instructions automatically —
carrying only the masked access code — once an `AccessRecord` has one (`MANUAL_ADDED` or
`CREATED_EXTERNAL`), becoming rule 11 exception 1's first living writer. `NotificationType`'s three
reminder members move from `WITHOUT_WRITER` to `WITH_WRITER` in `test_writer_census.py`, and gains one
new member for the access-instructions type. `sdd/specs/celery-jobs.md`'s "sólo un job de PRD §8.3
sigue sin estar aquí" debt note closes.

## Requirements

### R1 — Check-in reminders at 24h and 2h

**As a** guest, **I want** a reminder about my upcoming check-in 24 hours and 2 hours beforehand,
**so that** I know when and how to arrive.

Acceptance criteria:

1. WHEN a confirmed reservation's check-in instant — `Property.timezone`-local `default_check_in_time`
   on `check_in_date` (`backend/app/properties/domain/entities.py:30,35`) — falls inside the 24h
   reminder window and no `CHECKIN_REMINDER_24H` row exists yet for that reservation
   (`related_type`/`related_id`), THE SYSTEM SHALL write one `notification_logs` row addressed to
   `Guest.email`.
2. WHEN the same instant falls inside the 2h reminder window and no `CHECKIN_REMINDER_2H` row exists
   yet for that reservation, THE SYSTEM SHALL write one accordingly.
3. IF the guest has no usable email, THEN THE SYSTEM SHALL skip the reservation without error, and
   count it — the same shape `resolve_channels` already uses for a contact-less channel
   (`backend/app/notifications/domain/channel_resolver.py:70-91`).
4. THE SYSTEM SHALL compose the body from a fixed template plus reservation dates and the property's
   name only — never guest-authored free text — matching the "constante más identificadores" contract
   already governing every other builder in `notifications/domain/*` and
   `guests/domain/notifications.py`.

### R2 — Checkout reminder

**As a** guest, **I want** a reminder about checkout, **so that** I know when to leave.

Acceptance criteria:

1. WHEN a confirmed reservation's checkout instant — property-timezone-local `default_check_out_time`
   on `check_out_date` — falls inside the checkout reminder window and no `CHECKOUT_REMINDER` row
   exists yet for that reservation, THE SYSTEM SHALL write one row addressed to the guest's email.
2. THE SYSTEM SHALL apply the same contact-missing skip (R1.3) and template-only-content rule (R1.4).

**Declared divergence, same class as `dispatch_notifications`/`provision_access_records`/
`classify_incidents`**: PRD §8.3 names no checkout-reminder job at all — `send_checkin_reminders`'s row
only describes the two check-in reminders — even though `CHECKOUT_REMINDER` has existed in
`NotificationType` since `celery-jobs`. This proposal treats it as PRD §14's declared type finally
getting the job PRD §8.3 never named for it, and leaves the exact job name/grouping (one job for all
three reminder types, or `send_checkin_reminders` plus a separate checkout job) to `/sdd:design`.

### R3 — Automatic delivery of access instructions

**As a** guest, **I want** to receive my access code once it is available, **so that** I can get into
the property without asking staff.

Acceptance criteria:

1. WHEN an `AccessRecord` reaches `MANUAL_ADDED` or `CREATED_EXTERNAL` (i.e. `code_masked` is set,
   `backend/app/access/domain/entities.py:84-112`) and no access-instructions notification has been
   written yet for that record, THE SYSTEM SHALL write one `notification_logs` row addressed to the
   reservation's guest email, whose body carries only the masked form (`****XX`) under rule 11's
   exception 1 (`sdd/steering/security.md:184,234`) — the plaintext code is never available to this or
   any other code path, since `AccessRecordModel` has no column for it.
2. THE SYSTEM SHALL NOT interpolate `access_records.notes` or any other free-text field into the
   notification body — only the fixed template plus `code_masked`.
3. IF the guest has no usable email, THEN THE SYSTEM SHALL skip the record without error, and count
   it.
4. THE SYSTEM SHALL NOT change `AccessRecord.status` as a side effect of sending this notification:
   `mark_delivered` (`POST /access-records/{id}/delivered`) remains an explicit, independent operator
   action, unchanged by this proposal — it records that the operator confirmed the guest has the
   instructions, which is a different fact from this system having emailed them.

### R4 — Exactly-once delivery per reservation/record and type

**As the** platform operator, **I want** each reminder or access-instructions message sent at most
once per reservation (or access record) and type, **so that** a guest is never messaged twice by an
overlapping or restarted job run.

Acceptance criteria:

1. WHEN any of R1-R3's jobs considers a candidate, THE SYSTEM SHALL check for an existing
   `notification_logs` row with the same `(tenant_id, related_type, related_id, notification_type)`
   before writing a new one, the same existence check `check_sla_breaches`'s escalation write already
   relies on (`ix_notification_logs_related_type_related_id`).
2. THE SYSTEM SHALL take a `scheduler/locks.py` `task_lock` over each job's whole per-tenant sweep, so
   two overlapping runs of the same job cannot both pass the existence check for the same candidate
   before either writes (mirroring `check_sla_breaches`/`provision_access_records`'s `_guarded` shape).
3. WHEN a candidate has more than one outstanding notification type at once, THE SYSTEM SHALL evaluate
   each type independently and SHALL NOT let one type's existing row suppress another's.

### R5 — Guest-appropriate language, channel, and census accounting

**As a** guest, **I want** these messages in my own language and over a channel I actually have.

Acceptance criteria:

1. THE SYSTEM SHALL render every message this change introduces (R1-R3) in `Guest.preferred_language`,
   falling back to `"es"` for any value other than `"es"`/`"en"` — the same convention
   `guests/domain/notifications.py:20-23` already establishes for `GUEST_PORTAL_LINK_DELIVERED`.
2. THE SYSTEM SHALL deliver every message this change introduces over the `EMAIL` channel only.
   `IN_APP` does not apply (a guest has no authenticated inbox to poll) and `WHATSAPP` is out of scope
   (see Out of scope).
3. THE SYSTEM SHALL move `CHECKIN_REMINDER_24H`, `CHECKIN_REMINDER_2H` and `CHECKOUT_REMINDER` from
   `WITHOUT_WRITER` to `WITH_WRITER` in `backend/tests/notifications/test_writer_census.py`, and add
   the new access-instructions `NotificationType` member (exact name decided at design, following the
   "ASSUMPTION: divergence from PRD §14's sixteen" precedent `GUEST_PORTAL_LINK_DELIVERED` and
   `PASSWORD_RESET_REQUESTED` already set) directly to `WITH_WRITER` — the census's own
   `test_the_two_lists_partition_the_enum` requires every member to be in exactly one list.

## Out of scope

- **WhatsApp delivery** for any of these four notification types. `EMAIL` only, mirroring
  `guest-link-delivery`'s precedent; no code path today resolves a guest's WhatsApp identity for a
  clock-driven job (`channel_dispatch.py`'s fan-out is keyed to `User`, not `Guest`). Candidate for a
  future roadmap entry if the product wants it.
- **`PUSH` channel** — no adapter is registered for it anywhere in the codebase
  (`notifications/infrastructure/adapters.py`), by design.
- **Changing what `POST /access-records/{id}/delivered` means.** It keeps recording the operator's own
  out-of-band confirmation, independent of whether this change's automated email succeeded or even
  ran.
- **Anything `access-notifications`'s reconciler already owns**: creating, expiring or revoking
  `AccessRecord`s, or obtaining a code from GrinPass/Beds24/any real provider. This change only reacts
  to a code that already exists.
- **Retry/backoff policy beyond what `dispatch_notifications` already provides** via
  `notification_max_attempts` — no new retry mechanism for these writers.
- **Encryption at rest** for `access_records.notes` or `notification_logs` columns — tracked
  separately by the roadmap candidate `plaintext-sink-encryption-at-rest`.
- **A manual "resend" HTTP endpoint, or any new RBAC permission.** This change is a pure clock-driven
  job, the same class as `dispatch_notifications`/`provision_access_records`/`classify_incidents` —
  none of which has an HTTP surface or an actor.
- **Reworking `send_checkin_reminders`'s PRD-stated hourly cadence into the exact final cadence** —
  that number (and whether all three reminder types share one job or split across two) is a design
  decision this proposal deliberately leaves open (see R2's divergence note).

## Affected specs

- `sdd/specs/celery-jobs.md` — adds the reminder job(s) to the beat calendar; closes its own "sólo un
  job de PRD §8.3 sigue sin estar aquí" debt note.
- `sdd/specs/access-notifications.md` — records the first living writer of rule 11's exception 1, and
  documents the access-instructions delivery mechanism alongside the existing manual-confirmation
  endpoint it does not replace.
