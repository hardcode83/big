# Tasks: guest-link-delivery

## 1. Domain: token status, notification type, email templates

- [ ] 1.1 Add `issued_at: datetime` to the `GuestAccessToken` dataclass
      (`backend/app/guests/domain/portal_ports.py:26-38`). [R2, D2]
- [ ] 1.2 Add `find_live_for_reservation(tenant_id, reservation_id) -> GuestAccessToken | None`
      to the `GuestAccessTokenRepository` `Protocol` (`portal_ports.py:313-366`). Rewrite the
      class docstring (lines 314-320) to state what now reads by reservation (presence,
      `revoked_at`, `issued_at`) and why rule 3(a)'s "returned once" still holds (`token_hash`
      is never exposed by this method). [R2, D3]
- [ ] 1.3 Add `NotificationType.GUEST_PORTAL_LINK_DELIVERED` to
      `backend/app/notifications/domain/enums.py`, declared as an explicit PRD §14 divergence
      like `PASSWORD_RESET_REQUESTED`/`REVIEW_RESPONSE_APPROVED`. Add/confirm a test asserting
      `escalation_for` returns `None` for it (no SLA deadline). [R4.1, R4.2]
- [ ] 1.4 Add audit action `GUEST_ACCESS_TOKEN_SENT` next to `GUEST_ACCESS_TOKEN_ISSUED`/
      `_REVOKED` in the guests audit vocabulary (`backend/app/audit/domain/actions.py` or
      wherever those two already live — follow the existing constant, not a new module).
      [R3.6]
- [ ] 1.5 New `backend/app/guests/domain/notifications.py`:
      `render_guest_link_email(language: str) -> tuple[str, str]` returning constant
      `(subject, body)` for `es`/`en`, falling back to `es` for any other value, with **no
      interpolation of guest name, reservation id, or link** — only fixed prose (R3.4). Unit
      tests for both languages and the fallback. [R3.4, D6]

## 2. Infrastructure: repository read, row mapping

- [ ] 2.1 Implement `find_live_for_reservation` on `SqlAlchemyGuestAccessTokenRepository`
      (`backend/app/guests/infrastructure/portal_repositories.py`): `WHERE tenant_id = :tenant
      AND reservation_id = :reservation AND revoked_at IS NULL`, same predicate the partial
      unique index enforces. [R2.1, R2.3, D3]
- [ ] 2.2 Map `issued_at` from `GuestAccessTokenModel.created_at` in the existing row→entity
      conversion. [R2, D2]
- [ ] 2.3 Integration tests (`backend/tests/guests/`): live token found, no token found, only a
      revoked token found (→ `None`), a live token of another tenant not found (tenant
      isolation, security rule 1). [R2.1, R2.3]

## 3. Application: status and send use cases <!-- hard -->

- [ ] 3.1 New `GetGuestAccessTokenStatusUseCase` (`backend/app/guests/application/portal.py`),
      using `PortalStayLocator.find` (404 for absent/foreign-tenant stay) then
      `GuestAccessTokenRepository.find_live_for_reservation`, returning presence + `issued_at`
      only — never `token_hash`. [R2.1, R2.2, R2.3]
- [ ] 3.2 New `SendGuestAccessTokenUseCase` (`portal.py`) per design D4: load the stay via
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
- [ ] 3.3 Unit tests for `SendGuestAccessTokenUseCase` with fakes: happy path (mint + `SENT` +
      audit, one commit); adapter reports failure (mint still committed, row `FAILED` with its
      error code, R3.5); no `Guest` linked (422, `IssueGuestAccessTokenUseCase` never called);
      blank email (422, same); foreign-tenant reservation (404). [R3.1-R3.6]
- [ ] 3.4 Update `backend/tests/test_writer_census.py`: move `GUEST_PORTAL_LINK_DELIVERED` from
      `WITHOUT_WRITER` to `WITH_WRITER`, attributed to this change's builder. [R4.3]

## 4. API: routes, schemas, DI wiring, OpenAPI

- [ ] 4.1 New schemas in `backend/app/guests/api/schemas.py`:
      `GuestAccessTokenStatusResponse { is_live: bool, issued_at: datetime | None }`,
      `GuestAccessTokenSentResponse { delivered: bool }`. [D5]
- [ ] 4.2 New routes on `backend/app/guests/api/router.py`, same `ManageAccessTokenDep` and
      404-for-foreign-tenant convention as the existing `POST`/`DELETE`:
      `GET /api/v1/reservations/{reservation_id}/guest-access-token` (status) and
      `POST /api/v1/reservations/{reservation_id}/guest-access-token/send` (mint + deliver,
      `422` on no-guest/blank-email). Docstrings in the same style as the two existing routes.
      [R1.1, R2.1, R3.1, R3.2, D5]
- [ ] 4.3 Wire both in `backend/app/guests/api/dependencies.py`: the status use case (existing
      repositories only); the send use case with `SqlAlchemyGuestRepository`,
      `adapter_registry()`, `SqlAlchemyNotificationLogRepository`, and the composed
      `IssueGuestAccessTokenUseCase` built with `uow=CallerOwnedUnitOfWork()`. [D4, D5]
- [ ] 4.4 Update `backend/tests/test_route_authorization.py`'s permission census for the two new
      routes (both require `MANAGE_GUEST_ACCESS_TOKENS`, neither is anonymous). [security
      rule 2]
- [ ] 4.5 Integration tests (httpx `AsyncClient`): `GET` status (live/none), `POST /send`
      (delivered `true`/`false`, `422` no-guest, `422` blank-email, `404` foreign-tenant, `403`
      without the permission). [R1-R3]
- [ ] 4.6 Regenerate and commit `backend/openapi.json` (`make openapi`) — the `api-contract`
      workflow checks it matches the code (`steering/documentation.md`). [documentation]

## 5. Frontend: data source, hooks, UI

- [ ] 5.1 Regenerate `frontend/lib/api/generated/openapi.d.ts`
      (`cd frontend && npm run api:generate`, or the worktree copy-then-generate recipe in
      `sdd/project.md` § Worktree bootstrap) and commit it — the `frontend-api-contract`
      workflow checks it matches `backend/openapi.json`. [documentation]
- [ ] 5.2 Extend `frontend/features/reservations/data/{dto.ts,http/http-reservations-source.ts,
      index.ts}` with four operations: `getGuestAccessTokenStatus`, `issueGuestAccessToken`,
      `revokeGuestAccessToken`, `sendGuestAccessTokenEmail` — typed against the regenerated
      contract, following the existing `HttpReservationsSource` method shape. [R1, R2, R3, D7]
- [ ] 5.3 Add query keys for the new status query in
      `frontend/features/reservations/hooks/query-keys.ts` (`tenantScopedKey(tenantId,
      "guest-access-token-status", reservationId)`), and four hooks in
      `frontend/features/reservations/hooks/use-reservations.ts` (or a new
      `use-guest-access-token.ts` file, implementer's call): `useGuestAccessTokenStatus`
      (query), `useIssueGuestAccessToken`, `useRevokeGuestAccessToken`,
      `useSendGuestAccessTokenEmail` (mutations, each invalidating the status query key on
      success). [R1, R2, R3, D7]
- [ ] 5.4 New component `GuestPortalLinkCard`
      (`frontend/features/reservations/components/detail/guest-portal-link-card.tsx`), gated by
      `useHasPermission(Permission.MANAGE_GUEST_ACCESS_TOKENS)` — renders nothing when absent
      (R1.4). Shows live/none + `issued_at` (R1.1); a mint action revealing the token exactly
      once in a `TemporaryPasswordReveal`-style control that never re-displays after unmount
      (R1.2, mirroring `features/platform/components/temporary-password-reveal.tsx`); a revoke
      action updating status without reload (R1.3); a send action surfacing `delivered`
      true/false as inline feedback (R3.5). Every triggering control `disabled` while its
      mutation `isPending` (R1.5). [R1, R3, D7]
- [ ] 5.5 Wire `GuestPortalLinkCard` into `composeDetailSections`/`reservation-detail-view.tsx`
      as a new section rendered after `sections.guest`. [R1.1]
- [ ] 5.6 Add i18n keys to `frontend/locales/{es,en}/reservations.json` for every string the
      card renders (status, issued-since, copy, copied, revoke, send, delivered, not-delivered,
      warning) — nothing hardcoded (`steering/frontend.md`). [documentation]
- [ ] 5.7 Component tests (Testing Library) for `GuestPortalLinkCard`: hidden without the
      permission; one-time reveal never reappears after unmount/remount; controls disabled
      while pending; status renders live/none correctly; send surfaces delivered vs.
      not-delivered. [R1, R3, testing.md]

## 6. Verification

- [ ] 6.1 Backend suite green: `docker compose exec backend uv run pytest` (stack up) or
      `docker compose run --rm backend uv run pytest` (stack down).
- [ ] 6.2 Backend static typecheck clean: `uv run pyright .` (from `backend`, after `uv sync
      --frozen`).
- [ ] 6.3 `make check-rule11-ownership` green (host, no Docker) — this change adds no new
      free-text sink, so it should be a no-op pass; run it anyway because it touches
      `notification_logs`-adjacent code.
- [ ] 6.4 Frontend: `npm test` green; `npm run api:check` reports no drift against
      `backend/openapi.json`.
- [ ] 6.5 Manual end-to-end pass: from `/reservations/[id]`, mint the link and copy it; open
      `/guest/[token]` in a second browser context and confirm the portal loads; trigger
      "send" and confirm the email arrives (dev SMTP relay or `ConsoleEmailAdapter` log line);
      revoke and confirm the previously-copied link no longer authorizes the portal. <!-- manual -->

## Implementation Notes
