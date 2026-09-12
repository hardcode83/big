# Design: pms-ingest-change-events

## Context

`ReservationIngestor` (`backend/app/integrations/application/ingest.py`) is the single writer
behind three routes — PMS sync (`SyncReservationsFromPmsUseCase`, used by the manual CLI, the
`pms-sync-schedule` beat job, and the webhook re-read), CSV import
(`ImportReservationsFromCsvUseCase`), and the demo seed. Its `_ingest_row` either creates a
`Reservation` and calls `_record_imported` (emits `TimelineEventType.RESERVATION_IMPORTED`), or —
for an existing row — calls `existing.update_details(changes, now=now)` and, if it returned a
non-empty diff, saves and counts `updated`. No event is emitted on that second path today.

The manual HTTP path already solves the exact event-selection problem this change needs, twice:
`UpdateReservationUseCase.execute` (`reservations/application/use_cases.py:272-327`) captures
`was_cancelled` before calling `update_details`, and afterwards emits
`TimelineEventType.RESERVATION_CANCELLED` if the reservation is newly `CANCELLED`, or
`RESERVATION_UPDATED` otherwise, with `metadata={"changed": applied}` — `applied` being exactly
`update_details`'s own return value (`{field: {"from", "to"}}`, already JSON-safe;
`OPAQUE_IN_TIMELINE` fields report `{"changed": True}`). `CancelReservationUseCase.execute`
(:342-376) does the same for `DELETE`. Both event types already exist in `TimelineEventType`; no
new vocabulary is needed (settles roadmap-note decision point 1).

The property-side gap sits in `integrations/application/webhooks.py:568-575`
(`ProcessTenantWebhookEventsUseCase._reread`): after landing a batch of re-read notices for a
tenant, it calls `PropertyStateAdvancer.execute(trigger=RESERVATION_CANCELLED_BEFORE_CHECKIN)`
once, unconditionally. `PropertyStateAdvancer` (`integrations/domain/ports.py:204`) is a
`Protocol` sized to exactly this call, built for `ProcessTenantWebhookEventsUseCase` so that
module doesn't import `AdvancePropertyStatesUseCase` directly (design D12 of
`reservations-webhooks`). Neither the periodic sync nor the CSV path calls it at all.
`AdvancePropertyStatesUseCase.execute` (`properties/application/use_cases.py:146-194`) re-queries
`list_by_state(tenant_id, source_states_for(trigger))` at the top of every call, returns early
with **no write and no commit** when there are no candidates (:176-178), and otherwise commits
once at the end (`await self._uow.commit()`, :193-194) — its own transaction, controlled entirely
by which `UnitOfWork` it is constructed with (`SqlAlchemyUnitOfWork` commits for real,
`CallerOwnedUnitOfWork` defers to whoever composes it). This is the seam D2 below depends on.

## Decisions

### D1 — Reuse the existing event-selection rule, not a per-field-class scheme

**Chosen:** `ReservationIngestor` gains a private `_record_updated` mirroring `_record_imported`,
using the *same* rule already proven by `UpdateReservationUseCase`: capture
`was_cancelled = existing.status is ReservationStatus.CANCELLED` before calling
`update_details`, then emit `RESERVATION_CANCELLED` if the result is newly `CANCELLED` else
`RESERVATION_UPDATED`, with `metadata={"changed": applied}` (`applied` is `update_details`'s own
return value — no new diff computation needed). `actor_type`/`actor_user_id`/`source` come from
the same `ingest()` parameters `_record_imported` already uses.

Rejected: one event **per field class** (fechas/estado/importes), the roadmap note's suggestion —
it would need new `TimelineEventType` values, a new classification of `INGEST_OWNED_FIELDS`, and
would diverge from the one rule the manual path already established for the same before/after
transition. Reusing the proven rule keeps all four writers of reservation mutations (`PATCH`,
`DELETE`, and now the three ingest routes) speaking one vocabulary.

### D2 — The property transition call lives once per `ingest()` batch, composed with `CallerOwnedUnitOfWork`

**Chosen:** `ReservationIngestor` takes a new `advance: PropertyStateAdvancer | None = None`
collaborator (same optional-collaborator shape as `provisioner` in
`AdvancePropertyStatesUseCase`). `_ingest_row` returns whether this row just became newly
`CANCELLED`; `ingest()` tracks that across the batch and, if `advance is not None` and at least
one row cancelled, calls `advance.execute(tenant_id=tenant_id,
trigger=PropertyStateTrigger.RESERVATION_CANCELLED_BEFORE_CHECKIN, now=now)` **once**, after the
loop — mirroring the exact "once per batch, not per row" shape the webhook route already uses for
its own notices (D10 of `reservations-webhooks`). `SyncReservationsFromPmsUseCase` and
`ImportReservationsFromCsvUseCase` gain the same optional `advance` parameter and thread it
straight into their internal `ReservationIngestor`. This closes R3.3 for the sync and CSV routes,
which today never call it at all.

**Transaction boundary, corrected after the architecture review:** `AdvancePropertyStatesUseCase`
calls `await self._uow.commit()` itself once it has candidates
(`properties/application/use_cases.py:193-194`). `SyncReservationsFromPmsUseCase.execute()` and
`ImportReservationsFromCsvUseCase.execute()` are each one business transaction with one commit at
the end (D9), and `ReservationIngestor.ingest()` runs *inside* that transaction, per row, before
it. Wiring the *nested* `AdvancePropertyStatesUseCase` — the one built to be passed as
`ReservationIngestor`'s `advance=` — with a real `SqlAlchemyUnitOfWork(session)` would therefore
fire a real mid-loop commit inside the outer use case's still-open transaction: exactly the
composition bug `CallerOwnedUnitOfWork` (`core/unit_of_work.py:59-80`) exists to prevent, first
found in `guest-portal-api`. So every composition root that builds the `AdvancePropertyStatesUseCase`
to be nested inside `ReservationIngestor` (via `SyncReservationsFromPmsUseCase`/
`ImportReservationsFromCsvUseCase`) constructs it against the **same `session`** but with
`uow=CallerOwnedUnitOfWork()` — its `commit()` is a no-op, so the property-transition write lands
in the same session and is committed once, together with everything else, by the outer use case's
own real `uow.commit()`. This is a strictly better atomicity story than "two sequential commits":
the reservation's cancellation and the property's transition now land in one commit, not two.

`ProcessTenantWebhookEventsUseCase._reread`'s own, pre-existing `self._advance.execute(...)` call
is **left in place, unmodified, with its existing real `SqlAlchemyUnitOfWork(session)`** — it is
not nested inside another use case's transaction; it is its own sequential step in
`ProcessTenantWebhookEventsUseCase.execute()`, called *after* `self._sync.execute(...)` (the
re-read) has already returned and committed. By the time it runs, the re-read's own commit — which
now includes the nested `advance` call's write, if the re-read itself detected the cancellation —
is already durable. `AdvancePropertyStatesUseCase.execute()` re-queries
`list_by_state(tenant_id, source_states_for(trigger))` at the top of every call and returns early
with no commit at all when there are no candidates (`properties/application/use_cases.py:176-178`)
— so this second, outer call finds the property already moved out of `AWAITING_CHECKIN`, sees zero
candidates, and returns without writing or committing anything: one `PropertyStateTransition` row
for the cancellation, not two. This satisfies R3.2 ("never two independent callers producing two
rows") through the use case's existing idempotency, not by removing code.

Rejected: retiring `ProcessTenantWebhookEventsUseCase`'s own call and its `advance` constructor
parameter (the roadmap note's other option). It would touch that class's public constructor, the
`PropertyStateAdvancer` port's one caller, and every composition root that builds
`ProcessTenantWebhookEventsUseCase` (`scheduler/tasks.py`), for a purely defensive removal with no
behavioural difference (the extra call is, at most, one indexed query that finds zero candidates)
and a real one (a regression here would delete the webhook route's only safety net for this
trigger, with no idempotent second call to fall back on). Given the redundant call costs one cheap
query and nothing else, keeping it is the lower-risk choice for this change's size.

### D3 — No new `PropertyStateTrigger` for a date change on an already-`AWAITING_CHECKIN` property

**Chosen:** R5 is satisfied by the `RESERVATION_UPDATED` event alone (D1's rule already covers a
`check_in_date`/`check_out_date` change). No new trigger, no change to `transition_enums.py` or
`state_machine.py`. This matches the roadmap note's own MVP recommendation and the proposal's
"Out of scope".

Rejected: adding a "check-in window closed/stale" trigger — real design work (new source/target
states in `state_machine.py`, a new detector in `stalls.py`) for a scenario neither the proposal
nor the roadmap note treats as required for this change.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Ingest core | `backend/app/integrations/application/ingest.py` | `ReservationIngestor.__init__` gains `advance: PropertyStateAdvancer | None = None`. `_ingest_row` captures `was_cancelled` before `update_details`, calls new `_record_updated` when `applied` is non-empty, returns `bool` (newly cancelled). `ingest()` tracks the batch-level flag and makes the single `advance.execute(...)` call after the loop. New `_record_updated` method mirrors `_record_imported`. |
| Sync use case | `backend/app/integrations/application/use_cases.py` (`SyncReservationsFromPmsUseCase`) | `__init__` gains `advance: PropertyStateAdvancer | None = None`, threaded into its internal `ReservationIngestor(...)`. No `uow` handling here — the caller decides the port's transaction boundary at construction time (see composition rows below). |
| CSV use case | `backend/app/integrations/application/use_cases.py` (`ImportReservationsFromCsvUseCase`) | Same: `advance` param threaded into its internal `ReservationIngestor(...)`. |
| Scheduler — periodic sync | `backend/app/scheduler/tasks.py` (`_sync_pms_reservations`, ~line 333) | Construct `AdvancePropertyStatesUseCase(properties=..., reservations=..., transitions=..., timeline=..., configs=..., uow=CallerOwnedUnitOfWork())` — same `session`-backed repos already used for `_advance_property_states` at line ~145, but `uow=CallerOwnedUnitOfWork()` (not `SqlAlchemyUnitOfWork`), because it is nested inside `SyncReservationsFromPmsUseCase`'s own transaction. Pass it as `advance=` to `SyncReservationsFromPmsUseCase(...)`. |
| Scheduler — webhook re-read | `backend/app/scheduler/tasks.py` (`_webhook_tenant_use_case`, ~line 485) | Two separate `AdvancePropertyStatesUseCase` instances, both over the same `session`: (a) the pre-existing one passed to `ProcessTenantWebhookEventsUseCase(advance=...)` — **unchanged**, keeps `uow=SqlAlchemyUnitOfWork(session)`, since it is its own sequential step, not nested inside another use case's commit; (b) a new one passed to the nested `SyncReservationsFromPmsUseCase(advance=...)` — `uow=CallerOwnedUnitOfWork()`, same reasoning as the periodic-sync row. |
| CLI — manual sync | `backend/app/integrations/cli/pms_sync.py` (`sync_with_session`) | Construct `AdvancePropertyStatesUseCase(..., uow=CallerOwnedUnitOfWork())` over the same `session` and pass `advance=` to `SyncReservationsFromPmsUseCase(...)`. |
| API — CSV endpoint | `backend/app/integrations/api/dependencies.py` (`get_import_csv_use_case`) | Construct `AdvancePropertyStatesUseCase(..., uow=CallerOwnedUnitOfWork())` over the same `session` (new imports: `SqlAlchemyPropertyStateTransitionRepository`, `SqlAlchemyTenantConfigRepository`, `AdvancePropertyStatesUseCase`, `CallerOwnedUnitOfWork`) and pass `advance=` to `ImportReservationsFromCsvUseCase(...)`. |
| Demo seed | `backend/app/cli/seed_demo.py` | No change: its `ReservationIngestor(...)` call keeps `advance=None` (default) — seed data does not model a PMS-driven cancellation arriving through re-ingest today. |
| Specs | `sdd/specs/ingest.md`, `sdd/specs/reservations.md`, `sdd/specs/reservations-webhooks.md` | Per proposal's "Affected specs" — done at archive time, not here. |

**Rule of thumb for `/sdd:tasks`/`/sdd:run`, stated once instead of five times above:** an
`AdvancePropertyStatesUseCase` built to be handed to `ReservationIngestor` (directly, or via
`SyncReservationsFromPmsUseCase`/`ImportReservationsFromCsvUseCase`) always gets
`uow=CallerOwnedUnitOfWork()`. An `AdvancePropertyStatesUseCase` built for any other caller (the
three clock jobs at line ~145, and `ProcessTenantWebhookEventsUseCase`'s own pre-existing one)
keeps `uow=SqlAlchemyUnitOfWork(session)`, unchanged.

## Data & interfaces

No schema changes. No new `TimelineEventType` or `PropertyStateTrigger` values (D1, D3). New
optional constructor parameter `advance: PropertyStateAdvancer | None = None` on
`ReservationIngestor`, `SyncReservationsFromPmsUseCase`, `ImportReservationsFromCsvUseCase` —
backward compatible: R1's `TimelineEvent` is unconditional (any caller gets it), while the
*property transition* call is gated on `advance` being supplied. Tests that construct these use
cases directly without `advance` continue to compile; they simply won't see a
`PropertyStateTransition` row for a cancellation, which is already true today for the sync and
CSV paths.

## Risks & mitigations

- **Existing tests asserting "no event on update"** for the sync/CSV paths will now fail by
  design — that is the bug this change fixes. `/sdd:run` updates the relevant fixtures/assertions
  in the same section that changes `ingest.py`.
- **Existing tests for `ProcessTenantWebhookEventsUseCase`** that count `PropertyStateTransition`
  rows or `advance` calls could be sensitive to the *ingestor* now also calling `advance` inside
  the same webhook cycle. If any such test asserts "advance called exactly once" via a mock, it
  needs updating to reflect the (correctness-preserving) second call — this is expected and is
  scoped into the run.
- **Threading a fifth/sixth optional parameter through four composition roots** is mechanical but
  touches files outside `integrations/`: `scheduler/tasks.py` twice. Each site already builds the
  same five repos for its own `AdvancePropertyStatesUseCase` calls (or, for `pms_sync.py`, has the
  session needed to build them), so no new repository implementations are required.
- **Idempotency (R2, R6)**: unchanged from today — gated entirely on `update_details()` returning
  a non-empty `applied` dict, exactly as `report.updated`/`skipped` already are.

## Open questions

None — the roadmap note's two open decision points (event vocabulary, ownership of the property
transition call) are resolved in D1 and D2 above, both by reusing an existing, already-tested
mechanism rather than adding a new one.
