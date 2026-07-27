# Tasks: timeline-state-machine

Scope guard: implementation is limited to the new pure-domain Python modules and
unit-test files approved in `design.md`. Do not modify existing entities, persisted
enums, infrastructure, application/API layers, live specs, Proposal, or Design.

## 1. Domain contracts and errors

Section dependency: none.

- [ ] 1.1 TDD: first add failing assertions for all 16
  `PropertyStateTrigger` members and rejection of free-form trigger strings, then
  implement the non-persisted enum — files:
  `backend/tests/properties/test_state_machine.py`,
  `backend/app/properties/domain/transition_enums.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_machine.py -q`
  [R1, R2, R3]
- [ ] 1.2 TDD: first add failing construction/frozen-value tests for
  `PropertyTransitionContext`, `TransitionActor`, `TransitionEvidenceIds`,
  `PropertyStateChangeRequest`, and `PropertyStateChangeResult`, then implement the
  exact fields and optionality approved in Design D2/D7 — depends on: 1.1 — files:
  `backend/tests/properties/test_state_machine.py`,
  `backend/tests/properties/test_transition_result.py`,
  `backend/app/properties/domain/value_objects.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_machine.py tests/properties/test_transition_result.py -q`
  [R2, R5, R6, R7]
- [ ] 1.3 TDD: first add failing validation tests for aware
  `reference_instant`, distinct evidence UUIDs, non-empty optional
  `correlation_id`, `USER` actor/user-id consistency, and forbidden user IDs for
  non-user actors; then implement the minimal value-object validation — depends on:
  1.2 — files: `backend/tests/properties/test_state_machine.py`,
  `backend/tests/properties/test_transition_result.py`,
  `backend/app/properties/domain/value_objects.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_machine.py tests/properties/test_transition_result.py -q`
  [R2, R5, R6, R7]
- [ ] 1.4 TDD: first add failing tests for the structured exception families
  (`InvalidStateTransitionError`, `NoOperationalStateChangeError`,
  `InvalidTransitionInputError`, `TransitionScopeMismatchError`,
  `IncompatibleTransitionContextError`, `TimelineEventValidationError`,
  `TransitionEvidenceError`), then implement English technical messages and the
  approved diagnostic fields without HTTP/ORM concepts — depends on: 1.3 — files:
  `backend/tests/properties/test_state_machine.py`,
  `backend/tests/properties/test_state_resolution.py`,
  `backend/tests/timeline/test_event_factory.py`,
  `backend/app/properties/domain/exceptions.py`,
  `backend/app/timeline/domain/exceptions.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_machine.py tests/properties/test_state_resolution.py tests/timeline/test_event_factory.py -q`
  [R2, R4, R6, R7]

## 2. Timeline domain factory

Section dependency: section 1.

- [ ] 2.1 TDD: first add failing tests for immutable `TimelineEventData` and
  generic `TimelineEventFactory.create` construction with the existing
  `TimelineEvent`, `TimelineActorType`, `TimelineEventType`, and
  `TimelineSeverity`; then implement the minimal pure-domain contracts — depends
  on: 1.4 — files: `backend/tests/timeline/test_event_factory.py`,
  `backend/app/timeline/domain/value_objects.py`,
  `backend/app/timeline/domain/services.py` — verify:
  `docker compose exec backend uv run pytest tests/timeline/test_event_factory.py -q`
  [R6, R7]
- [ ] 2.2 TDD: first add failing tests for
  `TimelineEventFactory.property_state_changed`, including
  `PROPERTY_STATE_CHANGED`, `INFO`, shared identifiers/actor/instant/reason, and
  metadata keys `from_state`, `to_state`, `trigger`, optional
  `source_entity_id`, and optional `correlation_id`; then implement the specialized
  factory path — depends on: 2.1 — files:
  `backend/tests/timeline/test_event_factory.py`,
  `backend/app/timeline/domain/services.py`,
  `backend/app/timeline/domain/value_objects.py` — verify:
  `docker compose exec backend uv run pytest tests/timeline/test_event_factory.py -q`
  [R6, R7]
- [ ] 2.3 TDD: first add failing tests for timezone-aware timestamps, required
  common fields, defensive metadata copying, and no mutation of caller-owned
  metadata; then implement validation through `TimelineEventValidationError` —
  depends on: 2.2 — files: `backend/tests/timeline/test_event_factory.py`,
  `backend/app/timeline/domain/services.py`,
  `backend/app/timeline/domain/exceptions.py` — verify:
  `docker compose exec backend uv run pytest tests/timeline/test_event_factory.py -q`
  [R6, R7]
- [ ] 2.4 TDD: first add a failing test that creates one existing non-property
  `TimelineEventType` through the generic factory without workflow logic, then make
  that reuse pass while keeping the deterministic English property-state title as
  only the persisted technical fallback derivable for UI localization from
  `event_type` and metadata — depends on: 2.3 — files:
  `backend/tests/timeline/test_event_factory.py`,
  `backend/app/timeline/domain/services.py` — verify:
  `docker compose exec backend uv run pytest tests/timeline/test_event_factory.py -q`
  [R6, R7]

## 3. Contextual state resolution

Section dependency: section 1.

- [ ] 3.1 TDD: first add failing precedence tests for remaining active
  `CRITICAL` incidents and then active `HIGH` incidents, including severity changes
  HIGH↔CRITICAL and resolved/cancelled exclusion; then implement those resolver
  branches — depends on: 1.4 — files:
  `backend/tests/properties/test_state_resolution.py`,
  `backend/app/properties/domain/state_resolution.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_resolution.py -q`
  [R3, R4, R7]
- [ ] 3.2 TDD: first add failing precedence tests for cleaning
  `IN_PROGRESS` and for `CREATED`/`ASSIGNED`/`ACCEPTED`, then implement
  `CLEANING_IN_PROGRESS` and `AWAITING_CLEANING` resolution without implementing
  cleaning workflows — depends on: 3.1 — files:
  `backend/tests/properties/test_state_resolution.py`,
  `backend/app/properties/domain/state_resolution.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_resolution.py -q`
  [R3, R4, R7]
- [ ] 3.3 TDD: first add failing reservation-state and boundary tests for the
  half-open interval `[effective_check_in, effective_check_out)`, proving activity
  at `effective_check_in`, inactivity at `effective_check_out`, and contextual use
  of only `CONFIRMED`/`CHECKED_IN_ESTIMATED`; then implement the reservation
  predicates — depends on: 3.2 — files:
  `backend/tests/properties/test_state_resolution.py`,
  `backend/app/properties/domain/state_resolution.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_resolution.py -q`
  [R2, R3, R4, R7]
- [ ] 3.4 TDD: first add failing tests for property timezone conversion,
  aware instants, default check-in/out times, reservation overrides, date
  boundaries, and a DST edge; then implement effective timestamp calculation
  without a global clock — depends on: 3.3 — files:
  `backend/tests/properties/test_state_resolution.py`,
  `backend/app/properties/domain/state_resolution.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_resolution.py -q`
  [R2, R3, R4, R7]
- [ ] 3.5 TDD: first add failing tests for
  `after_cleaning_completion` (`AWAITING_CHECKIN`,
  `READY_FOR_NEXT_GUEST`, `VACANT_READY`) and
  `validate_explicit_target`, then implement both approved resolver APIs without
  exposing a state mutation path — depends on: 3.4 — files:
  `backend/tests/properties/test_state_resolution.py`,
  `backend/app/properties/domain/state_resolution.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_resolution.py -q`
  [R2, R3, R4, R5, R7]
- [ ] 3.6 TDD: first add failing tests for incomplete temporal data,
  overlapping active reservations, incompatible contexts, cross-tenant entities,
  cross-property entities, and order-independent collections; then implement
  explicit scope/context rejection without silently selecting a candidate —
  depends on: 3.5 — files:
  `backend/tests/properties/test_state_resolution.py`,
  `backend/app/properties/domain/state_resolution.py`,
  `backend/app/properties/domain/exceptions.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_resolution.py -q`
  [R2, R4, R7]

## 4. Explicit transition policy and complete matrix

Section dependency: sections 1 and 3.

- [ ] 4.1 TDD: first add parameterized failing tests for every approved
  reservation-driven arrow from `VACANT_READY`, `AWAITING_CHECKIN`,
  `OCCUPIED_ESTIMATED`, and `READY_FOR_NEXT_GUEST`; then implement the matching
  declarative policy entries in `state_machine.py` — depends on: 3.6 — files:
  `backend/tests/properties/test_state_machine.py`,
  `backend/app/properties/domain/state_machine.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_machine.py -q`
  [R1, R2, R3, R7]
- [ ] 4.2 TDD: first add parameterized failing tests for every approved
  cleaning-driven arrow from `AWAITING_CLEANING`, `CLEANING_SCHEDULED`, and
  `CLEANING_IN_PROGRESS`, including rejected/expired assignment; then implement the
  matching policy entries — depends on: 4.1 — files:
  `backend/tests/properties/test_state_machine.py`,
  `backend/app/properties/domain/state_machine.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_machine.py -q`
  [R1, R2, R3, R7]
- [ ] 4.3 TDD: first add parameterized failing tests for every approved
  incident-driven arrow, including HIGH→CRITICAL, CRITICAL→HIGH, contextual
  resolution, remaining active incidents, and owner blocking where declared; then
  implement the matching policy entries — depends on: 4.2 — files:
  `backend/tests/properties/test_state_machine.py`,
  `backend/app/properties/domain/state_machine.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_machine.py -q`
  [R1, R2, R3, R4, R7]
- [ ] 4.4 TDD: first add parameterized failing tests for owner block,
  `OUT_OF_SERVICE`, reactivation, and `BLOCKED_BY_OWNER` exit arrows exactly as
  listed in Design D4; then complete the corresponding policy entries without
  adding alternative transitions — depends on: 4.3 — files:
  `backend/tests/properties/test_state_machine.py`,
  `backend/app/properties/domain/state_machine.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_machine.py -q`
  [R1, R2, R3, R5, R7]
- [ ] 4.5 TDD: first add failing trigger-precondition tests for source entity
  IDs and exact reservation/cleaning/incident statuses, especially
  `CHECKOUT_TIME_REACHED` accepting `CONFIRMED` or `CHECKED_IN_ESTIMATED` at/after
  `effective_check_out` while rejecting `CANCELLED`, `COMPLETED`, and `NO_SHOW`;
  then implement the precondition guards so a missed check-in job cannot block
  checkout — depends on: 4.4 — files:
  `backend/tests/properties/test_state_machine.py`,
  `backend/app/properties/domain/state_machine.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_machine.py -q`
  [R2, R3, R7]
- [ ] 4.6 TDD: first add a generated failing test over the canonical
  state/trigger/destination combinations not declared by PRD §8.1, including
  no-ops, mismatched optional `requested_state`, unknown states, and any
  `DOOR_OPENED` dependency; then make every undeclared case reject through the
  policy — depends on: 4.5 — files:
  `backend/tests/properties/test_state_machine.py`,
  `backend/app/properties/domain/state_machine.py`,
  `backend/app/properties/domain/exceptions.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_machine.py -q`
  [R1, R2, R3, R7]

## 5. `PropertyStateMachine.evaluate`

Section dependency: sections 2, 3, and 4.

- [ ] 5.1 TDD: first add a failing happy-path test for
  `PropertyStateMachine.evaluate` proving the ordered pipeline
  input-validation → policy → destination → evidence factory, then implement the
  minimal stateless service for a fixed transition — depends on: 2.4, 3.6, 4.6 —
  files: `backend/tests/properties/test_state_machine.py`,
  `backend/app/properties/domain/state_machine.py`,
  `backend/app/properties/domain/value_objects.py`,
  `backend/app/timeline/domain/services.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_machine.py -q`
  [R2, R3, R6, R7]
- [ ] 5.2 TDD: first add failing evaluate tests for cleaning completion and
  incident resolution, including contextual destinations and a resolved destination
  equal to the current state; then integrate `ContextualStateResolver` and reject
  the no-op without a state-change event — depends on: 5.1 — files:
  `backend/tests/properties/test_state_machine.py`,
  `backend/app/properties/domain/state_machine.py`,
  `backend/app/properties/domain/state_resolution.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_machine.py -q`
  [R2, R3, R4, R6, R7]
- [ ] 5.3 TDD: first add failing evaluate tests for manual block,
  out-of-service, reactivation, and unblock with missing/present actor, user ID,
  non-empty reason, explicit destination, and context compatibility; then implement
  data validation only, with no role/permission checks and no previous-state
  restoration — depends on: 5.2 — files:
  `backend/tests/properties/test_state_machine.py`,
  `backend/app/properties/domain/state_machine.py`,
  `backend/app/properties/domain/exceptions.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_machine.py -q`
  [R2, R3, R5, R7]
- [ ] 5.4 TDD: first add failing assertions that every accepted and rejected
  evaluation leaves `Property`, reservations, cleaning tasks, incidents, and input
  metadata unchanged; then remove any mutation paths and keep
  `PropertyStateMachine.evaluate` as the sole public state-change authority —
  depends on: 5.3 — files:
  `backend/tests/properties/test_state_machine.py`,
  `backend/app/properties/domain/state_machine.py`,
  `backend/app/properties/domain/value_objects.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_state_machine.py -q`
  [R2, R6, R7]

## 6. Correlated result, determinism, and failure atomicity

Section dependency: section 5.

- [ ] 6.1 TDD: first add failing result tests that an accepted transition
  returns exactly one existing `PropertyStateTransition` and one existing
  `TimelineEvent(PROPERTY_STATE_CHANGED)` with matching tenant, property,
  from/to states, actor, reason, reference instant, reservation, trigger, and source
  entity; then complete coordinated result construction — depends on: 5.4 — files:
  `backend/tests/properties/test_transition_result.py`,
  `backend/app/properties/domain/state_machine.py`,
  `backend/app/properties/domain/value_objects.py`,
  `backend/app/timeline/domain/services.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_transition_result.py -q`
  [R1, R6, R7]
- [ ] 6.2 TDD: first add failing tests that optional `correlation_id` is copied
  unchanged into both metadata dictionaries, that actor/user and reason remain
  coherent, and that the deterministic English title is only the persisted
  technical fallback alongside localizable `event_type`/metadata; then implement
  the exact metadata projection — depends on: 6.1 — files:
  `backend/tests/properties/test_transition_result.py`,
  `backend/app/properties/domain/state_machine.py`,
  `backend/app/timeline/domain/services.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_transition_result.py -q`
  [R6, R7]
- [ ] 6.3 TDD: first add failing determinism tests proving identical complete
  requests produce exactly equal logical fields and that changing state, input,
  context, actor, or instant changes the corresponding result; then remove internal
  randomness, clock access, and order sensitivity — depends on: 6.2 — files:
  `backend/tests/properties/test_transition_result.py`,
  `backend/tests/properties/test_state_resolution.py`,
  `backend/app/properties/domain/state_machine.py`,
  `backend/app/properties/domain/state_resolution.py`,
  `backend/app/timeline/domain/services.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_transition_result.py tests/properties/test_state_resolution.py -q`
  [R2, R4, R6, R7]
- [ ] 6.4 TDD: first add failing tests for invalid transition, invalid context,
  invalid timeline data, and evidence-construction failure proving that no partial
  result is returned and no input is changed; then enforce all-or-nothing
  construction and `TransitionEvidenceError` without persistence or mocks —
  depends on: 6.3 — files:
  `backend/tests/properties/test_transition_result.py`,
  `backend/app/properties/domain/state_machine.py`,
  `backend/app/properties/domain/exceptions.py`,
  `backend/app/timeline/domain/services.py`,
  `backend/app/timeline/domain/exceptions.py` — verify:
  `docker compose exec backend uv run pytest tests/properties/test_transition_result.py -q`
  [R2, R4, R6, R7]

## 7. Verification and architecture gate

Section dependency: sections 1–6.

- [ ] 7.1 Run the complete focused domain suite and confirm all approved valid
  arrows, undeclared transitions, no-ops, temporal/context cases, manual actions,
  timeline reuse, and evidence invariants pass — files verified:
  `backend/tests/properties/test_state_machine.py`,
  `backend/tests/properties/test_state_resolution.py`,
  `backend/tests/properties/test_transition_result.py`,
  `backend/tests/timeline/test_event_factory.py` — command:
  `docker compose exec backend uv run pytest tests/properties/test_state_machine.py tests/properties/test_state_resolution.py tests/properties/test_transition_result.py tests/timeline/test_event_factory.py`
  [R1, R2, R3, R4, R5, R6, R7]
- [ ] 7.2 Run the full backend regression suite using the exact project command
  and keep every existing unit/integration test green — files verified:
  `backend/tests/` — command:
  `docker compose exec backend uv run pytest`
  [R1, R2, R3, R4, R5, R6, R7]
- [ ] 7.3 Validate the dependency boundary by confirming no forbidden imports
  occur in any new domain module — files:
  `backend/app/properties/domain/state_machine.py`,
  `backend/app/properties/domain/state_resolution.py`,
  `backend/app/properties/domain/value_objects.py`,
  `backend/app/properties/domain/transition_enums.py`,
  `backend/app/properties/domain/exceptions.py`,
  `backend/app/timeline/domain/services.py`,
  `backend/app/timeline/domain/value_objects.py`,
  `backend/app/timeline/domain/exceptions.py` — command (expected: no matches):
  `rg -n '^(from|import) (sqlalchemy|fastapi|pydantic(_settings)?|celery|redis)(\.|[[:space:]]|$)' backend/app/properties/domain/state_machine.py backend/app/properties/domain/state_resolution.py backend/app/properties/domain/value_objects.py backend/app/properties/domain/transition_enums.py backend/app/properties/domain/exceptions.py backend/app/timeline/domain/services.py backend/app/timeline/domain/value_objects.py backend/app/timeline/domain/exceptions.py`
  [R7]
- [ ] 7.4 Confirm no speculative port/protocol or persistence abstraction was
  added — files:
  `backend/app/properties/domain/state_machine.py`,
  `backend/app/properties/domain/state_resolution.py`,
  `backend/app/properties/domain/value_objects.py`,
  `backend/app/properties/domain/transition_enums.py`,
  `backend/app/properties/domain/exceptions.py`,
  `backend/app/timeline/domain/services.py`,
  `backend/app/timeline/domain/value_objects.py`,
  `backend/app/timeline/domain/exceptions.py` — command (expected: no matches):
  `rg -n '(Protocol|ABC|Repository|UnitOfWork)' backend/app/properties/domain/state_machine.py backend/app/properties/domain/state_resolution.py backend/app/properties/domain/value_objects.py backend/app/properties/domain/transition_enums.py backend/app/properties/domain/exceptions.py backend/app/timeline/domain/services.py backend/app/timeline/domain/value_objects.py backend/app/timeline/domain/exceptions.py`
  [R7]
- [ ] 7.5 Confirm existing entities, persisted enums, ORM, and migrations remain
  byte-for-byte unchanged — files:
  `backend/app/properties/domain/entities.py`,
  `backend/app/properties/domain/enums.py`,
  `backend/app/timeline/domain/entities.py`,
  `backend/app/timeline/domain/enums.py`,
  `backend/app/reservations/domain/entities.py`,
  `backend/app/reservations/domain/enums.py`,
  `backend/app/cleaning/domain/entities.py`,
  `backend/app/cleaning/domain/enums.py`,
  `backend/app/maintenance/domain/entities.py`,
  `backend/app/maintenance/domain/enums.py`,
  `backend/app/{properties,timeline,reservations,cleaning,maintenance}/infrastructure/`,
  `backend/alembic/` — command:
  `git diff --exit-code -- backend/app/properties/domain/entities.py backend/app/properties/domain/enums.py backend/app/timeline/domain/entities.py backend/app/timeline/domain/enums.py backend/app/reservations/domain/entities.py backend/app/reservations/domain/enums.py backend/app/cleaning/domain/entities.py backend/app/cleaning/domain/enums.py backend/app/maintenance/domain/entities.py backend/app/maintenance/domain/enums.py backend/app/properties/infrastructure backend/app/timeline/infrastructure backend/app/reservations/infrastructure backend/app/cleaning/infrastructure backend/app/maintenance/infrastructure backend/alembic`
  [R1, R7]
- [ ] 7.6 Review the implementation diff and confirm it contains only the eight
  approved new domain modules and four approved unit-test files, with no
  application, API, repository, persistence, job, RBAC, AuditLog, seed, frontend,
  infrastructure, documentation, live-spec, Proposal, or Design changes — files
  verified: `backend/app/properties/domain/`,
  `backend/app/timeline/domain/`, `backend/tests/properties/`,
  `backend/tests/timeline/`,
  `sdd/changes/timeline-state-machine/proposal.md`,
  `sdd/changes/timeline-state-machine/design.md` — commands:
  `git status --short`; `git diff --name-only`
  [R7]
- [ ] 7.7 Run whitespace/conflict validation and manually map the passing tests
  back to every Design D1–D11 decision and Proposal R1–R7 before marking any task
  complete — files verified: all files changed by this implementation — command:
  `git diff --check`
  [R1, R2, R3, R4, R5, R6, R7]
