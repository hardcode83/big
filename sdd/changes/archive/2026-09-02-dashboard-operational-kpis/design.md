# Design: dashboard-operational-kpis

## Context

`app/dashboard/` already serves two aggregates with **no `infrastructure/` of its own**
(`sdd/specs/dashboard-api.md` D1): `GetDashboardCardsUseCase` and
`GetPropertyDashboardUseCase` (`app/dashboard/application/use_cases.py`) compose ports owned
by `properties`, `reservations`, `guests`, `cleaning`, `maintenance`, `statements` and
`timeline`, and the two routes live in `app/dashboard/api/router.py`, gated by
`require(Permission.READ_PROPERTIES)` and registered on the router `app/main.py:181` already
includes under `API_V1_PREFIX`.

The three counts this change needs already have readers, but none at the shape this needs:

- `CleaningTaskRepository.list_live_for_properties` (`app/cleaning/domain/repositories.py`)
  takes a batch of `property_id`s and returns summaries, because its caller — the property
  card — needs one status per property.
- `ReservationRepository.list_for_properties` (`app/reservations/domain/repositories.py`)
  is the same shape, and its filter is **stay overlap**, not "check-in falls in this
  window" — a different question than R2 asks.
- `IncidentReader.count_open_for_properties` (`app/maintenance/domain/repositories.py`)
  already counts open incidents, but per property and without a severity breakdown.

None of the three can answer "how many, for the whole tenant" without either enumerating
every property first (a query this endpoint has no other reason to make) or summing a
per-property map in Python. Both are extra work for a number the database can already give
directly with `WHERE tenant_id = :t`.

## Decisions

### D1 — New endpoint lives inside the existing `app/dashboard/` module, not a new one

**Chosen:** `GET /api/v1/dashboard/operational-kpis`, served by the same router
(`app/dashboard/api/router.py`), a new `GetOperationalKpisUseCase` in the same
`application/use_cases.py`, a new frozen projection in the same `domain/read_models.py`, and
a new response model in the same `api/schemas.py`. No `infrastructure/` is added — the use
case composes ports of `cleaning`, `reservations` and `maintenance`, exactly like the two
existing use cases compose ports of seven domains between them.

This is the same call `sdd/specs/dashboard-api.md` D1 already made, for the same reason: the
proposal frames these three counts as "lecturas nuevas sobre dominios ya entregados", not a
new capability, and a dashboard-owned adapter here would again be "el segundo sitio donde se
aplica el scope de tenant".

Rejected: a new `app/operational_kpis/` module — would duplicate the
composition-without-infrastructure pattern this module already exists to hold, for three
numbers.

### D2 — Each count is tenant-wide, not a per-property batch

**Chosen:** the three new repository methods filter by `tenant_id` alone and return a single
scalar (or small struct), with no `property_id` in their signature at all — unlike
`list_live_for_properties` / `count_open_for_properties`, which batch by property because
their callers need a per-property breakdown. This endpoint never breaks a count down by
property, so there is nothing to batch: one query per domain, and the query cost does not
depend on portfolio size (no property-id enumeration query either — the existing endpoints
pay one to get their `property_ids` in hand; this one has no reason to).

Rejected: reuse `count_open_for_properties` after first listing every property id of the
tenant — costs an extra query, still returns per-property (this endpoint would sum it in
Python), and cannot give the urgent/total breakdown R3.2 asks for.

### D3 — Three new port methods, one per source domain, additive only

**Chosen:**

- `CleaningTaskRepository.count_live_for_day(tenant_id, day) -> int`
  (`app/cleaning/domain/repositories.py` / `SqlAlchemyCleaningTaskRepository`). Counts tasks
  whose `status` is in `LIVE_STATUSES` and whose `scheduled_start` falls on `day` (R1.1-R1.2).
  `LIVE_STATUSES` is not a parameter — same rule the existing method's docstring already
  states: "which statuses count as live is the domain's decision, and letting a caller
  choose would put a second copy of it in the caller."
- `ReservationRepository.count_check_ins_in_range(tenant_id, date_from, date_to) -> int`
  (`app/reservations/domain/repositories.py` / `SqlAlchemyReservationRepository`). Counts
  reservations whose `check_in_date` falls in `[date_from, date_to]` (both inclusive, R2.1)
  and whose `status` is **not** `CANCELLED` or `NO_SHOW` (R2.2, baked into the method rather
  than a parameter — same reasoning as `LIVE_STATUSES` above).
- `IncidentReader.count_open_for_tenant(tenant_id) -> OpenIncidentCounts`
  (`app/maintenance/domain/repositories.py` / `SqlAlchemyIncidentReader`), where
  `OpenIncidentCounts` is a new `@dataclass(frozen=True)` in
  `app/maintenance/domain/value_objects.py` with `total: int` and `urgent: int`. Counts
  incidents whose `status` is in `OPEN_INCIDENT_STATUSES` (R3.1) and, of those, how many have
  `severity` in `{HIGH, CRITICAL}` (R3.2) — both in the same query with a conditional
  aggregate (`func.count().filter(...)`, which Postgres compiles to `COUNT(*) FILTER (WHERE
  ...)`), so the breakdown costs nothing extra over the plain count.

All three are **new methods on existing Protocols** — no existing method's signature
changes, so no existing caller or adapter is touched.

Rejected: a single new port spanning all three domains — would be the "repositorio Dios"
`steering/backend-architecture.md` forbids, and would make one domain's adapter responsible
for another domain's table.

### D4 — Redaction: gate the query, not just the field

**Chosen:** each count is guarded by `is_allowed(role, permission)` — `READ_CLEANING_TASKS`
for cleanings, `READ_RESERVATIONS` for check-ins, `READ_INCIDENTS` for incidents (R4.3) —
mirroring the per-block gating `GetDashboardCardsUseCase` already does for
`current_or_next_reservation` and `cleaning_status`. The query for a count is **skipped
entirely** when the role lacks its permission, not run and then discarded: a role holding
none of the three costs zero domain queries, and the field comes back `null`
(`sdd/specs/dashboard-api.md` "el `null` de 'no puedes verlo' es deliberadamente
indistinguible del `null` de 'no hay ninguno'", R4.3).

Rejected: always querying and nulling only at the response layer — correct in output, wastes
a query a role with narrow permissions will never need, and duplicates the
permission-then-fetch order the existing use cases already establish.

### D5 — Response shape: one nested block for incidents, resolved with the user

**Chosen:** `open_incidents` is a single nested object (`{total, urgent}`), redacted as one
unit — `null` entirely when `READ_INCIDENTS` is absent, never one field present and the other
`null`. This matches the existing convention for a permission that protects more than one
number at once (`financial`, `access` in `PropertyDetail`): one permission, one block, one
redaction decision. `cleanings_today` and `upcoming_checkins` stay flat top-level fields
because each is already a single number gated by its own single permission — nesting them
would add a level with nothing to group.

Route: `GET /api/v1/dashboard/operational-kpis`, alongside `/dashboard/properties` under the
same `/dashboard` prefix, gated by the same `require(Permission.READ_PROPERTIES)` (R4.2) the
other two dashboard routes use (`ReadDep` in `router.py`).

### D6 — "Today" and the check-in window reuse the existing dependency, with their own constant

**Chosen:** `today` keeps coming from the existing `TodayDep` (`router.py`'s `_today()`,
UTC-based) rather than a second way to compute it. The 7-day check-in window (R2, an
`ASSUMPTION` the proposal already records) is its own constant,
`UPCOMING_CHECKIN_WINDOW_DAYS = 7`, distinct from `RESERVATION_LOOKAHEAD_DAYS = 90` already in
`use_cases.py` — the two answer different questions (that one bounds "the one stay to show on
a card", this one is the literal count window R2.1 asks for) and conflating them would make a
future change to either silently change the other.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Cleaning port | `app/cleaning/domain/repositories.py`, `app/cleaning/infrastructure/repositories.py` | New `count_live_for_day(tenant_id, day) -> int` on `CleaningTaskRepository` / `SqlAlchemyCleaningTaskRepository`. |
| Reservations port | `app/reservations/domain/repositories.py`, `app/reservations/infrastructure/repositories.py` | New `count_check_ins_in_range(tenant_id, date_from, date_to) -> int` on `ReservationRepository` / `SqlAlchemyReservationRepository`. |
| Maintenance port | `app/maintenance/domain/repositories.py`, `app/maintenance/domain/value_objects.py`, `app/maintenance/infrastructure/repositories.py` | New `OpenIncidentCounts` frozen dataclass; new `count_open_for_tenant(tenant_id) -> OpenIncidentCounts` on `IncidentReader` / `SqlAlchemyIncidentReader`. |
| Dashboard domain | `app/dashboard/domain/read_models.py` | New frozen `OperationalKpis` (`cleanings_today`, `upcoming_checkins`, `open_incidents: OpenIncidentCountsBlock \| None`) and `OpenIncidentCountsBlock` (`total`, `urgent`). |
| Dashboard application | `app/dashboard/application/use_cases.py` | New `GetOperationalKpisUseCase`; new `UPCOMING_CHECKIN_WINDOW_DAYS = 7` constant. |
| Dashboard API | `app/dashboard/api/router.py`, `api/schemas.py`, `api/dependencies.py` | New route, `OperationalKpisResponse` (+ nested `OpenIncidentCountsResponse`), `get_operational_kpis_use_case` wiring. |
| Contract | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | Regenerated (`docker compose exec ... npm run api:generate`, per project's worktree note) — no FE consumption in this change, only the contract. |
| Tests | `tests/dashboard/doubles.py`, `tests/dashboard/test_use_cases.py` (or a new `tests/dashboard/test_operational_kpis.py`), `tests/dashboard/test_api.py`, `tests/dashboard/test_isolation.py`, `tests/dashboard/test_read_models.py` | Fakes for the three new port methods; permission-redaction matrix (R4.3); one tenant-isolation test per count (R4.4); a fixed-query-count assertion per domain (mirrors `test_no_n_plus_one.py`'s method, applied to "0 or 1 query" rather than "N properties"). |

## Data & interfaces

New route, no request body, no query parameters (tenant comes from `RequestContext`, R4.1):

```
GET /api/v1/dashboard/operational-kpis
```

```json
{
  "cleanings_today": 3,
  "upcoming_checkins": 12,
  "open_incidents": { "total": 5, "urgent": 2 }
}
```

- All three top-level keys are always present, `null` included (matching the rest of
  `dashboard-api`'s contract convention).
- `cleanings_today` / `upcoming_checkins`: `int` when the caller may read the source domain
  and there is nothing to count → `0`; `null` when the caller may not read it (R1.3, R2.3,
  R4.3).
- `open_incidents`: `{ "total": int, "urgent": int }` when the caller may read incidents
  (`0`/`0` when there are none, R3.3); `null` — the whole object, not one of its two numbers
  — when the caller may not (R4.3, D5).

No schema/table change: three read-only queries against `cleaning_tasks`, `reservations`,
`incidents`.

## Risks & mitigations

- **`scheduled_start` is a `datetime`, "today" is a `date`.** Comparing with a wrapped
  column (`func.date(scheduled_start) = day`) would work but stops the query from using any
  index on `scheduled_start` as-is. The adapter compares against an explicit
  `[day, day + 1 day)` range instead, matching how the rest of the codebase avoids
  function-wrapped predicates on a filtered column.
- **Additive Protocol methods still touch every place a fake implements the port.**
  `tests/dashboard/doubles.py`'s existing fakes for `CleaningTaskRepository`,
  `ReservationRepository` and `IncidentReader` gain the three new methods; because Python
  duck-types rather than enforcing `Protocol` membership at runtime, the existing use cases'
  tests are unaffected — only the new use case's tests call the new methods.
  `SqlAlchemyLiveCleaningTaskReader` / `SqlAlchemyLiveCleaningTaskQuery` and other narrower
  cleaning/incident ports are untouched — the new methods land only on the three Protocols
  named in D3.
- **A fourth permission-redacted response gated by three independent permissions is one
  more combination for `tests/test_route_authorization.py`-style matrices to miss.** Mitigated
  by the per-count isolation/redaction tests named in Changes by area, one per count rather
  than one for the endpoint as a whole.
- No migration, no backward-compatibility concern: purely additive route and read paths.

## Open questions

None outstanding — route path and the incident-counts response shape were resolved with the
user during this design (D1, D5).
