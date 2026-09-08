# Proposal: guest-link-delivery

## Why

The guest portal (`/guest/[token]`) is fully built — stay info, check-in, incident reporting,
and a messaging thread with AI response and escalation — but no real guest can reach it.
Minting and revoking the portal token already exist (`POST`/`DELETE
/api/v1/reservations/{reservation_id}/guest-access-token`, `backend/app/guests/api/router.py:151,184`),
gated to `TENANT_OWNER`/`PROPERTY_MANAGER`, but only `frontend/lib/api/generated/openapi.d.ts:884-894`
knows about them — no screen calls them. The only place in the whole tree that ever prints the
token in clear is `backend/app/cli/demo_reset.py:1322` (`stdout`, documented in
`docs/demo-tenant.md:79-86`); `notification_logs` has never had a row addressed to a guest
(measured by `guest-scheduled-comms` on 2026-08-28, still true). `smtp-delivery-adapter` closed
the email side (real SMTP relay, verified end-to-end 2026-09-03) and `notification-channel-routing`
made the channel switch mean something — both landed with nothing yet calling them for this
recipient. This entry is Milestone "MVP operable" #2 (*the real guest*), audited 2026-09-04:
see `sdd/roadmap/guest-link-delivery.md` for the full analysis this proposal restates as
requirements.

## What changes

From `/reservations/[id]`, an operator with `MANAGE_GUEST_ACCESS_TOKENS` can mint the guest's
portal link, see it copyable exactly once (same pattern as
`features/platform/components/temporary-password-reveal.tsx`), see whether a live link exists
and since when, revoke it, and trigger sending it by email to `Guest.email` over the SMTP relay
`smtp-delivery-adapter` already wired. The email is a **new** notification writer — the first
one addressed to a guest — that follows the `auth-account-recovery` precedent: it invokes the
`EMAIL` adapter synchronously inside the request and writes its `notification_logs` row already
`SENT`/`FAILED`, never `PENDING`, because rule 11 of `steering/security.md` forbids a body that
carries a rendered link and the async dispatcher only ever reads `subject`/`body` back — the
same reason `auth-account-recovery` bypassed it for the password-reset link. Nothing here reads,
persists, or logs the token's cleartext beyond the single response that already returns it today.

## Requirements

### R1 — See and act on the guest's portal token from the reservation detail

**As a** property manager or tenant owner, **I want** to see whether a reservation's guest has a
live portal link and mint, copy, or revoke it from the reservation's own detail screen, **so
that** I don't have to leave `/reservations/[id]` or use a tool to hand a guest access to their
portal.

Acceptance criteria:

1. WHEN an authorized operator opens `/reservations/[id]`, THE SYSTEM SHALL show whether the
   reservation's guest currently has a live portal token and, if so, since when it was issued —
   without ever exposing the token value itself.
2. WHEN the operator mints a token, THE SYSTEM SHALL display the returned value in a
   copy-to-clipboard control, mark it as shown exactly once, and never re-display it after the
   component unmounts or the screen is left and returned to.
3. WHEN the operator revokes the token, THE SYSTEM SHALL update the visible status to "no live
   token" without requiring a page reload.
4. IF the signed-in user lacks `MANAGE_GUEST_ACCESS_TOKENS`, THEN THE SYSTEM SHALL NOT render any
   of the mint/copy/revoke/send controls.
5. WHILE a mint, revoke, or send request is in flight, THE SYSTEM SHALL disable the triggering
   control to prevent a duplicate submission.

### R2 — Expose live-token status without exposing the token

**As a** frontend consuming the reservation detail, **I want** an authenticated way to learn
whether a stay's portal token is currently live and since when, **so that** R1's screen does not
have to mint a token merely to check its status.

Acceptance criteria:

1. THE SYSTEM SHALL expose, on the authenticated surface gated by `MANAGE_GUEST_ACCESS_TOKENS`,
   whether the reservation currently has a non-revoked, non-expired portal token and, if so, its
   issuance instant.
2. THE SYSTEM SHALL NOT expose the token value or its hash on this surface — only presence and
   issuance instant, consistent with `guest-portal-api.md`'s rule that the cleartext value is
   returned exactly once and never read back.
3. THE SYSTEM SHALL apply the same tenant-isolation and 404-for-foreign-tenant behavior as the
   existing mint/revoke routes.

### R3 — Deliver the portal link to the guest by email

**As a** property manager or tenant owner, **I want** to trigger sending the guest's portal link
to their own email address, **so that** the guest actually receives it instead of me having to
copy-paste it into another channel by hand.

Acceptance criteria:

1. WHEN an authorized operator triggers sending the link for a reservation, THE SYSTEM SHALL mint
   a fresh token for that stay (revoking any live one, per the existing issuance contract) and,
   within the same request, send an email to the reservation's `Guest.email` containing the
   portal URL built from that token.
2. IF the reservation has no linked `Guest` or `Guest.email` is blank, THEN THE SYSTEM SHALL
   reject the send with an actionable `422` and SHALL NOT mint a token.
3. THE SYSTEM SHALL write exactly one `notification_logs` row for the send attempt, addressed to
   the guest, with `status` set directly to `SENT` or `FAILED` — never `PENDING` — mirroring
   `auth-account-recovery`'s synchronous-adapter pattern, because the dispatcher's async path
   only ever reads back `subject`/`body`, and this delivery's payload is a per-guest URL that
   rule 11 forbids persisting in either column.
4. THE SYSTEM SHALL compose the row's `subject`/`body` from constant text and identifiers only
   (reservation/property references), and NEVER SHALL persist the portal URL, the token, or its
   hash in `notification_logs`.
5. IF the email adapter reports failure, THEN THE SYSTEM SHALL still have minted and revoked the
   tokens as in AC1 (the mint is not rolled back by a delivery failure), record the row as
   `FAILED` with the adapter's structured error code, and return a response the operator can
   read as "link created, not delivered" — distinct from AC2's outright rejection.
6. THE SYSTEM SHALL audit the send attempt (success or failure) alongside the existing
   `GUEST_ACCESS_TOKEN_ISSUED` audit entry, without introducing a second write path for the same
   token.

### R4 — A guest-addressed notification type exists

**As the** notification subsystem, **I want** a `NotificationType` member for the guest portal
link email, **so that** R3's row is attributable and countable like every other notification.

Acceptance criteria:

1. THE SYSTEM SHALL add a new `NotificationType` member for the guest portal link delivery,
   declared as an explicit divergence from PRD §14's sixteen types — the same pattern
   `auth-account-recovery`'s `PASSWORD_RESET_REQUESTED` and `revenue-reviews`'s
   `REVIEW_RESPONSE_APPROVED` already established.
2. THE SYSTEM SHALL give it no SLA escalation (`escalation_for` resolves to nothing for it), since
   a link the operator chose to send has no deadline to breach.
3. THE SYSTEM SHALL register it in `test_writer_census.py`'s `WITH_WRITER` set, attributed to this
   change's writer.

## Out of scope

- **Access instructions, the door code, and the 24h/2h check-in reminders** — that boundary
  belongs to `guest-scheduled-comms`, which also has to solve rule 11's masked-form question for
  a door code in a notification body. This change carries only the portal link.
- **Automatic emission** on reservation confirmation or from the `provision_access_records` sweep
  — the roadmap note's recommendation for the MVP is manual, from the reservation detail; the
  automatic trigger is `guest-scheduled-comms`'s to decide.
- **SES.Hospedajes** (`guests/api/router.py:216`) — no screen exists for it; a separate candidate
  if picked up.
- **Showing the guest's portal activity** (completed check-in, uploaded documents) on the
  reservation detail, beyond what it already shows.
- **WhatsApp delivery of the link** — the MVP sends by email only and shows the link copyable so
  an operator can paste it elsewhere by hand; `notification-channel-routing`'s channel switches
  govern user-addressed notifications, not this guest-addressed one.
- **Any change to the token's lifecycle, hashing, rate limits, or authorization** — `R1`-`R4`
  consume the existing mint/revoke contract of `guest-portal-api.md` as-is.

## Affected specs

- `sdd/specs/guest-portal-api.md` — update "La entrega del enlace al huésped es manual hoy" and
  the deuda declarada item about automatic emission, to record that a manual, operator-triggered
  delivery path now exists; add the read-only live-token-status surface (R2).
- `sdd/specs/access-notifications.md` — add this change's writer to "El censo de escritores" (the
  new `NotificationType` member, its builder, and its synchronous-delivery exception alongside
  `auth-account-recovery`'s).
- `sdd/specs/reservations.md` — document the new UI affordance on `/reservations/[id]` if that
  spec is the home of the detail screen's contract (verify at design time; create a
  `guest-link-delivery.md` spec instead if the detail screen's behavior doesn't already have a
  natural home).
