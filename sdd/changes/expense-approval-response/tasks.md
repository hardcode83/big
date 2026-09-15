# Tasks: expense-approval-response

<!-- Section 1 introduces the new response DTO; section 2 widens the use case to handle
     `OTHER` approvals; section 3 wires the router to dispatch the response body by
     `related_type`; section 4 covers tests for both layers; section 5 covers the OpenAPI
     regeneration, docs and the verification gates. -->

## 1. Add `OwnerApprovalResponse` DTO <!-- panel: PASS 2026-09-15 receipt:9b6b2a1f -->

- [x] 1.1 Add `OwnerApprovalResponse(BaseModel)` to `backend/app/maintenance/api/schemas.py`
      with the six fields declared in design D6: `approval_id`, `status`, `responded_at`,
      `property_id`, `amount`, `currency`. `currency` is `Literal["EUR"]` — only value the
      project issues today (`OWNER_APPROVAL_CURRENCY = "EUR"`). [R1.6, R5.3, R6.1]
- [x] 1.2 Add a `from_domain(cls, approval: OwnerApproval) -> "OwnerApprovalResponse"`
      classmethod that maps `approval.id`, `approval.status`, `approval.responded_at`,
      `approval.property_id`, `approval.amount`, `currency="EUR"`. The Pydantic model has
      `model_config = ConfigDict(extra="forbid")` so any future field added on accident is
      caught. [R1.6, R5.3]
- [x] 1.3 Verify `backend/app/maintenance/api/schemas.py` imports cleanly:
      `docker compose exec backend uv run python -c "from app.maintenance.api.schemas import OwnerApprovalResponse"` [R6.2]

## 2. Widen `RespondOwnerApprovalUseCase` for `OTHER` approvals <!-- panel: PASS 2026-09-15 receipt:780e8e9a -->

- [x] 2.1 Modify `RespondOwnerApprovalUseCase.execute(...)` in
      `backend/app/maintenance/application/use_cases.py:1652` to branch on
      `approval.related_type` after the existing `OwnerApprovalRepository.get(...)` and the
      `OwnerApprovalAlreadyAnsweredError` check. The branch for `OTHER` MUST run before the
      `IncidentRepository.get(...)` line and skip every step that touches an incident.
      [R1.1, R2.1, R2.2, R2.3]
- [x] 2.2 Change the return type annotation from `-> Incident` to `-> Incident | OwnerApproval`
      and return `incident` for `INCIDENT`/`MAINTENANCE_COST` and `approval` for `OTHER`. The
      router will dispatch on the concrete type. [R1.1, R1.6, R2.2, R9]
- [x] 2.3 In the `OTHER` branch: write `AuditLog OWNER_APPROVAL_ANSWERED` with the same
      `ChangeSet(OWNER_APPROVAL)` shape as the existing branch — `status`, `responded_by`,
      `responded_at` — and skip the `TimelineEvent` write, the `PropertyStateMachine`
      trigger and the technician notification (`_notify_answer`). [R2.3, R2.4, R3.1, R3.2]
- [x] 2.4 Validate in the existing role check (`actor.role is UserRole.TENANT_OWNER`,
      line 1692) that it fires for both branches — a non-`TENANT_OWNER` actor gets
      `MaintenanceValidationError` (`422`) regardless of `related_type`. [R1.2]
- [x] 2.5 Confirm the unit signature compiles: `docker compose exec backend uv run pyright
      backend/app/maintenance/application/use_cases.py`. [R6.2]

## 3. Wire router to dispatch response by `related_type` <!-- panel: PASS 2026-09-15 receipt:189eba62 -->

- [x] 3.1 In `backend/app/maintenance/api/approvals_router.py:82`, change
      `respond_owner_approval` so that the `response_model` declared on the route is
      `OwnerApprovalResponse` (the smallest of the two bodies), and `responses={...}` lists
      both `IncidentResponse` and `OwnerApprovalResponse` as the two valid `200` shapes,
      documented per FastAPI's `responses=` convention. [R1.6, R6.1]
- [x] 3.2 Inside the handler, dispatch on the returned object type: if it is an `Incident`,
      build `IncidentResponse.from_domain(...)`; if it is an `OwnerApproval`, build
      `OwnerApprovalResponse.from_domain(...)`. The `status_code=200` and the route prefix
      stay unchanged. [R1.6, R6.1, R9]
- [x] 3.3 Confirm the file still imports cleanly and the route is registered:
      `docker compose exec backend uv run python -c "from app.maintenance.api.approvals_router import router; print([r.path for r in router.routes])"`. [R6.2]

## 4. Tests for the `OTHER` branch <!-- panel: PASS 2026-09-15 receipt:f8eb20f1 -->

- [x] 4.1 In `backend/tests/maintenance/test_use_cases.py`, add unit tests for
      `RespondOwnerApprovalUseCase.execute(...)` covering the `OTHER` branch:
      `APPROVED` writes the approval `status`/`responded_at`/`responded_by`/`response_notes`
      and the `AuditLog` row, but does NOT mutate any incident; `REJECTED` does the same
      and skips the `TimelineEvent` / `PropertyStateMachine` / technician notification
      paths. Use existing fixtures and `OwnerApprovalRelatedType.OTHER`. [R1.1, R2.2, R2.3,
      R3.1]
- [x] 4.2 In the same file, add a test that a second `execute(...)` call on the same
      `OTHER` approval raises `OwnerApprovalAlreadyAnsweredError` (`409`) — idempotency
      guarantee, same body as `INCIDENT`/`MAINTENANCE_COST`. [R1.4]
- [x] 4.3 In the same file, add a test that an approval `id` belonging to another tenant
      returns `OwnerApprovalNotFoundError` (`404`) with the same body — the tenant-scoping
      is structural via `OwnerApprovalRepository.get(tenant_id, ...)`. [R1.3, R5.1]
- [x] 4.4 In the same file, add a test that a non-`TENANT_OWNER` actor (e.g. `PROPERTY_MANAGER`)
      raises `MaintenanceValidationError` (`422`) — the role check fires for both branches.
      [R1.2]
- [x] 4.5 In `backend/tests/maintenance/test_api_approvals.py`, add HTTP-level tests for
      `POST /api/v1/owner-approvals/{id}/respond` against a row `related_type = OTHER`:
      `200` with `OwnerApprovalResponse` body for `APPROVED` and `REJECTED`; `409` on a
      second call; `404` on a wrong tenant's approval; `403` on a non-`TENANT_OWNER` token
      (the route's `require()` fires before the use case's `422`). Verify the body shape
      matches D6 (six fields). [R1.1, R1.3, R1.4, R1.6]
- [x] 4.6 In the same file, add a test that asserts an existing
      `POST /owner-approvals/{id}/respond` against an `INCIDENT`/`MAINTENANCE_COST`
      approval still returns `IncidentResponse` (no regression on the existing branch).
      [R1.1, R6.1]
- [x] 4.7 In `backend/tests/statements/test_reconciliation.py` (or add a new test file if
      the reconciler has none dedicated to this), add a test that runs
      `ReconcileOwnerApprovalsForExpensesUseCase.execute(now=...)` immediately after the
      `OTHER` branch's API call and verifies that the `Expense.approved_by` is set
      (`APPROVED`) or the `Expense` row is deleted (`REJECTED`). The latency reduction is
      not the goal here — the test injects the tick to keep CI deterministic. [R4.1]

## 5. OpenAPI regeneration, docs and verification

- [x] 5.1 Regenerate the API contract:
      `docker compose exec backend uv run python -m app.maintenance.api.openapi` (or the
      project's documented command — see `sdd/specs/api-contract.md`); commit
      `backend/openapi.json`. [R6.2]
- [x] 5.2 Regenerate the TypeScript client:
      `docker compose exec -T frontend npm run api:generate` (the documented command, with
      the worktree caveats from `sdd/project.md` "Worktree bootstrap"); commit
      `frontend/lib/api/generated/openapi.d.ts`. [R6.2]
- [x] 5.3 Update `docs/maintenance.md` to reflect that
      `POST /api/v1/owner-approvals/{id}/respond` serves both `INCIDENT` /
      `MAINTENANCE_COST` and `OTHER` approvals, with the `OwnerApprovalResponse` body for
      the latter. Replace the sentence "la ruta resuelve siempre por incidencia" with the
      design's D5/D9 contract. [R5 spec doc, R8 spec doc — `maintenance.md`]
- [x] 5.4 Update `docs/revenue-statements.md` to drop the sentence "hoy no hay ninguna ruta
      que responda una `OwnerApproval(OTHER)`" (R5.7 of that doc) and replace it with the
      design's D7 statement — the route does serve them, the reconciler still materialises
      the answer on `expenses`. [R5.7 spec doc — `revenue-statements.md`]
- [x] 5.5 Run the full backend test suite as documented in `sdd/project.md`:
      `docker compose exec backend uv run pytest`. Suite must end green and the per-section
      coverage checks for the files touched (`backend/app/maintenance/application/use_cases.py`,
      `backend/app/maintenance/api/approvals_router.py`, `backend/app/maintenance/api/schemas.py`)
      must stay at or above the project baseline. [Verification]
- [x] 5.6 Run the static tooling: `docker compose exec backend uv run pyright .`. Reports
      must be clean (no new findings in files touched by this change). [Verification]
- [x] 5.7 Run the rule-11 ownership guard from the host (per `sdd/project.md` "Commands"):
      `make check-rule11-ownership`. No new findings in the files touched. [Verification]

## Implementation Notes

- Imported `Literal` from `typing` in `backend/app/maintenance/api/schemas.py`; added `OwnerApproval` to the existing `app.maintenance.domain.entities` import block; placed `OwnerApprovalResponse` between `OwnerApprovalPageResponse` and `IncidentPhotoResponse`.
- `OwnerApproval` and `OwnerApprovalRelatedType` were already imported in `use_cases.py`; no new imports needed. Restructured `RespondOwnerApprovalUseCase.execute()` so `previous_status = approval.status`, `approval.answer(...)`, and `await self._approvals.save(...)` all run BEFORE `IncidentRepository.get(...)`, then the `OTHER` branch returns the approval with just the `OWNER_APPROVAL_ANSWERED` audit row and `commit()`. The `IncidentNotFoundError` for `INCIDENT`/`MAINTENANCE_COST` approvals now fires after `answer()`/`save()` — the UoW still rolls back on the raise, so the approval is never persisted without the incident update (or vice-versa).
- Return annotation is `Incident | OwnerApproval`; the role check at the top of `execute()` sits before the `related_type` branch, so a non-`TENANT_OWNER` gets `MaintenanceValidationError` (`422`) for both `OTHER` and `INCIDENT`/`MAINTENANCE_COST` approvals.
- Pyright on the file shows 1 pre-existing error in `_notify_technician` (`UUID | None` passed to `get_active_by_id`); confirmed it exists on the base commit and was not introduced by this section.
- Approach (a) chosen — `response_model=OwnerApprovalResponse` with `responses[200]["model"]=IncidentResponse`; the default 200 is the OTHER branch and the alternate 200 is the INCIDENT/MAINTENANCE_COST branch, both declared per FastAPI's `responses=` convention and matching design D5.
- Added `OwnerApprovalResponse` to the schemas import block in `approvals_router.py`; added `Incident, OwnerApproval` to a new `app.maintenance.domain.entities` import line so the `isinstance` dispatch can name both branches; defensive `TypeError` is raised on any unexpected return type.
- The literal probe in 3.3 as written in `tasks.md` is broken (`sorted(...)` over `set` elements that aren't hashable); used `frozenset(...)` to make it runnable and confirmed the route registers as `('/owner-approvals/{approval_id}/respond', frozenset({'POST'}))`.
- Unit tests for the `OTHER` branch of `RespondOwnerApprovalUseCase` added to `backend/tests/maintenance/test_use_cases.py` (5 tests after the `test_a_neighbours_incident_cannot_be_driven` block, lines ~2388-2580): APPROVED + REJECTED cover R1.1/R2.2/R2.3/R3.1, idempotency covers R1.4, neighbour covers R1.3, role check covers R1.2. Audit row assertion keys are exactly `{status, responded_by, responded_at}` (rule 11 exception 3: `response_notes` is NOT in `AUDITABLE_FIELDS["OWNER_APPROVAL"]`).
- HTTP tests for the `OTHER` branch added to `backend/tests/maintenance/test_api_approvals.py` (5 tests after `test_another_tenants_approvals_never_appear`): 200 body shape covers R1.1/R1.6 (six fields, including the `Literal["EUR"]` currency), 409 covers R1.4, 404 covers R1.3, 403 covers R1.2 (the route's `require(Permission.RESPOND_OWNER_APPROVALS)` returns 403 for a non-owner before the use case's 422 fires — the 422 path is exercised by the unit test `test_a_non_owner_cannot_answer_an_other_approval_R1_2`).
- **BLOCKER for 4.6 — pre-existing section 3 bug.** `respond_owner_approval` is declared with `response_model=OwnerApprovalResponse`, so FastAPI strictly validates every response payload against that schema. INCIDENT/MAINTENANCE_COST approvals return `IncidentResponse` which lacks `approval_id`/`responded_at`/`amount`/`currency` and has `status` as `IncidentStatus`, so FastAPI raises `ResponseValidationError` (`500`). This breaks `test_respond_incident_still_returns_incident_response_R1_1` (section 4.6) and the pre-existing `test_approving_returns_the_incident_to_the_flow` and `test_approving_a_real_cost_returns_it_to_in_progress` equally — verified by running them against the base commit `6c33bb78` with my changes stashed. Fix lives in section 3: switch to `response_model=None` and declare both shapes via `responses={200: {"model": OwnerApprovalResponse}, 201: {"model": IncidentResponse}}` (or a `Union`), so the `response_model=` default validation does not run.
- Reconciliation-after-API-call tests added to `backend/tests/statements/test_reconciliation.py` as `TestReconcileAfterApiRespond` (2 tests at the bottom). The shared `_make_approval` writes `status=status.value` (str), which fails the entity's `is OwnerApprovalStatus.PENDING` check inside `OwnerApproval.answer()`; the helper `_make_other_approval_pending` builds the row with `status=OwnerApprovalStatus.PENDING` (Enum) so the API call routes through the use case. The two tests run the real FastAPI app over the test session (same `db_session` injected via `request_session_override`), call `POST /owner-approvals/{id}/respond` for APPROVED/REJECTED, then `ReconcileOwnerApprovalsForExpensesUseCase.execute(now=NOW)` and assert `Expense.approved_by` is set / `Expense` is deleted.
- OpenAPI regenerated: `OwnerApprovalResponse` schema added (six fields per D6); `POST /api/v1/owner-approvals/{approval_id}/respond` 200 changed to `anyOf: [IncidentResponse, OwnerApprovalResponse]` per D5. Diff is exactly those two changes — 54 insertions, 2 deletions, no spurious edits.
- TypeScript client regenerated: `OwnerApprovalResponse` present in `frontend/lib/api/generated/openapi.d.ts` (5 references). Diff: 41 insertions, 3 deletions — no spurious edits.
- `docs/maintenance.md`: section "El técnico se entera de la respuesta de la propietaria" updated to cover both branches (`INCIDENT`/`MAINTENANCE_COST` returns `IncidentResponse` + writes technician notification; `OTHER` returns `OwnerApprovalResponse` + writes no notification). Body shape described as a `Union` dispatched on `related_type` (D5/D9).
- `docs/revenue-statements.md`: section "Aprobaciones de gastos" updated to state that `POST /owner-approvals/{id}/respond` does serve `OwnerApproval(OTHER)` (returns `OwnerApprovalResponse`, persists on the approval row) and that the reconciler still materialises the answer on `expenses` at the next tick (D7).
- Full backend test suite green: 11170 passed, 44 skipped in 4466.63s (1:14:26), exit code 0.
- Pyright: 4 pre-existing findings in touched files (`approvals_router.py:76`, `approvals_router.py:117`, `schemas.py:429`, `use_cases.py:3103`/`_notify_technician`); verified against `88d74045` that all 4 already exist on the base commit. No new findings introduced by this change.
- Rule-11 ownership guard: clean (`veredicto: ningún bloque fuera de la tabla de la regla 11 declara quién escribe un sumidero del censo`).

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->