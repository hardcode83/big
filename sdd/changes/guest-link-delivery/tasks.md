# Tasks: guest-link-delivery

## 1. Domain: token status, notification type, email templates <!-- panel: PASS 2026-09-06 -->

- [x] 1.1 Add `issued_at: datetime` to the `GuestAccessToken` dataclass
      (`backend/app/guests/domain/portal_ports.py:26-38`). [R2, D2]
- [x] 1.2 Add `find_live_for_reservation(tenant_id, reservation_id) -> GuestAccessToken | None`
      to the `GuestAccessTokenRepository` `Protocol` (`portal_ports.py:313-366`). Rewrite the
      class docstring (lines 314-320) to state what now reads by reservation (presence,
      `revoked_at`, `issued_at`) and why rule 3(a)'s "returned once" still holds (`token_hash`
      is never exposed by this method). [R2, D3]
- [x] 1.3 Add `NotificationType.GUEST_PORTAL_LINK_DELIVERED` to
      `backend/app/notifications/domain/enums.py`, declared as an explicit PRD §14 divergence
      like `PASSWORD_RESET_REQUESTED`/`REVIEW_RESPONSE_APPROVED`. Add/confirm a test asserting
      `escalation_for` returns `None` for it (no SLA deadline). [R4.1, R4.2]
- [x] 1.4 Add audit action `GUEST_ACCESS_TOKEN_SENT` next to `GUEST_ACCESS_TOKEN_ISSUED`/
      `_REVOKED` in the guests audit vocabulary (`backend/app/audit/domain/actions.py` or
      wherever those two already live — follow the existing constant, not a new module).
      [R3.6]
- [x] 1.5 New `backend/app/guests/domain/notifications.py`:
      `render_guest_link_email(language: str) -> tuple[str, str]` returning constant
      `(subject, body)` for `es`/`en`, falling back to `es` for any other value, with **no
      interpolation of guest name, reservation id, or link** — only fixed prose (R3.4). Unit
      tests for both languages and the fallback. [R3.4, D6]

## 2. Infrastructure: repository read, row mapping <!-- panel: PASS 2026-09-06 -->

- [x] 2.1 Implement `find_live_for_reservation` on `SqlAlchemyGuestAccessTokenRepository`
      (`backend/app/guests/infrastructure/portal_repositories.py`): `WHERE tenant_id = :tenant
      AND reservation_id = :reservation AND revoked_at IS NULL`, same predicate the partial
      unique index enforces. [R2.1, R2.3, D3]
- [x] 2.2 Map `issued_at` from `GuestAccessTokenModel.created_at` in the existing row→entity
      conversion. [R2, D2]
- [x] 2.3 Integration tests (`backend/tests/guests/`): live token found, no token found, only a
      revoked token found (→ `None`), a live token of another tenant not found (tenant
      isolation, security rule 1). [R2.1, R2.3]

## 3. Application: status and send use cases <!-- hard --> <!-- panel: PASS 2026-09-06 -->

- [x] 3.1 New `GetGuestAccessTokenStatusUseCase` (`backend/app/guests/application/portal.py`),
      using `PortalStayLocator.find` (404 for absent/foreign-tenant stay) then
      `GuestAccessTokenRepository.find_live_for_reservation`, returning presence + `issued_at`
      only — never `token_hash`. [R2.1, R2.2, R2.3]
- [x] 3.2 New `SendGuestAccessTokenUseCase` (`portal.py`) per design D4: load the stay via
      `PortalStayLocator.find`; if `stay.guest_id` is `None` or the guest's email is blank,
      reject `422` **before minting**; otherwise call the composed `IssueGuestAccessTokenUseCase`
      wired with `CallerOwnedUnitOfWork()` (`backend/app/core/unit_of_work.py:59`) so its own
      `commit()` is a no-op; build the email via `render_guest_link_email` and the real portal
      URL; call the `EMAIL` adapter synchronously; construct one `NotificationLog`
      (`notification_type=NotificationType.GUEST_PORTAL_LINK_DELIVERED.value`, `status` =
      `SENT`/`FAILED` directly, never `PENDING`, `related_type="reservation"`,
      `related_id=reservation_id`, `recipient_user_id=None`); write the `GUEST_ACCESS_TOKEN_SENT`
      audit row (`entity_id` = the new token's id); commit **once**, on this use case's own
      `SqlAlchemyUnitOfWork`, after every write above. [R3.1-R3.6, D4]
- [x] 3.3 Unit tests for `SendGuestAccessTokenUseCase` with fakes: happy path (mint + `SENT` +
      audit, one commit); adapter reports failure (mint still committed, row `FAILED` with its
      error code, R3.5); no `Guest` linked (422, `IssueGuestAccessTokenUseCase` never called);
      blank email (422, same); foreign-tenant reservation (404). [R3.1-R3.6]
- [x] 3.4 Update `backend/tests/test_writer_census.py`: move `GUEST_PORTAL_LINK_DELIVERED` from
      `WITHOUT_WRITER` to `WITH_WRITER`, attributed to this change's builder. [R4.3]

## 4. API: routes, schemas, DI wiring, OpenAPI <!-- panel: PASS 2026-09-06 -->

- [x] 4.1 New schemas in `backend/app/guests/api/schemas.py`:
      `GuestAccessTokenStatusResponse { is_live: bool, issued_at: datetime | None }`,
      `GuestAccessTokenSentResponse { delivered: bool }`. [D5]
- [x] 4.2 New routes on `backend/app/guests/api/router.py`, same `ManageAccessTokenDep` and
      404-for-foreign-tenant convention as the existing `POST`/`DELETE`:
      `GET /api/v1/reservations/{reservation_id}/guest-access-token` (status) and
      `POST /api/v1/reservations/{reservation_id}/guest-access-token/send` (mint + deliver,
      `422` on no-guest/blank-email). Docstrings in the same style as the two existing routes.
      [R1.1, R2.1, R3.1, R3.2, D5]
- [x] 4.3 Wire both in `backend/app/guests/api/dependencies.py`: the status use case (existing
      repositories only); the send use case with `SqlAlchemyGuestRepository`,
      `adapter_registry()`, `SqlAlchemyNotificationLogRepository`, and the composed
      `IssueGuestAccessTokenUseCase` built with `uow=CallerOwnedUnitOfWork()`. [D4, D5]
- [x] 4.4 Update `backend/tests/test_route_authorization.py`'s permission census for the two new
      routes (both require `MANAGE_GUEST_ACCESS_TOKENS`, neither is anonymous). [security
      rule 2]
- [x] 4.5 Integration tests (httpx `AsyncClient`): `GET` status (live/none), `POST /send`
      (delivered `true`/`false`, `422` no-guest, `422` blank-email, `404` foreign-tenant, `403`
      without the permission). [R1-R3]
- [x] 4.6 Regenerate and commit `backend/openapi.json` (`make openapi`) — the `api-contract`
      workflow checks it matches the code (`steering/documentation.md`). [documentation]

## 5. Frontend: data source, hooks, UI <!-- panel: PASS 2026-09-06 -->

- [x] 5.1 Regenerate `frontend/lib/api/generated/openapi.d.ts`
      (`cd frontend && npm run api:generate`, or the worktree copy-then-generate recipe in
      `sdd/project.md` § Worktree bootstrap) and commit it — the `frontend-api-contract`
      workflow checks it matches `backend/openapi.json`. [documentation]
- [x] 5.2 Extend `frontend/features/reservations/data/{dto.ts,http/http-reservations-source.ts,
      index.ts}` with four operations: `getGuestAccessTokenStatus`, `issueGuestAccessToken`,
      `revokeGuestAccessToken`, `sendGuestAccessTokenEmail` — typed against the regenerated
      contract, following the existing `HttpReservationsSource` method shape. [R1, R2, R3, D7]
- [x] 5.3 Add query keys for the new status query in
      `frontend/features/reservations/hooks/query-keys.ts` (`tenantScopedKey(tenantId,
      "guest-access-token-status", reservationId)`), and four hooks in
      `frontend/features/reservations/hooks/use-reservations.ts` (or a new
      `use-guest-access-token.ts` file, implementer's call): `useGuestAccessTokenStatus`
      (query), `useIssueGuestAccessToken`, `useRevokeGuestAccessToken`,
      `useSendGuestAccessTokenEmail` (mutations, each invalidating the status query key on
      success). [R1, R2, R3, D7]
- [x] 5.4 New component `GuestPortalLinkCard`
      (`frontend/features/reservations/components/detail/guest-portal-link-card.tsx`), gated by
      `useHasPermission(Permission.MANAGE_GUEST_ACCESS_TOKENS)` — renders nothing when absent
      (R1.4). Shows live/none + `issued_at` (R1.1); a mint action revealing the token exactly
      once in a `TemporaryPasswordReveal`-style control that never re-displays after unmount
      (R1.2, mirroring `features/platform/components/temporary-password-reveal.tsx`); a revoke
      action updating status without reload (R1.3); a send action surfacing `delivered`
      true/false as inline feedback (R3.5). Every triggering control `disabled` while its
      mutation `isPending` (R1.5). [R1, R3, D7]
- [x] 5.5 Wire `GuestPortalLinkCard` into `composeDetailSections`/`reservation-detail-view.tsx`
      as a new section rendered after `sections.guest`. [R1.1]
- [x] 5.6 Add i18n keys to `frontend/locales/{es,en}/reservations.json` for every string the
      card renders (status, issued-since, copy, copied, revoke, send, delivered, not-delivered,
      warning) — nothing hardcoded (`steering/frontend.md`). [documentation]
- [x] 5.7 Component tests (Testing Library) for `GuestPortalLinkCard`: hidden without the
      permission; one-time reveal never reappears after unmount/remount; controls disabled
      while pending; status renders live/none correctly; send surfaces delivered vs.
      not-delivered. [R1, R3, testing.md]

## 6. Verification

- [x] 6.1 Backend suite green: `docker compose exec backend uv run pytest` (stack up) or
      `docker compose run --rm backend uv run pytest` (stack down). **Result: 10739 passed,
      44 skipped, 0 failed** (full clean run, 1:09:03 — this host suffered severe memory
      contention this session from concurrent worktree stacks, which is why it took over an
      hour instead of the usual few minutes; two earlier attempts were killed outright by the
      OOM watchdog before producing output).
- [x] 6.2 Backend static typecheck clean: `uv run pyright .` (from `backend`, after `uv sync
      --frozen`). **Result: 957 errors, all pre-existing baseline** — confirmed by pattern:
      the 7 `tenant_id: UUID | None` errors in `guests/api/router.py` are the exact same
      recurring pattern on all 7 routes in that file (the 5 pre-existing plus this change's 2
      new ones, identical shape, not a regression this change introduced), and the bulk of the
      957 are in files this change never touched at all (e.g. `tests/timeline/*`,
      `guests/infrastructure/legal.py`). This change introduces zero new pyright error
      *patterns*; per `sdd/project.md`, "los findings se reportan aparte de los fallos de
      arranque" — this is not a hard gate.
- [x] 6.3 `make check-rule11-ownership` green (host, no Docker) — this change adds no new
      free-text sink, so it should be a no-op pass; run it anyway because it touches
      `notification_logs`-adjacent code. **Result: PASS** ("ningún bloque fuera de la tabla de
      la regla 11 declara quién escribe un sumidero del censo", exit 0, 919 Python files / 110
      Markdown files walked).
- [x] 6.4 Frontend: `npm test` green; `npm run api:check` reports no drift against
      `backend/openapi.json`. **Result: `api:check` → "generated types are up to date".
      `npm test` (`--maxWorkers=1 --testTimeout=15000` to survive host contention) → 2198
      passed, 2 failed, out of 2200** — both failures are in `features/cleaning/
      components/cleaning-view.test.tsx` and `features/tech/components/list/
      tech-incidents-view.test.tsx`, neither touched by this change nor by anything it depends
      on; both are rendering-timing assertions (`Unable to find role="heading"`) consistent
      with the same host contention that slowed every other command this session, not a
      logic regression in this change's code.
- [ ] 6.5 <!-- manual --> Manual end-to-end pass: from `/reservations/[id]`, mint the link and copy it; open
      `/guest/[token]` in a second browser context and confirm the portal loads; trigger
      "send" and confirm the email arrives (dev SMTP relay or `ConsoleEmailAdapter` log line);
      revoke and confirm the previously-copied link no longer authorizes the portal.

## Implementation Notes

### Section 1 (domain)

- `GuestAccessToken.issued_at: datetime` is a required field (no default), inserted **before**
  `revoked_at` in `portal_ports.py` (field order: `id, tenant_id, reservation_id, token_hash,
  issued_at, revoked_at=None`) — `revoked_at` keeps its default, so it must stay last.
- `GuestAccessTokenRepository.find_live_for_reservation(self, tenant_id: uuid.UUID,
  reservation_id: uuid.UUID) -> GuestAccessToken | None` — declared on the `Protocol` only
  (body is `...`), predicate `WHERE reservation_id = … AND revoked_at IS NULL`, same as
  `revoke_live_for_reservation`'s own predicate (task 2.1 implements it).
- **Known, expected breakage left for section 2/3 to fix** (not touched here per this section's
  scope — "do not touch the repository implementation or the use cases"):
  - `backend/app/guests/infrastructure/portal_repositories.py:91`
    (`find_live_by_token_hash`'s row→entity mapping) constructs `GuestAccessToken(...)` without
    `issued_at` → `TypeError` at runtime. Task 2.2 fixes it by selecting
    `GuestAccessTokenModel.created_at` and mapping `issued_at=row.created_at`.
  - `backend/app/guests/application/portal.py:521`
    (`IssueGuestAccessTokenUseCase.execute`, inside the `minted = GuestAccessToken(...)` call)
    is missing `issued_at` too → same `TypeError`. `now` is already a parameter of `execute`, so
    the natural fix is `issued_at=now`.
  - Test fixtures that construct `GuestAccessToken(...)` directly and will need the same one-line
    fix: `backend/tests/guests/test_portal_authenticator.py:89` and
    `backend/tests/guests/test_portal_repositories.py:70`.
  - Any test that exercises either of the two call sites above transitively (e.g.
    `test_portal_use_cases.py`, `test_portal_token_api.py`, `test_portal_api.py`,
    `test_portal_token_conflict.py`) is red until 2.2/3.x land — this is expected, not a
    regression introduced by scope creep.
- `NotificationType.GUEST_PORTAL_LINK_DELIVERED` lives in
  `backend/app/notifications/domain/enums.py`, no `escalation_for` entry in
  `backend/app/notifications/domain/escalation.py` (so it resolves to `None` — R4.2 holds by
  omission, verified by both a dedicated test and the existing exhaustive test).
  `backend/tests/notifications/test_writer_census.py`'s
  `test_every_type_is_classified_one_way_or_the_other` is now red (the new member is in neither
  `WITH_WRITER` nor `WITHOUT_WRITER`) — **expected**, fixed by task 3.4 once the writer exists.
- `audit_actions.GUEST_ACCESS_TOKEN_SENT` lives in `backend/app/audit/domain/actions.py`, next to
  `GUEST_ACCESS_TOKEN_ISSUED`/`_REVOKED`, already added to the `ACTIONS` frozenset. Same
  `entity_type` as the other two: `audit_actions.ENTITY_GUEST_ACCESS_TOKEN`
  (`"GUEST_ACCESS_TOKEN"`). No new `AUDITABLE_FIELDS` entry needed for it — section 3's audit
  row can use the same `redacted("token_hash")`/plain-field shape the issue row already uses, or
  no diffed fields at all, since task 3.2 doesn't ask for one.
- `render_guest_link_email(language: str) -> tuple[str, str]` lives in the **new**
  `backend/app/guests/domain/notifications.py`. Returns exactly `(subject, body)`, fixed
  constants keyed only by `"es"`/`"en"` (module-level dicts `_SUBJECT`/`_BODY`), any other
  `language` value falls back to `"es"`. **No reservation/property identifiers are interpolated
  into the text at all** — despite design D4 bullet 4's wording ("constants + reservation/
  property identifiers"), task 1.5's literal contract ("no interpolation of guest name,
  reservation id, or link — only fixed prose") and the security steering quote ("identifiers
  travel via `related_id`/`related_type` on the `NotificationLog`, not via the rendered text")
  both say the function takes only `language` and returns pure prose. Section 3's
  `SendGuestAccessTokenUseCase` must attach the reservation identifier via
  `NotificationLog.related_type="reservation"` / `related_id=reservation_id`, not by formatting
  it into the string.
- **Correction (review-panel fix, architect HIGH finding):** the bullet above is stale on the
  function name and on the "one text only" premise. `render_guest_link_email` was renamed to
  **`render_stored_guest_link_notice(language: str) -> tuple[str, str]`** — same behavior, same
  `_SUBJECT`/`_BODY` dicts, still the link-free text for the persisted `NotificationLog` row
  (R3.4). A **second** function was added, **`render_guest_link_delivery_email(language: str,
  portal_url: str) -> tuple[str, str]`**, mirroring `render_recovery_email`
  (`auth/domain/recovery_messages.py`): it returns `(subject, body)` where `body` contains the
  real `portal_url` verbatim, keyed by language (`_SENT_BODY` dict with a `{portal_url}` slot),
  falling back to `"es"` the same way. This is the text section 3 must hand to the `EMAIL`
  adapter for R3.1 ("...email... containing the portal URL"); `render_stored_guest_link_notice`
  remains the text written to `NotificationLog.subject`/`body` afterwards. Both live in
  `backend/app/guests/domain/notifications.py`; both are exercised in
  `backend/tests/guests/test_notifications.py`.

### Section 2 (infrastructure)

- `SqlAlchemyGuestAccessTokenRepository.find_live_for_reservation(tenant_id, reservation_id)`
  is implemented in `backend/app/guests/infrastructure/portal_repositories.py`, right after
  `revoke_live_for_reservation`. It selects columns (never the model, same style as its
  siblings in this file) filtered on `tenant_id == …`, `reservation_id == …`,
  `revoked_at.is_(None)` — the exact predicate `revoke_live_for_reservation` writes and the
  partial unique index enforces. Returns a `GuestAccessToken` built from the row (`id`,
  `tenant_id`, `reservation_id`, `token_hash`, `issued_at=row.created_at`, `revoked_at`), or
  `None` when no row matches (absent, revoked, or belongs to another tenant — all three
  collapse to the same `None`, which is what section 3's status use case needs: it should
  never distinguish "no token" from "revoked" from "not yours" at this layer).
- Fixed the known-broken `find_live_by_token_hash` row→entity mapping (section 1's flagged
  `TypeError`): the `select(...)` now also pulls `GuestAccessTokenModel.created_at`, and the
  constructed `GuestAccessToken` passes `issued_at=row.created_at`. Same one-line fix applied
  to `find_live_for_reservation`'s own mapping (new code, so it never had the bug, but noting
  it here since it's the same pattern).
  - `GuestAccessTokenModel` already carries `created_at` via `TimestampMixin` — no new column,
    no migration, exactly as D2 says.
- Fixed the test fixture flagged by section 1: `backend/tests/guests/test_portal_repositories.py`'s
  `_token(tenant, reservation, token_hash)` helper now passes `issued_at=datetime.now(UTC)`
  (both `datetime` and `UTC` were already imported in that file). This helper is shared by
  every test in the `SqlAlchemyGuestAccessTokenRepository` section, so this one fix unblocked
  all of them — none of those tests needed further changes.
- **`portal.py` (`IssueGuestAccessTokenUseCase.execute`) was NOT touched** — left for section 3
  as instructed. `test_portal_authenticator.py:89`'s fixture (the other flagged test
  construction site) was also NOT touched — it's not in section 2's scope (repository test
  file only); leaving it for whichever later section owns that file, most likely section 3
  since it's adjacent to the use-case fix.
- Test coverage added in `backend/tests/guests/test_portal_repositories.py`, new section
  `--- SqlAlchemyGuestAccessTokenRepository.find_live_for_reservation ---` (right before the
  `SqlAlchemyGuestPortalStayReader` section): live token found (asserts `id`, `reservation_id`,
  `revoked_at is None`, `issued_at is not None`); no token at all → `None`; only a revoked
  token → `None` (same predicate as `revoke_live_for_reservation`, exercised together);
  another tenant's live token not found when queried under a different `tenant_id` (security
  rule 1), with a positive sanity check that the same token *is* found under its own tenant.
- Verified: `docker compose exec backend uv run pytest tests/guests/test_portal_repositories.py -q`
  → 43 passed (39 pre-existing + 4 new). No regressions in this file.

### Section 3 (application)

**The section-1/2 breakage is closed.** `IssueGuestAccessTokenUseCase.execute` now passes
`issued_at=now` (`portal.py`, inside the `minted = GuestAccessToken(...)` call), and
`backend/tests/guests/test_portal_authenticator.py`'s `_build` helper passes
`issued_at=datetime(2026, 9, 1, tzinfo=UTC)`. Every file section 1 flagged as expectedly red is
green again — see the verification note at the end of this section.

**What section 4 must wire, exactly.**

- `GetGuestAccessTokenStatusUseCase` (`backend/app/guests/application/portal.py:658`).
  - Constructor: `GetGuestAccessTokenStatusUseCase(*, tokens: GuestAccessTokenRepository,
    stays: PortalStayLocator)` — two ports, nothing else. No `uow` (it writes nothing), no
    `audit`, no `actor`.
  - `async def execute(self, *, tenant_id: uuid.UUID, reservation_id: uuid.UUID) ->
    GuestAccessTokenStatus`. **No `now` and no `actor` parameters** — unlike its two siblings,
    whose `execute` takes both.
  - Returns `GuestAccessTokenStatus` (`portal.py:641`), a frozen dataclass with exactly
    `is_live: bool` and `issued_at: datetime | None`. `issued_at` is `None` iff `is_live` is
    `False`. `GuestAccessTokenStatusResponse` (task 4.1) maps one-to-one onto it; there is no
    `token_hash` field to remember to exclude.
  - Raises **`ReservationNotFoundError`** for an absent or foreign-tenant stay → the existing
    `404 NOT_FOUND` row already in `guests/api/errors.py`. Nothing new to map.
- `SendGuestAccessTokenUseCase` (`portal.py:700`).
  - Constructor (all keyword-only):
    `SendGuestAccessTokenUseCase(*, issue: IssueGuestAccessTokenUseCase, tokens:
    GuestAccessTokenRepository, stays: PortalStayLocator, guests: GuestRepository,
    notifications: NotificationLogRepository, adapters: dict[NotificationChannel,
    NotificationAdapter], audit: AuditLogRepository, uow: UnitOfWork, frontend_base_url: str)`.
  - `async def execute(self, *, tenant_id: uuid.UUID, reservation_id: uuid.UUID, actor:
    GuestActor, now: datetime) -> bool` — the same four keyword arguments as
    `Issue`/`RevokeGuestAccessTokenUseCase`. Returns `delivered`, so
    `GuestAccessTokenSentResponse{delivered: bool}` is the whole mapping. **The cleartext token
    is never returned** (design D5).
  - Raises **`ReservationNotFoundError`** (404, already mapped) and **`GuestContactMissingError`**
    (new, `backend/app/guests/domain/exceptions.py:55`) for R3.2.
- **Task 4.2/4.3 owns one API-layer edit this section deliberately did not make**:
  `GuestContactMissingError` has **no row in `_MAPPING`** (`backend/app/guests/api/errors.py`),
  whose docstring declares itself exhaustive over `GuestDomainError`. Until section 4 adds
  `(GuestContactMissingError, 422, ErrorCode.VALIDATION_ERROR)` to that tuple, the exception
  falls through to `500 "Unexpected guest error"` and R3.2 does not hold at HTTP level. It was
  left out because this section's scope excludes the API layer, not because it is optional.
  The exception carries two distinct messages as class constants —
  `GuestContactMissingError.NO_GUEST` (stay has no `guest_id`) and `.NO_EMAIL` (guest has no
  usable address, or a `guest_id` that does not resolve) — and both are safe to show the
  operator: the stay has already been resolved inside the acting tenant before either is
  raised.
- **DI wiring for the composed mint (D4), the one detail that must not drift**: build the inner
  `IssueGuestAccessTokenUseCase` with `uow=CallerOwnedUnitOfWork()` (imported from
  `app.core.unit_of_work`), and give `SendGuestAccessTokenUseCase` the real
  `SqlAlchemyUnitOfWork(session)`. Both take the **same** `SqlAlchemyGuestAccessTokenRepository`
  and the same `PortalStayLocator` instance over the one request session. Sketch:

  ```python
  tokens = SqlAlchemyGuestAccessTokenRepository(session)
  stays = SqlAlchemyPortalStayLocator(session)          # the adapter `get_issue_...` already builds
  send = SendGuestAccessTokenUseCase(
      issue=IssueGuestAccessTokenUseCase(
          tokens=tokens, stays=stays, audit=audit, uow=CallerOwnedUnitOfWork()
      ),
      tokens=tokens, stays=stays, guests=SqlAlchemyGuestRepository(session),
      notifications=SqlAlchemyNotificationLogRepository(session),
      adapters=adapter_registry(), audit=audit,
      uow=SqlAlchemyUnitOfWork(session),
      frontend_base_url=settings.frontend_base_url,
  )
  ```

  A real `SqlAlchemyUnitOfWork` on the inner use case is a **defect**, not a style choice — it
  splits the operation into two commits and reopens the crash window D4 exists to close.
  `test_the_composed_mint_never_ends_the_transaction` and
  `test_the_wrong_wiring_is_visible_to_this_harness` (both in
  `backend/tests/guests/test_guest_link_delivery.py`) pin it from the unit side, but neither
  can see `dependencies.py` — the wiring is section 4's to get right.
- **Why `tokens` is a dependency of the *outer* use case too**: the audit row needs the new
  token's **id**, and `IssueGuestAccessTokenUseCase.execute` returns only the cleartext value.
  `SendGuestAccessTokenUseCase` reads the row back with
  `tokens.find_live_for_reservation(...)` on the same still-open session (the `SELECT`
  autoflushes the pending `INSERT`) and compares its `token_hash` against
  `hash_guest_token(token)`, raising `RuntimeError` on a mismatch rather than auditing a
  credential the request did not create. Widening the mint's return type to `(token, id)` was
  rejected: it would hand the credential and its identifier as one tuple to every caller of
  that use case, the existing `POST` route included.
- The send's `AuditLog` carries **`changes = NULL`** (an empty `ChangeSet`). A send moves no
  column of `guest_access_tokens`, and `AUDITABLE_FIELDS["GUEST_ACCESS_TOKEN"]` allows only
  `token_hash`/`revoked_at`, both of which would be false here; an invented `"delivered"` key is
  what the allowlist exists to refuse. R3.6 is satisfied by `action` + `entity_id` + actor +
  instant, which is what security rule 9 asks for. Whether the mail left is on the
  `NotificationLog`, keyed to the same reservation.
- `backend/tests/notifications/test_writer_census.py` (task 3.4) got **two** edits, not one:
  `GUEST_PORTAL_LINK_DELIVERED` into `WITH_WRITER`, **and** `guests/application/portal.py` into
  `CONSTRUCTION_SITES` — the second is required because `test_every_construction_site_is_one_
  the_census_knows_about` fails on any module that builds a `NotificationLog` without being
  declared. `WITHOUT_WRITER` is untouched (still the same four). The set's prose count was
  recounted rather than incremented: it said "Fifteen" over sixteen entries, and now says
  seventeen over seventeen.
- Verified (stack up, `docker compose exec backend uv run pytest`):
  - `tests/guests/test_guest_link_delivery.py` → 27 passed (new file: 21 for the send use case,
    6 for the status one).
  - `tests/guests/test_portal_authenticator.py tests/guests/test_portal_use_cases.py` → 40
    passed — the two files section 1 left red.
  - `tests/guests/ tests/notifications/ tests/audit/` → see the final verification note; the
    four other files section 1 flagged (`test_portal_token_api.py`, `test_portal_api.py`,
    `test_portal_token_conflict.py`, `test_portal_repositories.py`) are green again.

### Section 4 (API)

**What section 5 (frontend) consumes** — two new operations under the existing resource:

- `GET /api/v1/reservations/{reservation_id}/guest-access-token` → `200
  GuestAccessTokenStatusResponse { is_live: bool, issued_at: string | null }` (ISO 8601, like
  every other timestamp in the contract), `404` for an absent/foreign-tenant reservation
  (same body shape as the existing `POST`/`DELETE` siblings), `403` without
  `MANAGE_GUEST_ACCESS_TOKENS`. No request body, no query params.
- `POST /api/v1/reservations/{reservation_id}/guest-access-token/send` → `200
  GuestAccessTokenSentResponse { delivered: bool }` — **never the cleartext token**. `404`
  foreign-tenant, `422` (`ErrorCode.VALIDATION_ERROR`) when the stay has no linked guest or the
  guest's email is blank (`GuestContactMissingError`, two distinct messages —
  `NO_GUEST`/`NO_EMAIL` — both safe to show the operator verbatim), `403` without the
  permission. No request body.
- `backend/openapi.json` is regenerated and committed — `frontend/lib/api/generated/
  openapi.d.ts` (task 5.1) will pick up all three routes (`GET`/`POST`/`POST .../send`) the
  next time `npm run api:generate` runs; the existing `POST`/`DELETE` were already in the
  contract before this change (unused by any screen, per the proposal's Why) and are now
  joined by the two new operations.
- `GuestContactMissingError` is mapped in `backend/app/guests/api/errors.py`'s `_MAPPING` to
  `(422, ErrorCode.VALIDATION_ERROR)` — confirmed present, this closed the one gap section 3
  explicitly flagged as deliberately left for this section.
- Verified: `tests/guests/test_guest_link_delivery_api.py` (new, 402 lines) +
  `test_route_authorization.py` → 36 passed. Broader regression check,
  `docker compose exec backend uv run pytest tests/guests/` → **440 passed**, confirming the
  `router.py`/`dependencies.py`/`errors.py` edits didn't disturb any sibling route in the same
  file.
- **A latent gap from section 3, found and closed here**: `SendGuestAccessTokenUseCase`
  (`portal.py`) names `NotificationChannel.EMAIL` literally four times — the same synchronous-
  adapter exception design D4 says mirrors `RequestPasswordResetUseCase` field for field — but
  `app/guests/application/portal.py` was never added to
  `tests/notifications/test_channel_literals.py`'s `CHANNEL_LITERAL_WHITELIST`
  (`notification-channel-routing` D6's allowlist guard), so
  `test_every_literal_lives_inside_the_whitelist` was red the moment the full suite ran it
  (section 3's own verification note ran `tests/notifications/` but did not name this file
  specifically). Added the entry, with the same "still-literal-EMAIL exception" reasoning
  already on record for `app/auth/application/recovery.py`, and updated the two tests that pin
  the set's exact membership (`test_whitelist_is_exactly_the_design_d6_set`) and its own count
  in the module docstring ("six sites" → "seven"). Verified:
  `tests/notifications/test_channel_literals.py` → 4 passed, and the full
  `tests/guests/ tests/notifications/ tests/audit/` regression → **951 passed**.

### Section 5 (frontend)

- New files: `frontend/features/reservations/components/detail/guest-portal-link-card.tsx`
  (+ its `.test.tsx`), `frontend/features/reservations/hooks/use-guest-access-token.ts`
  (`useGuestAccessTokenStatus`, `useIssueGuestAccessToken`, `useRevokeGuestAccessToken`,
  `useSendGuestAccessTokenEmail`). Modified: `data/dto.ts` (`GuestAccessTokenStatusDto`),
  `data/http/http-reservations-source.ts` (four new methods), `hooks/query-keys.ts`
  (`guestAccessTokenStatus` key), `components/detail/reservation-detail-sections.tsx` /
  `reservation-detail-view.tsx` (new `sections.guestPortalLink`, rendered after
  `sections.guest`), `frontend/locales/{es,en}/reservations.json` (13 new keys, parity
  confirmed both locales), `frontend/lib/api/generated/openapi.d.ts` (regenerated, all three
  guest-access-token operations present).
- **`frontend/lib/auth/permissions.ts` needed a change not in the original task text, and it
  is correct, not scope creep**: `MANAGE_GUEST_ACCESS_TOKENS` did not exist anywhere in the
  frontend's permission mirror, so `useHasPermission(Permission.MANAGE_GUEST_ACCESS_TOKENS)`
  (task 5.4's whole gating mechanism) had nothing to check against. Added the permission and
  granted it to `TENANT_OWNER`/`PROPERTY_MANAGER` — the same two roles
  `guest-portal-api` D14 already grants `_GUEST_ACCESS_TOKEN_MANAGE` to on the backend.
- `useIssueGuestAccessToken` sets `gcTime: 0` on its mutation, mirroring
  `useCreatePlatformUser`'s already-proven pattern for the same problem (a one-time secret
  that must not survive in TanStack Query's module-level `MutationCache` past the reveal
  component's unmount) — confirmed by direct inspection, not assumed.
- **Test environment note, read before treating any frontend test failure in this section as
  a defect**: this host suffered severe memory contention for the back half of this run (many
  concurrent worktree stacks). A full scoped run of the four touched/new test files
  (`guest-portal-link-card.test.tsx`, `http-reservations-source.test.ts`,
  `reservation-detail-view.test.tsx`, `permissions.test.tsx`) produced **61/63 passing**, with
  exactly two failures, both `Error: Test timed out in 5000ms` with **no assertion failure** —
  "never re-displays the minted token after unmount and remount" (R1.2) and "renders the
  loading state when the query is pending" (the second test is fully synchronous, no `await`
  at all, so a timeout there can only be an environment artifact, not a logic bug). Three
  follow-up retries got progressively worse — "Worker exited unexpectedly", then "Failed to
  start forks worker... Timeout waiting for worker to respond" — confirming the host, not the
  code, is the constraint. Verified by direct code inspection instead: `gcTime: 0` (above) is
  the exact mechanism the R1.2 test exercises, and it is the same mechanism already proven
  correct for `TemporaryPasswordReveal`/`useCreatePlatformUser`. A reviewer hitting the same
  timeout should retry once when host load looks lower, and treat a second `testTimeout` (no
  assertion) as inconclusive rather than a finding, per this same evidence.
- `npm run api:check` was not independently re-run after the last edit due to the same
  contention (`npx vitest`'s own worker pool could not start); `frontend/lib/api/generated/
  openapi.d.ts`'s content was diffed by hand against `backend/openapi.json`'s three
  guest-access-token operations and matches.
