# Tasks: super-admin-identity

## 1. Schema: `tenant_id` becomes nullable on `users` and `user_sessions` <!-- panel: PASS 2026-09-02 -->

- [x] 1.1 `backend/app/auth/infrastructure/models.py`: drop `TenantScopedMixin` from
      `UserModel` and `UserSessionModel`; declare `tenant_id: Mapped[uuid.UUID | None]` by
      hand on each (same `Uuid` type, `ForeignKey("tenants.id")`, `index=True`), mirroring
      `WebhookEventModel` (`backend/app/integrations/infrastructure/models.py`). [R1.1, R1.2]
      **Panel amendment (2026-09-02):** `UserModel.__table_args__` gains
      `CheckConstraint("(role = 'SUPER_ADMIN') = (tenant_id IS NULL)",
      name="ck_users_super_admin_tenant_id_null")` — R1.2 ("la relajación no alcanza a
      ningún otro rol") had no enforcement at all before this: nothing stopped a
      `TENANT_OWNER`/`PROPERTY_MANAGER`/`CLEANER`/`TECHNICIAN` row from acquiring
      `tenant_id IS NULL` and then authenticating with its session left unmarked while
      holding that role's full permissions. Found and demonstrated live (rollback-only) by
      the review panel.
- [x] 1.2 New Alembic migration (`backend/alembic/versions/<new>_super_admin_identity.py`):
      `ALTER COLUMN users.tenant_id DROP NOT NULL` and the same for
      `user_sessions.tenant_id`, no backfill. `downgrade()` first queries both tables for
      `tenant_id IS NULL` rows and raises rather than reinstating `NOT NULL` over data that
      already violates it. [R1.3, R1.4] **Panel amendment:** `upgrade()` also creates
      `ck_users_super_admin_tenant_id_null` (see 1.1); `downgrade()` drops it before
      reinstating `NOT NULL`, after the existing NULL-row check.
- [x] 1.3 `backend/tests/test_migrations.py`: add a chain-walk test for the new revision
      mirroring the existing `assignment_note`/`eta_at` pattern —
      (a) upgrade with a `NULL` `tenant_id` row already present in each table succeeds and the
      column reports nullable; (b) downgrade with no `NULL` row present succeeds and restores
      `NOT NULL`; (c) downgrade with a `NULL` row present raises instead of altering the
      column. [R1.3, R1.4]
- [x] 1.4 Confirm `alembic check` (`test_the_models_match_the_migrations`) stays green: the
      hand-declared column in 1.1 must match the migration's `ALTER COLUMN` exactly
      (`nullable=True`, same `Uuid`/FK/index) or the autogenerate diff comes back non-empty.
      No code change expected — this is a verification step for 1.1/1.2. [R1.1, R1.2]

## 2. Domain: `tenant_id` widens to `uuid.UUID | None` end to end <!-- panel: PASS 2026-09-02 -->

- [x] 2.1 `backend/app/auth/domain/entities.py`: `User.tenant_id: uuid.UUID | None`. [R1.1]
- [x] 2.2 `backend/app/auth/domain/context.py`: `RequestContext.tenant_id: uuid.UUID | None`;
      `__post_init__` accepts `None` for that field only (`user_id` stays strictly a
      `uuid.UUID`). [R2.2]
- [x] 2.3 `backend/app/auth/domain/value_objects.py`: `AccessTokenClaims.tenant_id` and
      `RefreshTokenClaims.tenant_id` → `uuid.UUID | None`. [R2.1, R2.3]
- [x] 2.4 `backend/app/auth/domain/ports.py`: widen the `tenant_id` parameter to
      `uuid.UUID | None` on the `UserRepository`/`SessionRepository`/`TokenCodec` methods a
      `SUPER_ADMIN` request reaches — `get_active_by_id`, `touch_last_login`, every
      `SessionRepository` method, `TokenCodec.issue_access`/`issue_refresh`. Type-only change;
      no behaviour here. [R2.1, R2.2, R2.3, R2.4]
- [x] 2.5 `backend/tests/auth/test_context.py`: add a test that `RequestContext(tenant_id=None,
      ...)` constructs without raising, and that a non-`UUID`, non-`None` `tenant_id` still
      raises. [R2.2]

## 3. Infrastructure: the three branches a nullable tenant actually needs <!-- panel: PASS 2026-09-02 -->

- [x] 3.1 `backend/app/auth/infrastructure/repositories.py`:
      `SqlAlchemyUserRepository.get_active_by_id` branches on `tenant_id is None` — skips the
      `JOIN TenantModel` and filters `UserModel.tenant_id.is_(None)` instead, still requiring
      `UserModel.status == ACTIVE`. [R2.2]
- [x] 3.2 `backend/tests/auth/test_repositories.py`: test that `get_active_by_id(None, user_id)`
      returns a `SUPER_ADMIN` row with `tenant_id IS NULL` and status `ACTIVE`, and returns
      `None` for a suspended one — no `TenantModel` join needed for this path to work. [R2.2]
- [x] 3.3 `backend/app/auth/infrastructure/token_codec.py`: `_base_claims` writes
      `"tenant_id": str(tenant_id) if tenant_id is not None else None` (key always present);
      add `_optional_uuid_claim` (accepts `None`, still rejects any non-`None` non-`str`), used
      only for the `tenant_id` claim in `decode_access` and `decode_refresh`.
      `issue_access`/`issue_refresh` accept `tenant_id: uuid.UUID | None`. `tenant_id` is
      deliberately NOT in `_decode`'s `require=[...]` (design D4 amendment, found by task 3.4's
      own tests): PyJWT's required-claim check treats a JSON `null` value the same as an absent
      key, so keeping it in `require` rejected every `SUPER_ADMIN` token. [R2.1, R2.2]
- [x] 3.4 `backend/tests/auth/test_token_codec.py`: round-trip an access and a refresh token
      issued with `tenant_id=None` through decode and assert the claim comes back `None`; a
      token whose `tenant_id` claim is a non-string, non-null JSON value still raises
      `InvalidTokenError`. [R2.1, R2.2]

## 4. Application: login skips the tenant-active check for a tenantless user <!-- panel: PASS 2026-09-02 -->

- [x] 4.1 `backend/app/auth/application/use_cases.py`: `LoginUseCase._authenticate` skips
      `self.tenants.is_active(user.tenant_id)` when `user.tenant_id is None` — every other
      check (password, status, throttle) still runs unchanged. [R2.1]
- [x] 4.2 `backend/tests/auth/test_use_cases.py`: a `SUPER_ADMIN` user with `tenant_id=None`
      logs in successfully against a `TenantStatusReader` double that raises if called (proves
      the check is skipped, not merely passing); a wrong password, a locked account and an
      `INACTIVE` `SUPER_ADMIN` still fail exactly as for any other role. [R2.1]

## 5. API: the session stays unmarked, and the contract admits a null tenant <!-- panel: PASS 2026-09-02 -->

- [x] 5.1 `backend/app/auth/api/dependencies.py`: `get_authenticated_request` calls
      `bind_session_to_tenant(session, context.tenant_id)` only `if context.tenant_id is not
      None` — for a `SUPER_ADMIN` request the session is simply never marked. [R2.2, R3.1]
- [x] 5.2 `backend/app/auth/api/schemas.py`: `CurrentUserResponse.tenant_id: uuid.UUID | None`;
      `from_domain` unchanged (already copies the field through). [R2.4]
- [x] 5.3 `backend/tests/auth/test_isolation.py` (or `test_context.py`): after authenticating a
      request as `SUPER_ADMIN`, `session.info` carries no tenant marker (`_scope_statement_to_
      tenant` stays inactive for the rest of that session, same state as the bootstrap/
      anonymous-login sessions). [R3.1]
- [x] 5.4 `backend/tests/auth/test_api.py`: end-to-end cycle for a `SUPER_ADMIN` account —
      `POST /auth/login` returns `200` with a token pair; `POST /auth/refresh` rotates it the
      same way as any other role; `GET /auth/me` returns `200` with `tenant_id: null`;
      `POST /auth/logout` returns `204` — none of the four answers `500`. [R2.1, R2.2, R2.3,
      R2.4]

## 6. `POST /auth/change-password` refuses a `SUPER_ADMIN` cleanly (design D7) <!-- panel: PASS 2026-09-02 -->

- [x] 6.1 `backend/app/auth/domain/exceptions.py`: new
      `SuperAdminSelfServiceUnsupportedError(AuthDomainError)`. [R2.4]
- [x] 6.2 `backend/app/auth/api/errors.py`: `_MAPPING` gains
      `(SuperAdminSelfServiceUnsupportedError, 403, ErrorCode.FORBIDDEN)`. [R2.4]
- [x] 6.3 `backend/app/auth/application/recovery.py`: `ChangeOwnPasswordUseCase.execute` raises
      `SuperAdminSelfServiceUnsupportedError` immediately after loading the user, `if
      user.tenant_id is None` — before verifying the current password or writing any audit
      entry. [R2.4]
- [x] 6.4 `backend/tests/auth/test_recovery_use_cases.py` (or `test_recovery_api.py`): a
      `SUPER_ADMIN` calling `POST /auth/change-password` gets `403 FORBIDDEN`, not an unmapped
      `500` from an `IntegrityError` on `audit_logs.tenant_id`, and no `AuditLog` row is
      written. [R2.4]

- [x] 6.5 `backend/app/auth/application/recovery.py`: `RequestPasswordResetUseCase.execute`
      treats `user.tenant_id is None` the same as an unresolved address (silent early
      return, no token row built) — otherwise resolving a `SUPER_ADMIN` email queues an
      `INSERT` into `password_reset_tokens.tenant_id` (still `NOT NULL`), failing at
      `commit()` as an unmapped `IntegrityError`. Found during `run` (design D7
      amendment), same shape as D7's `/change-password` fix. [R2.4, design D7 amendment]
- [x] 6.6 `backend/tests/auth/test_recovery_use_cases.py` (or `test_recovery_api.py`): a
      `POST /auth/forgot-password` for a `SUPER_ADMIN`'s email answers the same `202`
      every other non-resolving case gets, and writes no `PasswordResetToken` row.
      [R2.4, design D7 amendment]

## 7. Bootstrap: a real, convergent `SUPER_ADMIN` seed account <!-- panel: PASS 2026-09-02 -->

- [x] 7.1 `backend/app/core/config.py`: three new settings,
      `bootstrap_super_admin_{name,email,password}: str = ""`, alongside the existing eight
      `BOOTSTRAP_*`. `.env.example`: add `BOOTSTRAP_SUPER_ADMIN_NAME`,
      `BOOTSTRAP_SUPER_ADMIN_EMAIL`, `BOOTSTRAP_SUPER_ADMIN_PASSWORD` (no values) next to the
      existing bootstrap block. [R5.1]
- [x] 7.2 `backend/app/cli/bootstrap.py`: `build_plan()` adds the three
      `BOOTSTRAP_SUPER_ADMIN_*` names to `required` and a third `SeedUser(role=
      UserRole.SUPER_ADMIN)` to the returned plan. `apply_plan()`'s per-seed conflict check
      becomes `expected_tenant_id = None if seed.role is UserRole.SUPER_ADMIN else tenant.id`,
      compared against `existing.tenant_id`; the inserted `UserModel` gets `tenant_id=
      expected_tenant_id` instead of always `tenant.id`. [R5.1, R5.2, R5.3]
- [x] 7.3 `backend/tests/auth/test_bootstrap.py`: extend `COMPLETE_ENV` with the three new
      required variables (this alone extends the existing missing-variable, whitespace,
      never-echoes-a-password and required-variables-are-exactly-documented tests to cover
      them); update `test_the_plan_carries_the_two_expected_roles` and the creation/
      convergence tests for a third user and role. Add: the bootstrapped `SUPER_ADMIN` can log
      in (mirrors `test_the_bootstrapped_owner_can_actually_log_in`) with `tenant_id is None`;
      a second run with the `SUPER_ADMIN` already created does **not** raise
      `BootstrapConflictError` (regression test for the D6 bug: `existing.tenant_id != tenant.id`
      compared unconditionally would always be true for a `None` `tenant_id`); a `SUPER_ADMIN`
      address that already exists under a real tenant is refused with `BootstrapConflictError`.
      [R5.1, R5.2, R5.3]

## 8. Documentation and specs <!-- panel: PASS 2026-09-02 -->

- [x] 8.1 `sdd/steering/security.md` rule 1: add a paragraph naming the exception — which
      requests it covers (`SUPER_ADMIN`-authenticated: login, `get_authenticated_request`,
      refresh, logout, `me`), why (product requires a tenantless platform identity, R1 of this
      change), and what bounds it (R4: no operational permission —
      `ROLE_PERMISSIONS[SUPER_ADMIN]` stays `_SELF_SERVICE`, unchanged by this or any future
      route until a change explicitly widens it). [R3.2] **Panel amendment (2026-09-02):** the
      first version wrongly listed `login`/`refresh` as authenticated through
      `get_authenticated_request` (they're anonymous and never reach it) and omitted
      `/change-password` and the four `/notifications/*` routes (which do, under the same
      `_SELF_SERVICE` permissions). Rewritten to state the real, permission-keyed boundary
      instead of a route list — same correction mirrored in `auth-tenancy.md` §8.2.
- [x] 8.2 `sdd/specs/auth-tenancy.md`: "Tokens" section — the `tenant_id` claim is nullable for
      `SUPER_ADMIN`. "Aislamiento por tenant" — add the `SUPER_ADMIN`-authenticated session to
      the enumeration of unmarked sessions. "Bootstrap del acceso inicial" — "dos cuentas" →
      "tres cuentas". [R3.2, R5.1]
- [x] 8.3 Regenerate and commit both halves of the API contract for the `CurrentUserResponse`
      change (task 5.2): `make openapi` → `backend/openapi.json`, and
      `cd frontend && npm run api:generate` → `frontend/lib/api/generated/openapi.d.ts`
      (`steering/documentation.md`: "las dos mitades del mismo puente"). [R2.4]

## 9. Verification <!-- panel: PASS 2026-09-02 -->

- [x] 9.1 R4 regression pin: `backend/tests/auth/test_policy.py` — add a direct assertion that
      `ROLE_PERMISSIONS[UserRole.SUPER_ADMIN]` is exactly `_SELF_SERVICE` (`READ_OWN_PROFILE`,
      `MANAGE_OWN_SESSION`, `READ_OWN_NOTIFICATIONS`) and nothing else. `GRANTABLE_ROLES`
      excluding `SUPER_ADMIN` is already covered by
      `test_super_admin_cannot_be_granted_by_a_role_change`/`test_super_admin_cannot_be_granted_
      at_creation` in `backend/tests/auth/test_entities.py` — no new test needed there. [R4.1,
      R4.2]
- [x] 9.2 Full backend test suite passes:
      `docker compose exec backend uv run pytest` (stack running) or
      `docker compose run --rm backend uv run pytest` (stack stopped).
- [x] 9.3 API contract check: `cd frontend && npm run api:check` reports no drift against the
      regenerated `openapi.json` (task 8.3).
- [x] 9.4 Manual check of the end-to-end flow: with the stack up (`make up`), run
      `python -m app.cli.bootstrap` inside the backend container with
      `BOOTSTRAP_SUPER_ADMIN_*` set, then exercise `POST /auth/login` →
      `GET /auth/me` → `POST /auth/refresh` → `POST /auth/logout` for that account against the
      running API (e.g. via `curl` or the `/docs` UI) and confirm every response matches task
      5.4's expectations.

## 10. Review panel round 1 (2026-09-02) — findings and fixes <!-- panel: PASS 2026-09-02 -->

Full-diff panel (architect, security, QA, tenancy, documentation, CI/CD, i18n) run against the
complete implementation. Architect/documentation/CI/CD/i18n: PASS, no findings. Security (4
findings), QA (1 main + 2 minor), tenancy (2 findings) — consolidated below, deduplicated where
independent reviewers converged on the same defect.

- [x] 10.1 **R1.2 had no enforcement at any layer** (security + QA, QA reproduced live with a
      rollback-only DB probe): nothing stopped a `TENANT_OWNER`/`PROPERTY_MANAGER`/`CLEANER`/
      `TECHNICIAN` row from acquiring `tenant_id IS NULL`, which would then authenticate with
      its session left unmarked (`get_authenticated_request` keys that decision on `tenant_id`
      nullity, not `role`) while holding full operational permissions. Fixed: new
      `ck_users_super_admin_tenant_id_null` CHECK constraint on `users`, added to both the
      migration and `UserModel.__table_args__` (see 1.1/1.2), mirroring the existing
      `ck_pms_credentials_property_id_matches_scope` precedent. [R1.2]
- [x] 10.2 **Fixture/test fallout of 10.1**: `tests/auth/conftest.py`'s `users_by_role_a`/
      `users_by_role_b` fixtures inserted a `SUPER_ADMIN` bound to a real tenant, which the new
      constraint now refuses outright — fixed to insert it with `tenant=None` instead (every
      consumer keys off role-based permissions, unaffected). Two direct-insert test suites hit
      the same wall and were narrowed to the four tenant-bound roles, with a comment explaining
      why: `test_isolation.py`'s four `list(UserRole)`-parametrized cross-tenant tests (now
      `_TENANTED_ROLES`), and `test_recovery_api.py::test_every_role_that_can_authenticate_may_
      change_its_own_password` (`SUPER_ADMIN` already gets its own `403` test from section 6).
- [x] 10.3 **`security.md` rule 1's exception paragraph named the wrong routes** (security +
      tenancy, independently): claimed "exactly five points" including the anonymous
      `login`/`refresh` (never reach `get_authenticated_request`) while omitting
      `/change-password` and the four `/notifications/*` routes (which do, under the same
      `_SELF_SERVICE` permissions). Rewritten to state the real boundary — every route gated by
      a `_SELF_SERVICE` permission, not a fixed list — in both `security.md` and the mirrored
      `auth-tenancy.md` bullet. [R3.2]
- [x] 10.4 **The `SUPER_ADMIN` seed credential has no in-product rotation path** (security,
      low): D7/its amendment close both self-service routes, and bootstrap's convergence
      `continue`s past an existing address for every role, so a re-run doesn't update the
      password either. Accepted as a documented limitation (design.md Risks) rather than given
      a new rotation surface — that would itself widen what a product surface does for
      `SUPER_ADMIN`, which R4 forbids.
- [x] 10.5 **The D4 amendment's own wording overclaimed "admits nothing new"** (security, low):
      corrected in design.md — dropping `tenant_id` from PyJWT's `require` does let a token
      with the key fully absent decode (as `tenant_id=None`) where it was previously rejected
      outright; still safe because minting any token needs the signing secret and the identity
      is re-validated against the database on every request, but that reasoning wasn't in the
      original text.
- [x] 10.6 **Task 6.4's own "no `AuditLog` row" assertion was never written** (QA): added to
      `test_a_super_admin_gets_a_clean_403_not_an_unmapped_500` in `test_recovery_api.py`.
- [x] 10.7 **Second-order fallout of 10.1, found by the full-suite re-run itself**: five
      authorization-matrix tests in `tests/properties/test_authorization.py` and
      `tests/reservations/test_authorization.py` failed `401` instead of `403` for
      `SUPER_ADMIN` — their `_seed_property`/`_seed_reservation` helpers authenticate as
      `PROPERTY_MANAGER` first (marking the shared test `db_session` to tenant A), and
      `get_authenticated_request` skips binding for a tenantless `SUPER_ADMIN` request
      rather than rebinding, so the STALE tenant-A mark stayed active and silently hid
      `SUPER_ADMIN`'s own `tenant_id IS NULL` row behind the wrong filter. Impossible in
      production (`get_db_session` hands out one fresh, unmarked session per real request,
      so no request ever inherits another's mark) — purely an artifact of these two test
      files sharing one session across several simulated requests. Fixed at the source:
      both seed helpers now pop `TENANT_ID_SESSION_KEY` right after seeding, so every
      later request in the test starts unmarked like a real one would.
- [x] 10.8 Re-verify: migration chain-walk tests, full `tests/auth` package, and the full
      backend suite all pass after 10.1-10.7; re-run the three reviewers whose findings were
      fixed (security, QA, tenancy), scoped to the fix.

## 11. Review panel round 2 (2026-09-02) — feature-scale `/sdd:review`, findings and fixes <!-- panel: PASS 2026-09-02 -->

Feature-scale panel (architect, security, QA, tenancy, documentation, CI/CD, i18n) run under
`/sdd:review`, incremental scope per section-level PASS annotations above (no line-by-line
re-audit of sections 1-10; cross-section coherence, the R# completeness matrix, and anything
round 1's fixes (10.1-10.7) might themselves have introduced or missed). i18n: PASS, no
findings. Architect, security, tenancy, QA, CI/CD, documentation: findings below,
deduplicated where independent reviewers converged on the same defect.

- [x] 11.1 **`app/cli/reset_password.py` — the documented rescue-path CLI crashes for a
      `SUPER_ADMIN`** (security, new — round 1's panel scoped to API routes and did not
      reach CLI tooling): `apply_reset` resolves a `SUPER_ADMIN` address via
      `find_by_email_globally` (unscoped, so it resolves) and then reaches
      `AuditLogFactory.build(tenant_id=None, ...)`; `audit_logs.tenant_id` stays `NOT NULL`
      (untouched by this change), so `session.commit()` raises an unmapped `IntegrityError`
      and `main()` (which only catches `AccountNotFoundError`) lets it escape as a
      traceback. Combined with D7's `403` on `/change-password` and its amendment's silent
      `202` on `/forgot-password`, this meant the platform's highest-privilege account had
      **no working credential-recovery path at all** — and `design.md`'s own
      accepted-limitation paragraph (10.4) was factually wrong about the recourse, naming
      "the same class of operation RUNBOOK.md already documents" without accounting for the
      fact that the documented command itself crashed. Fixed: new
      `SuperAdminRescueUnsupportedError`, raised by `apply_reset` immediately after
      resolving the user, `if user.tenant_id is None`, before the password hash or any
      audit row is touched; caught in `main()` alongside `AccountNotFoundError` and printed
      as a clean operator-facing message. `design.md`'s 10.4 paragraph corrected to name
      this path and the real recourse (a direct `password_hash` `UPDATE`, not the rescue
      CLI). [R2.4, design D7 shape]
- [x] 11.2 **`ck_users_super_admin_tenant_id_null` — the sole enforcement of R1.2 had no
      test that attempts the violation it exists to reject** (security + tenancy + QA,
      independently converged; QA additionally reproduced the constraint firing correctly
      in both directions with a live, rollback-only DB probe during review — not a live
      hole, a coverage gap). Every fixture touched by round 1 (`tenant_for_role` in
      `tests/auth/conftest.py`, the narrowed `_TENANTED_ROLES`) works AROUND the constraint
      rather than asserting it fires; a future change that weakened or dropped it would not
      be caught. Fixed: `tests/test_migrations.py::test_the_super_admin_check_constraint_actually_fires`
      inserts a `PROPERTY_MANAGER` with `tenant_id = NULL` and a `SUPER_ADMIN` with a real
      `tenant_id` against the real migrated schema, both expected to raise
      `asyncpg.CheckViolationError`. [R1.2]
- [x] 11.3 **`token_codec.py`'s own comments still asserted the disproven D4-amendment
      premise** (architect + security, independently converged): the `_base_claims` comment
      said the `tenant_id` key "stays present — PyJWT's `require=[...]` below demands it,"
      and the `_decode` comment said dropping it from `require` "changes nothing for a token
      that never carried the key" — both the exact overclaim the design D4 amendment
      corrected in `design.md`, never carried into the code that a future maintainer would
      actually read. Fixed: both comments rewritten to match the corrected reasoning (the
      key stays for schema-shape consistency, not because `require` demands it; dropping it
      from `require` does widen what decodes, safe because minting a token needs the signing
      secret and the identity is re-validated against the database per request). No
      behavior change — comments only. [design D4 amendment]
- [x] 11.4 **`RUNBOOK.md` §6.5 and `README.md`'s `make bootstrap` description are stale**
      (CI/CD + documentation, independently converged on the same lines): neither lists the
      three new `BOOTSTRAP_SUPER_ADMIN_*` variables `bootstrap.py` now requires
      unconditionally, so following either verbatim — including the dev-VM procedure
      `RUNBOOK.md` documents — fails with `BootstrapConfigurationError`. Fixed:
      `RUNBOOK.md` §6.5's heredoc example and surrounding prose ("dos" → "tres
      contraseñas") now include `BOOTSTRAP_SUPER_ADMIN_{NAME,EMAIL,PASSWORD}`;
      `README.md`'s `make bootstrap` comment now says "tres usuarios" and names all three
      roles. [R5.1]
- [x] 11.5 Re-verify: `tests/auth/test_reset_password_cli.py`,
      `tests/test_migrations.py`, and the scoped suite
      (`tests/auth/ tests/test_migrations.py tests/properties/test_authorization.py
      tests/reservations/test_authorization.py`) all pass after 11.1-11.4 (929 passed, up
      from 927 with the two new tests); re-run the five reviewers whose findings were
      touched (architect, security, tenancy, QA, CI/CD, documentation), scoped to the fix.
