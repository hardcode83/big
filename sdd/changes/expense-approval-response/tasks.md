# Tasks: expense-approval-response

<!-- Section 1 introduces the new response DTO; section 2 widens the use case to handle
     `OTHER` approvals; section 3 wires the router to dispatch the response body by
     `related_type`; section 4 covers tests for both layers; section 5 covers the OpenAPI
     regeneration, docs and the verification gates. -->

## 1. Add `OwnerApprovalResponse` DTO

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

## 2. Widen `RespondOwnerApprovalUseCase` for `OTHER` approvals

- [ ] 2.1 Modify `RespondOwnerApprovalUseCase.execute(...)` in
      `backend/app/maintenance/application/use_cases.py:1652` to branch on
      `approval.related_type` after the existing `OwnerApprovalRepository.get(...)` and the
      `OwnerApprovalAlreadyAnsweredError` check. The branch for `OTHER` MUST run before the
      `IncidentRepository.get(...)` line and skip every step that touches an incident.
      [R1.1, R2.1, R2.2, R2.3]
- [ ] 2.2 Change the return type annotation from `-> Incident` to `-> Incident | OwnerApproval`
      and return `incident` for `INCIDENT`/`MAINTENANCE_COST` and `approval` for `OTHER`. The
      router will dispatch on the concrete type. [R1.1, R1.6, R2.2, R9]
- [ ] 2.3 In the `OTHER` branch: write `AuditLog OWNER_APPROVAL_ANSWERED` with the same
      `ChangeSet(OWNER_APPROVAL)` shape as the existing branch — `status`, `responded_by`,
      `responded_at` — and skip the `TimelineEvent` write, the `PropertyStateMachine`
      trigger and the technician notification (`_notify_answer`). [R2.3, R2.4, R3.1, R3.2]
- [ ] 2.4 Validate in the existing role check (`actor.role is UserRole.TENANT_OWNER`,
      line 1692) that it fires for both branches — a non-`TENANT_OWNER` actor gets
      `MaintenanceValidationError` (`422`) regardless of `related_type`. [R1.2]
- [ ] 2.5 Confirm the unit signature compiles: `docker compose exec backend uv run pyright
      backend/app/maintenance/application/use_cases.py`. [R6.2]

## 3. Wire router to dispatch response by `related_type`

- [ ] 3.1 In `backend/app/maintenance/api/approvals_router.py:82`, change
      `respond_owner_approval` so that the `response_model` declared on the route is
      `OwnerApprovalResponse` (the smallest of the two bodies), and `responses={...}` lists
      both `IncidentResponse` and `OwnerApprovalResponse` as the two valid `200` shapes,
      documented per FastAPI's `responses=` convention. [R1.6, R6.1]
- [ ] 3.2 Inside the handler, dispatch on the returned object type: if it is an `Incident`,
      build `IncidentResponse.from_domain(...)`; if it is an `OwnerApproval`, build
      `OwnerApprovalResponse.from_domain(...)`. The `status_code=200` and the route prefix
      stay unchanged. [R1.6, R6.1, R9]
- [ ] 3.3 Confirm the file still imports cleanly and the route is registered:
      `docker compose exec backend uv run python -c "from app.maintenance.api.approvals_router import router; print([r.path for r in router.routes])"`. [R6.2]

## 4. Tests for the `OTHER` branch

- [ ] 4.1 In `backend/tests/maintenance/test_use_cases.py`, add unit tests for
      `RespondOwnerApprovalUseCase.execute(...)` covering the `OTHER` branch:
      `APPROVED` writes the approval `status`/`responded_at`/`responded_by`/`response_notes`
      and the `AuditLog` row, but does NOT mutate any incident; `REJECTED` does the same
      and skips the `TimelineEvent` / `PropertyStateMachine` / technician notification
      paths. Use existing fixtures and `OwnerApprovalRelatedType.OTHER`. [R1.1, R2.2, R2.3,
      R3.1]
- [ ] 4.2 In the same file, add a test that a second `execute(...)` call on the same
      `OTHER` approval raises `OwnerApprovalAlreadyAnsweredError` (`409`) — idempotency
      guarantee, same body as `INCIDENT`/`MAINTENANCE_COST`. [R1.4]
- [ ] 4.3 In the same file, add a test that an approval `id` belonging to another tenant
      returns `OwnerApprovalNotFoundError` (`404`) with the same body — the tenant-scoping
      is structural via `OwnerApprovalRepository.get(tenant_id, ...)`. [R1.3, R5.1]
- [ ] 4.4 In the same file, add a test that a non-`TENANT_OWNER` actor (e.g. `PROPERTY_MANAGER`)
      raises `MaintenanceValidationError` (`422`) — the role check fires for both branches.
      [R1.2]
- [ ] 4.5 In `backend/tests/maintenance/test_api_approvals.py`, add HTTP-level tests for
      `POST /api/v1/owner-approvals/{id}/respond` against a row `related_type = OTHER`:
      `200` with `OwnerApprovalResponse` body for `APPROVED` and `REJECTED`; `409` on a
      second call; `404` on a wrong tenant's approval; `422` on a non-`TENANT_OWNER` token.
      Verify the body shape matches D6 (six fields). [R1.1, R1.3, R1.4, R1.6]
- [ ] 4.6 In the same file, add a test that asserts an existing
      `POST /owner-approvals/{id}/respond` against an `INCIDENT`/`MAINTENANCE_COST`
      approval still returns `IncidentResponse` (no regression on the existing branch).
      [R1.1, R6.1]
- [ ] 4.7 In `backend/tests/statements/test_reconciliation.py` (or add a new test file if
      the reconciler has none dedicated to this), add a test that runs
      `ReconcileOwnerApprovalsForExpensesUseCase.execute(now=...)` immediately after the
      `OTHER` branch's API call and verifies that the `Expense.approved_by` is set
      (`APPROVED`) or the `Expense` row is deleted (`REJECTED`). The latency reduction is
      not the goal here — the test injects the tick to keep CI deterministic. [R4.1]

## 5. OpenAPI regeneration, docs and verification

- [ ] 5.1 Regenerate the API contract:
      `docker compose exec backend uv run python -m app.maintenance.api.openapi` (or the
      project's documented command — see `sdd/specs/api-contract.md`); commit
      `backend/openapi.json`. [R6.2]
- [ ] 5.2 Regenerate the TypeScript client:
      `docker compose exec -T frontend npm run api:generate` (the documented command, with
      the worktree caveats from `sdd/project.md` "Worktree bootstrap"); commit
      `frontend/lib/api/generated/openapi.d.ts`. [R6.2]
- [ ] 5.3 Update `docs/maintenance.md` to reflect that
      `POST /api/v1/owner-approvals/{id}/respond` serves both `INCIDENT` /
      `MAINTENANCE_COST` and `OTHER` approvals, with the `OwnerApprovalResponse` body for
      the latter. Replace the sentence "la ruta resuelve siempre por incidencia" with the
      design's D5/D9 contract. [R5 spec doc, R8 spec doc — `maintenance.md`]
- [ ] 5.4 Update `docs/revenue-statements.md` to drop the sentence "hoy no hay ninguna ruta
      que responda una `OwnerApproval(OTHER)`" (R5.7 of that doc) and replace it with the
      design's D7 statement — the route does serve them, the reconciler still materialises
      the answer on `expenses`. [R5.7 spec doc — `revenue-statements.md`]
- [ ] 5.5 Run the full backend test suite as documented in `sdd/project.md`:
      `docker compose exec backend uv run pytest`. Suite must end green and the per-section
      coverage checks for the files touched (`backend/app/maintenance/application/use_cases.py`,
      `backend/app/maintenance/api/approvals_router.py`, `backend/app/maintenance/api/schemas.py`)
      must stay at or above the project baseline. [Verification]
- [ ] 5.6 Run the static tooling: `docker compose exec backend uv run pyright .`. Reports
      must be clean (no new findings in files touched by this change). [Verification]
- [ ] 5.7 Run the rule-11 ownership guard from the host (per `sdd/project.md` "Commands"):
      `make check-rule11-ownership`. No new findings in the files touched. [Verification]

## Implementation Notes

- Imported `Literal` from `typing` in `backend/app/maintenance/api/schemas.py`; added `OwnerApproval` to the existing `app.maintenance.domain.entities` import block; placed `OwnerApprovalResponse` between `OwnerApprovalPageResponse` and `IncidentPhotoResponse`.

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->