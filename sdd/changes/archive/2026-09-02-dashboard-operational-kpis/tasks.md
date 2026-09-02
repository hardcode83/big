# Tasks: dashboard-operational-kpis

## 1. Cleaning port — count of live tasks for a day <!-- panel: PASS 2026-09-01 -->

- [x] 1.1 Add `count_live_for_day(tenant_id, day) -> int` to `CleaningTaskRepository`
  (`backend/app/cleaning/domain/repositories.py`), documented like the sibling
  `list_live_for_properties`: `LIVE_STATUSES` is not a parameter (design D3). [R1]
- [x] 1.2 Implement it on `SqlAlchemyCleaningTaskRepository`
  (`backend/app/cleaning/infrastructure/repositories.py`): `func.count()` filtered by
  `tenant_id`, `status IN LIVE_STATUSES`, and `scheduled_start` inside the explicit
  `[day, day + 1 day)` range (design risk — never `func.date(scheduled_start)`, which
  defeats an index on the column). [R1.1, R1.2]
- [x] 1.3 Integration tests in `backend/tests/cleaning/test_repositories.py`: a task
  scheduled today in a `LIVE_STATUSES` status is counted; one in `COMPLETED`,
  `CANCELLED`, `REJECTED` or `FAILED` is not; a task with no `CleaningTask` scheduled
  today returns `0`, not `null`; a task scheduled yesterday/tomorrow is excluded; a task
  of another tenant is never counted. [R1.1, R1.2, R1.3]

## 2. Reservations port — count of check-ins in a window <!-- panel: PASS 2026-09-01 -->

- [x] 2.1 Add `count_check_ins_in_range(tenant_id, date_from, date_to) -> int` to
  `ReservationRepository` (`backend/app/reservations/domain/repositories.py`): both
  bounds inclusive, `CANCELLED`/`NO_SHOW` excluded and baked into the method, not a
  parameter (design D3) — a different question from `list_for_properties`'s stay-overlap
  filter, documented as such. [R2]
- [x] 2.2 Implement it on `SqlAlchemyReservationRepository`
  (`backend/app/reservations/infrastructure/repositories.py`): `func.count()` filtered
  by `tenant_id`, `check_in_date BETWEEN date_from AND date_to`,
  `status NOT IN (CANCELLED, NO_SHOW)`. [R2.1, R2.2]
- [x] 2.3 Integration tests in `backend/tests/reservations/test_repositories.py`: a
  check-in today and one exactly 7 days out are both counted (inclusive bounds); one 8
  days out and one yesterday are excluded; a `CANCELLED` and a `NO_SHOW` check-in inside
  the window are excluded; no check-ins in the window returns `0`; a reservation of
  another tenant is never counted. [R2.1, R2.2, R2.3]

## 3. Maintenance port — open-incident counts with urgent breakdown <!-- panel: PASS 2026-09-01 -->

- [x] 3.1 Add `OpenIncidentCounts` frozen dataclass (`total: int`, `urgent: int`) to
  `backend/app/maintenance/domain/value_objects.py`, following the existing
  `IncidentSummary`/`OwnerApprovalSummary` docstring style. [R3]
- [x] 3.2 Add `count_open_for_tenant(tenant_id) -> OpenIncidentCounts` to `IncidentReader`
  (`backend/app/maintenance/domain/repositories.py`): total is `OPEN_INCIDENT_STATUSES`,
  urgent is the subset with `severity IN (HIGH, CRITICAL)`, both from one query (design
  D3). [R3]
- [x] 3.3 Implement it on `SqlAlchemyIncidentReader`
  (`backend/app/maintenance/infrastructure/repositories.py`) with one conditional
  aggregate — `func.count().filter(...)` (compiles to `COUNT(*) FILTER (WHERE ...)`) for
  `urgent` alongside a plain `func.count()` for `total`, both scoped to
  `OPEN_INCIDENT_STATUSES`. [R3.1, R3.2]
- [x] 3.4 Integration tests in `backend/tests/maintenance/test_repositories.py`: an open
  `HIGH`/`CRITICAL` incident counts in both `total` and `urgent`; an open `LOW`/`MEDIUM`
  incident counts only in `total`; a `RESOLVED`/`CANCELLED` incident counts in neither; no
  open incidents returns `(0, 0)`, not `null`; an incident of another tenant is never
  counted. [R3.1, R3.2, R3.3]

## 4. Dashboard domain — the projection <!-- panel: PASS 2026-09-01 -->

- [x] 4.1 Add `OpenIncidentCountsBlock` (`total: int`, `urgent: int`) and `OperationalKpis`
  (`cleanings_today: int | None`, `upcoming_checkins: int | None`,
  `open_incidents: OpenIncidentCountsBlock | None`) as frozen dataclasses to
  `backend/app/dashboard/domain/read_models.py`, with the same field-by-field,
  no-pydantic-no-sqlalchemy discipline as the existing blocks (design D5). [R4.3]
- [x] 4.2 Add both to `ALL_BLOCKS` in `backend/tests/dashboard/test_read_models.py` and
  assert their exact field sets — the structural-absence guarantee the rest of the
  file enforces. [R4.3]

## 5. Dashboard application — the use case <!-- panel: PASS 2026-09-01 -->

- [x] 5.1 Add `UPCOMING_CHECKIN_WINDOW_DAYS = 7` constant to
  `backend/app/dashboard/application/use_cases.py`, distinct from
  `RESERVATION_LOOKAHEAD_DAYS` (design D6). [R2]
- [x] 5.2 Add `GetOperationalKpisUseCase` to the same file: derives `tenant_id` from the
  caller (never a request parameter, R4.1), and for each of the three counts checks
  `is_allowed(role, permission)` before querying — skips the query entirely and sets the
  field to `None` when the role lacks it (design D4), rather than querying and discarding.
  `open_incidents` is gated as one unit on `READ_INCIDENTS` (design D5). [R1, R2, R3, R4.1,
  R4.3]
- [x] 5.3 Unit tests in a new `backend/tests/dashboard/test_operational_kpis.py`, over
  fakes extended in `backend/tests/dashboard/doubles.py`
  (`FakeCleaningRepository.count_live_for_day`,
  `FakeReservationRepository.count_check_ins_in_range`,
  `FakeIncidentReader.count_open_for_tenant`, each recording its calls the way the
  existing fakes do):
  - a role with all three permissions (`TENANT_OWNER`) gets three real, non-null values;
  - `CLEANER` (holds only `READ_CLEANING_TASKS`) gets a real `cleanings_today` and
    `null` for the other two, and the reservations/incidents fakes are never called;
  - `TECHNICIAN` (holds only `READ_INCIDENTS`) gets a real `open_incidents` and `null`
    for the other two, and the cleaning/reservations fakes are never called;
  - `SUPER_ADMIN` (holds none of the three) gets `null` for all three and none of the
    three fakes is called at all (design D4's "costs zero domain queries");
  - a tenant with nothing scheduled/open gets `0`/`0`/`{total: 0, urgent: 0}` for a role
    that may read everything, never `null`;
  - the reservations fake is called with `(today, today + 7 days)` inclusive, proving the
    constant from 5.1 is what is used. [R1.3, R2.3, R3.3, R4.1, R4.3]

## 6. Dashboard API — route, schemas, wiring <!-- panel: PASS 2026-09-01 -->

- [x] 6.1 Add `OpenIncidentCountsResponse` (`total: int`, `urgent: int`) and
  `OperationalKpisResponse` (`cleanings_today: int | None`, `upcoming_checkins: int | None`,
  `open_incidents: OpenIncidentCountsResponse | None`) to
  `backend/app/dashboard/api/schemas.py`, each with an explicit `from_domain` — never
  `from_attributes` (file's existing rule). [R4.3]
- [x] 6.2 Add `get_operational_kpis_use_case` to `backend/app/dashboard/api/dependencies.py`,
  wiring the three adapters already imported/available plus the new repository methods. [R1,
  R2, R3]
- [x] 6.3 Add `GET /api/v1/dashboard/operational-kpis` to
  `backend/app/dashboard/api/router.py`, on the same `ReadDep`
  (`require(Permission.READ_PROPERTIES)`, R4.2) and `TodayDep` as the other two routes,
  with a `description` documenting the per-field redaction the way the existing two routes
  document theirs. [R4.2]
- [x] 6.4 API tests in `backend/tests/dashboard/test_api.py`: the three keys are always
  present (`null` included, never omitted); a happy-path response with seeded data returns
  the right numbers; the door-gate role matrix (`@pytest.mark.parametrize("role",
  list(UserRole))`, `200 if role in READERS else 403`) mirroring the existing two tests at
  `:209` and `:219`. [R4.2, R4.3]
- [x] 6.5 Add `/api/v1/dashboard/operational-kpis` to the protected-endpoints snapshot in
  `backend/tests/test_route_authorization.py` (`test_the_protected_endpoints_are_the_ones_
  expected`, around `:476`), with a comment explaining the per-field redaction the same
  way the neighbouring entries there explain theirs.

## 7. Tenant isolation (R4.4)

- [x] 7.1 In `backend/tests/dashboard/test_isolation.py`, extend `neighbour_world` if
  needed and add one isolation test per count against
  `GET /api/v1/dashboard/operational-kpis`: tenant A's `cleanings_today` does not include
  a live cleaning task scheduled today for tenant B; tenant A's `upcoming_checkins` does
  not include a check-in in the window for tenant B; tenant A's `open_incidents.total`/
  `.urgent` does not include an open/urgent incident of tenant B. [R4.4]

## 8. Contract

- [x] 8.1 Regenerate `backend/openapi.json`: `make openapi`.
- [x] 8.2 Regenerate `frontend/lib/api/generated/openapi.d.ts` following the worktree
  note in `sdd/project.md` (`docker compose cp` the fresh `backend/openapi.json` into the
  `frontend` container, then `npm run api:generate`), and commit both files together.

## 9. Verification

- [x] 9.1 Full backend test suite passes:
  `docker compose exec backend uv run pytest`. 1910 passed, 0 failed (verified during
  `/sdd:review`).
- [x] 9.2 `cd frontend && npm run api:check` reports no drift against the regenerated
  contract. Confirmed: "api: generated types are up to date" (verified during
  `/sdd:review`).
- [x] 9.3 Manual check: as `TENANT_OWNER`, `GET /api/v1/dashboard/operational-kpis`
  returns the three fields with real counts against seeded data; as a role lacking one of
  the three domain permissions (verified at the use-case level in 5.3, since no seeded
  role in this project currently holds `READ_PROPERTIES` without also holding all three),
  confirm via the unit tests that the corresponding field comes back `null`. Confirmed via
  `backend/tests/dashboard/test_api.py`'s operational-kpis happy-path test (real seeded
  data through the FastAPI `TestClient`, full stack including auth) plus the door-gate role
  matrix and `test_operational_kpis.py`'s redaction-by-role unit tests (verified during
  `/sdd:review`).
