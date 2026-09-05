# Design: guest-link-delivery

## Context

`backend/app/guests/api/router.py:151,184` already exposes `POST`/`DELETE
/api/v1/reservations/{reservation_id}/guest-access-token`, gated by
`Permission.MANAGE_GUEST_ACCESS_TOKENS`, backed by `IssueGuestAccessTokenUseCase` and
`RevokeGuestAccessTokenUseCase` (`backend/app/guests/application/portal.py:469,549`), a
`GuestAccessTokenRepository` port (`backend/app/guests/domain/portal_ports.py:313`) with
**exactly three methods and no read by reservation** — its own docstring says why: *"no
`get_by_reservation`... A port that offered a listing would be the open door for the change
that comes next."* This change is that door. `GuestAccessTokenModel`
(`backend/app/guests/infrastructure/models.py:71`) already carries `created_at` via
`TimestampMixin`; the domain dataclass `GuestAccessToken` (`portal_ports.py:26`) does not
expose it yet.

The email side follows `auth-account-recovery`'s precedent exactly:
`backend/app/auth/application/recovery.py:280-335` mints a token, builds `subject`/`body`
**without the link** from constants (`STORED_RECOVERY_SUBJECT`/`STORED_RECOVERY_BODY`), calls
the `EMAIL` adapter synchronously with the real link, and writes one `NotificationLog` row
already `SENT`/`FAILED` — never `PENDING` — in the same request. `steering/security.md`'s rule
11 table (row `notification_logs.subject`/`body` — el contrato vivo) already lists
`auth-account-recovery` as a writer of that same "constante más identificadores" contract; this
change adds a second writer to that list, not a new exception.

`NotificationAdapter`/`NotificationChannel`/`adapter_registry()` live in
`backend/app/notifications/{domain/ports.py,infrastructure/adapters.py}`; `adapter_registry()`
is already called from two places (`auth/api/dependencies.py:254`, `scheduler/tasks.py:186`).
`GuestRepository.get(tenant_id, guest_id) -> GuestSummary | None`
(`backend/app/guests/domain/repositories.py:28`) already returns `email` and
`preferred_language` (`backend/app/guests/domain/value_objects.py:25-44`).
`PortalStayLocator.find(tenant_id, reservation_id) -> PortalStay | None`
(`backend/app/guests/domain/portal_ports.py:369,381`) — the port `IssueGuestAccessTokenUseCase`
and `RevokeGuestAccessTokenUseCase` already use — gives `guest_id` (nullable) without this
domain reaching into `reservations/domain`'s own `ReservationRepository` (see D4).
`CallerOwnedUnitOfWork` (`backend/app/core/unit_of_work.py:59`) is the existing seam for a use
case composing another over one session, built after an incident where composing
`SetGuestDocumentUseCase` inside `SubmitGuestCheckinUseCase` shipped with two independent
commits (see D4).

On the frontend, `frontend/app/(workspace)/reservations/[id]/page.tsx` is the detail screen;
`frontend/lib/auth/permissions.ts:61`'s `useHasPermission(permission)` is the existing gating
hook; `features/platform/components/temporary-password-reveal.tsx` is the "show a secret
exactly once, never persist it client-side" pattern R1 reuses.

## Decisions

### D1 — A dedicated read endpoint for live-token status, not a field on `ReservationResponse`

**Chosen:** `GET /api/v1/reservations/{reservation_id}/guest-access-token` (new verb on the
existing path), gated by the same `MANAGE_GUEST_ACCESS_TOKENS` as the `POST`/`DELETE` siblings,
returning `GuestAccessTokenStatusResponse { is_live: bool, issued_at: datetime | null }`.
`ReservationResponse` is visible to anyone with `READ_RESERVATIONS`; token status is a fact
about a security credential, and this keeps its visibility exactly as narrow as minting and
revoking it already are, and keeps the route file that a security reviewer already opens
(`guests/api/router.py`'s own docstring says this) the one place that changes.

Rejected: adding `guest_access_token_issued_at`/`is_live` to `ReservationResponse` — cheaper for
the frontend (one request instead of two) but widens who learns a token exists to every
`READ_RESERVATIONS` holder, which R2.2 does not ask for and rule 4's masking spirit argues
against.

### D2 — `GuestAccessToken` gains `issued_at`; no migration

**Chosen:** add `issued_at: datetime` to the `GuestAccessToken` domain dataclass
(`portal_ports.py:26`), mapped from `GuestAccessTokenModel.created_at`, which already exists via
`TimestampMixin`. `SqlAlchemyGuestAccessTokenRepository`'s existing row-to-entity mapping gains
one field; no `alembic` revision needed.

Rejected: a new `issued_at`-only projection type — the entity already carries exactly the two
facts D1 needs (`token_hash` is never returned; the caller sees only `id`/`revoked_at`/new
`issued_at`), so a second type would duplicate the row-to-object mapping for no isolation gain
(unlike `PortalStay`/`GuestSummary`, which exist to exclude fields this response never had).

### D3 — `find_live_for_reservation` on `GuestAccessTokenRepository`, and the port's docstring changes

**Chosen:** add `find_live_for_reservation(tenant_id, reservation_id) -> GuestAccessToken |
None` to `GuestAccessTokenRepository` (`WHERE reservation_id = … AND revoked_at IS NULL`, the
same predicate the partial unique index enforces, so "the live one" is unambiguous). The port's
docstring (`portal_ports.py:314-320`) explicitly reasoned that *no* read-by-reservation should
exist yet; this change is the one its own last sentence anticipated, so the docstring is
rewritten to say **what** now reads by reservation and **why the boundary still holds**: it
returns presence/`revoked_at`/`issued_at`, never `token_hash`, so rule 3(a)'s "returned once" is
still true — nothing new exposes the credential.

Rejected: reusing `find_live_by_token_hash` — that query resolves an unmarked session by hash
and has no `reservation_id` input; repurposing it would either add an unused parameter or search
by a hash the caller does not have.

### D4 — Delivery is a new use case that calls the existing mint, not a flag on it; one
transaction, one commit, `CallerOwnedUnitOfWork` on the composed mint

**Chosen:** `SendGuestAccessTokenUseCase` (new class, `guests/application/portal.py`, sibling to
`Issue`/`RevokeGuestAccessTokenUseCase`), with its own `execute(tenant_id, reservation_id,
actor, now)`. It composes `IssueGuestAccessTokenUseCase` **over the same session**, wired at
construction with `uow=CallerOwnedUnitOfWork()` instead of `SqlAlchemyUnitOfWork(session)` —
exactly the mechanism `app/core/unit_of_work.py:59` documents for this precise situation ("one
use case composes another... and then exactly one of the two may end it"), built after
`SubmitGuestCheckinUseCase`'s own composition of `SetGuestDocumentUseCase` first shipped with
two independent real commits and four of five reviewers caught it. `SendGuestAccessTokenUseCase`
itself holds the one real `SqlAlchemyUnitOfWork` and is the only one that calls `commit()`,
once, at the very end:

1. Load the stay via `PortalStayLocator.find(tenant_id, reservation_id)` — the same narrow,
   guests-owned projection `IssueGuestAccessTokenUseCase`/`RevokeGuestAccessTokenUseCase`
   already use (`portal.py:511,584`), **not** `ReservationRepository`: `PortalStay` already
   carries `guest_id` (`portal_ports.py:59`), and reaching into `reservations/domain`'s own
   repository from `guests/application` would reopen exactly the aggregate-leak
   `PortalStayLocator`/`LegalRegistrationStayStore` were both built to avoid (their docstrings
   say so explicitly). Reject `404` if the stay is absent/foreign-tenant, like the two existing
   use cases.
2. IF `stay.guest_id` is **not** `None`, look up the guest via `GuestRepository.get` and reject
   `422` if its `email` is blank; IF `stay.guest_id` **is** `None` (no `Guest` linked to this
   stay yet — e.g. before check-in), reject `422` directly — **before minting anything** (R3.2).
   This is why the guest/email check is its own step and not folded into the mint use case,
   which has no reason to know about guests or email at all.
3. Call the composed `IssueGuestAccessTokenUseCase.execute(...)` — same revoke-and-replace
   logic, same audit row, same "never re-issued to the caller" contract (R3.1) — but its
   `CallerOwnedUnitOfWork.commit()` is a no-op, so nothing is durable yet.
4. Build `subject`/`body` from constants + reservation/property identifiers only (never the
   guest's name, never the link) via a new pure builder `render_guest_link_email(language:
   str) -> tuple[str, str]` in `guests/domain/notifications.py`, choosing `es`/`en` from
   `GuestSummary.preferred_language` (already a stored field, default `"es"`; see D6).
5. Call the `EMAIL` adapter synchronously with the **real** portal URL (built from the
   cleartext token step 3 returned, `{frontend_base_url}/guest/{token}` — same shape
   `render_recovery_email` uses) and the guest's `email` — **before** the commit, on the same
   open session, exactly as `recovery.py:280-335` itself does it (its own design D2 rejected a
   post-response `BackgroundTask` precisely because the session would already be closed and the
   adapter's result could not land in the same transaction as the mint — not because the
   adapter call must happen after a commit; the two intermediate design paragraphs that said
   otherwise were a misreading of that precedent and are corrected here).
6. Build one `NotificationLog`, `SENT`/`FAILED` (R3.3-R3.5), `related_type = "reservation"`,
   `related_id = reservation_id`, `recipient_user_id = None` (the recipient is a guest, not a
   `User` — the column already allows `NULL`), `recipient_contact = guest.email`, mirroring
   `recovery.py:303-333` field for field, and add it on the same session.
7. Audit the send attempt (R3.6) via the same `GuestAuditWriter` the other two use cases
   already use, action `GUEST_ACCESS_TOKEN_SENT` (new, see D5), `entity_id` = the **new**
   token's id (already known from step 3), so `ix_audit_logs_tenant_id_entity_type_entity_id`
   keeps answering "everything that happened to this credential" the way `portal.py:356-361`
   already documents for issue/revoke.
8. `commit()` once, here, on `SendGuestAccessTokenUseCase`'s own `SqlAlchemyUnitOfWork` — the
   token, its audit row, the `NotificationLog` and the send's audit row land together or not at
   all. There is no crash window where a token exists with zero notification/audit rows for it.

Rejected: an optional `deliver: bool` parameter on `IssueGuestAccessTokenUseCase` — every
existing caller and test of that use case would gain an unused dependency on `GuestRepository`
and the adapter registry, for a capability only one caller needs; the two-step composition
keeps mint single-purpose and testable without email infrastructure, and `CallerOwnedUnitOfWork`
is exactly the seam this codebase already built for composing it safely.

Rejected (this design's own earlier draft): two independent commits — mint commits on its own,
then a second small transaction for the notification row. Flagged by the architecture review as
both a misattribution of `auth-account-recovery`'s actual precedent (which commits once, at the
end) and a repeat of the exact `SubmitGuestCheckinUseCase` incident `CallerOwnedUnitOfWork` was
built to prevent — a crash between the two commits would leave a live token with no
`notification_logs` row and no `GUEST_ACCESS_TOKEN_SENT` audit row, violating R3.3/R3.6.

### D5 — New route, response, `NotificationType` member and audit action

**Chosen:**
- `POST /api/v1/reservations/{reservation_id}/guest-access-token/send` (sibling path segment
  under the existing resource, so it inherits the same file, same permission dependency
  `ManageAccessTokenDep`, same 404-for-foreign-tenant shape as its two neighbours).
- Response `GuestAccessTokenSentResponse { delivered: bool }` — **never** the cleartext token
  (R1's two actions stay distinct: "copy it yourself" is the existing `POST`, "email it to the
  guest" is this one; an operator who triggers "send" has no reason to also see the value in
  their own browser).
- `NotificationType.GUEST_PORTAL_LINK_DELIVERED` (new member, `notifications/domain/enums.py`),
  declared as an explicit PRD §14 divergence alongside `PASSWORD_RESET_REQUESTED` and
  `REVIEW_RESPONSE_APPROVED`; no entry in `escalation_for` (R4.2) — a link the operator chose to
  send has no SLA to breach.
- `audit_actions.GUEST_ACCESS_TOKEN_SENT` (new, `guests/domain/*` audit vocabulary next to
  `GUEST_ACCESS_TOKEN_ISSUED`/`_REVOKED`), same entity type `GUEST_ACCESS_TOKEN`.

### D6 — Language: use `Guest.preferred_language` as it already exists, not a new resolver

**Chosen:** `render_guest_link_email` takes the plain `preferred_language: str` already on
`GuestSummary` (default `"es"`, per `guests/domain/entities.py:17`) and picks between two fixed
templates, the same shape `render_recovery_email` already uses for `User.preferred_language`.

Rejected: inventing a resolver mirroring `messaging/domain/language.py`'s `detect_language` —
that module classifies the language of a **message a guest just wrote**; at send time there is
no guest-authored text to classify, only a stored preference. The roadmap note's caution ("un
`Guest` no tiene `preferred_language` de usuario") is true in the sense that nothing today
*writes* a non-default value to it — but that is a gap in a different, already-existing column,
not a reason to build a second mechanism here. Using the field as-is is both the simplest choice
and the one that benefits automatically the day some writer starts populating it for real.

### D7 — Frontend: one card, three mutations, one query

**Chosen:** a new `GuestPortalLinkCard` component (`frontend/features/reservations/...`,
final path TBD in `run` against the existing detail screen's layout) rendered inside
`/reservations/[id]/page.tsx`, gated by `useHasPermission(Permission.MANAGE_GUEST_ACCESS_TOKENS)`
(R1.4) exactly like other permission-gated controls elsewhere in the app. It consumes:
- `useGuestAccessTokenStatus(reservationId)` — TanStack Query, backs R1.1/R2.
- `useIssueGuestAccessToken(reservationId)` — mutation; on success renders the returned token
  in a `TemporaryPasswordReveal`-style one-time reveal (R1.2) and invalidates the status query.
- `useRevokeGuestAccessToken(reservationId)` — mutation; invalidates the status query on
  success (R1.3).
- `useSendGuestAccessTokenEmail(reservationId)` — mutation calling the new `send` route;
  surfaces `delivered` to the operator as a toast/inline status (R3.5) and invalidates the
  status query (a send mints a fresh token, so "since when" changes too).

All four disable their triggering control while `isPending` (R1.5).

## Changes by area

| Area | Files | Change |
|---|---|---|
| Domain | `backend/app/guests/domain/portal_ports.py` | `GuestAccessToken` gains `issued_at`; `GuestAccessTokenRepository` gains `find_live_for_reservation`; docstring rewritten (D3) |
| Domain | `backend/app/guests/domain/notifications.py` (new) | `render_guest_link_email(language) -> (subject, body)`; the constant `subject`/`body` pair the notification row actually stores |
| Domain | `backend/app/guests/domain/audit_actions.py` (or wherever `GUEST_ACCESS_TOKEN_ISSUED` lives) | new `GUEST_ACCESS_TOKEN_SENT` |
| Domain | `backend/app/notifications/domain/enums.py` | new `NotificationType.GUEST_PORTAL_LINK_DELIVERED`, no escalation entry |
| Application | `backend/app/guests/application/portal.py` | new `SendGuestAccessTokenUseCase` (D4) |
| Infrastructure | `backend/app/guests/infrastructure/portal_repositories.py` | `SqlAlchemyGuestAccessTokenRepository.find_live_for_reservation`; row mapping gains `issued_at` |
| API | `backend/app/guests/api/router.py` | `GET`/`POST .../guest-access-token/send` routes |
| API | `backend/app/guests/api/schemas.py` | `GuestAccessTokenStatusResponse`, `GuestAccessTokenSentResponse` |
| API | `backend/app/guests/api/dependencies.py` | `get_guest_access_token_status_use_case` (unless folded into a query, see Open Questions), `get_send_guest_access_token_use_case` wiring `SqlAlchemyGuestRepository`, `adapter_registry()`, `NotificationLogRepository`, and the composed `IssueGuestAccessTokenUseCase` with `uow=CallerOwnedUnitOfWork()` (D4) |
| Tests | `backend/tests/test_writer_census.py` | move `GUEST_PORTAL_LINK_DELIVERED` from `WITHOUT_WRITER` to `WITH_WRITER` |
| Tests | `backend/tests/test_route_authorization.py` | new routes' permission coverage |
| Frontend | `frontend/features/reservations/...` (new files) | `GuestPortalLinkCard`, its four hooks |
| Frontend | `frontend/app/(workspace)/reservations/[id]/page.tsx` | render the card, gated |
| Frontend | `frontend/lib/api/generated/openapi.d.ts` | regenerated (three new operations) |
| Frontend i18n | `frontend/locales/{es,en}/...` | new strings for the card (status, copy, send, delivered/failed) |
| Specs | `sdd/specs/guest-portal-api.md` | update "la entrega es manual hoy" and the automatic-emission deuda item; document the new `GET` and `find_live_for_reservation`'s narrowed boundary |
| Specs | `sdd/specs/access-notifications.md` | add this change to the rule-11 "contrato vivo" writer list and the writer census prose |
| Specs | `sdd/specs/guest-link-delivery.md` (new) | the reservation-detail UI contract, since no existing spec owns `/reservations/[id]`'s screen behavior (confirmed: only `frontend-foundation.md` mentions the route, for route-registry purposes) |

## Data & interfaces

- **No new table, no new column, no migration.** `issued_at` is a new field on an existing
  domain type backed by an existing DB column (`created_at`, via `TimestampMixin`).
- New API operations, all under the existing `/api/v1/reservations/{reservation_id}/guest-access-token`
  resource:
  - `GET` → `200 GuestAccessTokenStatusResponse { is_live: bool, issued_at: string | null }`,
    `404` for foreign tenant/missing reservation (same body as the siblings).
  - `POST .../send` → `200 GuestAccessTokenSentResponse { delivered: bool }`, `404` (foreign
    tenant), `422` (no guest / blank email, R3.2).
- New `NotificationType.GUEST_PORTAL_LINK_DELIVERED` (enum value, no schema change —
  `notification_logs.notification_type` is already free text per `access-notifications.md`).
- New audit action `GUEST_ACCESS_TOKEN_SENT` on the existing `GUEST_ACCESS_TOKEN` entity type —
  no schema change, `AuditLog.action` is already a string column.
- No env vars. Reuses `SMTP_*`/`smtp-delivery-adapter`'s already-provisioned relay and
  `adapter_registry()` as-is.

## Risks & mitigations

- **A guest with an email that bounces looks identical to one delivered**, per
  `access-notifications.md`'s own declared limit ("`SENT` significa «el relay lo aceptó», no
  «llegó a un buzón»"). Mitigation: none beyond what the platform already accepts for every
  other `EMAIL` notification; out of scope to solve here (proposal's "Out of scope" already
  excludes changing the token/adapter contract).
- **Sending re-mints the token (D4 step 3), so a guest mid-session with the old link is cut off
  the moment "send" is clicked**, exactly as minting already does today for the existing `POST`.
  Not a new risk this change introduces — R1.1's live-status display is what lets an operator
  see there is already a live link before deciding to re-send.
- **The `find_live_for_reservation` addition contradicts a documented invariant** (D3) — mitigated
  by rewriting the docstring in the same commit that adds the method, not leaving the old
  claim stale next to new code that violates it.
- **`Guest.preferred_language` defaults to `"es"` for every guest today** (D6) since nothing
  populates it yet — not a regression this change causes, and every guest gets a functioning
  email either way; revisit if/when a real writer for that column exists.

## Open questions

None blocking. D1-D7 above are the resolved decisions; each states its rejected alternative.
The one genuinely open item — exact frontend file path for `GuestPortalLinkCard` under
`frontend/features/reservations/` — is left to `/sdd:tasks`/`/sdd:run` to place next to
whatever the existing detail screen's component structure already is, not a design-level
decision.
