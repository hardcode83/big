# Tasks: pms-ingest-change-events

## 1. Ingest core emits timeline evidence on update <!-- panel: PASS 2026-09-12 receipt:3b0c3539 -->

- [x] 1.1 `ReservationIngestor.__init__` (`backend/app/integrations/application/ingest.py`) gains
      `advance: PropertyStateAdvancer | None = None` (import `PropertyStateAdvancer` from
      `app.integrations.domain.ports`), stored as `self._advance`. [R3]
- [x] 1.2 `_ingest_row`: capture `was_cancelled = existing.status is ReservationStatus.CANCELLED`
      immediately before `existing.update_details(changes, now=now)`. When `applied` (the dict
      `update_details` returns) is non-empty, call a new `_record_updated` method instead of
      falling straight through to `report.updated += 1`; when empty, behavior is unchanged
      (`report.skipped += 1`, no event). `_ingest_row` returns `bool` — whether this row's status
      became `CANCELLED` and was not before. [R1, R2, R6]
- [x] 1.3 New `_record_updated` method on `ReservationIngestor`, mirroring `_record_imported`:
      builds a `TimelineEventFactory.create(TimelineEventData(...))` with
      `event_type=TimelineEventType.RESERVATION_CANCELLED` if the update left the reservation
      newly `CANCELLED`, else `TimelineEventType.RESERVATION_UPDATED`; `title="Reservation
      cancelled"` / `"Reservation updated"` to match the wording `reservations/application/
      use_cases.py:294-325` already uses; `metadata={"changed": applied}`;
      `actor_type`/`actor_user_id` from `ingest()`'s own parameters (same as
      `_record_imported`). [R1]
- [x] 1.4 `ingest()`: track whether any row in the batch newly cancelled (from 1.2's return
      value). After the row loop, `if self._advance is not None and <any newly cancelled>:
      await self._advance.execute(tenant_id=tenant_id,
      trigger=PropertyStateTrigger.RESERVATION_CANCELLED_BEFORE_CHECKIN, now=now)` — once per
      batch, not per row. [R3.1]
- [x] 1.5 Unit tests (new module `backend/tests/integrations/test_ingest_updates.py`, constructing
      `ReservationIngestor` directly against `db_session` the way `test_sync.py`'s `_use_case`
      helper does): an update that changes `check_in_date` emits exactly one
      `RESERVATION_UPDATED` event with `metadata["changed"]` naming the field; an update that
      changes `status` to `CANCELLED` emits exactly one `RESERVATION_CANCELLED` event and no
      `RESERVATION_UPDATED`; a row whose `update_details` returns `{}` (no real change) emits no
      event and stays counted `skipped`; `created`/`updated`/`skipped` counts match today's
      behavior exactly (R6) regardless of whether an event fired. [R1, R2, R6]

## 2. Thread `advance` through the Sync and CSV use cases <!-- panel: PASS 2026-09-12 receipt:e8b40f2a -->

- [x] 2.1 `SyncReservationsFromPmsUseCase.__init__` (`backend/app/integrations/application/
      use_cases.py`) gains `advance: PropertyStateAdvancer | None = None`, passed straight into
      its internal `ReservationIngestor(...)`. [R3.3]
- [x] 2.2 `ImportReservationsFromCsvUseCase.__init__` (same file) gains the identical
      `advance: PropertyStateAdvancer | None = None`, passed into its internal
      `ReservationIngestor(...)`. [R3.3, R4]
- [x] 2.3 Confirm every existing construction of `SyncReservationsFromPmsUseCase` and
      `ImportReservationsFromCsvUseCase` in `backend/tests/` still passes with the new parameter
      defaulting to `None` (no behavior change for a caller that doesn't supply it) — fix any
      test helper whose constructor call uses positional args that this shifts.

## 3. Wire the property-transition trigger at every composition root <!-- hard --> <!-- panel: PASS 2026-09-12 receipt:76a24d42 -->

- [x] 3.1 `backend/app/scheduler/tasks.py`, `_sync_pms_reservations` (~line 333, the periodic
      `pms-sync-schedule` job): construct `AdvancePropertyStatesUseCase(properties=..., reservations=...,
      transitions=..., timeline=..., configs=..., uow=CallerOwnedUnitOfWork())` over the same
      `session`, and pass it as `advance=` to the `SyncReservationsFromPmsUseCase(...)` built
      there. Import `CallerOwnedUnitOfWork` from `app.core.unit_of_work`. [R3.3]
- [x] 3.2 `backend/app/scheduler/tasks.py`, `_webhook_tenant_use_case` (~line 485): build a
      **second** `AdvancePropertyStatesUseCase(..., uow=CallerOwnedUnitOfWork())` over the same
      `session` and pass it as `advance=` to the nested `SyncReservationsFromPmsUseCase(...)`.
      Leave the existing `AdvancePropertyStatesUseCase(..., uow=SqlAlchemyUnitOfWork(session))`
      passed to `ProcessTenantWebhookEventsUseCase(advance=...)` exactly as it is today — do not
      touch that wiring. [R3.1, R3.2]
- [x] 3.3 `backend/app/integrations/cli/pms_sync.py`, `sync_with_session`: same wiring as 3.1 —
      construct `AdvancePropertyStatesUseCase(..., uow=CallerOwnedUnitOfWork())` over the
      function's `session` and pass `advance=` to `SyncReservationsFromPmsUseCase(...)`. [R3.3]
- [x] 3.4 `backend/app/integrations/api/dependencies.py`, `get_import_csv_use_case`: add imports
      for `SqlAlchemyPropertyStateTransitionRepository`, `SqlAlchemyTenantConfigRepository`,
      `AdvancePropertyStatesUseCase` (from `app.properties.application.use_cases`) and
      `CallerOwnedUnitOfWork` (from `app.core.unit_of_work`); construct
      `AdvancePropertyStatesUseCase(..., uow=CallerOwnedUnitOfWork())` over the endpoint's
      `session` and pass `advance=` to `ImportReservationsFromCsvUseCase(...)`. [R3.3, R4]
- [x] 3.5 Tests proving the sync and CSV routes now trigger the transition end-to-end (extend
      `backend/tests/integrations/test_sync.py`, `backend/tests/integrations/test_import_csv.py`,
      and `backend/tests/scheduler/test_sync_pms_reservations.py`): seed a property in
      `AWAITING_CHECKIN` for a reservation, ingest a row that cancels that same reservation via
      each route, and assert the property lands in `VACANT_READY` with one
      `PropertyStateTransition` row — the same shape `backend/tests/integrations/
      test_webhook_causality.py` already proves for the webhook route. [R3.1, R3.3]
- [x] 3.6 Regression test for R3.2: construct the webhook composition exactly as
      `_webhook_tenant_use_case` now does (nested `SyncReservationsFromPmsUseCase` with its own
      `advance`, plus `ProcessTenantWebhookEventsUseCase`'s outer `advance`) against one session,
      run a cancellation through it, and assert exactly **one** `PropertyStateTransition` row for
      that reservation — not two. [R3.2]

## 4. CSV/date-change coverage and regression sweep

- [ ] 4.1 `backend/tests/integrations/test_sync.py`, `test_import_csv.py`,
      `test_beds24_end_to_end.py`, `test_channex_end_to_end.py`,
      `backend/tests/integrations/test_webhook_processing.py`: re-run and inspect every existing
      assertion that counts or enumerates `TimelineEvent`s after an *update* to an existing
      reservation (not just creation). Update any assertion that now legitimately sees an extra
      `RESERVATION_UPDATED`/`RESERVATION_CANCELLED` event, without weakening what it was actually
      checking (creation-only assertions like `test_the_imported_events_are_system_events` need
      no change — they run before any update happens). [R1, R2]
- [ ] 4.2 New test for R4: a CSV re-import that changes `check_in_date`/`status` on a row
      matching an existing `external_pms_id` emits the same `RESERVATION_UPDATED`/
      `RESERVATION_CANCELLED` event as the sync path, with `actor_type=USER` — the same actor the
      CSV creation path already asserts for `RESERVATION_IMPORTED`. [R4]
- [ ] 4.3 New test for R5: a sync/webhook update that changes `check_in_date` or
      `check_out_date` on a reservation whose property is `AWAITING_CHECKIN` for that same stay
      emits `RESERVATION_UPDATED` and does **not** raise, does **not** need a new
      `PropertyStateTrigger`, and does not touch `current_operational_state`. [R5]
- [ ] 4.4 Full backend suite passes: `docker compose exec backend uv run pytest` (stack already
      up in this worktree via `make up`).
- [ ] 4.5 Static typing passes: `docker compose exec backend uv run pyright .` — run from
      `backend` per `sdd/project.md`'s documented invocation (`uv sync --frozen` first if not
      already run in this worktree).
- [ ] 4.6 Manual smoke of the roadmap note's verification script: `make pms-sync
      TENANT=<demo tenant id>` after moving `SEED-AIRBNB-1`'s check-out date in the mock adapter
      fixture, confirm `updated: 1` and a new event on `/timeline`; then cancel `SEED-BOOKING-1`
      the same way and confirm the reservation is `CANCELLED`, carries its event, and REDES11
      leaves `AWAITING_CHECKIN` if it was sitting there. <!-- manual -->

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->

- Section 1: `_ingest_row` now returns `bool` (whether this row newly cancelled a reservation); its only call site is `ingest()`'s row loop, which now does `any_newly_cancelled = any_newly_cancelled or newly_cancelled` per row and calls `self._advance.execute(...)` once after the loop — no other call sites existed.
- Section 1: `_record_updated(self, *, tenant_id, reservation, newly_cancelled: bool, applied: dict[str, object], now, actor_type, actor_user_id) -> None` — no `source` param (unlike `_record_imported`), since its title is a fixed string, not "from {source}".
- Section 1: `ReservationIngestor.__init__`'s new `advance` param is keyword-only with a default, so the three existing construction sites (`use_cases.py:108`, `use_cases.py:650`, `cli/seed_demo.py:1900`, `tests/properties/test_inactive_property_guard.py:181`) needed no changes — confirmed by running their tests.
- Section 1: no existing assertion in `test_sync.py`/`test_import_csv.py` asserted "no event on update" — both still pass unchanged, nothing for section 4 to reconcile there.
- Section 2: `PropertyStateAdvancer` was NOT yet imported in `use_cases.py`; added it to the existing `from app.integrations.domain.ports import (...)` block alongside `PMSAdapterFactory` and `ReservationCsvParser`.
- Section 2: both `SyncReservationsFromPmsUseCase.__init__` and `ImportReservationsFromCsvUseCase.__init__` gained `advance: PropertyStateAdvancer | None = None` as the LAST keyword-only param (after `email_exclusion`/`max_rows`+`email_exclusion` respectively), forwarded verbatim as `advance=advance` into their internal `ReservationIngestor(...)` call. Section 3 can pass `advance=` by keyword at either composition root with no other signature changes.
- Section 2: no test in `backend/tests/` constructs `ImportReservationsFromCsvUseCase(...)` directly (grep found zero hits) — nothing there could break. All `SyncReservationsFromPmsUseCase(...)` construction sites already use keyword args exclusively (the class is `*`-only), so the new trailing default param was a no-op for them; confirmed by running `tests/integrations` (976 passed, same as section 1's baseline, 0 failures).
- Section 3: exact import paths the wiring needed — `SqlAlchemyPropertyStateTransitionRepository` lives in `app.properties.infrastructure.repositories` (beside `SqlAlchemyPropertyRepository`), and `SqlAlchemyTenantConfigRepository` in `app.tenants.infrastructure.repositories` (NOT under `properties/`). `AdvancePropertyStatesUseCase` from `app.properties.application.use_cases`, `CallerOwnedUnitOfWork` from `app.core.unit_of_work`.
- Section 3: `scheduler/tasks.py` got one shared private helper, `_nested_advance(session)` (right after the existing `_advance`), used by BOTH 3.1 and 3.2 — same five repos as `_advance`, `uow=CallerOwnedUnitOfWork()`, no provisioner. The CLI and the API dependency construct theirs inline (different modules, one call site each).
- Section 3: `_webhook_tenant_use_case` now holds two `AdvancePropertyStatesUseCase` instances; the pre-existing one (`ProcessTenantWebhookEventsUseCase(advance=...)`, real `SqlAlchemyUnitOfWork`) is untouched, the new one is `advance=_nested_advance(session)` on the nested `SyncReservationsFromPmsUseCase`.
- Section 3: `app/integrations/api/dependencies.py` importing `app.properties.application.use_cases` is allowed — `tests/test_layering.py` (1521 checks) passes unchanged.
- Section 3: the ingestor only fires `advance` on an UPDATE that newly cancels; a row that is CANCELLED on CREATION never sets the flag. Every new test therefore runs two passes (CONFIRMED, then CANCELLED) — section 4 should assume the same shape for R5's date-change tests.
- Section 3: `test_webhook_causality.py`'s `_use_case` helper was updated to mirror `_webhook_tenant_use_case` (nested advancer included), so its five pre-existing tests now exercise the real composition; none of them changed behaviour, because they all take the creation path.
- Section 3: the R3.2 test wraps BOTH advancers in a `_CountingAdvancer` spy and asserts `nested.calls == 1 and outer.calls == 1` before asserting one `PropertyStateTransition` row — without that premise "exactly one row" would also pass on a cycle where only one advancer ran.
- Section 3: extra guard beyond the task list — `test_the_nested_advancer_does_not_commit_inside_the_syncs_transaction` (`tests/integrations/test_sync.py`) counts `session.commit()` calls during a cancelling sync and pins it at ONE. Verified it reports 2 if the nested advancer is given `SqlAlchemyUnitOfWork`, so D2's boundary is now machine-checked, not only wired.
- Section 3: `tests/scheduler/test_sync_pms_reservations.py` drives its cancellation by monkeypatching `app.scheduler.tasks.SqlAlchemyPMSAdapterFactory` only — everything below it (repos, both uows, `_nested_advance`) stays real. `MockPMSAdapter`'s own seed rows cannot be used: neither stay falls inside `candidate_window` AND before check-in at once.
- Section 3: task 3.5 named three test files and none of them covers `cli/pms_sync.py`, so 3.3's wiring is verified by reading plus `tests/integrations/test_pms_sync_cli.py` still passing — the CLI and the beat job compose the identical `SyncReservationsFromPmsUseCase(advance=...)`, which `tests/scheduler/test_sync_pms_reservations.py` does cover end to end. Section 4 may want one CLI-level cancellation test if it wants the route asserted rather than inferred.
- Section 3 (review follow-up, sdd-qa finding on `pms_sync.py:159`): the gap above was real — no test asserted the manual CLI actually triggers `RESERVATION_CANCELLED_BEFORE_CHECKIN`. Closed by adding `test_a_cancellation_the_manual_sync_discovers_frees_the_property` to `backend/tests/integrations/test_pms_sync_cli.py`, same shape as the scheduler's cancellation test: monkeypatches only `pms_sync.SqlAlchemyPMSAdapterFactory`, drives `sync_with_session` twice (CONFIRMED then CANCELLED), asserts the property lands `VACANT_READY` with exactly one `PropertyStateTransition` row. `backend/tests/integrations/test_pms_sync_cli.py` is now implicitly one of task 3.5's satisfied files alongside the three it named. No production code changed — `sync_with_session`'s `advance=` wiring (line 159) was already correct.
