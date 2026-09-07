# Tasks: staff-messaging

## 1. Schema: two twin message tables, their migration, the notification types <!-- panel: PASS 2026-09-02 -->

- [x] 1.1 `backend/app/cleaning/domain/entities.py`: add `CleaningTaskMessage` — a plain
      dataclass (`id`, `tenant_id`, `task_id`, `author_id`, `author_role: UserRole`, `content`,
      `created_at`), no `__post_init__` invariant — same shape as `CleaningPhoto`/`IncidentPhoto`,
      no validation of its own (design D1, D2). Add `MAX_CLEANING_TASK_MESSAGE_LENGTH = 2000`
      next to it (design D5) — this module owns the column, so the API schema imports the
      constant rather than repeating the literal, same pattern as `MAX_MATERIALS`. [R1, R5]
- [x] 1.2 `backend/app/maintenance/domain/entities.py`: add `IncidentMessage` — the mirror of
      1.1 with `incident_id` instead of `task_id` — and `MAX_INCIDENT_MESSAGE_LENGTH = 2000`.
      [R2, R5]
- [x] 1.3 `backend/app/cleaning/domain/repositories.py`: add `CleaningTaskMessagePage`
      (`items: tuple[CleaningTaskMessage, ...]`, `total: int`, same shape as `Page`/
      `TemplatePage`) and `CleaningTaskMessageRepository` Protocol with `add(tenant_id,
      message) -> None` and `list_for_task(tenant_id, task_id, *, page, per_page) ->
      CleaningTaskMessagePage`, ordered chronologically ascending (`created_at`, `id` for
      tie-break, same stability rule as `CleaningTaskRepository.list`'s docstring). [R1]
- [x] 1.4 `backend/app/maintenance/domain/repositories.py`: mirror of 1.3 —
      `IncidentMessagePage`, `IncidentMessageRepository` with `add`/`list_for_incident`. [R2]
- [x] 1.5 `backend/app/cleaning/infrastructure/models.py`: add `CleaningTaskMessageModel` —
      `Base, UUIDPrimaryKeyMixin, TenantScopedMixin` (design D1: **not** `cleaning_photos`'
      tenant-less shape — the twin table gets its own `tenant_id`, literally the
      `__table_args__` of `IncidentPhotoModel`): `ForeignKeyConstraint(["tenant_id",
      "task_id"], ["cleaning_tasks.tenant_id", "cleaning_tasks.id"], ondelete="RESTRICT")`,
      `Index("ix_cleaning_task_messages_tenant_id_task_id", "tenant_id", "task_id")`. Columns:
      `task_id: Mapped[uuid.UUID]` (no separate FK — the composite one already covers it, same
      note as `IncidentPhotoModel`), `author_id: Mapped[uuid.UUID] = mapped_column(Uuid,
      ForeignKey("users.id", ondelete="RESTRICT"))`, `author_role: Mapped[UserRole] =
      mapped_column(Enum(UserRole, native_enum=False, length=32))` (design's schema note says
      `varchar`, not the existing native `user_role` Postgres type — reusing that type across a
      second table's migration is complexity this design does not ask for; `native_enum=False`
      gives a plain `VARCHAR` column while keeping the Python-side `UserRole` round-trip),
      `content: Mapped[str] = mapped_column(String(MAX_CLEANING_TASK_MESSAGE_LENGTH))`,
      `created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))` — **no
      `server_default`**, written by the use case (design D1/D5, same reasoning as
      `IncidentPhotoModel.created_at`: a burst under one Postgres `now()` would collapse
      chronological order). `__tablename__ = "cleaning_task_messages"`. [R1]
- [x] 1.6 `backend/app/maintenance/infrastructure/models.py`: mirror of 1.5 —
      `IncidentMessageModel`, `__tablename__ = "incident_messages"`, composite FK to
      `incidents.tenant_id`/`incidents.id`, `incident_id` column, otherwise identical shape.
      [R2]
- [x] 1.7 `backend/app/notifications/domain/enums.py`: add `CLEANING_TASK_MESSAGE =
      "CLEANING_TASK_MESSAGE"` and `INCIDENT_MESSAGE = "INCIDENT_MESSAGE"` to `NotificationType`
      — the divergence from PRD §14's sixteen that D8 declares, same precedent as
      `REVIEW_RESPONSE_APPROVED`. [R4]
- [x] 1.8 Migration. First confirm there is one alembic head: `docker compose exec backend uv
      run alembic heads` (stack up — `make up` in this worktree first). Design's Risk section
      measured a single head (`2b28c6b3f82a`, `guest_portal_messaging`) as of 2026-09-02 by a
      static scan of `down_revision`, but says explicitly to re-check live before writing
      `down_revision` — if `alembic heads` prints more than one, resolve with `alembic merge`
      first (same preflight PR #153 needed). Then `docker compose exec backend uv run alembic
      revision -m "cleaning_task_messages_and_incident_messages"` and hand-write `upgrade`/
      `downgrade` creating both tables from 1.5/1.6 in **one** revision (design D1's "un solo
      change"). Apply with `docker compose exec backend uv run alembic upgrade head` and
      confirm `alembic heads` shows the new single head. [R1, R2]
- [x] 1.9 Test: `backend/tests/cleaning/test_models.py` and
      `backend/tests/maintenance/test_models.py` (or new sibling files) — a message row can be
      inserted and its composite FK rejects a `task_id`/`incident_id` from another tenant (the
      same case `test_a_photo_cannot_be_attached_to_an_incident_of_another_tenant` drives for
      `incident_photos`). [R1, R2, R3.2]

## 2. Cleaning: send/list use cases and the notification <!-- panel: PASS 2026-09-02 -->

- [x] 2.1 `backend/app/cleaning/domain/notifications.py`: add `staff_message_notification(...)`
      — same shape as `assignment_notification`/`no_cleaner_available_notification`: `body`
      carries only `message_id` and `task_id` plus a constant text ("Tienes un mensaje nuevo en
      la tarea…"), never `content` (design D8). `notification_type =
      NotificationType.CLEANING_TASK_MESSAGE.value`, `related_type =
      RELATED_TYPE_CLEANING_TASK`, `related_id = task_id`. No `sla_deadline_at` (design D8: no
      response deadline). [R4]
- [x] 2.2 `backend/app/cleaning/application/use_cases.py`: add `SendCleaningTaskMessageUseCase`
      — inherits `_TaskTransitionMixin` for `_load_task` alone (same reason
      `UploadCleaningPhotoUseCase` does). Constructor: `tasks`, `messages:
      CleaningTaskMessageRepository`, `users: UserRepository`, `configs:
      TenantConfigRepository`, `notifications: NotificationLogRepository`, `uow: UnitOfWork`.
      `execute(*, tenant_id, task_id, actor: CleaningActor, content: str, now: datetime) ->
      CleaningTaskMessage`:
      1. `task = await self._load_task(tenant_id, task_id, actor)` — R1.1/R1.3/R1.4's scoping
         and the shared `CleaningTaskNotFoundError` for an unowned task, in one call.
      2. Build the message with `author_id=actor.user_id`, `author_role=actor.role` (frozen at
         write time, design D2 — never a `JOIN` to `users.role`), `content`, `now`.
      3. `await self._messages.add(tenant_id, message)`.
      4. Notify (R4.2/R4.3, design D9): if `actor.role` is `CLEANER`, fan out one
         `staff_message_notification` per active `PROPERTY_MANAGER` of the tenant, same pattern
         as `_notify_manager_unassigned` — `self._users.list(tenant_id, UserFilters(role=
         UserRole.PROPERTY_MANAGER, status=UserStatus.ACTIVE), page=1, per_page=
         _MAX_MANAGER_RECIPIENTS)` (reuse the module's existing `_MAX_MANAGER_RECIPIENTS = 20`),
         `dispatch_and_persist(..., log_builder=staff_message_notification, ...)` per recipient,
         logging (not failing) if the tenant has no active manager — exactly
         `_notify_manager_unassigned`'s fallback. If `actor.role` is `PROPERTY_MANAGER`, notify
         the task's `assigned_cleaner_id` alone, one `dispatch_and_persist` call — skip
         entirely if the task has no assignee (nobody to notify).
      5. `await self._uow.commit()` once, after the message row and every notification row are
         staged — message + fan-out is one transaction.
      Never accept `author_role`/`author_id` from a request field — always `actor`.
      `author_role` stores the persisted `UserRole`, never `MessageSenderType` (R3.3): do not
      import anything from `app.messaging.domain.enums`, and do not touch `Conversation`,
      `READ_CONVERSATIONS` or `MANAGE_CONVERSATIONS` anywhere in this section. [R1, R3.3, R4]
- [x] 2.3 `backend/app/cleaning/application/use_cases.py`: add
      `ListCleaningTaskMessagesUseCase(_TaskTransitionMixin)` — mirrors
      `ListCleaningPhotosUseCase`: constructor takes `tasks`, `messages`. `execute(*, tenant_id,
      task_id, actor: CleaningActor, page: int, per_page: int) -> CleaningTaskMessagePage`
      resolves `_load_task` first (so an unowned task's `404` is the shared, byte-identical
      `CleaningTaskNotFoundError` and not an empty list), then
      `self._messages.list_for_task(...)`. [R1]
- [x] 2.4 `backend/app/cleaning/infrastructure/repositories.py`: add
      `SqlAlchemyCleaningTaskMessageRepository` — unlike `SqlAlchemyCleaningPhotoRepository`,
      `cleaning_task_messages` carries its own `tenant_id` (design D1, same departure
      `IncidentPhotoModel` took from `CleaningPhotoModel`), so `add` filters `tenant_id`
      directly (with the explicit `CrossTenantWriteError` guard —
      `SqlAlchemyIncidentPhotoRepository.add`'s pattern, needed because limit 3 of
      `app/core/db.py` says the global filter does not cover INSERTs) and `list_for_task` reads
      through the composite index, ordered `created_at, id` ascending, paginated with
      `LIMIT`/`OFFSET` and a `COUNT(*)` for `total`. [R1]
- [x] 2.5 Tests: `backend/tests/cleaning/test_use_cases.py` (or a new
      `test_task_messages_use_case.py`) — `SendCleaningTaskMessageUseCase`: a `CLEANER` writes
      on her own task (201-equivalent, persists, notifies every active manager); a `CLEANER` on
      someone else's task raises `CleaningTaskNotFoundError`, never `403` (R1.3); a
      `PROPERTY_MANAGER` writes on any task of the tenant and notifies the assigned cleaner
      (R1.4); a manager writing on an unassigned task persists the message and sends no
      notification. `ListCleaningTaskMessagesUseCase`: chronological order, pagination,
      `CLEANER` scoped to her own task, manager sees all. Tenant isolation: a task from tenant B
      is invisible to tenant A's actor (steering/security.md rule 1, R3.2) — new test, not a
      variant of an existing one, per `steering/testing.md`'s DoD §28.18 obligation. [R1, R3.2,
      R4]

## 3. Cleaning: the API — router, schemas, the "either permission" gate <!-- panel: PASS 2026-09-02 -->

- [x] 3.1 `backend/app/auth/api/dependencies.py`: add `require_any(*permissions: Permission) ->
      Callable[..., Awaitable[AuthenticatedRequest]]` next to `require`. Authorises if the
      caller's role holds **any** of the given permissions (design D3: writing a cleaning-task
      message needs `EXECUTE_CLEANING_TASKS` **or** `MANAGE_CLEANING_TASKS`, because
      `PROPERTY_MANAGER` has the latter and not the former — `require()` only ever checks one).
      Tag the returned callable's `REQUIRED_PERMISSION_ATTR` with `frozenset(permissions)`
      rather than a single `Permission` (a tuple/frozenset is the only way the route-walk test
      can see **both** declared permissions instead of picking one arbitrarily). [R3.1]
- [x] 3.2 `backend/tests/test_route_authorization.py`: update `_declared_permissions`'s `walk`
      to flatten a `frozenset` tag into the `found` set element-by-element (so
      `test_every_declared_permission_is_in_the_catalogue`'s `isinstance(permission,
      Permission)` still holds for each element) while still adding a bare `Permission` tag
      as-is. Add a small dedicated test for `require_any` itself, same shape as
      `test_the_check_catches_an_endpoint_that_forgets`: a route gated by
      `require_any(Permission.A, Permission.B)` is authorised for a role holding either one and
      refused for a role holding neither. Add the two new paths (`POST`/`GET
      /api/v1/cleaning-tasks/{task_id}/messages`) to `test_the_protected_endpoints_are_the_ones_expected`'s
      snapshot once 3.4 mounts them. [R3.1]
- [x] 3.3 `backend/app/cleaning/api/schemas.py`: add `SendCleaningTaskMessageRequest`
      (`content: Annotated[MultiLineText, Field(min_length=1,
      max_length=MAX_CLEANING_TASK_MESSAGE_LENGTH)]`, `model_config = ConfigDict(extra="forbid",
      str_strip_whitespace=True)` — the exact shape of `CompleteIncidentRequest.materials`,
      design D5) and `CleaningTaskMessageResponse` (`id`, `author_id`, `author_role`, `content`,
      `created_at` — an allowlist built with a `from_domain` classmethod, never
      `model_validate`, same discipline as `CleaningPhotoResponse` even though this entity has
      no field that needs excluding) and `CleaningTaskMessagePageResponse` (`data: list[...]`,
      `total`, `page`, `per_page`, `total_pages` — `CleaningTaskPageResponse`'s `build`
      pattern, reusing the file's existing `MAX_PAGE`/`MAX_PER_PAGE`). [R1, R5]
- [x] 3.4 `backend/app/cleaning/api/dependencies.py`: add
      `get_send_cleaning_task_message_use_case`/`get_list_cleaning_task_messages_use_case`,
      wiring `SqlAlchemyCleaningTaskMessageRepository` alongside the existing task/user/config/
      notification repositories, same shape as the photo use-case wiring. [R1]
- [x] 3.5 New `backend/app/cleaning/api/messages_router.py` (design's file table — its own
      module, the way `photos_router.py` is its own module rather than living in
      `tasks_router.py`), `router = APIRouter(prefix="/cleaning-tasks", tags=["cleaning"],
      responses=AUTHENTICATED_RESPONSES)`:
      - `POST /{task_id}/messages` → `201 CleaningTaskMessageResponse`, gated by
        `Annotated[AuthenticatedRequest, Depends(require_any(Permission.EXECUTE_CLEANING_TASKS,
        Permission.MANAGE_CLEANING_TASKS))]` (design D3). Reuses `tasks_router.py`'s `_actor`
        shape to build a `CleaningActor` from `authenticated`/`client_ip` (either import it or
        redeclare identically — match the existing module's choice for photos vs. tasks).
      - `GET /{task_id}/messages` → `200 CleaningTaskMessagePageResponse`, gated by `ReadDep`
        (`READ_CLEANING_TASKS` — both `CLEANER` and `PROPERTY_MANAGER` already hold it, no `or`
        needed for reads, design D3), `page`/`per_page` query params bounded by
        `MAX_PAGE`/`MAX_PER_PAGE` like `list_cleaning_tasks`.
      Both docstrings state plainly that the row-level scoping (a `CLEANER` reaching only her
      own task) is derived inside the use case from `CleaningActor.restrict_to_cleaner_id`, not
      from any request field — the house convention every sibling route states. [R1, R3.1, R4]
- [x] 3.6 `backend/app/main.py`: `from app.cleaning.api.messages_router import router as
      cleaning_task_messages_router` and `app.include_router(cleaning_task_messages_router,
      prefix=API_V1_PREFIX)` next to `cleaning_tasks_router`. [R1]
- [x] 3.7 `sdd/steering/security.md` — rule 11 census: add the row for
      `cleaning_task_messages.content` under **excepción 3**, same wording pattern as
      `incidents.materials`'s row: escritor `staff-messaging` (this change), teclea una `CLEANER`
      con `EXECUTE_CLEANING_TASKS` (o un `PROPERTY_MANAGER` con `MANAGE_CLEANING_TASKS`) sobre
      un hilo que ya alcanza, acotado a `MAX_CLEANING_TASK_MESSAGE_LENGTH` (2000) **en el DDL y
      en el esquema**, con recorte de espacios, `min_length=1` y el guardián de
      `app/core/storable_text.py`. **No propaga**: `CleaningTaskMessage` no está en
      `AUDITABLE_FIELDS` (design D7 — no es una entidad auditada, no una mutación de
      `CleaningTask`) y no hay `TimelineEvent` que la lleve en su `metadata` (design D6 — no se
      emite ninguno). Update the header counts (columnas, filas) against the table itself per
      the section's own rule ("se cuentan contra la tabla al tocarla, no se incrementan de
      memoria") — do **not** copy this task's prose numbers, recount after editing. [R5.3]
- [x] 3.8 `make check-rule11-ownership` (host `python3`, no Docker, no stack) passes after 3.7.
      [R5.3]
- [x] 3.9 Tests: `backend/tests/cleaning/test_messages_api.py` (new, mirrors
      `test_photos_api.py`'s shape) — per-role authorization matrix (`CLEANER` on her own task:
      201/200; `CLEANER` on another cleaner's task: 404, never 403; `PROPERTY_MANAGER`: 201/200
      on any task of the tenant; `TECHNICIAN`/other roles: 403 or 404 per the route-walk
      convention), the response body is the field allowlist of 3.3 and not a raw entity dump,
      `content` over `MAX_CLEANING_TASK_MESSAGE_LENGTH` is `422`, and a `NotificationLog` row
      lands for the right recipient(s) after each write (assert via the repository, not by
      re-deriving `dispatch_and_persist`'s internals). Extend
      `backend/tests/cleaning/test_free_text_sink_contract.py` (or add a small sibling) with the
      two structural claims rule 11 needs pinned per column: `content` never reaches
      `audit_logs.changes` and never reaches any `timeline_events.metadata`. [R1, R3.1, R3.2,
      R4, R5]

## 4. Maintenance: send/list use cases and the notification (mirror of section 2) <!-- panel: PASS 2026-09-02 -->

- [x] 4.1 `backend/app/maintenance/domain/notifications.py`: add `staff_message_notification(...)`
      — the literal mirror of 2.1, `notification_type =
      NotificationType.INCIDENT_MESSAGE.value`, `related_type` the incident's existing constant,
      `related_id = incident_id`. [R4]
- [x] 4.2 `backend/app/maintenance/application/use_cases.py`: add
      `SendIncidentMessageUseCase` — mirror of 2.2, using the module-level
      `_load_incident_in_scope(incidents, tenant_id, incident_id, actor)` instead of a mixin
      method (maintenance's existing pattern, not `cleaning`'s mixin). Recipient rule (R4.2/
      R4.3, design D9): if `actor.role` is `TECHNICIAN`, fan out to every active
      `PROPERTY_MANAGER` of the tenant (new local `_MAX_MANAGER_RECIPIENTS = 20` in this module,
      same value as `cleaning`'s — there is no existing manager fan-out in `maintenance` to
      reuse); if `actor.role` is `PROPERTY_MANAGER`, notify the incident's
      `assigned_technician_id` alone, skipping if unassigned. Constructor: `incidents`,
      `messages: IncidentMessageRepository`, `users`, `configs`, `notifications`, `uow`. Same
      R3.3 constraint as 2.2: `author_role` is the persisted `UserRole`, never
      `MessageSenderType`. [R2, R3.3, R4]
- [x] 4.3 `backend/app/maintenance/application/use_cases.py`: add
      `ListIncidentMessagesUseCase` — mirror of 2.3, resolving through
      `_load_incident_in_scope` first. [R2]
- [x] 4.4 `backend/app/maintenance/infrastructure/repositories.py`: add
      `SqlAlchemyIncidentMessageRepository` — mirror of 2.4, following
      `SqlAlchemyIncidentPhotoRepository`'s already-tenant-scoped shape (this table needs no
      join, unlike its cleaning cousin, because both twin tables carry `tenant_id` per design
      D1 — the only place `cleaning`/`maintenance` diverge in shape here is that `cleaning`'s
      *existing* photo table has no `tenant_id` and this new one does, while `maintenance`'s
      photo table already did). [R2]
- [x] 4.5 Tests: mirror of 2.5 in `backend/tests/maintenance/` — `TECHNICIAN` on her own
      incident, `TECHNICIAN` on another's (404, never 403, R2.3), `PROPERTY_MANAGER` on any
      incident of the tenant (R2.4), chronological order and pagination, tenant isolation
      (rule 1, R3.2). [R2, R3.2, R4]

## 5. Maintenance: the API (mirror of section 3, no "or" needed) <!-- panel: PASS 2026-09-03 -->

- [x] 5.1 `backend/app/maintenance/api/schemas.py`: `SendIncidentMessageRequest`,
      `IncidentMessageResponse`, `IncidentMessagePageResponse` — mirror of 3.3, using
      `MAX_INCIDENT_MESSAGE_LENGTH`. [R2, R5]
- [x] 5.2 `backend/app/maintenance/api/dependencies.py`:
      `get_send_incident_message_use_case`/`get_list_incident_messages_use_case`. [R2]
- [x] 5.3 New `backend/app/maintenance/api/messages_router.py`, `prefix="/incidents"`:
      - `POST /{incident_id}/messages` → `201 IncidentMessageResponse`, gated by `ExecuteDep`
        (`EXECUTE_INCIDENTS` — both `TECHNICIAN` and `PROPERTY_MANAGER` already hold it, design
        D3: **no** `require_any` needed here, unlike cleaning).
      - `GET /{incident_id}/messages` → `200 IncidentMessagePageResponse`, gated by `ReadDep`
        (`READ_INCIDENTS`).
      Same docstring convention as 3.5 about where the row-level scoping actually lives
      (`IncidentActor.restrict_to_technician_id`, inside the use case). [R2, R3.1, R4]
- [x] 5.4 `backend/app/main.py`: mount the new router next to `incidents_router`. [R2]
- [x] 5.5 `sdd/steering/security.md` — rule 11 census row for `incident_messages.content`,
      mirror of 3.7 (excepción 3, escritor `staff-messaging`, `TECHNICIAN` con
      `EXECUTE_INCIDENTS` o `PROPERTY_MANAGER`, `MAX_INCIDENT_MESSAGE_LENGTH`). Recount the
      header numbers again against the table (3.7 already moved them once; this row moves them
      again). [R5.3]
- [x] 5.6 `make check-rule11-ownership` passes after 5.5. [R5.3]
- [x] 5.7 Tests: `backend/tests/maintenance/test_messages_api.py`, mirror of 3.9 —
      authorization matrix, response allowlist, `422` over the length bound, notification
      fan-out assertions, and the two `test_free_text_sink_contract.py` structural claims
      (never `audit_logs.changes`, never `timeline_events.metadata`) for `incident_messages.
      content`. [R2, R3.1, R3.2, R4, R5]

## 6. Verification

- [x] 6.1 Full backend suite: `docker compose exec backend uv run pytest` (stack up). Every
      test from sections 1-5 green, no regression elsewhere. Result: 9778 passed, 41 skipped,
      1 failed (`test_the_committed_contract_matches_the_code`, expected — fixed by 6.5) in
      587.65s.
- [x] 6.2 `make check-rule11-ownership` green (host, no Docker) — confirms 3.7/5.5 didn't leave
      a stray ownership claim outside the census table. Result: green, "ningún bloque fuera de
      la tabla de la regla 11 declara quién escribe un sumidero del censo".
- [x] 6.3 `docker compose exec backend uv run alembic heads` shows exactly one head, and it is
      the revision from 1.8. Result: `3488de4c4f49 (head)`, matches.
- [x] 6.4 `cd backend && uv run pyright .` — static findings reported separately from test
      failures, per `sdd/project.md`. Result: 869 errors, 0 warnings (pre-change baseline per
      section 4's own measurement: 857 — the domain already carried a large pre-existing static
      debt). Checked every error inside a `staff-messaging`-touched or -created file: all are
      either (a) the same `authenticated.context.tenant_id: UUID | None` → `execute(tenant_id:
      UUID)` narrowing gap every sibling router already has (`tasks_router.py` etc.), or (b) the
      same cross-method `get_active_by_id(tenant_id, task.assigned_cleaner_id)` narrowing
      artifact already reviewed and accepted in sections 2/4 (the caller guards with `is not
      None` before calling; pyright can't see the caller's guard from the callee), or (c)
      pre-existing errors in code this change did not write (`list_rejecters_for_reservation`,
      `list_open_for_property`'s Protocol-stub return type). No new error class was introduced by
      this change's own logic.
- [x] 6.5 Regenerate and commit the API contract: `make openapi` (backend/openapi.json) plus
      the frontend-derived artefact — from this worktree, the `docker compose cp` workaround
      `sdd/project.md`'s "Worktree bootstrap" section documents (`mkdir -p /backend`, `cp
      backend/openapi.json`, symlink `/frontend`, then `npm run api:generate`) — since a linked
      worktree's `frontend` container cannot resolve `/backend/openapi.json` on its own.
      Result: both regenerated; `tests/test_openapi_contract.py` (14 tests) and
      `npm run api:check` both green after.
- [x] 6.6 Manual pass with the stack up (`make up`, or `make up PORT_OFFSET=<n>` for a browser):
      as a seeded `CLEANER`, write and read a message on her own assigned task; confirm a
      seeded `PROPERTY_MANAGER` sees it in the in-app notification inbox
      (`GET /notifications`) and can reply; confirm the reply notifies the cleaner. Repeat the
      same round trip for a `TECHNICIAN` and an incident. Confirm a `CLEANER` gets `404` (not
      `403`) against a task assigned to a different cleaner.

      Result: this feature has no frontend UI (no task in sections 1-5 touches `frontend/`), so
      the pass was done via real HTTP calls against the live stack (`make up`, `make bootstrap` +
      `make seed-demo` — this worktree had no `.env` bootstrap/seed values filled in, so they
      were filled with disposable dev-local credentials first) run from inside the `backend`
      container (a linked worktree publishes no ports, so `localhost:8000` isn't reachable from
      the host). All checks passed: `CLEANER` `POST`/`GET
      /api/v1/cleaning-tasks/{task_id}/messages` on her own seeded task (201/200, full field
      allowlist); `PROPERTY_MANAGER`'s `GET /api/v1/notifications` showed a
      `CLEANING_TASK_MESSAGE` row; manager's reply `POST` returned 201; cleaner's own
      `GET /notifications` then showed a fresh `CLEANING_TASK_MESSAGE` row for the reply.
      Identical round trip for `TECHNICIAN`/incident with `INCIDENT_MESSAGE`. One deviation from
      the literal task wording: `make seed-demo` provisions exactly one `CLEANER` per tenant, so
      there is no second cleaner's task to test against — the isolation check used a random
      unknown `task_id` instead (same code path as an unowned task, since `_load_task` can't
      distinguish "exists, not mine" from "doesn't exist" by design D4), and got the expected
      `404` with `{"error":{"code":"NOT_FOUND",...}}`, never `403` — the exact "another cleaner's
      task" case is exhaustively covered by the automated suite instead (sections 2/3/4/5's
      dedicated cross-tenant/cross-assignee tests).

## Implementation Notes

- `CleaningTaskMessage`/`IncidentMessage` are plain dataclasses in `app/{cleaning,maintenance}/domain/entities.py`, no invariant — construct directly, no factory method.
- `MAX_CLEANING_TASK_MESSAGE_LENGTH` / `MAX_INCIDENT_MESSAGE_LENGTH` = 2000, both in the respective `domain/entities.py`, importable by `api/schemas.py`.
- `CleaningTaskMessageRepository`/`IncidentMessageRepository` Protocols live in the respective `domain/repositories.py`; both take `tenant_id` first on every method and both `add`/`list_for_task`/`list_for_incident` never commit (use case owns the transaction).
- `CleaningTaskMessagePage`/`IncidentMessagePage` are frozen dataclasses (`items`, `total`), same shape as `Page`/`IncidentPage`.
- **`cleaning_tasks` had no `UniqueConstraint("tenant_id", "id")` before this change** — unlike `incidents`, which already had `uq_incidents_tenant_id_id` from `incident_photos`. Added it here as `uq_cleaning_tasks_tenant_id_id` (model `__table_args__` + migration) because the composite FK on `cleaning_task_messages` requires it. Not called out explicitly in tasks.md 1.5 but required for the schema to be buildable at all — same precedent `incident_photos` set for `incidents`.
- `CleaningTaskMessageModel`/`IncidentMessageModel`: `TenantScopedMixin` only (no `TimestampMixin` — immutable after insert, no `updated_at`), `created_at` has **no `server_default`** — the use case in section 2/4 must pass `now` explicitly or the column will reject the insert (`NOT NULL`, no default at the DB or ORM level).
- `author_role` column is `Enum(UserRole, native_enum=False, length=32)` — compiles to plain `VARCHAR(32)` with **no CHECK constraint** (verified by compiling the mapped table's DDL before writing the migration). Not the native `user_role` Postgres enum type.
- Migration `3488de4c4f49_cleaning_task_messages_and_incident_.py` (down_revision `2b28c6b3f82a`) creates both tables plus `uq_cleaning_tasks_tenant_id_id` in one revision. `alembic check` reports no drift against the models. Up/down/up round-trip verified.
- `NotificationType.CLEANING_TASK_MESSAGE` and `NotificationType.INCIDENT_MESSAGE` added to `app/notifications/domain/enums.py` — section 2/4's `staff_message_notification` builders should use `.value` for `notification_type`.
- Test helper `_tenant_property_user` in `tests/cleaning/test_models.py` was widened to accept `name`/`billing_email`/`user_email` kwargs (previously hardcoded) — needed to build a second tenant for the isolation test since `UserModel.email` is globally unique (`uq_users_lower_email`). Existing callers are unaffected (defaults unchanged).
- No `application/`, `api/`, or notification-builder code was touched in section 1 — `staff_message_notification`, the use cases, the repositories' SQL implementations (`infrastructure/repositories.py`), and the routers are all section 2+ work, still open.
- **Adding a new tenant-scoped table also requires updating `backend/tests/cli/test_demo_reset.py`** — its coverage test pins the expected table set by literal value on purpose, and its `populate_tenant` fixture needs one row per scoped table for the isolation assertion to be non-vacuous. Fixed here for `cleaning_task_messages`/`incident_messages` (literal set entries + two rows added to `populate_tenant`, reusing the existing `task`/`incident`/`user` fixtures). Not listed anywhere in tasks.md — a full-suite run is what caught it. Worth remembering for any future change that adds a tenant-scoped table.
- Full backend suite verified green for section 1's scope after that fix. Two unrelated pre-existing findings from the same run, neither a section-1 regression: `tests/test_openapi_contract.py::test_the_committed_contract_matches_the_code` fails because `NotificationType` gained two members and `openapi.json` hasn't been regenerated yet — expected until task 6.5; `tests/messaging/test_free_text_sink_contract.py::test_the_portal_never_puts_the_message_in_the_timeline` failed once on a random UUID coincidentally containing the literal leak-marker substring `"4471"` — a pre-existing flake unrelated to this change (not touched by any staff-messaging code).

### Section 2 (cleaning use cases/notification) — notes for section 4 (`maintenance` mirror)

- `staff_message_notification` lives in `app/cleaning/domain/notifications.py`, signature `(*, tenant_id, task_id, message_id, recipient_id, recipient_contact="", now, channel=IN_APP, contact=None)` — the `maintenance` twin should take `incident_id` in place of `task_id` and keep the same kwarg names otherwise (`dispatch_and_persist` forwards `tenant_id` on its own; only pass the rest as `builder_kwargs`).
- `body` is a plain f-string embedding only `task_id`/`message_id` plus a constant Spanish sentence ("Tienes un mensaje nuevo en la tarea de limpieza…") — never `content`, no JSON shape. `related_type`/`related_id` point at the task, not the message row (same as every other builder in the file).
- `SendCleaningTaskMessageUseCase`/`ListCleaningTaskMessagesUseCase` sit at the bottom of `app/cleaning/application/use_cases.py`, right after `ListCleaningPhotosUseCase` and before `_effective_checkout`. Both inherit `_TaskTransitionMixin` **only** for `_load_task` — no `_transition` call anywhere, same as the photo use cases.
- The manager fan-out is its own method (`_notify_managers`) rather than reusing `_notify_manager_unassigned`: R4.2 wants `PROPERTY_MANAGER` **only**, with no `TENANT_OWNER` fallback (design D9 rejects an "assigned manager" concept) — copying `_notify_manager_unassigned`'s two-role loop verbatim would over-notify owners R4.2 never asks for. When the active-manager page is empty, log (`cleaning.staff_message_without_manager`) and return — do not raise, do not fall back to another role.
- The cleaner-notification branch (`_notify_cleaner`) resolves the recipient with `self._users.get_active_by_id(tenant_id, task.assigned_cleaner_id)`, exactly `_notify_validation_failure`'s pattern (line ~1312 of `use_cases.py`) — an inactive/deleted cleaner logs (`cleaning.staff_message_without_cleaner`, `reason="inactive"`) and sends nothing rather than failing the whole `execute`.
- Skip notifying entirely (no branch taken) when a `PROPERTY_MANAGER` messages a task with `assigned_cleaner_id is None` — checked before calling `_notify_cleaner`, not inside it, so an unassigned task never even resolves a (nonexistent) recipient.
- `CleaningTaskMessagePage`/`CleaningTaskMessageRepository` needed importing into `use_cases.py`'s existing `from app.cleaning.domain.repositories import (...)` block — the `maintenance` equivalent will need the same for `IncidentMessagePage`/`IncidentMessageRepository` in that module's import block.
- `SqlAlchemyCleaningTaskMessageRepository` (in `app/cleaning/infrastructure/repositories.py`, placed right after `SqlAlchemyCleaningPhotoRepository` and before `SqlAlchemyUnscopedCleaningPhotoLocationQuery`) filters `tenant_id` directly on both `add` and `list_for_task` — no join, unlike the sibling photo repo — and `add` raises `CrossTenantWriteError(entity="cleaning_task_message", ...)` before touching the session, exactly `SqlAlchemyIncidentPhotoRepository.add`'s shape. `list_for_task` does a `COUNT(*)` then a `LIMIT`/`OFFSET` select, `ORDER BY created_at, id` — same idiom as `SqlAlchemyCleaningTaskRepository.list`.
- `test_writer_census.py` needed updating the moment `staff_message_notification` got a real call site: `CLEANING_TASK_MESSAGE` moved from `WITHOUT_WRITER` to `WITH_WRITER`, and `test_exactly_six_types_have_no_writer` became `test_exactly_five_types_have_no_writer` (only `INCIDENT_MESSAGE` remains without a writer). Section 4 will need the mirror edit: move `INCIDENT_MESSAGE` too and rename/update that test again (four → zero of the `staff-messaging` pair left, five → four types overall without a writer... it will actually go to **four** once `INCIDENT_MESSAGE` also gains its writer — recount `WITHOUT_WRITER` at that point rather than trusting this sentence).
- Repository-level tenant-isolation test for the new table lives in `tests/cleaning/test_repositories.py` (new `# --- cleaning_task_messages ---` section at the end of the file), not only at the use-case/fake level — `cleaning_task_messages` carries its own `tenant_id` column (unlike `cleaning_photos`), so a real DB-backed isolation test is the one that actually exercises the repository's `WHERE tenant_id = ...` rather than a hand-written fake's bookkeeping. Mirror this for `incident_messages` in `tests/maintenance/test_repositories.py` (or wherever that module's repository tests live) rather than relying on the use-case-level fake test alone.
- Use-case tests live in a new file, `tests/cleaning/test_task_messages_use_case.py` (fakes only, no DB) — `tests/cleaning/test_use_cases.py` does not exist in this codebase, despite the task wording offering it as an option.

### Section 3 (cleaning API/router) — notes for section 5 (`maintenance` mirror)

- `require_any(*permissions)` now lives in `app/auth/api/dependencies.py`, next to `require`. It tags its returned dependency's `REQUIRED_PERMISSION_ATTR` with a `frozenset(permissions)` rather than a scalar `Permission` — `tests/test_route_authorization.py`'s `_declared_permissions` walk was updated to flatten a `frozenset` tag element-by-element (`isinstance(permission, frozenset)` branch) while still handling a bare `Permission` as before. Section 5's incident-message write route should reuse `require_any(Permission.EXECUTE_INCIDENTS, Permission.MANAGE_INCIDENTS)` directly — it is generic infrastructure, not something to redeclare per module. Its own dedicated test is `test_require_any_authorises_either_permission_and_refuses_neither` in that same file; no analogous test is needed for the `maintenance` route since it exercises the identical mechanism.
- `SendCleaningTaskMessageRequest`/`CleaningTaskMessageResponse`/`CleaningTaskMessagePageResponse` live at the bottom of `app/cleaning/api/schemas.py`, under a `# --- cleaning task messages (staff-messaging) ---` heading. `CleaningTaskMessagePageResponse.build` takes the domain `CleaningTaskMessagePage` object directly (`page: CleaningTaskMessagePage, *, page_number: int, per_page: int`) rather than `(items, total, page, per_page)` like the sibling `CleaningTaskPageResponse.build` — a deliberate deviation since `ListCleaningTaskMessagesUseCase.execute` already returns the page object with both `items` and `total` on it. The `maintenance` mirror can pick either shape; there is no house rule forcing one over the other, just internal consistency within whichever schemas.py it lands in.
- `get_send_cleaning_task_message_use_case`/`get_list_cleaning_task_messages_use_case` are new builders at the bottom of `app/cleaning/api/dependencies.py`, after `get_serve_cleaning_photo_use_case`. Neither uses `_lifecycle_kwargs` (sending/listing messages moves no property state), the same non-lifecycle shape `get_upload_cleaning_photo_use_case` already established.
- `app/cleaning/api/messages_router.py` is its own module (the `photos_router.py` precedent), `prefix="/cleaning-tasks"`, and redeclares its own `_actor`/`ReadDep` rather than importing `tasks_router.py`'s — matching the existing convention that no cleaning router imports another router module. Its write-gate dependency is named `SendMessageDep` (not `ExecuteDep`, since it is `require_any(...)`, not `require(...)`). Mounted in `app/main.py` right after `cleaning_tasks_router` and before `cleaning_photos_router`, with `from app.cleaning.api.messages_router import router as cleaning_task_messages_router`. No new error handler was needed: the use case only ever raises `CleaningTaskNotFoundError`, already mapped by `register_cleaning_error_handlers`.
- `tests/test_route_authorization.py`'s `test_the_protected_endpoints_are_the_ones_expected` snapshot gained exactly one new path, `"/api/v1/cleaning-tasks/{task_id}/messages"` (both `POST` and `GET` live on the one path, same convention as `/photos`). Section 5's incident-message path will be a second new entry there, e.g. `"/api/v1/incidents/{incident_id}/messages"`.
- The rule-11 census row for `cleaning_task_messages.content` went in `sdd/steering/security.md` under **excepción 3**, as the seventh column/sixth writer of that exception's form — a new paragraph was added there (`"staff-messaging trae el sexto escritor..."`) alongside the existing `tech-cycle-completion` one, and the "Cubre X columnas —Y escritores—" lead sentence was updated from six/five to seven/six. **While touching the header counts, a pre-existing, unrelated drift was found and corrected**: `revenue-reviews` (archived 2026-09-02) had added four columns/four rows to the table without ever updating the "Veintiuna columnas, veintinueve filas" sentence — the true count before this change's own row was 25 columns/33 rows, not 21/29. Both numbers were corrected and the correction is noted in prose (the doc's own established style for this kind of fix). Section 5 should recount against the table again when adding `incidents.messages` — i.e. expect the baseline to already read 26 columns/34 rows before its own addition, not 21/29.
- `make check-rule11-ownership` passes with the security.md edits as they stand: the table itself (`sdd/steering/security.md`) is explicitly out of the guard's scan (it is the declared **authority**, per the `<!-- rule11-scope -->` comment), so writing ownership prose inside the table's own rows and surrounding paragraphs is not itself a violation — only a *second* place outside this table claiming who writes a sink column would trip the guard.
- `tests/cleaning/test_messages_api.py` (new) covers the full per-role matrix end-to-end over ASGI, including that `TENANT_OWNER` (who holds `READ_CLEANING_TASKS` but neither `EXECUTE_` nor `MANAGE_CLEANING_TASKS`) can `GET` but gets `403` on `POST` — a good case to mirror for `maintenance` if an analogous role split exists there (check `TENANT_OWNER`'s incident permissions before assuming the same asymmetry holds).
- `tests/cleaning/test_free_text_sink_contract.py` (new, since no such file existed for `cleaning` before this change) is deliberately much smaller than `tests/maintenance/test_free_text_sink_contract.py`'s multi-writer AST census — `cleaning_task_messages.content` has exactly one writer (RBAC-gated, never anonymous), so there is no writer census to walk. It pins three things: the DDL/schema bound agree, `ChangeSet("CLEANING_TASK_MESSAGE")` raises at construction because the entity type itself is absent from `AUDITABLE_FIELDS` (stronger than merely lacking `content` in an allowlist), and `SendCleaningTaskMessageUseCase.__init__`'s parameter set has no `timeline` collaborator at all (structural proof it cannot write a `TimelineEvent`, checked via `inspect.signature`). Section 5 should write an equivalent small file for `incident_messages.content` rather than trying to extend the existing incidents census file, which is about a different, multi-writer set of columns.
- Full section-3 verification: `docker compose exec backend uv run pytest tests/cleaning/ tests/test_route_authorization.py tests/notifications/ -q` → 1000 passed. `docker compose exec backend uv run pytest tests/ -q -k "openapi or free_text_sink"` → 1 failed (`test_the_committed_contract_matches_the_code`, expected until task 6.5 regenerates `openapi.json`; not a section-3 regression), 62 passed. Isolated `-k "free_text_sink"` alone → 41 passed, no regressions.

### Section 4 (maintenance use cases/notification) — notes for section 5 (`maintenance` API mirror)

- `staff_message_notification` was appended to `app/maintenance/domain/notifications.py` right after `incident_high_notification` (the module's last existing builder), literal mirror of `cleaning`'s: same kwarg names but `incident_id` in place of `task_id`, `notification_type = NotificationType.INCIDENT_MESSAGE.value`, `related_type = RELATED_TYPE_INCIDENT` (the module's existing constant), body is a constant Spanish sentence plus `incident_id`/`message_id`, never `content`, no `sla_deadline_at`.
- `SendIncidentMessageUseCase`/`ListIncidentMessagesUseCase` sit at the bottom of `app/maintenance/application/use_cases.py`, right after `ListIncidentPhotosUseCase`. Neither inherits a mixin — both call the module-level `_load_incident_in_scope(incidents, tenant_id, incident_id, actor)` directly, exactly as `ListIncidentPhotosUseCase` already does. `_MAX_MANAGER_RECIPIENTS = 20` is a new module-level constant placed immediately above `SendIncidentMessageUseCase` (this module had no existing manager fan-out to reuse the value from).
- The manager fan-out (`_notify_managers`) and technician-notification (`_notify_technician`) methods are literal mirrors of `cleaning`'s `_notify_managers`/`_notify_cleaner`: `_notify_managers` pages `UserFilters(role=PROPERTY_MANAGER, status=ACTIVE)` and logs `maintenance.staff_message_without_manager` (not raise) when the page is empty; `_notify_technician` resolves via `get_active_by_id` and logs `maintenance.staff_message_without_technician`, `reason="inactive"` when `None`. The "skip entirely when unassigned" branch is checked in `execute` before calling `_notify_technician`, same as `cleaning`.
- `IncidentMessage`, `IncidentMessagePage`, `IncidentMessageRepository` needed importing into `use_cases.py`'s existing `from app.maintenance.domain.entities import (...)` and `from app.maintenance.domain.repositories import (...)` blocks; `staff_message_notification` needed adding to the existing `from app.maintenance.domain.notifications import (...)` block. `dispatch_and_persist`, `NotificationType`, `NotificationLogRepository`, `UserFilters`, `UserRole`, `UserStatus`, `UserRepository` were already imported in this module (used by other flows), so no new import lines were needed for those.
- `SqlAlchemyIncidentMessageRepository` (in `app/maintenance/infrastructure/repositories.py`, placed at the very end of the file, after `SqlAlchemyUnscopedIncidentPhotoLocationQuery`, with its own `_to_message` helper right before the class) filters `tenant_id` directly on both `add` and `list_for_incident` — no join, confirming the task's premise that both twin tables carry their own `tenant_id`. `add` raises `CrossTenantWriteError(entity="incident_message", ...)`, `list_for_incident` does `COUNT(*)` then `LIMIT`/`OFFSET`, `ORDER BY created_at, id` — identical idiom to the cleaning adapter.
- `test_writer_census.py` (`tests/notifications/`) needed its mirror edit exactly as section 2's notes predicted: `INCIDENT_MESSAGE` moved from `WITHOUT_WRITER` to `WITH_WRITER`, `WITHOUT_WRITER` is now the pre-existing **four** (`LOCK_ALERT` + three `guest-scheduled-comms` reminders), and the test was renamed `test_exactly_four_types_have_no_writer` (from `test_exactly_five_types_have_no_writer`). The comment note's own hedge ("recount at that point") was correct to hedge — the final number is four, matching the arithmetic but worth confirming rather than trusting.
- Repository-level tenant-isolation test lives in `tests/maintenance/test_repositories.py`, new `# --- incident_messages ---` section at the end of the file (mirroring `cleaning_task_messages`'s section in the sibling file), not only at the use-case/fake level. Built against the real database using the module's existing local helpers `_tenant`/`_property`/`_incident` (module-level functions already in that file, not fixtures) for the second tenant, since the `world` fixture is single-tenant; a plain `UserModel(role=UserRole.TECHNICIAN, ...)` was constructed inline for the neighbour tenant's author (no existing multi-tenant user helper in this file to reuse).
- Use-case tests live in a new file, `tests/maintenance/test_incident_messages_use_case.py` (fakes only, no DB), literal structural mirror of `tests/cleaning/test_task_messages_use_case.py` — 11 tests, all passing. `IncidentActor` (unlike `CleaningActor`) has a mandatory `__post_init__` that rejects `user_id=None`, but every test here always passes a real id, so it needed no special handling.
- Section 5's read/write permission gate needs **no `require_any`**, unlike `cleaning`'s section 3: per tasks.md 5.3, `EXECUTE_INCIDENTS` already covers both `TECHNICIAN` and `PROPERTY_MANAGER` (design D13, cited at `IncidentActor.restrict_to_technician_id`'s docstring) — confirmed by reading that property's own comment, not assumed. `SendIncidentMessageUseCase.execute`'s `actor.role is UserRole.TECHNICIAN` branch is what does the row-level restriction inside the use case, exactly as the docstring convention in 3.5/5.3 requires.
- Full section-4 verification: `docker compose exec backend uv run pytest tests/maintenance/ tests/notifications/ -q` → **1015 passed**, no regressions. `docker compose exec backend uv run pytest tests/maintenance/test_repositories.py -q` → 71 passed (isolated, before the combined run). `uv run pyright` on the touched files shows the same pre-existing `reportArgumentType` noise on `get_active_by_id(tenant_id, Optional[UUID])` calls that `cleaning`'s already-panel-PASSed `_notify_cleaner` produces at the identical call shape (line 2429 there, mirrored here) — not a regression, not fixed, since `cleaning`'s equivalent was accepted as-is. Full-tree `uv run pyright .` baseline is 857 pre-existing errors unrelated to this section (per `sdd/project.md`, static findings are reported separately from test failures and owned by task 6.4).

### Section 5 (maintenance API/router) — notes for section 6

- Confirmed before writing any router code, per this section's own contract: `EXECUTE_INCIDENTS` needs no `require_any` (design D3, `IncidentActor.restrict_to_technician_id`'s docstring literally says "this is also why `EXECUTE_INCIDENTS` can belong to two roles"), and `ROLE_PERMISSIONS` was read directly to confirm `TECHNICIAN = _SELF_SERVICE | _INCIDENT_EXECUTE` and `PROPERTY_MANAGER` holds `_INCIDENT_MANAGE | _INCIDENT_EXECUTE` — both cover `EXECUTE_INCIDENTS` and `READ_INCIDENTS`. `TENANT_OWNER` holds `_INCIDENT_READ` only, giving the same read/write asymmetry `cleaning`'s `TENANT_OWNER` has, which is why `test_the_owner_can_read_but_not_write` mirrors cleanly. `CLEANER` holds no incident permission at all, so it stood in for `cleaning`'s "a technician is refused" case (there, `TECHNICIAN`; here, `CLEANER`).
- `app/maintenance/api/schemas.py` gained the message DTOs at the very end, under a `# --- incident messages (staff-messaging) ---` heading, importing `MAX_INCIDENT_MESSAGE_LENGTH`/`IncidentMessage` from `domain/entities.py` and `IncidentMessagePage` from `domain/repositories.py`, plus `UserRole` from `app.auth.domain.enums` (not previously imported in this file). `IncidentMessagePageResponse.build` takes the domain `IncidentMessagePage` object directly (`page`, `page_number`, `per_page`), the same deviation from `IncidentPageResponse.from_domain`'s `(items, total, page, per_page)` shape that `cleaning`'s `CleaningTaskMessagePageResponse` already established over `CleaningTaskPageResponse` — internal consistency within the messages DTOs, not a house rule.
- `app/maintenance/api/dependencies.py` gained `get_send_incident_message_use_case`/`get_list_incident_messages_use_case` at the end, under a `# --- incident messages (staff-messaging) ---` heading, mirroring `get_upload_incident_photo_use_case`'s non-`_flow_kwargs` shape exactly as section 4's notes predicted.
- `app/maintenance/api/messages_router.py` (new) is its own module, `prefix="/incidents"`, redeclaring its own `_actor`/`ReadDep`/`ExecuteDep` rather than importing `incidents_router.py`'s — same no-router-imports-another-router convention. Its write-gate dependency is named `ExecuteDep` (not `SendMessageDep` as `cleaning`'s router calls it) because it is a plain `require(...)`, not a `require_any(...)` — there is no "or" to name. Mounted in `app/main.py` right after `incidents_router` and before `incident_photos_router`, with `from app.maintenance.api.messages_router import router as incident_messages_router`. No new error handler needed: the use case only ever raises `IncidentNotFoundError`, already mapped by `register_maintenance_error_handlers`.
- `tests/test_route_authorization.py`'s `test_the_protected_endpoints_are_the_ones_expected` snapshot gained exactly one new path, `"/api/v1/incidents/{incident_id}/messages"` (both `POST` and `GET`), and its `maintenance` route count comment was bumped from "sixteen" to "seventeen" (fifteen → sixteen here, plus the owner approval route).
- `tests/maintenance/test_free_text_sink_contract.py` (the **existing**, multi-writer AST census for `incidents.title`/`description`/`assignment_note`/`materials` — a different set of columns from `incident_messages.content`) needed one addition, not a rewrite: `messages_router.py` lives under the gated `maintenance/` prefix and its two route decorators each carry a `description=` OpenAPI-metadata keyword, which the census's broad `ast.Call` keyword matcher picks up regardless of intent (`description` is one of that file's `SINK_COLUMNS`). Added `"maintenance/api/messages_router.py": {"description"}` to the allowlist mapping, the same false-positive shape `photos_router.py`'s existing entry already documents. `content` itself is **not** one of that census's `SINK_COLUMNS` — it is a different column under rule 11's excepción 3, with its own row and its own (new, small) test file, per this section's contract.
- `sdd/steering/security.md` rule 11 recounted against the table (not trusted from the notes' hedge) at **26 columns / 34 rows** before this section's edit — confirmed by parsing the table with a script rather than eyeballing it, matching the notes' predicted baseline exactly, no further drift found this time. After adding `incident_messages.content`'s row: **27 columns / 35 rows** (also machine-recounted). Inside excepción 3's own sub-count, the new row does **not** add a seventh distinct escritor: it is the *same* `staff-messaging` change that already contributed `cleaning_task_messages.content` as the sixth escritor, so the paragraph bumped from "siete columnas —seis escritores—" to "ocho columnas —seis escritores—" (columns +1, escritores unchanged) — the same one-escritor-two-columns shape `cleaner-incident-report` already established for `incidents.title`/`description`.
- `backend/tests/maintenance/test_messages_api.py` (new) covers the full per-role matrix end-to-end over ASGI — 16 tests, all passing on first run — including `test_the_owner_can_read_but_not_write` (`TENANT_OWNER`) and `test_a_cleaner_is_refused_on_both_routes` (`CLEANER`, built inline since `tests/maintenance/conftest.py`'s `world` fixture has no cleaner). Uses `world.other_technician` (already a fixture field) for the "not my incident" 404 cases, so no second-tenant machinery was needed for the row-level-scoping tests. A dedicated real cross-tenant test was **not** added here, per this section's own contract note that R3.2 is "already covered at the use-case/repo layer in section 4 — this section wires the router" (`test_incident_messages_use_case.py`'s `test_an_incident_of_another_tenant_is_invisible_to_this_tenants_actor` and `test_repositories.py`'s dedicated `incident_messages` section already exercise it against fakes and against the real database respectively).
- `backend/tests/maintenance/test_incident_messages_free_text_sink_contract.py` (new — deliberately **not** an extension of the existing `test_free_text_sink_contract.py`, which censuses a different, multi-writer set of columns) pins the same two structural claims `cleaning`'s equivalent file does: `"INCIDENT_MESSAGE" not in AUDITABLE_FIELDS` plus `ChangeSet("INCIDENT_MESSAGE")` raising at construction, and `SendIncidentMessageUseCase.__init__` holding no `timeline` parameter (collaborator set: `incidents`, `messages`, `users`, `configs`, `notifications`, `uow`) — 4 tests, all passing.
- Full section-5 verification: `docker compose exec backend uv run pytest tests/maintenance/test_messages_api.py -q` → 16 passed. `docker compose exec backend uv run pytest tests/maintenance/test_incident_messages_free_text_sink_contract.py -q` → 4 passed. `docker compose exec backend uv run pytest tests/maintenance/ tests/test_route_authorization.py tests/notifications/ -q` → **1055 passed**, no regressions (this run already includes the `test_free_text_sink_contract.py` allowlist fix and the route-authorization snapshot fix, both required before this command went green). `make check-rule11-ownership` (host, no Docker) → passes. `openapi.json` is now further out of date (a third pair of routes since section 3's note), still owned by task 6.5. No `app/cleaning/` file was touched by this section.
