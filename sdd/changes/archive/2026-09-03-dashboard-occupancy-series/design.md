# Design: dashboard-occupancy-series

## Context

`app/dashboard/` composes seven other domains behind three use cases
(`GetDashboardCardsUseCase`, `GetPropertyDashboardUseCase`, `GetOperationalKpisUseCase` in
`app/dashboard/application/use_cases.py`) and owns no `infrastructure/` of its own
(`sdd/specs/dashboard-api.md` D1) — every repository it touches belongs to another domain's
port. This change adds a fourth use case, `GetOccupancySeriesUseCase`, following the same
shape as `GetOperationalKpisUseCase`: no pagination, one tenant-wide answer, permission-gated
fields.

Two ports it needs already exist and are read verbatim:

- `PropertyRepository.list_by_status(tenant_id, PropertyStatus.ACTIVE)`
  (`app/properties/domain/repositories.py:147`) — unpaginated, gives both the count and the
  ids of the tenant's active properties in one statement.
- `ReservationRepository.list_for_properties(tenant_id, property_ids, date_from, date_to)`
  (`app/reservations/domain/repositories.py:72`) — stay-overlap batch read, already used by
  the other two card/detail use cases with `RESERVATION_LOOKAHEAD_DAYS`; this change gives it
  the calendar week instead.

One port is missing: nothing today reads `property_state_transitions` in batch. The only
reader, `PropertyStateTransitionRepository.last_for_property`
(`app/properties/domain/repositories.py:434`), answers "the newest transition of **one**
property" — the single-property shape `GET /properties/{id}/state` needs. R3 asks for the
opposite: every tenant property's history over a date window, in a fixed number of
statements. `TimelineEventReader.last_for_properties`
(`app/timeline/infrastructure/repositories.py:95`) is the closest existing precedent for
"latest row per property, one Postgres `DISTINCT ON` statement" and is followed directly.

`app/pricing/domain/occupancy.py` defines `FREE_STATUSES` — the reservation statuses that do
**not** count as an occupied night — for a different question (30-day-ahead, per-property
occupancy). R2.1 asks for "the same `FREE_STATUSES`", so this design reuses the constant
rather than reimplementing the function it lives next to (which stays untouched, per Out of
scope).

## Decisions

### D1 — New use case beside the existing three, not a variant of one of them

**Chosen:** `GetOccupancySeriesUseCase` in `app/dashboard/application/use_cases.py`, wired
through its own `get_occupancy_series_use_case` dependency and its own route
`GET /api/v1/dashboard/occupancy-series`, sitting next to `/dashboard/operational-kpis` for
the same reason that one is not under `/properties`: it is not in the PRD, so it is free to
name its own prefix (design D7 of `dashboard-api`).

Rejected: folding it into `GetOperationalKpisUseCase` — that use case returns three
independent tenant-wide **counts**, each optional; this returns one **series** of seven
points with its own permission rule (R4.3: redact the whole series, not counted separately
per field), and forcing it into the same response would make `OperationalKpisResponse`
answer two unrelated PRD sections.

### D2 — `PropertyStateTransitionRepository` gains a batch reader, shaped like the other batch ports

**Chosen:** `history_for_properties(tenant_id, property_ids, start, end)` returning
`dict[uuid.UUID, Sequence[PropertyStateTransition]]`, sparse (R3's own composition
convention, `sdd/specs/dashboard-api.md` "Composición por lotes": "los mapas por lotes
**dispersos** ... no mapeada a `None`"). For each property present, the sequence holds — in
chronological order — the one transition immediately before `start` if it exists, followed
by every transition with `created_at` inside `[start, end]` (both converted to UTC instant
bounds, per R2.4). A property that never transitioned, or has none in range and none before
it, is absent.

Two SQL statements, not one and not N:
1. `DISTINCT ON (property_id) ... WHERE created_at < start_instant ORDER BY property_id,
   created_at DESC, id DESC` — the "entering" transition per property, same technique as
   `SqlAlchemyTimelineEventReader.last_for_properties`.
2. A plain range scan, `created_at >= start_instant AND created_at < end_instant_exclusive`,
   ordered ascending.

Both filtered by `tenant_id` and `property_id IN (...)`, so the cost is fixed regardless of
portfolio size (R3.2) — the same ceiling `tests/dashboard/test_no_n_plus_one.py` already
enforces for the cards collection, extended to this reader.

Rejected: a window function (`ROW_NUMBER() OVER (PARTITION BY property_id ORDER BY
created_at DESC)`) collapsed into one UNIONed statement — technically one round trip fewer,
but it requires filtering the partition inside a CTE/subquery either way, and the two-plain-
statements shape matches an existing, reviewed pattern in this exact file family instead of
introducing a second SQL idiom for the same problem.

Rejected: taking no `property_ids` and reading the whole tenant — the codebase's established
rule for every other batch reader this use case touches (`list_for_properties`,
`last_for_properties`, `count_open_for_properties`) is "the caller names the ids it already
resolved"; reading unscoped would silently include inactive properties' history for no
reason and would be the only batch port in `app/dashboard/`'s composition that does not
follow the pattern.

### D3 — "Occupied on day D" resolves as one pure function over three already-batched inputs

**Chosen:** `app/dashboard/domain/occupancy.py`, a new file (mirroring `next_action.py` and
`financials.py`: one small rule, its own module, no I/O), holding:

- `week_bounds(today) -> tuple[date, date]` — Monday/Sunday of `today`'s ISO week
  (`today - timedelta(days=today.weekday())` and `+6`).
- `occupancy_series(week_start, active_property_ids, reservations, transitions_by_property)
  -> tuple[OccupancyPoint, ...]` — the pure computation, unit-testable with hand-built
  fixtures and no database, the same style `_current_or_next_per_property` and
  `occupancy_pct_for` already use in this codebase.

Per property, per day, R2.1's three conditions reduce to two independent checks unioned by
a plain `set` (no double counting is structural — the day's occupied set is a union, not a
sum):

- **Reservation coverage**: `reservation.check_in_date <= day < reservation.check_out_date`
  and `reservation.status not in FREE_STATUSES` (imported from `app.pricing.domain.occupancy`,
  not redeclared — see Context).
- **Blocked/out-of-service coverage**: walk `transitions_by_property[property_id]` — sorted
  defensively by `(created_at, id)` inside the function rather than trusted from the
  adapter — advancing a pointer while `created_at < end_of_day_exclusive(day)`; the state so
  reached is "in effect" for that day. `day` with no transition at or before it (property
  never transitioned) resolves to "neither blocked nor out of service", per R2.3.

**R2.2 is read as the operational definition of R2.1's "estuvo en ... en algún instante de
D", not as a second, competing rule.** R2.1's prose ("en algún instante de D") and R2.2's
mechanism ("el `to_state` de la transición vigente al final de ese día") could be read as two
different algorithms — end-of-day snapshot vs. true any-instant interval overlap — but R2.2
gives the literal, parenthesised "how", immediately after naming what it resolves, so it is
the specification of the "instante" check, not an alternative to it. Consequence made
explicit because it is real: a property that enters `BLOCKED_BY_OWNER` and leaves it again
within the same calendar day counts as occupied only if it is **still** blocked at the
day's last instant (`23:59:59.999... UTC`) — a same-day block-and-release does not surface.
**Confirmed with Jose at the design gate (2026-09-02): end-of-day snapshot is the intended
behaviour**, not any-instant interval overlap — R2.2's literal mechanism stands as written,
and the same-day block-and-release consequence above is accepted knowingly rather than
assumed.

The same function handles days after `today` (the current week can include them) without a
special case: a future day's history is whatever transitions already exist with `created_at`
at or before that day's end, which today is simply "the most recent one so far" — the
current block/unblock state carried forward. No `today` parameter is needed inside
`occupancy_series` at all; `week_bounds` is the only place `today` is used.

Rejected: computing "occupied" per property first and then per day — the day-first,
property-second order above is what lets the transition walk be a single forward pointer
pass per property (transitions arrive pre-ordered by the adapter and are `O(transitions)`,
not `O(7 × transitions)`).

### D4 — `occupancy_pct` is a rounded `Decimal`, serialized as a JSON number, not a string

**Chosen:** `occupied / total * 100`, quantized to one decimal place, carried as `Decimal`
through `OccupancyPoint` (mirroring `occupancy_pct_for`'s return type) and serialized by
`OccupancyPointResponse` as a plain JSON number.

Rejected: a decimal **string**, the convention `sdd/specs/dashboard-api.md` mandates for
`FinancialBlock`/`ApprovalBlock` — that rule exists because a float loses cents
(`120.50` → `120.49999999999999`), which is a money problem. A 0–100 percentage rendered to
one decimal place has no such failure mode in IEEE-754 double precision, and a plain number
is what a charting library on the frontend consumes directly. `ASSUMPTION`: neither the PRD
nor `dto.ts` (no occupancy-series type exists there yet — the `[FE]` half is explicitly out
of scope) fixes the precision; one decimal place is chosen as a reasonable display
granularity and is a one-line change if wrong.

### D5 — Permission redaction is one boundary check, not per-block

**Chosen:** `GetOccupancySeriesUseCase.execute` checks
`is_allowed(role, Permission.READ_RESERVATIONS)` once, before touching any port, and returns
"series absent" (`None`) with **zero** domain queries when it fails — the same short-circuit
`GetOperationalKpisUseCase` already applies per-field (`app/dashboard/application/use_cases.py:406-425`).
`READ_PROPERTIES` still gates the route itself (`require()` in the router, matching the other
three dashboard routes).

This diverges from the block-level redaction of `PropertyDashboardCard`/`PropertyDetail`
(design D10 of `dashboard-api`) on purpose, per R4.3: a role without `READ_RESERVATIONS`
does not get a series built only from blocks/out-of-service days, because "reservations is
the majority source of an occupied night, and a partial series with the same shape is a
different number wearing the same contract" (R4.3's own wording, "una proyección puede
estrechar, nunca unir" from `dashboard-api.md`'s permissions section). There is only one
source-gating permission here (unlike the four the detail aggregate composes), so there is
only one branch, not a per-field one.

Rejected: gating on `READ_PROPERTIES` alone and redacting `occupied_properties` post-hoc —
would still run the reservations query for a role that must never see its result, and would
leave a code path where "compute, then discard" is one omitted `if` away from "compute, then
leak" (the same risk class D10 of `dashboard-api` was written to close).

## Changes by area

| Area | Files | Change |
|---|---|---|
| Properties port | `app/properties/domain/repositories.py` | Add `history_for_properties` to `PropertyStateTransitionRepository` Protocol (D2) |
| Properties adapter | `app/properties/infrastructure/repositories.py` | Implement `history_for_properties` on `SqlAlchemyPropertyStateTransitionRepository` — two statements (D2) |
| Properties tests | `tests/properties/test_repositories.py` | Unit/integration coverage of `history_for_properties`: boundary transition included, window transitions included, absent when none, statement count |
| Dashboard domain | `app/dashboard/domain/occupancy.py` (new) | `week_bounds`, `occupancy_series` — pure functions (D3) |
| Dashboard domain | `app/dashboard/domain/read_models.py` | Add `OccupancyPoint` frozen dataclass (`date`, `occupied_properties`, `total_properties`, `occupancy_pct`) |
| Dashboard application | `app/dashboard/application/use_cases.py` | Add `GetOccupancySeriesUseCase` (D1, D5) |
| Dashboard API | `app/dashboard/api/schemas.py` | Add `OccupancyPointResponse`, `OccupancySeriesResponse` (`data: list[...] | None`) |
| Dashboard API | `app/dashboard/api/router.py` | Add `GET /dashboard/occupancy-series`, `READ_PROPERTIES` gate, reusing `ReadDep`/`TodayDep` |
| Dashboard API | `app/dashboard/api/dependencies.py` | Add `get_occupancy_series_use_case` |
| Dashboard tests | `tests/dashboard/test_occupancy_series.py` (new) | Unit tests of `occupancy_series`/`week_bounds` against hand-built reservations/transitions (no DB) — the three R2.1 conditions, the union/no-double-count case, R1.3's zero-total null, the same-day block-and-release consequence of D3 |
| Dashboard tests | `tests/dashboard/test_use_cases.py` | `GetOccupancySeriesUseCase` against fakes: permission redaction, empty portfolio |
| Dashboard tests | `tests/dashboard/test_api.py` | Route-level: shape, `READ_PROPERTIES` gate via `tests/test_route_authorization.py`'s matrix, `data: null` for a role without `READ_RESERVATIONS` |
| Dashboard tests | `tests/dashboard/test_isolation.py` | R4.4: a neighbour tenant's reservations/blocks/out-of-service properties never move this tenant's series |
| Dashboard tests | `tests/dashboard/test_no_n_plus_one.py` (or a sibling file) | R3.2: fixed statement count across portfolio sizes for `/dashboard/occupancy-series`, same technique as the existing cards test |
| Docs | `sdd/specs/dashboard-api.md` | New "Serie semanal de ocupación" section, `docs/dashboard.md` | Document the new route and the occupied-night union rule, per `steering/documentation.md` |

## Data & interfaces

No schema change, no migration: `property_state_transitions` and `reservations` are read
only, through a new query shape.

**New endpoint**

```
GET /api/v1/dashboard/occupancy-series
Auth: require(Permission.READ_PROPERTIES)

200:
{
  "data": [
    {"date": "2026-09-01", "occupied_properties": 3, "total_properties": 5, "occupancy_pct": 60.0},
    ... 7 entries, Monday to Sunday of the current ISO week, UTC ...
  ] | null   // null when the caller's role lacks READ_RESERVATIONS (R4.3)
}
```

`occupancy_pct` is `null` on every point only when `total_properties` is `0` for the whole
series (R1.3); otherwise a number between `0` and `100`.

**New port method**

```python
class PropertyStateTransitionRepository(Protocol):
    async def history_for_properties(
        self,
        tenant_id: uuid.UUID,
        property_ids: Collection[uuid.UUID],
        start: date,
        end: date,
    ) -> dict[uuid.UUID, Sequence[PropertyStateTransition]]:
        ...
```

**New domain type**

```python
@dataclass(frozen=True)
class OccupancyPoint:
    date: date
    occupied_properties: int
    total_properties: int
    occupancy_pct: Decimal | None
```

## Risks & mitigations

- **Reading `history_for_properties` on a tenant with a long-lived property and years of
  transitions**: bounded by `property_ids IN (...)` and the two date filters, same shape as
  every other batch reader here — no unbounded scan, and the leading index
  (`ix_property_state_transitions_property_id_created_at`) covers the per-property ordering
  both statements need.
- **The same-day block-and-release gap (D3)**: accepted consequence of R2.2's literal
  algorithm, confirmed at the design gate rather than fixed quietly — `test_occupancy_series.py`
  SHALL include a case that pins this behaviour down explicitly, so a future change cannot
  "fix" it without noticing it was a decision.
- **`occupancy_pct` precision (D4)**: a display choice with no requirement behind it
  (`ASSUMPTION`); changing it later is a one-line change to `occupancy_series` and does not
  touch the contract's shape (still a number, still `0`-`100`).
- **Adding a fourth `app/dashboard/` use case widens `dependencies.py` further** — already
  the largest wiring file in the project by design (D1 of `dashboard-api`); one more builder
  function is in character, not a new pattern.

## Open questions

None outstanding. The one real fork (D3 — end-of-day snapshot vs. any-instant overlap for
`BLOCKED_BY_OWNER`/`OUT_OF_SERVICE`) was resolved with Jose at the design gate on
2026-09-02: end-of-day snapshot, as R2.2 literally specifies.
