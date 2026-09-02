# Design: super-admin-identity

## Context

`SUPER_ADMIN` already exists as a `UserRole` member (`backend/app/auth/domain/enums.py`) and its
policy row is already the one the product wants: `ROLE_PERMISSIONS[UserRole.SUPER_ADMIN]` is
`_SELF_SERVICE` and nothing else, `GRANTABLE_ROLES` already excludes it
(`backend/app/auth/domain/entities.py:14`). **R4 is already true in code** — this design changes
no permission and no grant rule; it only makes the role able to exist and authenticate.

What is not true today: `users.tenant_id` and `user_sessions.tenant_id` are `NOT NULL`
(`TenantScopedMixin`, `backend/app/core/db.py`), `User.tenant_id` and `RequestContext.tenant_id`
are non-optional, the JWT claims always carry a `tenant_id` string, and
`SqlAlchemyUserRepository.get_active_by_id` inner-joins `tenants` — so a role with no tenant
cannot be created, cannot log in, and cannot pass `get_authenticated_request` even if a row
existed. `app/cli/bootstrap.py` seeds exactly two accounts (`TENANT_OWNER`, `PROPERTY_MANAGER`);
there is no third.

The precedent this design follows already lives in the tree: `WebhookEventModel`
(`backend/app/integrations/infrastructure/models.py`) is the one existing table with a nullable
`tenant_id`, and it does **not** use `TenantScopedMixin` — it declares the column by hand,
keeping the mixin's type/FK/index, because the mixin hard-codes `nullable=False`. `users` and
`user_sessions` follow the same shape.

## Decisions

### D1 — Nullable `tenant_id`, declared by hand, on `users` **and** `user_sessions`

**Chosen:** Drop `TenantScopedMixin` from `UserModel` and `UserSessionModel`; declare
`tenant_id: Mapped[uuid.UUID | None]` on each, same `Uuid` type, same `ForeignKey("tenants.id")`,
same index — mirroring `WebhookEventModel`. One Alembic migration alters both columns to
`nullable=True`, no backfill (R1.3): every existing row already has a concrete `tenant_id`.

**Why both tables, not just `users` as R1.3's wording names:** R2 requires login, refresh and
logout to work end-to-end for `SUPER_ADMIN`, and refresh/logout are keyed off
`user_sessions` rows carrying the session's `tenant_id`. A `SUPER_ADMIN` login has to persist a
`UserSession` row somewhere, and that row's `tenant_id` is `None` too — there is no tenant to
attribute it to. Relaxing only `users.tenant_id` would satisfy R1's letter and break R2's. This
is the one place the proposal's migration scope needed correcting during design (see
[[design-must-verify-out-of-scope-claims]] pattern); R1.3/R1.4 apply identically to
`user_sessions.tenant_id`.

`tenant_scoped_classes()` (`app/core/db.py`) selects by column presence, not by mixin, so
removing `TenantScopedMixin` does **not** remove `users`/`user_sessions` from the global tenant
filter — a session marked for tenant A still only sees tenant A's users and sessions, exactly as
today. Only an *unmarked* session (D3) sees the `NULL` rows, the same mechanism that already
protects `webhook_events`.

Rejected: a sentinel "platform tenant" row that `SUPER_ADMIN` belongs to — this is the second
option the roadmap note left open (`sdd/roadmap/super-admin-console.md`: "tenant nulo o tenant de
plataforma"). The proposal's "What changes" already resolved this to null, not a sentinel: R1
asks for the schema to admit "sin pertenecer a ningún tenant", not a tenant that means "none". A
sentinel would also need its own `TenantStatus.ACTIVE` row for every `is_active` check to keep
working, adding a fake entity to avoid a null check — worse than the null it avoids.

### D2 — `tenant_id` becomes `uuid.UUID | None` end to end, not a second code path

**Chosen:** Every layer that carries `tenant_id` for `SUPER_ADMIN` accepts `None` as a normal
value rather than branching into "super admin" vs "tenant" copies of login/refresh/logout/me:
`User.tenant_id`, `UserSession.tenant_id`, `RequestContext.tenant_id`,
`AccessTokenClaims.tenant_id`, `RefreshTokenClaims.tenant_id`, and the `tenant_id` parameter of
`UserRepository`/`SessionRepository` methods all become `uuid.UUID | None`.

This works with almost no branching because SQLAlchemy's `Column == None` already compiles to
`IS NULL`: `SqlAlchemySessionRepository.get/consume/revoke_family`,
`SqlAlchemyUserRepository.touch_last_login/apply_changes`, `add()`'s tenant-match guards — all
already do the right thing once the type is widened, with zero logic changes. Verified by
reading each call site; none needed a new branch. The three places that genuinely need one:

- `SqlAlchemyUserRepository.get_active_by_id`: the `JOIN TenantModel ... WHERE TenantModel.status
  = ACTIVE` returns nothing for a `NULL` tenant_id row (an INNER JOIN against nothing). Branch:
  `tenant_id is None` skips the join entirely and filters `UserModel.tenant_id.is_(None)`
  instead — still revalidating `status == ACTIVE` against the database, per R2.2.
- `LoginUseCase._authenticate`: `self.tenants.is_active(user.tenant_id)` would call
  `TenantStatusReader.is_active(None)`, which finds no `tenants` row and always returns `False`
  — locking every `SUPER_ADMIN` out. Guard: skip the tenant-active check when `user.tenant_id is
  None`.
- `RequestContext.__post_init__` currently rejects any `tenant_id` that is not a `uuid.UUID`.
  Relaxed to accept `None` too, `user_id` unaffected (a `SUPER_ADMIN` always has one).

Rejected: a parallel `PlatformRequestContext`/second use-case family for `SUPER_ADMIN`. Doubles
every future change to login/refresh/logout/me and is exactly the kind of duplication
`steering/backend-architecture.md` "cuándo simplificar" warns against for four routes this thin.

### D3 — The session stays unmarked for a `SUPER_ADMIN` request; no new guard needed

**Chosen:** `get_authenticated_request` (`backend/app/auth/api/dependencies.py`) calls
`bind_session_to_tenant(session, context.tenant_id)` only `if context.tenant_id is not None`.
For a `SUPER_ADMIN` request the session is simply never marked — the same state the bootstrap,
the anonymous login lookup and `POST /auth/refresh` are already in, which is precisely the
exception R3.1 asks for by name ("igual que ya ocurre hoy con el bootstrap...").

No new mechanism: `_scope_statement_to_tenant`'s docstring already says "which things mark a
session is deliberately not enumerated here" for exactly this reason — the set was always
open-ended, not a fixed list to extend. `require_unmarked_session` /
`tests/test_unscoped_reads.py`'s census is unaffected: that guard protects reads that resolve a
tenant *out of* an unscoped row (`find_by_email_globally`-shaped), and a `SUPER_ADMIN`'s
`get_active_by_id(None, user_id)` is not that — it is a read explicitly scoped to `tenant_id IS
NULL`, a predicate only `SUPER_ADMIN` rows can satisfy. It does not belong in that census and
does not call that guard.

Rejected: binding the session to a sentinel value (e.g. a nil UUID) so the global filter stays
"on". Rejected for the same reason D1 rejects a sentinel tenant row — it fabricates an identity
the filter would then scope everything to, when the actual requirement is that nothing scopes at
all for this one request.

### D4 — Token claims carry `tenant_id: null` for a `SUPER_ADMIN`, not an absent claim

**Chosen:** `JwtTokenCodec._base_claims` writes `"tenant_id": str(tenant_id) if tenant_id is not
None else None` — the claim key is always present, its value is JSON `null` when there is no
tenant. `_uuid_claim` gets a sibling, `_optional_uuid_claim`, used only for `tenant_id`: `None`
passes through, any non-`None` non-string still raises `InvalidTokenError` exactly as today.
`user_id`, `role`, `jti`, `fam` keep the strict, non-optional `_uuid_claim`/`_role_claim` — only
the one claim that can legitimately be absent gets a second reading.

Rejected: omitting the `tenant_id` key from the payload for `SUPER_ADMIN` tokens. Carrying two
different claim shapes for the same token type is a second thing every future auth change has
to remember, and the key staying present is what a reader would expect from "the claim is
`null`, not absent."

**Amendment during `run` (2026-08-31): `tenant_id` is NOT in PyJWT's `require=[...]`, and the
first version of this decision was wrong about why it didn't need to be.** The original text
said the always-present key "satisfies PyJWT's `require=[...]`" — measured false the moment the
first `SUPER_ADMIN` token round-tripped through `decode_access`: PyJWT's
`_validate_required_claims` tests `payload.get(claim) is None`, so a claim whose value is JSON
`null` fails the presence check exactly like a claim whose key is absent — `.get()` cannot tell
the two apart, and neither can PyJWT's check built on it. Every `SUPER_ADMIN` token was rejected
with `MissingRequiredClaimError` in `decode_access`/`decode_refresh`, an unconditional `401` that
made R2 unimplementable as designed, caught by the six token/login/isolation/API tests this
change added for the null-tenant path (all six failed the same way).

**Fixed by dropping `tenant_id` from `require`, not by finding a PyJWT option that
distinguishes null from absent — there is none.** `_optional_uuid_claim` reads a missing key
and an explicit `null` identically (`claims.get(name)` returns `None` either way), which is
what made the fix safe — but not, as an earlier version of this paragraph claimed, a no-op.
**Corrected by the review panel (2026-09-02): dropping the check DOES widen what decodes.**
Before this amendment, a correctly-signed token whose payload omitted the `tenant_id` key
entirely was rejected outright by PyJWT's `require`; after it, `_optional_uuid_claim` reads
the same token as `tenant_id=None` and it decodes. That is a real behaviour change, not
"nothing the codec did not already accept" — the prior sentence conflated "the codec's own
claim-reading logic already tolerates this" (true) with "PyJWT's gate already let it through"
(false). It stays safe for a reason the original paragraph didn't need but should have named:
minting any token at all requires the HS256 signing secret, and the resulting `tenant_id=None`
identity is re-validated against the database on every request
(`SqlAlchemyUserRepository.get_active_by_id(None, user_id)`, R2.2) — it authenticates only if a
real `SUPER_ADMIN` row with that exact `user_id` and `status = ACTIVE` exists. `sub`, `role`,
`type`, `jti`, `fam`, `iat`, `exp` stay required and none of this widens their handling: none of
them can legitimately be `null`, so the conflation only ever applied to the one claim that can.

### D5 — `CurrentUserResponse.tenant_id` becomes `uuid.UUID | None`

**Chosen:** The Pydantic field, not just the domain type. This one is load-bearing and not
cosmetic: unlike the dataclasses in D2, Pydantic validates on construction, so
`CurrentUserResponse.from_domain(user)` with `user.tenant_id = None` against a non-optional
`uuid.UUID` field raises a `ValidationError` at the API boundary — `GET /me` would 500 for
exactly the role R2.4 requires it not to. `openapi.json` marks the field nullable, so this is a
public contract change; `platform-admin-api`/`super-admin-console` (dependents) and the frontend
generated types pick it up when they regenerate.

### D6 — Bootstrap's conflict check compares against the *expected* tenant for the seed's role, not always `tenant.id`

**Chosen:** `apply_plan`'s per-seed conflict check
(`if existing is not None and existing.tenant_id != tenant.id`) is corrected to
`expected_tenant_id = None if seed.role is UserRole.SUPER_ADMIN else tenant.id`, then compares
against `expected_tenant_id`. Verified by reading the loop: as written today, a second bootstrap
run with a `SUPER_ADMIN` seed already created (`existing.tenant_id is None`) would compare
`None != tenant.id` — always true — and raise `BootstrapConflictError` on every re-run,
violating R5.2's convergence requirement and firing before R5.3's real conflict case (address
under a *different* tenant) even gets to matter. This was found and fixed during design, not
carried as a known bug.

`apply_plan` gains a third `SeedUser(role=UserRole.SUPER_ADMIN)` from three new
`BOOTSTRAP_SUPER_ADMIN_{NAME,EMAIL,PASSWORD}` settings, validated in `build_plan()` alongside the
existing eight (R5.1). The `UserModel` it inserts gets `tenant_id=None` instead of `tenant.id`
— the only per-seed branch `apply_plan`'s loop needs.

### D7 — `POST /auth/change-password` refuses a `SUPER_ADMIN` with a clean 403, not a 500

**Chosen** (resolved at the design gate — see rationale under Risks below): a new domain
exception, `SuperAdminSelfServiceUnsupportedError` (`backend/app/auth/domain/exceptions.py`),
raised by `ChangeOwnPasswordUseCase.execute` immediately after loading the user, `if
user.tenant_id is None`, before any password verification or audit write. Mapped in
`backend/app/auth/api/errors.py`'s `_MAPPING` to `403 FORBIDDEN` — reusing the existing
`ErrorCode.FORBIDDEN` rather than minting a new contract value, since the shape is exactly that
one: the caller authenticated fine, the credential is not what is being refused, the operation is
(design D8 of `user-management` uses the same 422-vs-403 reasoning for its own three refusals;
this one keeps `403` rather than `422` because — unlike those three — the account genuinely
cannot reach the state a retry with different input would fix).

This closes the gap `POST /auth/change-password` was already exposed to the moment `SUPER_ADMIN`
can authenticate (Risks below), without widening what the role can do (R4): the account still
cannot rotate its own password through this endpoint, it now fails legibly instead of with an
unmapped `IntegrityError`.

Rejected: fixing it by making `audit_logs.tenant_id` nullable too, or by writing the audit row
with some sentinel tenant. Both reach past this change's boundary — `AuditLog`'s tenant scoping
belongs to whichever change first needs a `SUPER_ADMIN` action audited (the proposal's own "Out
of scope" already assigns that to `platform-admin-api`), and this design should not decide it as
a side effect of closing an unrelated 500.

**Amendment during `run` (2026-08-31): a second, identically-shaped 500 on `POST
/auth/forgot-password`.** Tracing `RequestPasswordResetUseCase.execute` for a `SUPER_ADMIN`
email during implementation of task 3.1 found the same failure class D7 already closed, on a
route this design's Risk analysis never reached: `password_reset_tokens.tenant_id` keeps
`TenantScopedMixin` (`NOT NULL`, unchanged by this change), so a `SUPER_ADMIN`'s
`PasswordResetToken(tenant_id=None, ...)` queues an `INSERT` that only fails at `commit()`, as
an unmapped `IntegrityError` — a `500` where every other outcome of this anonymous endpoint
answers `202` (R2.2's indistinguishability). Unreachable before this change because no
`SUPER_ADMIN` account could exist; reachable the moment R5's bootstrap seed can create one.

Confirmed with the user rather than silently patched or silently deferred (run step 4): fix it
here, with the same reasoning D7 already established for `/change-password` — treat a
`SUPER_ADMIN` exactly like an unresolved address, the state R2.2 already collapses five other
cases into. **Chosen**: `RequestPasswordResetUseCase.execute` extends its first resolution
guard from `user is None or user.status is not UserStatus.ACTIVE` to also cover `user.tenant_id
is None` — same silent early return, same log line, no new exception type needed (unlike D7,
this path never authenticated, so there is no caller-facing error to map; the anonymous
contract is "identical response for every non-resolving case," and this is simply one more of
them). No token row is ever built, so `add()` never reaches the `NOT NULL` column.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Domain entities | `backend/app/auth/domain/entities.py` | `User.tenant_id: uuid.UUID \| None` |
| Domain entities | `backend/app/auth/domain/context.py` | `RequestContext.tenant_id: uuid.UUID \| None`; `__post_init__` accepts `None` for that field only |
| Domain entities | `backend/app/auth/domain/value_objects.py` | `AccessTokenClaims.tenant_id`, `RefreshTokenClaims.tenant_id` → `uuid.UUID \| None` |
| Domain ports | `backend/app/auth/domain/ports.py` | `tenant_id` parameter widened to `uuid.UUID \| None` on `UserRepository`/`SessionRepository`/`TokenCodec` methods that a `SUPER_ADMIN` request reaches (`get_active_by_id`, session CRUD, `issue_access`/`issue_refresh`) |
| Infrastructure models | `backend/app/auth/infrastructure/models.py` | `UserModel`, `UserSessionModel`: drop `TenantScopedMixin`, declare `tenant_id: Mapped[uuid.UUID \| None]` by hand (D1) |
| Infrastructure repositories | `backend/app/auth/infrastructure/repositories.py` | `get_active_by_id` branches on `tenant_id is None` (D2); no other method needs a branch |
| Infrastructure token codec | `backend/app/auth/infrastructure/token_codec.py` | `_base_claims`/`issue_access`/`issue_refresh`/`decode_*` handle optional `tenant_id` (D4) |
| Application use cases | `backend/app/auth/application/use_cases.py` | `LoginUseCase._authenticate` skips `tenants.is_active` when `user.tenant_id is None` (D2) |
| API dependencies | `backend/app/auth/api/dependencies.py` | `get_authenticated_request` binds the session only `if context.tenant_id is not None` (D3) |
| API schemas | `backend/app/auth/api/schemas.py` | `CurrentUserResponse.tenant_id: uuid.UUID \| None` (D5) |
| CLI | `backend/app/cli/bootstrap.py` | Third `SeedUser` (`SUPER_ADMIN`, `tenant_id=None`); conflict check compares against the seed's expected tenant, not always `tenant.id` (D6) |
| Domain exceptions | `backend/app/auth/domain/exceptions.py` | New `SuperAdminSelfServiceUnsupportedError` (D7) |
| Application use cases | `backend/app/auth/application/recovery.py` | `ChangeOwnPasswordUseCase.execute` raises it for `user.tenant_id is None`, before verifying the password or writing audit (D7); `RequestPasswordResetUseCase.execute` treats `user.tenant_id is None` as an unresolved address, same silent return (D7 amendment) |
| API error mapping | `backend/app/auth/api/errors.py` | New `_MAPPING` entry: `SuperAdminSelfServiceUnsupportedError` → `403 FORBIDDEN` (D7) |
| Config | `backend/app/core/config.py`, `.env.example` | Three new `bootstrap_super_admin_{name,email,password}` settings, same pattern as the existing eight `BOOTSTRAP_*` |
| Migration | `backend/alembic/versions/<new>_super_admin_identity.py` | `ALTER COLUMN users.tenant_id DROP NOT NULL`, same for `user_sessions.tenant_id`; `downgrade()` counts `NULL` rows in both tables first and raises rather than reinstating `NOT NULL` over data that already violates it (R1.4) |
| Steering | `sdd/steering/security.md` rule 1 | New paragraph naming the exception: which requests it covers (`SUPER_ADMIN`-authenticated: login, `get_authenticated_request`, refresh, logout, `me`), why (product requires a tenantless platform identity, R1 of this change), what bounds it (R4: no operational permission — `ROLE_PERMISSIONS[SUPER_ADMIN]` stays `_SELF_SERVICE`, unchanged by this or any future route until a change explicitly widens it) |
| Spec | `sdd/specs/auth-tenancy.md` | "Tokens" section: claim `tenant_id` is nullable for `SUPER_ADMIN`. "Aislamiento por tenant": add the `SUPER_ADMIN`-authenticated session to the enumeration of unmarked sessions. "Bootstrap del acceso inicial": "dos cuentas" → "tres cuentas" |

## Data & interfaces

**Schema**: `users.tenant_id` and `user_sessions.tenant_id` become nullable (one migration, no
backfill, irreversible downgrade guard per R1.4). No other table changes. No new table.

**API contract**: `GET /api/v1/auth/me` response's `tenant_id` becomes nullable in
`openapi.json`. `POST /api/v1/auth/login`/`refresh` responses (`TokenPairResponse`) are
unchanged shape — only the JWT payload inside the opaque token string carries a nullable
`tenant_id` claim now, which is not part of the OpenAPI contract. No other endpoint's request or
response schema changes.

**Config**: three new required environment variables, `BOOTSTRAP_SUPER_ADMIN_NAME`,
`BOOTSTRAP_SUPER_ADMIN_EMAIL`, `BOOTSTRAP_SUPER_ADMIN_PASSWORD`, validated the same way as the
existing eight `BOOTSTRAP_*` (fail fast, listed together if missing). No defaults, per
`steering/security.md` rule 8 (real passwords).

## Risks & mitigations

- **Migration irreversibility once a `SUPER_ADMIN` exists.** Mitigated by R1.4's explicit
  downgrade guard: `downgrade()` queries both tables for `tenant_id IS NULL` rows and raises
  before altering the column back to `NOT NULL`, rather than failing opaquely at the `ALTER
  TABLE` or silently corrupting data. `tests/test_migrations.py`'s existing chain-walk pattern
  (`test_the_chain_upgrades_to_head_and_unwinds_revision_by_revision`) is the place this gets
  exercised in both directions — with and without a `NULL` row present, matching how it already
  tests `assignment_note`/`eta_at` over populated tables.

- **`alembic check` (`test_the_models_match_the_migrations`) diverging from the model.** Since
  D1 removes `TenantScopedMixin` and declares the column by hand, the declared type must match
  the migration's `ALTER COLUMN` exactly (`nullable=True`, same `Uuid`/FK/index) or the
  autogenerate diff comes back non-empty. `WebhookEventModel`'s existing nullable column is the
  reference shape already passing this check today.

- **A latent 500, found and closed within this change (D7).**
  `POST /api/v1/auth/change-password` is reachable by `SUPER_ADMIN` today, unrelated to this
  change: it requires `MANAGE_OWN_SESSION`, which `SUPER_ADMIN` already holds
  (`_SELF_SERVICE`), and R4 keeps that permission set unchanged. Once `SUPER_ADMIN` can actually
  authenticate, this route becomes reachable for the first time, and
  `ChangeOwnPasswordUseCase.execute` unconditionally writes an `AuditLog` row
  (`_AuditWriter.record`) whose `tenant_id` would be `None` — `audit_logs.tenant_id` is `NOT
  NULL` (`AuditLogModel` keeps `TenantScopedMixin`, untouched by this change), so the write
  would raise an `IntegrityError` with nothing to map it to a clean 4xx. This corrected the
  proposal's "Out of scope" claim that "ninguna ruta de esta entrada... escribe una entidad
  auditada" — that is true of the four R2 routes, but `/change-password` is not one of them and
  is reachable anyway through a permission this change did not add. Resolved at the design gate:
  guard it (D7), not document-and-defer. `/notifications/*` is reachable by the same route
  (`READ_OWN_NOTIFICATIONS`) but was checked and is safe: every query there resolves to
  `tenant_id IS NULL AND ...`, which returns zero rows on a `NOT NULL` column rather than
  crashing.

- **A second latent 500, found and closed during `run` (D7 amendment).**
  `POST /api/v1/auth/forgot-password` is anonymous — no permission check, so `SUPER_ADMIN`'s
  `_SELF_SERVICE` role never gated it the way it gated `/change-password`. The same shape D7
  describes recurs one layer earlier: resolving a `SUPER_ADMIN` email builds a
  `PasswordResetToken(tenant_id=None, ...)`, and `password_reset_tokens.tenant_id` is `NOT NULL`
  (`TenantScopedMixin`, untouched). Found while implementing task 3.1 (`get_active_by_id`'s new
  branch is what makes the address resolve at all), confirmed with the user, and closed the same
  way D7 was: `RequestPasswordResetUseCase.execute` treats `tenant_id is None` as one more
  unresolved-address case, so no token row is ever built. See the D7 section above for the full
  trace.

- **The `SUPER_ADMIN` seed password has no in-product rotation path, found by the review
  panel (2026-09-02).** D7 and its amendment both close off self-service: `/change-password`
  refuses `SUPER_ADMIN` with `403`, `/forgot-password` treats it as unresolved. Bootstrap's own
  convergence (design D6) does not fill the gap either — `apply_plan`'s per-seed loop
  `continue`s past an address that already exists, for every role, so a re-run with a changed
  `BOOTSTRAP_SUPER_ADMIN_PASSWORD` does not update the stored hash any more than it would for
  the owner or manager seeds. Accepted rather than fixed here: rotation is an operational
  concern, not a capability the role gains or loses, and R4 forbids widening what `SUPER_ADMIN`
  can do through a product surface — adding one to solve this would be exactly that.

  **Corrected by the review panel (2026-09-02, round 2): the "direct-DB fix" recourse this
  paragraph originally described was itself wrong about which command performs it.**
  `app/cli/reset_password.py` — the "rescue path for an account nobody else can recover"
  (R6.5/D12 of `auth-account-recovery`) — reached `AuditLogFactory.build(tenant_id=None,
  ...)` for a `SUPER_ADMIN` and only failed at `commit()` as an unmapped `IntegrityError`
  (`audit_logs.tenant_id` stays `NOT NULL`, untouched by this change): the one documented
  rescue command a `SUPER_ADMIN` could reach crashed instead of refusing cleanly, so an
  operator following `RUNBOOK.md`'s break-glass pattern via that command would hit a
  traceback, not a working fix. Closed the same way D7 closes the API routes: `apply_reset`
  now refuses a `tenant_id IS NULL` account up front with `SuperAdminRescueUnsupportedError`,
  before touching the password hash or building an audit row. The actual, correct recourse
  is what it always should have been: an operator updates `users.password_hash` directly for
  the `tenant_id IS NULL` row (a fresh `BcryptPasswordHasher().hash(...)` value) — true
  hand-written SQL, not the rescue CLI, which now says so explicitly rather than crashing
  partway through.

## Open questions

None outstanding. Two substantive questions came up, both resolved in favour of guarding within
this change rather than deferring: D7 (`/auth/change-password` for `SUPER_ADMIN`) at the design
gate, and its amendment (`/auth/forgot-password`, same shape) during `run`.
