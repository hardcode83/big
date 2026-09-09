# Tasks: approvals-web

## 1. Backend RBAC — `READ_OWNER_APPROVALS` for the owner and the manager <!-- panel: PASS 2026-09-05 -->

- [x] 1.1 Add `Permission.READ_OWNER_APPROVALS` to `backend/app/auth/domain/policy.py`, a new
      bundle `_OWNER_APPROVAL_READ = frozenset({Permission.READ_OWNER_APPROVALS})`, and grant it
      to `ROLE_PERMISSIONS[UserRole.TENANT_OWNER]` and `ROLE_PERMISSIONS[UserRole.PROPERTY_MANAGER]`
      only (D1). Rewrite the comment block above `RESPOND_OWNER_APPROVALS`/`READ_INCIDENTS`
      (currently "There is deliberately **no** `READ_OWNER_APPROVALS` and no listing route…") so it
      no longer declares the absence this change ends, and rewrite the module docstring of
      `backend/app/maintenance/api/approvals_router.py` (currently "One route, and one is the whole
      surface on purpose… There is deliberately **no listing**…") the same way. [R1.4, R1.6]
- [x] 1.2 Update `backend/tests/auth/test_policy.py`: add `READ_OWNER_APPROVALS` to the role-set
      assertions so `TENANT_OWNER` and `PROPERTY_MANAGER` hold it and no other role does (mirror the
      existing `RESPOND_OWNER_APPROVALS`-only-owner assertions around line 297). [R1.4]

## 2. Backend read model — the owner-approval listing as a projection <!-- panel: PASS 2026-09-05 -->

- [x] 2.1 Add to `backend/app/maintenance/domain/read_models.py` (beside `IncidentContext`): frozen
      dataclasses `OwnerApprovalIncidentRef` (`id`, `title`, `category`, `severity`),
      `OwnerApprovalPropertyRef` (`id`, `name`, `internal_code`), `OwnerApprovalListItem` (`id`,
      `related_type`, `status`, `amount`, `currency`, `requested_at`, `responded_at`,
      `incident: OwnerApprovalIncidentRef | None`, `property: OwnerApprovalPropertyRef`), and
      `OwnerApprovalPage` (`items: tuple[OwnerApprovalListItem, ...]`, `total: int`). Declare
      `OWNER_APPROVAL_CURRENCY = "EUR"` as a module constant with a docstring citing
      `owner_approval_threshold_eur` as why EUR is not a guess (D2, D3). No pydantic, no
      SQLAlchemy — pure Python, per the module's own layering rule enforced by
      `backend/tests/test_layering.py`. [R1.3]
- [x] 2.2 Add `OwnerApprovalFilters` (`status: OwnerApprovalStatus | None = None`) and
      `OwnerApprovalReader.list_for_tenant(tenant_id, filters, *, page, per_page) ->
      OwnerApprovalPage` to `backend/app/maintenance/domain/repositories.py`, documenting the
      ordering rule (absent/`PENDING` → `requested_at ASC, id ASC`; any answered status →
      `responded_at DESC, id DESC`) and that a property absent from the tenant is dropped from the
      page (D4, D5). [R1.1, R1.2]
- [x] 2.3 Implement `SqlAlchemyOwnerApprovalReader.list_for_tenant` in
      `backend/app/maintenance/infrastructure/repositories.py`: one `LEFT OUTER JOIN` of
      `owner_approvals` to `incidents` gated on `related_type != OTHER` for the approval+incident
      columns, the two orderings of D5, and log
      `maintenance.owner_approval_property_unresolved` (same shape as
      `GetIncidentContextUseCase`'s `maintenance.incident_context_property_unresolved`) for a row
      whose property does not resolve inside the tenant, dropping it from the page rather than
      raising (D4). [R1.1, R1.2, R1.3]
- [x] 2.4 Tests in `backend/tests/maintenance/test_repositories.py`: default (no status) returns
      only `PENDING` oldest-first; an answered-status filter returns newest-responded-first;
      `OTHER` rows come back with `incident=None`; a property outside the tenant is dropped and
      logged, not raised; pagination (`page`/`per_page`) matches `total`. [R1.1, R1.2, R1.3, D4]

## 3. Backend list endpoint — `GET /api/v1/owner-approvals` <!-- panel: PASS 2026-09-05 -->

- [x] 3.1 Add `ListOwnerApprovalsUseCase` to `backend/app/maintenance/application/use_cases.py`:
      takes `approvals: OwnerApprovalReader` and `properties: PropertyRepository`, calls
      `list_for_tenant`, and is a plain read (no `UnitOfWork`, no audit repository) — same shape as
      `GetIncidentContextUseCase`/`ListIncidentsUseCase`. [R1.1, R1.2, R1.3]
- [x] 3.2 Add `OwnerApprovalListItemResponse` and `OwnerApprovalPageResponse` to
      `backend/app/maintenance/api/schemas.py` (D2's field list, `from_domain` classmethods
      following `IncidentPageResponse`'s pattern). In the same file, tighten
      `RespondOwnerApprovalRequest.response_notes` to
      `Annotated[MultiLineText, Field(max_length=MAX_RESPONSE_NOTES)] | None = None` (D12) — `str`
      today lets a `U+0000` or a lone surrogate reach asyncpg as an undeclared `500`; `MultiLineText`
      is already imported in this file. [R1.3, D12]
- [x] 3.3 Add `GET ""` to `backend/app/maintenance/api/approvals_router.py`: `page`/`per_page`
      (bounds `MAX_PAGE`/`MAX_PER_PAGE`, same as `incidents_router.py`), optional `status` query
      param, guarded by `require(Permission.READ_OWNER_APPROVALS)`, tenant from the token only
      (never a parameter), responding `403` with no hint of existence to a caller without the
      permission (R1.5, inherited from `require()`/`AUTHENTICATED_RESPONSES` — not restated).
      [R1.1, R1.2, R1.4, R1.5]
- [x] 3.4 Wire `get_list_owner_approvals_use_case` in `backend/app/maintenance/api/dependencies.py`
      (`SqlAlchemyOwnerApprovalReader` + `SqlAlchemyPropertyRepository`, no `uow`, no `audit`).
      [R1.1]
- [x] 3.5 Tests in `backend/tests/maintenance/test_api_approvals.py`: 200 for `TENANT_OWNER` and
      `PROPERTY_MANAGER`, 403 for `TECHNICIAN`/`CLEANER` (R1.4 — the measured false reuse of
      `READ_INCIDENTS` must NOT grant this), default-to-`PENDING`, `status` filter round-trips,
      response shape carries `incident`/`property` blocks and no raw UUID-only row, tenant
      isolation (another tenant's approvals never appear). Also extend
      `backend/tests/maintenance/test_free_text_sink_contract.py` (or add a case) asserting
      `response_notes` now rejects `U+0000`/a lone surrogate with `422` instead of `500` (D12), and
      add the new `GET /api/v1/owner-approvals` route to the matrix in
      `backend/tests/test_route_authorization.py`, asserting it is guarded by
      `READ_OWNER_APPROVALS`. [R1.1, R1.4, R1.5, D12]
- [x] 3.6 Regenerate the contract: `make openapi` (commits `backend/openapi.json`), then from the
      worktree run the four-command workaround in `sdd/project.md` §Worktree bootstrap before
      `cd frontend && npm run api:generate` (commits `frontend/lib/api/generated/openapi.d.ts`).
      Both files change together in this section's commit. [steering/documentation.md]

## 4. Backend notifications — the technician learns the answer (R4) <!-- panel: PASS 2026-09-05 -->

- [x] 4.1 Add `OWNER_APPROVAL_APPROVED` and `OWNER_APPROVAL_REJECTED` to `NotificationType` in
      `backend/app/notifications/domain/enums.py`, as enum members (not bare string constants) so
      the AST census in `backend/tests/notifications/test_writer_census.py` can see them (D6).
      Re-measure and rewrite the docstring's member count where it is stale (D14): this enum's own
      docstring says "sixteen" describing PRD §14's list, which stays true and is not touched;
      leave it as is. [R4.2]
- [x] 4.2 Add `owner_approval_approved_notification` and `owner_approval_rejected_notification` to
      `backend/app/maintenance/domain/notifications.py`, calqued on
      `incident_critical_notification`/`incident_high_notification`: subject/body a constant plus
      `incident_id`, `property_id`, `approval_id`; no `sla_deadline_at` and no `escalation_for`
      rule (nobody is late for reading an outcome); `related_type=RELATED_TYPE_INCIDENT`,
      `related_id=incident_id` (D6). [R4.1, R4.2, R4.4]
- [x] 4.3 In `RespondOwnerApprovalUseCase` (`backend/app/maintenance/application/use_cases.py`):
      add constructor collaborators `users: UserRepository`, `notifications:
      NotificationLogRepository`, `configs: TenantConfigRepository`; after `incident.save`/audit/
      timeline and before `self._uow.commit()`, resolve `incident.assigned_technician_id` via
      `users.get(tenant_id, …)` and, when it resolves, call `dispatch_and_persist(...)` with the
      builder matching `approved_cost is not None` vs. `None` (approved vs. rejected). A missing or
      unresolved assignee writes nothing and raises nothing, logged under
      `maintenance.owner_approval_answer_without_recipient` (mirroring `_notify_owner`'s pattern
      for the same anomaly) (D7). [R4.1, R4.3, R4.5]
- [x] 4.4 Wire the three new collaborators into `get_respond_owner_approval_use_case` in
      `backend/app/maintenance/api/dependencies.py` (`SqlAlchemyUserRepository`,
      `SqlAlchemyNotificationLogRepository`, `SqlAlchemyTenantConfigRepository`, alongside the
      existing `approvals=` and `**_flow_kwargs(session)`). [R4]
- [x] 4.5 Add both new members to `WITH_WRITER` in
      `backend/tests/notifications/test_writer_census.py` (currently fifteen members — re-measure
      and rewrite the count comment to seventeen, never increment by habit). [R4.2, D14]
- [x] 4.6 Tests in `backend/tests/maintenance/test_notifications.py` and
      `backend/tests/maintenance/test_use_cases.py` (or a focused new test module for
      `RespondOwnerApprovalUseCase`): an approval writes `OWNER_APPROVAL_APPROVED` to the assigned
      technician; a rejection writes `OWNER_APPROVAL_REJECTED`; an incident with no assigned
      technician writes nothing and does not fail the response; the notification carries no
      `reason`/`response_notes` (closed form); the write happens inside the same commit as the
      answer (no window — assert via the existing transaction/mocking pattern
      `TriageIncidentUseCase`'s tests already use for `_notify_severity`). [R4.1, R4.3, R4.4, R4.5]

## 5. Frontend notifications — the bell leads to `/approvals` and to the technician's incident (R5) <!-- panel: PASS 2026-09-05 -->

- [x] 5.1 In `frontend/features/notifications/lib/notification-destinations.ts`: add
      `NOTIFICATION_TYPE_DESTINATIONS: Record<ShellProfile, Partial<Record<string, () => string>>>`
      with `workspace: { OWNER_APPROVAL_REQUIRED: () => "/approvals" }`; change `notificationHref`
      to take the notification type as a new first-class first argument and consult this table
      **before** the `related_type` one, keeping the `Object.hasOwn` prototype guard and the
      `startsWith("/")` check on both tables (D8). Fill the previously-empty `technician` row with
      `{ incident: (id) => \`/tech/incidents/${id}\` }` and delete the now-false comment ("until
      `tech-app` delivers `/tech/incidents/[id]`") (R5.2). Leave `cleaner` empty (R5.4). [R5.1,
      R5.2, R5.3, R5.4]
- [x] 5.2 Update the one call site, `frontend/features/notifications/components/notification-row.tsx`,
      to pass `notification.type` into `notificationHref` as the new first argument. [R5.1, R5.2]
- [x] 5.3 Update `frontend/features/notifications/lib/notification-destinations.test.ts` and
      `frontend/features/notifications/components/notification-row.test.tsx`: `OWNER_APPROVAL_REQUIRED`
      in the `workspace` profile resolves to `/approvals`; `incident` in the `technician` profile
      resolves to `/tech/incidents/{id}`; a type/`related_type` with either half missing still
      yields `null` and never the raw UUID; `cleaner` stays empty. [R5.1, R5.2, R5.3, R5.4]

## 6. Frontend approvals data layer <!-- panel: PASS 2026-09-05 -->

- [x] 6.1 Add `RESPOND_OWNER_APPROVALS` to `Permission` in `frontend/lib/auth/permissions.ts`,
      granted only to `TENANT_OWNER` in `ROLE_UI_PERMISSIONS` (D10). Update
      `frontend/lib/auth/permissions.test.tsx` accordingly. [R3.2]
- [x] 6.2 Create `frontend/features/approvals/data/dto.ts`: `OwnerApprovalListItemDto` (camelCase
      mirror of `OwnerApprovalListItemResponse`: `id`, `relatedType`, `status`, `amount`,
      `currency`, `requestedAt`, `respondedAt`, `incident: {id, title, category, severity} | null`,
      `property: {id, name, internalCode}`), `OwnerApprovalPage` (`items`, `total`, `page`,
      `perPage`), `OwnerApprovalFilters` (`status?`, `page?`, `perPage?`), and
      `RespondOwnerApprovalInput` (`approvalId`, `status`, `responseNotes?`) — same enumerated-field
      style as `frontend/features/incidents/data/dto.ts`. [R1.3, R2.1]
- [x] 6.3 Create `frontend/features/approvals/data/http/http-approvals-source.ts`
      (`HttpApprovalsSource`): `listApprovals(tenantId, filters)` → `GET /api/v1/owner-approvals`
      mapping snake_case → camelCase (only emit query keys the contract admits, `undefined` filters
      omitted, mirroring `HttpIncidentsSource.listIncidents`); `respond(tenantId, input)` → `POST
      /api/v1/owner-approvals/{id}/respond` with `{ status, response_notes }`. [R1.1, R1.2, R3.3]
- [x] 6.4 Create `frontend/features/approvals/data/index.ts` as the composition point
      (`getApprovalsDataSource()`), same shape as `frontend/features/incidents/data/index.ts`.
- [x] 6.5 Create `frontend/features/approvals/hooks/query-keys.ts` (`approvalsKeys`: `list`,
      `listPrefix`, tenant-scoped via `tenantScopedKey`, mirroring `incidentsKeys`).
- [x] 6.6 Create `frontend/features/approvals/hooks/use-approvals.ts`: `useApprovals()` — one
      `useQuery` with no status filter (the pending queue) — and `useApprovalsHistory()` — a
      `useQueries` over `[{status: "APPROVED", perPage: 5}, {status: "REJECTED", perPage: 5}]`
      merged and re-sorted by `respondedAt` descending, sliced to five, mirroring the
      `useIncidentContexts`/`useIncidentsPages` `useQueries` pattern (D9, D5's single-valued
      `status` filter is why history needs two requests). [R2.1, R2.3]
- [x] 6.7 Create `frontend/features/approvals/hooks/use-respond-approval.ts`
      (`useRespondOwnerApproval`): posts via the data source and invalidates
      `approvalsKeys.listPrefix(tenantId)` on success so the queue and history both refresh (R3.3).
- [x] 6.8 Create `frontend/features/approvals/lib/error-mapping.ts`, mirroring
      `features/incidents/lib/error-mapping.ts`'s discriminated union, with one addition: a `409`
      (`OwnerApprovalAlreadyAnsweredError`) maps to a distinct `"already-answered"` kind so the
      component can show the translated "ya respondida" message and trigger the same invalidation
      as a success (R3.4). [R3.4]
- [x] 6.9 Tests: `frontend/features/approvals/data/http/http-approvals-source.test.ts`,
      `frontend/features/approvals/hooks/query-keys.test.ts`,
      `frontend/features/approvals/hooks/use-approvals.test.tsx` (queue + history merge/sort/slice
      logic), `frontend/features/approvals/hooks/use-respond-approval.test.tsx` (invalidation),
      `frontend/features/approvals/lib/error-mapping.test.ts` (all five kinds, including 409).
      [R1.1, R1.2, R2.1, R2.3, R3.3, R3.4]

## 7. Frontend approvals screen, route, i18n, and the property-detail link <!-- panel: PASS 2026-09-05 -->

- [x] 7.1 Add the `approvals` namespace to both locales
      (`frontend/locales/{es,en}/approvals.json`) and register it in
      `frontend/lib/i18n/resources.ts`/`NAMESPACES` (same steps `incidents` or `notifications` took):
      queue/history labels, column headers, empty state, the reject warning ("cancela la
      incidencia y no es reversible"), the `OTHER`-row note, relative "waiting since" strings. Add
      the two new notification copy keys to
      `frontend/locales/{es,en}/notifications.json`. [R2.5]
- [x] 7.2 Add `OWNER_APPROVAL_APPROVED`/`OWNER_APPROVAL_REJECTED` entries to
      `NOTIFICATION_COPY_KEYS` in `frontend/features/notifications/lib/notification-copy.ts` and to
      `NotificationType`'s consumer in `frontend/features/notifications/data/dto.ts`'s stale count
      comment (D14: both currently say "seventeen", already wrong; re-measure against the
      regenerated contract from section 3 and write the counted figure — do not increment). [R4.2,
      D14]
- [x] 7.3 Create `frontend/features/approvals/components/approvals-view.tsx`: the queue (no status
      filter) and a short history (last five answered), reusing `states:` loading/empty/error
      shapes and the retry button exactly as `incidents-view.tsx` does (R2.4); empty queue renders
      `states:empty.*` (R2.2); no raw UUID ever painted — property name + internal code, incident
      category/severity/title (translated), amount + currency, relative "waiting since" from
      `requestedAt` (R2.6). Approve/reject controls render only behind
      `useHasPermission("RESPOND_OWNER_APPROVALS")` (R3.2); an `OTHER` row never gets the controls,
      only the translated note (D11); the reject control shows the cancellation warning next to
      the button, not only in a confirmation dialog (R3.5); an optional `responseNotes` field is
      sent verbatim (R3.1, R3.6); a `409` from `useRespondOwnerApproval` shows the translated "ya
      respondida" message and refetches instead of leaving a stale row (R3.4). [R2, R3]
- [x] 7.4 Mount the view: replace the `RoutePlaceholder` in
      `frontend/app/(workspace)/approvals/page.tsx` with `<ApprovalsView />`. Add
      `"(workspace)/approvals/page.tsx": "approvals"` to `REAL_PAGE_ROUTE_IDS` in
      `frontend/app/route-coverage.test.ts`. [R2.1]
- [x] 7.5 In `frontend/features/dashboard/components/detail/property-detail-sections.tsx`, add a
      `Link` to `/approvals` under the `detail.approvals` `Section` (D13) — the constant path only,
      no id in the href, `OwnerApprovalSummary`/`ApprovalBlock`/`PendingApprovalResponse` untouched.
      Add/extend the section's test to assert the link renders and points at `/approvals`. [D13]
- [x] 7.6 Tests: `frontend/features/approvals/components/approvals-view.test.tsx` covering loading,
      empty, error+retry, a mixed queue (`INCIDENT`/`MAINTENANCE_COST`/`OTHER` rows), the manager
      seeing no buttons, the owner approving/rejecting, the reject warning text, the 409 recovery,
      and that no UUID is ever rendered as visible text. Extend
      `frontend/lib/i18n/catalog-parity.test.ts` coverage implicitly by having both locale files
      complete (the test itself needs no new cases, only both JSON files to be in parity). [R2, R3,
      R2.5]

## 8. Verification

- [x] 8.1 Full backend suite passes: `docker compose exec backend uv run pytest`.
- [x] 8.2 Backend static tooling: from `backend`, `uv sync --frozen` then `uv run pyright .` — no
      new findings.
- [x] 8.3 Rule-11 ownership guard (host, no Docker, stack down):
      `make check-rule11-ownership` — confirms `response_notes` stays outside `AUTHORABLE_FIELDS`
      and no new sink was added.
- [x] 8.4 Frontend: `cd frontend && npm test`, `npm run typecheck`, `npm run lint`.
- [x] 8.5 Contract in sync: `git status` shows `backend/openapi.json` and
      `frontend/lib/api/generated/openapi.d.ts` committed together (from section 3.6); re-run
      `npm run api:check` if the worktree workaround was used, to confirm no drift.
- [ ] 8.6 Manual end-to-end pass (needs an **assigned** incident — start from `make bootstrap` /
      `seed_demo` or the CLI, per the proposal's `ASSUMPTION`; the UI has no assign action yet):
      resolve an incident with a final cost above the tenant's threshold → it appears in
      `/approvals` → the owner approves (or rejects) with a note → the technician sees the
      incident unblocked (or cancelled) in `/tech` and the bell notification leads to
      `/tech/incidents/{id}`; the owner's own bell notification for a *new* approval leads to
      `/approvals`; the property detail's approvals block link opens `/approvals`.
      **Partially done, left unchecked — see notes below for exactly what's verified vs. still
      pending, and how to finish it.**

## Implementation Notes

### Section 1 (backend RBAC)

- New permission: `Permission.READ_OWNER_APPROVALS = "READ_OWNER_APPROVALS"`, added right after
  `RESPOND_OWNER_APPROVALS` in the `Permission` enum in `backend/app/auth/domain/policy.py`
  (around line 73-74).
- New bundle: `_OWNER_APPROVAL_READ = frozenset({Permission.READ_OWNER_APPROVALS})`, defined
  right after `_OWNER_APPROVAL_RESPOND` (around line 253-258).
- Granted via `| _OWNER_APPROVAL_READ` in both `ROLE_PERMISSIONS[UserRole.TENANT_OWNER]`
  (placed right after `| _OWNER_APPROVAL_RESPOND`) and `ROLE_PERMISSIONS[UserRole.PROPERTY_MANAGER]`
  (placed right after `| _INCIDENT_EXECUTE`, before the `_CONVERSATION_MANAGE` comment). Only
  those two roles hold it — verified by
  `test_read_owner_approvals_is_the_owner_and_the_managers_alone` in
  `backend/tests/auth/test_policy.py`.
- Rewrote the "deliberately no `READ_OWNER_APPROVALS`" comment block above `READ_INCIDENTS` in
  `policy.py` and the module docstring of `backend/app/maintenance/api/approvals_router.py`
  (which said "One route... deliberately no listing"). The router docstring now says the listing
  route (`GET ""`) lands in this same module in a later section of `approvals-web`, backing the
  new permission — do not re-introduce an "absence" framing there.
- `backend/tests/auth/test_policy.py`: added `Permission.READ_OWNER_APPROVALS` to
  `INCIDENT_PERMISSIONS` and to `EXPECTED_INCIDENT_PERMISSIONS[TENANT_OWNER]` and
  `[PROPERTY_MANAGER]`; added an assertion in `test_the_technician_may_execute_but_never_manage`
  and a new test `test_read_owner_approvals_is_the_owner_and_the_managers_alone`. The existing
  `test_the_cleaner_gets_nothing_from_the_incident_flow` and
  `test_the_super_admin_gets_nothing_from_the_incident_flow` automatically cover the new
  permission because they iterate `INCIDENT_PERMISSIONS`.
- Verified: `docker compose exec backend uv run pytest tests/auth/test_policy.py -q` → 72 passed;
  `tests/test_route_authorization.py -q` → 21 passed (no references to
  `READ_OWNER_APPROVALS`/`RESPOND_OWNER_APPROVALS` there yet — section 3.5 adds the new route's
  row to that matrix); full `tests/auth/` → 879 passed. Note: from inside the container, pytest
  paths are relative to `backend/` (i.e. `tests/...`, not `backend/tests/...`).
- Nothing else touched: no route added, no `read_models.py`/`use_cases.py` changes — those are
  sections 2-3.

### Section 2 (backend read model)

- **Dataclass shapes** — `backend/app/maintenance/domain/read_models.py`: added
  `OWNER_APPROVAL_CURRENCY = "EUR"` (module constant, docstring cites
  `owner_approval_threshold_eur`), `OwnerApprovalIncidentRef(id, title, category, severity)`,
  `OwnerApprovalPropertyRef(id, name, internal_code)`, `OwnerApprovalListItem(id, related_type,
  status, amount, currency, requested_at, responded_at, incident: OwnerApprovalIncidentRef |
  None, property: OwnerApprovalPropertyRef)`, `OwnerApprovalPage(items, total)` — exactly the
  shapes tasks.md 2.1 specifies, no pydantic/SQLAlchemy imports (verified by
  `tests/test_layering.py`).
- **THE DOMAIN/READER/USE-CASE SPLIT — read this before writing `ListOwnerApprovalsUseCase`
  (section 3.1).** `design.md` D4 is explicit that "the reader must NOT itself resolve
  property names" and that the use case does that via one `PropertyRepository.list_for_ids`
  call, and design.md's own per-file table (line ~321) assigns the infra reader only "the
  outer join and the two orderings (D4, D5)" — no property/drop/log responsibility. This
  contradicts a literal reading of tasks.md 2.3's prose ("log
  `maintenance.owner_approval_property_unresolved` … for a row whose property does not
  resolve inside the tenant, dropping it from the page"), which reads as if the *reader* does
  the drop+log. **Followed design.md as authoritative** (it is the more specific, more
  detailed source and its per-file table settles it unambiguously): the reader in
  `infrastructure/repositories.py` — `SqlAlchemyOwnerApprovalReader.list_for_tenant` — does
  ONLY a `LEFT OUTER JOIN owner_approvals→incidents` (gated `related_type != OTHER`) plus the
  two D5 orderings and pagination. **It never queries `properties` at all.** Every returned
  `OwnerApprovalListItem.property` is a **placeholder**:
  `OwnerApprovalPropertyRef(id=<approval.property_id>, name="", internal_code="")`. `total` is
  the reader's own `COUNT(*)` over `owner_approvals` matching the status filter — it is not
  reduced by any later drop.
  **Section 3's `ListOwnerApprovalsUseCase` still has to**: call `properties.list_for_ids(tenant_id,
  {item.property.id for item in page.items})`, build the map, then for each item either
  `dataclasses.replace(item, property=OwnerApprovalPropertyRef(id=prop.id, name=prop.name,
  internal_code=prop.internal_code))` when the id resolves, or **drop the item from the final
  list** when it does not — logging `maintenance.owner_approval_property_unresolved` (same
  `extra={tenant_id, ...}` shape as `GetIncidentContextUseCase`'s
  `maintenance.incident_context_property_unresolved`) for the dropped row. This mirrors
  `ListReservationsUseCase` (`backend/app/reservations/application/use_cases.py:418-476`,
  cited by design.md as `reservation-property-identity` D2) for the "batch-resolve after the
  page query" mechanics, except reservations *degrade* (keep the row, blank the name) where
  this flow *drops* (design D4's explicit choice) — do not copy the degrade behaviour.
  Because of this, `page.total` returned by section 3's use case to the API **can be larger
  than the number of items actually returned** on the rare row with a crossed property
  pointer; this is accepted (design D4 calls it "a crossed pointer, not a normal state") and
  not something section 3 needs to reconcile — do not "fix" `total` by counting post-drop.
- **Task 2.4 test-suite scope note**: no "property outside the tenant is dropped and logged"
  test was written against the reader (`test_repositories.py`), because the reader never
  touches `properties` and cannot exhibit that behaviour — see the split above. That test
  belongs to section 3 (`ListOwnerApprovalsUseCase`'s own test module), against
  `PropertyRepository.list_for_ids`, not against `SqlAlchemyOwnerApprovalReader`.
- **Ordering implementation**: `status = filters.status or PENDING`; `PENDING` →
  `requested_at ASC, id ASC`; any other status (`APPROVED`/`REJECTED`/`EXPIRED`) →
  `responded_at DESC, id DESC`. `EXPIRED` is out of scope for the rest of this change but the
  reader accepts it as a filter value without special-casing (it is a normal enum member of
  `OwnerApprovalStatus`).
- **Join mechanics**: `OwnerApprovalModel` LEFT OUTER JOIN `IncidentModel` on
  `IncidentModel.id == OwnerApprovalModel.related_id AND OwnerApprovalModel.related_type !=
  OwnerApprovalRelatedType.OTHER` (the `ON` clause, not a `WHERE`, so it stays a LEFT join and
  `OTHER` rows still come back with `incident=None`, not filtered out).
- **Tests added** (`backend/tests/maintenance/test_repositories.py`, extended the existing
  `_approval` fixture with optional `responded_at`/`related_type`/`related_id`/`amount`
  kwargs, all backward compatible): default-PENDING-oldest-first,
  answered-status-newest-first (with a PENDING row proven absent from that page),
  incident-join populates all four `OwnerApprovalIncidentRef` fields plus the property
  placeholder and `currency == "EUR"`, an `OTHER` row never picks up a same-id incident,
  pagination across 3 pages sums to `total`, cross-tenant isolation, non-positive
  page/per_page raises `MaintenanceValidationError`.
- **Verified**: `docker compose exec backend uv run pytest tests/maintenance/test_repositories.py -q`
  → 79 passed (72 pre-existing + 7 new). `tests/test_layering.py -q` → 1405 passed. Full
  `tests/maintenance/` sweep also run as a final sanity check (see below for result).
- Nothing else touched: no `use_cases.py`, `api/schemas.py`, or `api/approvals_router.py`
  changes — those are section 3's job.

### Section 3 (backend list endpoint)

- **`ListOwnerApprovalsUseCase`** (`backend/app/maintenance/application/use_cases.py`):
  constructor `__init__(self, *, approvals: OwnerApprovalReader, properties:
  PropertyRepository)`; `async def execute(self, *, tenant_id, filters: OwnerApprovalFilters,
  page: int, per_page: int) -> OwnerApprovalPage`. Implements exactly the split section 2's
  notes hand off: calls `list_for_tenant`, batch-resolves `properties.list_for_ids`, replaces
  each item's placeholder `property` via `dataclasses.replace`, drops unresolved rows logging
  `maintenance.owner_approval_property_unresolved`, and passes `total` through **unadjusted**.
- **Wiring** (`backend/app/maintenance/api/dependencies.py`):
  `get_list_owner_approvals_use_case(session) -> ListOwnerApprovalsUseCase` composes
  `SqlAlchemyOwnerApprovalReader(session)` + `SqlAlchemyPropertyRepository(session)`, no `uow`,
  no `audit` — same shape as `get_incident_context_use_case`.
- **Schemas** (`backend/app/maintenance/api/schemas.py`): `OwnerApprovalIncidentRefResponse`,
  `OwnerApprovalPropertyRefResponse`, `OwnerApprovalListItemResponse` (wire fields:
  `id, related_type, status, amount, currency, requested_at, responded_at, incident, property`
  — all snake_case, `incident`/`property` are nested objects, `incident` nullable),
  `OwnerApprovalPageResponse` (`items, total, page, per_page`), both with `from_domain`
  classmethods mirroring `IncidentPageResponse`. `MAX_RESPONSE_NOTES = 2000` (module constant
  near the other length constants); `RespondOwnerApprovalRequest.response_notes` is now
  `Annotated[MultiLineText, Field(max_length=MAX_RESPONSE_NOTES)] | None = None`.
- **Router** (`backend/app/maintenance/api/approvals_router.py`): `GET ""` — `page`
  (`ge=1, le=MAX_PAGE`), `per_page` (`ge=1, le=MAX_PER_PAGE`), `status` (query alias, optional
  `OwnerApprovalStatus`), guarded by `Depends(require(Permission.READ_OWNER_APPROVALS))`,
  tenant taken only from `authenticated.context.tenant_id`. Module docstring rewritten again to
  describe both routes now that the list one is real (no more "lands later" framing).
- **Tests**: `backend/tests/maintenance/test_api_approvals.py` grew from the section-3.5-era
  respond-only file to also cover the list route (owner/manager 200, technician/cleaner 403,
  default-PENDING-oldest-first, status filter round-trip, response shape has
  incident/property blocks with no raw UUID row, cross-tenant isolation).
  `test_free_text_sink_contract.py` gained the `response_notes` D12 cases (schema-level
  type/length/guard assertion, plus an HTTP-level `U+0000` → `422` case and a lone-surrogate
  case) — explicitly documented as *not* a fifth rule-11 sink column, just the existing
  excepción-3 field getting the same guard other sinks already have.
  `test_route_authorization.py` and `test_api_authorization.py` both got `GET
  /api/v1/owner-approvals` added to their route census, with the "recounted, not incremented"
  comment style D14 requires (nineteen authenticated routes on `maintenance`, measured against
  the app's route table, not incremented from the old "seventeen").
- **Contract regen (task 3.6)**: `make openapi` + the four-command worktree workaround both
  ran; `backend/openapi.json` (+262 lines) and `frontend/lib/api/generated/openapi.d.ts`
  (+139 lines) are both in the working tree, both touching `/api/v1/owner-approvals` and the
  new `OwnerApprovalListItemResponse`/`OwnerApprovalPageResponse` schemas.
- **Verified** (re-run after resuming from a mid-section interruption, since the report from
  the agent that wrote this code was lost to a rate limit before it could confirm): `docker
  compose exec backend uv run pytest tests/maintenance/test_api_approvals.py
  tests/maintenance/test_free_text_sink_contract.py tests/test_route_authorization.py
  tests/maintenance/test_api_authorization.py -q` → 72 passed. Broader sweep `tests/test_layering.py
  tests/maintenance tests/auth tests/test_route_authorization.py -q` → 3158 passed.
- Nothing else touched: no notification collaborators added to `RespondOwnerApprovalUseCase`
  (that's section 4), no frontend files (sections 5-7).

### Fix round 1 (post-panel, after sections 1-3)

The review panel run against sections 1-3 combined (`sdd-architect` PASS, `sdd-review-i18n`
PASS — deferred, no UI yet — `sdd-security` FAIL, `sdd-review-tenancy` FAIL, `sdd-qa` FAIL)
surfaced two real findings, both fixed here:

- **Security + tenancy (independently converged on the same finding)**: the `LEFT OUTER JOIN`
  in `SqlAlchemyOwnerApprovalReader.list_for_tenant`
  (`backend/app/maintenance/infrastructure/repositories.py`) constrained only
  `IncidentModel.id == OwnerApprovalModel.related_id` (plus `related_type != OTHER`) and never
  `IncidentModel.tenant_id == tenant_id`. `owner_approvals.related_id` deliberately carries no
  `ForeignKey` (polymorphic pointer), so a crossed pointer to another tenant's incident would
  have surfaced that incident's `title`/`category`/`severity` in the page, relying only on
  `app/core/db.py`'s `with_loader_criteria` net (documented everywhere else as defence in
  depth, never the mechanism). **Fixed**: added `IncidentModel.tenant_id == tenant_id` to the
  join's `and_(...)` conditions, matching the established pattern in `access`/`cleaning`'s
  equivalent joins. **Regression test**: `test_list_for_tenant_join_does_not_leak_another_tenants_incident`
  in `test_repositories.py` — seeds an approval whose `related_id` is deliberately set to an
  incident belonging to a different tenant (an adversarial state the app doesn't produce
  today, constructed directly against the models) and asserts the row comes back with
  `incident=None` rather than the other tenant's data, on an unmarked session so the loader
  net can't mask a missing explicit filter.
- **QA**: `ListOwnerApprovalsUseCase`'s D4 behavior (drop a row whose property doesn't resolve
  inside the tenant, log `maintenance.owner_approval_property_unresolved`, leave `total`
  unadjusted) had zero test coverage — the reader's own tests correctly can't exercise it
  (the reader never touches `properties`), and section 3 never wrote the use-case-level test
  that gap implied. **Fixed**: added
  `test_list_owner_approvals_drops_a_row_whose_property_does_not_resolve` to
  `test_use_cases.py` — seeds an approval whose `property_id` belongs to another tenant,
  asserts the page comes back with zero items, `total == 1` (unadjusted), and the warning log
  fires.
- **Verified**: `docker compose exec backend uv run pytest tests/maintenance/test_repositories.py
  tests/maintenance/test_api_approvals.py tests/maintenance/test_use_cases.py -q` → 197 passed.
  Broader sweep `tests/test_layering.py tests/maintenance tests/auth tests/test_route_authorization.py -q`
  run to confirm nothing else regressed.
- Nothing else touched: no `domain/` changes (the fix is entirely in `infrastructure/` plus
  tests), no task checkboxes altered — this is a fix within already-checked sections 2/3.

### Section 4 (backend notifications — R4)

- **New `NotificationType` members** (`backend/app/notifications/domain/enums.py`): exactly
  `OWNER_APPROVAL_APPROVED = "OWNER_APPROVAL_APPROVED"` and
  `OWNER_APPROVAL_REJECTED = "OWNER_APPROVAL_REJECTED"`, added after `INCIDENT_MESSAGE` with a
  comment citing design D6. The module docstring's "sixteen" (about PRD §14's own list) was
  left untouched exactly as task 4.1 says.
- **D14 gotcha, measured rather than trusted**: task 4.1/4.5's prose said `WITH_WRITER` "currently
  has fifteen members" and should become "seventeen". Measured by AST-parsing the actual
  `WITH_WRITER` set (not by eyeballing), it was **sixteen** before this section (the prose was
  already stale) and is **eighteen** after — not seventeen. `test_writer_census.py`'s comment
  now says "Eighteen" and explains the correction. Total `NotificationType` members: 20 → 22
  (`WITH_WRITER` 18 + `WITHOUT_WRITER` 4, unchanged).
- **New builders** (`backend/app/maintenance/domain/notifications.py`), calqued on
  `incident_critical_notification`/`incident_high_notification`:
  `owner_approval_approved_notification(*, tenant_id, incident_id, property_id, approval_id,
  technician_id, recipient_contact="", now, channel=IN_APP, contact=None) -> NotificationLog`
  and `owner_approval_rejected_notification(...)` — identical signature. Both set
  `recipient_user_id=technician_id`, `related_type=RELATED_TYPE_INCIDENT`,
  `related_id=incident_id`, no `sla_deadline_at` field at all (not even `None` passed
  conditionally — the field is simply absent from the constructor call, same as their
  `incident_critical_notification` model). Body is a constant sentence plus the three UUIDs,
  never `reason`/`response_notes`.
- **`RespondOwnerApprovalUseCase`** (`backend/app/maintenance/application/use_cases.py`) new
  constructor: `__init__(self, *, approvals: OwnerApprovalRepository, users: UserRepository,
  notifications: NotificationLogRepository, configs: TenantConfigRepository, **kwargs)`. New
  private method `_notify_answer(*, tenant_id, incident, approval, approved_cost, now)`,
  called from `execute` right after the existing `_record_timeline` call (and after the
  rejection-only `_fire_trigger(INCIDENT_RESOLVED)` block), still before `self._uow.commit()`.
  Resolves the recipient via `self._users.get(tenant_id, incident.assigned_technician_id)` —
  `None` `assigned_technician_id` short-circuits before even calling `.get`. A `None` result
  either way logs `maintenance.owner_approval_answer_without_recipient` with
  `extra={"tenant_id": str(tenant_id), "owner_approval_id": str(approval.id)}` (same two keys
  `_notify_owner` logs) and returns — no exception. Builder/type selection is
  `approved_cost is not None` → `OWNER_APPROVAL_APPROVED` / `owner_approval_approved_notification`,
  else `OWNER_APPROVAL_REJECTED` / `owner_approval_rejected_notification`, dispatched via the
  same `dispatch_and_persist(...)` helper every other writer in this module uses (so channel
  fan-out still goes through `notification-channel-routing`, per design D7's closing point).
- **Wiring** (`backend/app/maintenance/api/dependencies.py`):
  `get_respond_owner_approval_use_case` now passes `approvals=SqlAlchemyOwnerApprovalRepository(session)`,
  `users=SqlAlchemyUserRepository(session)`,
  `notifications=SqlAlchemyNotificationLogRepository(session)`,
  `configs=SqlAlchemyTenantConfigRepository(session)`, `**_flow_kwargs(session)` — kept as four
  explicit kwargs (matching tasks.md's literal wording) rather than switching to the existing
  `_gate_kwargs(session)` helper, even though `_gate_kwargs` already returns the same four keys.
- **Not in tasks.md, but required to keep the suite green**: `tests/maintenance/conftest.py`'s
  `Flow.__init__` constructs `self.respond = RespondOwnerApprovalUseCase(...)` directly (not
  through `dependencies.py`) and had to gain the same three new kwargs, or every existing
  `flow.respond.execute(...)` call across `test_use_cases.py` would fail with a
  `TypeError` on the changed constructor. Also `tests/notifications/test_escalation.py`'s
  `DECLARED_DIVERGENCES` tuple is a **snapshot** of every `NotificationType` member beyond
  PRD §14's sixteen (`test_the_enum_is_the_sixteen_types_of_prd_14_plus_its_declared_divergences`
  asserts exact tuple equality against the live enum) — it needed
  `OWNER_APPROVAL_APPROVED`/`OWNER_APPROVAL_REJECTED` appended in enum declaration order or that
  test fails. Neither file is named in tasks 4.1-4.6, but both are load-bearing for the suite.
- **Tests added**:
  - `backend/tests/maintenance/test_notifications.py` (pure domain, no DB): parametrized over
    both builders — no `sla_deadline_at`, `related_type`/`related_id` point at the incident, no
    `reason`/`response_notes` leak (driven with recognisable strings in neither builder's
    inputs, same style `test_neither_notification_carries_incident_free_text` already uses) —
    plus one test that the two builders write distinguishable `notification_type`/`subject`.
  - `backend/tests/maintenance/test_use_cases.py` (integration over the real DB, the house
    pattern this module's `conftest.py` documents — fakes were **not** used, per that file's own
    documented departure from `steering/backend-architecture.md`, already established before
    this section): `test_approving_notifies_the_assigned_technician`,
    `test_rejecting_notifies_the_assigned_technician`,
    `test_an_incident_with_no_assigned_technician_writes_no_notification` (asserts the response
    itself still succeeds), `test_the_answer_notification_carries_no_reason_or_response_notes`,
    and `test_the_answer_notification_reaches_the_same_commit_as_the_response` — the last one
    mirrors `test_the_alert_and_the_verdict_reach_the_same_commit`'s `_WatchesTheCommit` wrapper
    around `flow.respond._uow`, asserting the notification row is already visible in the
    session at the moment `commit()` is called. All five use the `MAINTENANCE_COST` gate path
    (`_in_progress` + `flow.resolve.execute(final_cost=500.00)`) to get an
    **assigned-technician** incident into `AWAITING_OWNER_APPROVAL`, except the
    no-recipient test, which uses the `INCIDENT`/estimated-cost gate
    (`flow.triage.execute(estimated_cost=450.00)` on an unassigned `CLASSIFIED` incident) since
    that path never assigns anyone.
- **Verified**: `docker compose exec backend uv run pytest tests/maintenance/test_use_cases.py
  tests/maintenance/test_notifications.py tests/notifications tests/maintenance/test_api_approvals.py -q`
  → 396 passed. Broader sweep `tests/notifications tests/maintenance -q` → 1109 passed.
  `tests/test_layering.py -q` → 1405 passed (untouched, run as a sanity check since
  `domain/notifications.py` and `application/use_cases.py` both changed). `uv run pyright`
  against the four touched files surfaced one pre-existing error at
  `use_cases.py:3044` (`_notify_technician`, unrelated `staff-messaging` code, confirmed via
  `git diff` to be outside this section's changes) — not introduced here, left for section 8.2
  to track as the full-project baseline (`uv run pyright .` was not run project-wide; only the
  four files this section touched).
- Nothing else touched: no route/schema changes, no frontend files (sections 5-7), no
  `AuditLog` behavior changed (still the pre-existing two `_audit.record` calls, untouched).
- **Review panel (architect/security/qa/tenancy) — all PASS, no findings.** Two reviewers
  (security and qa) independently surfaced the same non-blocking observation, not raised as a
  finding because no R#/steering rule covers it: `_notify_answer` resolves the recipient via
  `UserRepository.get(tenant_id, technician_id)` with no `ACTIVE` filter (unlike `_notify_owner`,
  which uses `UserFilters(status=ACTIVE)`), so a technician deactivated after assignment still
  receives the answer notification. Worth a roadmap candidate for whoever next touches
  notification recipient resolution; not this change's to fix (R1/R3 as written are satisfied by
  current behavior — the technician is still "assigned", just inactive).

### Section 5 (frontend notifications — R5)

- **New `notificationHref` signature**
  (`frontend/features/notifications/lib/notification-destinations.ts`):
  `notificationHref(type: string, profile: ShellProfile, relatedType: string | null, relatedId:
  string | null): string | null` — `type` is the new first-class first argument, ahead of
  `profile` (per design D8's wording "a new first-class first argument"). The single call site,
  `frontend/features/notifications/components/notification-row.tsx`, was updated to
  `notificationHref(notification.type, profile, notification.relatedType,
  notification.relatedId)`. No other call site exists — `frontend/features/notifications/index.ts`
  only re-exports the function, it does not call it.
- **`NOTIFICATION_TYPE_DESTINATIONS` shape**: `Record<ShellProfile, Partial<Record<string, () =>
  string>>>` — builders here take **no `id` argument** (unlike `NOTIFICATION_DESTINATIONS`'s
  `(id: string) => string` builders), because `/approvals` is a queue route, not a per-row detail
  page. Populated: `workspace: { OWNER_APPROVAL_REQUIRED: () => "/approvals" }`. `cleaner`,
  `technician`, `public`, `guest`, `authenticated`, `platform` are all declared and empty, same
  "every shell is a row" convention as the existing table.
- **Lookup order in `notificationHref`**: `NOTIFICATION_TYPE_DESTINATIONS[profile]` is consulted
  first, with the identical `Object.hasOwn` guard + `typeof === "function"` check + `href.startsWith("/")`
  check as the `related_type` table. A hit there returns immediately — it does not check
  `relatedType`/`relatedId` at all (irrelevant for a queue link). Only on a miss does the
  function fall through to the pre-existing `relatedType === null || relatedId === null` guard
  and the `NOTIFICATION_DESTINATIONS` lookup. This means a row could theoretically carry an
  unrelated/malformed `related_type`/`related_id` pair alongside `OWNER_APPROVAL_REQUIRED` and
  still resolve to `/approvals` — that is intended, matching D8's "wins outright" framing.
- **`NOTIFICATION_DESTINATIONS.technician`** now reads `{ incident: (id) =>
  \`/tech/incidents/${id}\` }`; the old "Empty until `tech-app` delivers…" comment is gone. This
  also covers section 4's two new notification types (`OWNER_APPROVAL_APPROVED`/
  `OWNER_APPROVAL_REJECTED`), since both write `related_type = "incident"` — no type-table entry
  was needed for them, they resolve purely through the pre-existing `related_type` path.
  `NOTIFICATION_DESTINATIONS.cleaner` is untouched (still `{}`).
- **Gotcha for the next call site**: if anyone adds a second caller of `notificationHref`, the
  argument order is `(type, profile, relatedType, relatedId)` — easy to transpose `type`/`profile`
  since both are strings-ish; TypeScript will not catch `type` and `profile` being swapped if a
  caller passes a `ShellProfile`-shaped string first, since `NOTIFICATION_TYPE_DESTINATIONS`'
  index type is `string`, not a literal union — only test coverage catches that today.
- **Tests updated**:
  `frontend/features/notifications/lib/notification-destinations.test.ts` — all existing calls
  updated to the new 4-argument signature (using a `NO_TYPE_OVERRIDE` placeholder type string for
  cases that only exercise the `related_type` table), plus a new nested
  `describe("type-keyed destinations …")` block covering: `OWNER_APPROVAL_REQUIRED` → `/approvals`
  in `workspace` (including when `related_type`/`related_id` are present or absent — the type
  table wins either way); no link for that type outside `workspace`; fallthrough to the
  `related_type` table for a type with no override; `technician` + `incident` → `/tech/incidents/{id}`
  for both new section-4 types and a pre-existing one (`TECHNICIAN_ASSIGNED`); the
  prototype-pollution guard repeated against the type table; `cleaner` still empty in both tables.
  `frontend/features/notifications/components/notification-row.test.tsx` — the old "technician
  shell renders without a link" test was rewritten (that behavior no longer holds for `incident`,
  now that `technician` is populated) into two tests: one for a `cleaner`-shell `cleaning_task` row
  (still no link, R5.4) and one for a `technician`-shell `incident` row (now links to
  `/tech/incidents/i1`, R5.2), plus a new test for `OWNER_APPROVAL_REQUIRED` in `workspace`
  linking to `/approvals` with `relatedType`/`relatedId` both `null` (R5.1).
- **Verified**: `docker compose exec frontend npm test -- notification-destinations
  notification-row` → 31 passed (17 + 14), 2 files. `npm run typecheck` → clean. `npm run lint` →
  clean. Full `npm test` was run twice and showed two very different failure sets across
  unrelated files (color-tokens, eslint-boundaries, pricing, cleaning, guest-portal,
  tech-incident-detail-view, etc. — 18 files one run, 4 files including
  `conversations-view.test.tsx` the other) with zero overlap with anything touched in this
  section, consistent with the documented host-contention flakiness rather than a regression from
  this change; a third run with `--maxWorkers=2` was launched to get a stable read. Neither run's
  failures included `notification-destinations.test.ts` or `notification-row.test.tsx`.
- Nothing else touched: no query/store code, no i18n strings (route paths only, not user-visible
  text), no files under `frontend/features/approvals/` or the `/approvals` route (sections 6-7).

### Section 6 (frontend approvals data layer)

- **Permission** (`frontend/lib/auth/permissions.ts`, `permissions.test.tsx`): `Permission` gained
  `"RESPOND_OWNER_APPROVALS"`, granted only in `ROLE_UI_PERMISSIONS.TENANT_OWNER` (alongside the
  existing `"MANAGE_PRICE_RECOMMENDATIONS"`). `PROPERTY_MANAGER`/`CLEANER`/`TECHNICIAN`/
  `SUPER_ADMIN` all get `false` from `useHasPermission("RESPOND_OWNER_APPROVALS")` — section 7's
  queue hides the approve/reject controls behind exactly this check (R3.2).
- **DTOs** (`frontend/features/approvals/data/dto.ts`): `OwnerApprovalStatus` and
  `OwnerApprovalRelatedType` are re-exported aliases of the generated schema enums.
  `OwnerApprovalDecision = "APPROVED" | "REJECTED"` — narrower than `OwnerApprovalStatus` on
  purpose (the entity refuses `PENDING`/`EXPIRED` as an answer) and is the type of
  `RespondOwnerApprovalInput.status`. `OwnerApprovalListItemDto`: `{ id, relatedType, status,
  amount, currency, requestedAt, respondedAt, incident: OwnerApprovalIncidentRefDto | null,
  property: OwnerApprovalPropertyRefDto }`. `OwnerApprovalIncidentRefDto`: `{ id, title, category,
  severity }`. `OwnerApprovalPropertyRefDto`: `{ id, name, internalCode }`. `OwnerApprovalPage`:
  `{ items, total, page, perPage }`. `OwnerApprovalFilters`: `{ status?, page?, perPage? }`.
  `RespondOwnerApprovalInput`: `{ approvalId, status: OwnerApprovalDecision, responseNotes? }`.
- **`HttpApprovalsSource`** (`frontend/features/approvals/data/http/http-approvals-source.ts`):
  `listApprovals(tenantId, filters = {})` → `GET /api/v1/owner-approvals` with query
  `{ status?, page?, per_page? }` (each key omitted when its filter is `undefined`; `status` is
  always single-valued, never an array — D5). `respond(tenantId, input)` → `POST
  /api/v1/owner-approvals/{approval_id}/respond`, body `{ status, response_notes? }` —
  `response_notes` is **omitted entirely** when `input.responseNotes` is `undefined` (never sent as
  `""`), and never trimmed (sent verbatim per R3.1/R3.6, unlike `HttpIncidentsSource.resolve`'s
  `materials` which does trim). **`respond` returns `Promise<void>`** — the backend's 200 body is
  the **incident**, not the approval (`IncidentResponse`), and this source deliberately discards
  it: the caller (section 7's component, via `useRespondOwnerApproval`) refreshes the queue by
  query invalidation, never by reading this response. If section 7 later needs the returned
  incident (e.g. to navigate or show its new status inline) `respond`'s return type will need to
  change to expose it — it is thrown away today, not merely untyped.
- **Composition point** (`frontend/features/approvals/data/index.ts`):
  `getApprovalsDataSource(): HttpApprovalsSource`, singleton wired through
  `createAuthenticatedClients`, identical shape to `features/incidents/data/index.ts`.
- **Query keys** (`frontend/features/approvals/hooks/query-keys.ts`): `approvalsKeys.list(tenantId,
  filters = {})` → `tenantScopedKey(tenantId, "approvals-list", filters)`;
  `approvalsKeys.listPrefix(tenantId)` → `tenantScopedKey(tenantId, "approvals-list")`. No
  `detail`/`context`/`photos` keys — this feature has no per-row detail query yet.
- **Hooks** (`frontend/features/approvals/hooks/use-approvals.ts`):
  - `useApprovals(): UseQueryResult<OwnerApprovalPage>` — **takes no arguments**. Calls
    `getApprovalsDataSource().listApprovals(tenantId)` with **no second argument at all** (not even
    `{}`) — the pending queue is not parameterized. Section 7 must NOT call this with a filters
    object; if a filtered queue is ever needed, add a new hook rather than widening this one's
    signature (the point is "this is always the to-do-list default").
  - `useApprovalsHistory(): ApprovalsHistoryResult` where `ApprovalsHistoryResult = { items:
    OwnerApprovalListItemDto[], isPending, isError, error: Error | null }`. Internally
    `useQueries` over `[{status: "APPROVED", perPage: 5}, {status: "REJECTED", perPage: 5}]`,
    flat-mapped, sorted by `respondedAt` string descending (`localeCompare`, ISO-8601 timestamps
    sort correctly as strings), sliced to 5. `isPending`/`isError` are `true` if **either** branch
    is pending/errored; `error` is the first errored branch's error or `null`.
  - `HISTORY_PER_PAGE = 5` is a private module constant, not exported — section 7 should not need
    it (the hook already enforces the slice).
- **Mutation** (`frontend/features/approvals/hooks/use-respond-approval.ts`):
  `useRespondOwnerApproval(): UseMutationResult<void, Error, RespondOwnerApprovalInput>`.
  `retry: false`. **Invalidates `approvalsKeys.listPrefix(tenantId)` in `onSuccess` only** — a
  failed mutation (including a 409) does **not** trigger this hook's own invalidation. R3.4's "same
  invalidation as a success" on a 409 is therefore section 7's job: the component must call
  `queryClient.invalidateQueries({ queryKey: approvalsKeys.listPrefix(tenantId) })` itself (or a
  second `useRespondOwnerApproval` call / equivalent) when `mapApprovalsError` returns
  `{ kind: "already-answered" }`. This was a deliberate reading of the task split (6.7 says
  "invalidates … on success"; 6.8 says the error-mapping/component layer "triggers the same
  invalidation as a success" for 409) — **not yet wired end-to-end**, since no component exists in
  this section. Section 7 must not assume the 409 case already refetches by itself.
- **Error mapping** (`frontend/features/approvals/lib/error-mapping.ts`): `ApprovalsErrorState<TData>
  = { kind: "loading" } | { kind: "forbidden" } | { kind: "not-found" } | { kind: "validation" } |
  { kind: "already-answered" } | { kind: "error" } | { kind: "ok"; data: TData }`.
  `mapApprovalsError(result)` takes the same `{ isPending, isError, error, data }` shape as
  `mapIncidentsError`, which is structurally satisfied by **both** `UseQueryResult` and
  `UseMutationResult` in TanStack Query v5 — so section 7 can feed either the queue query or the
  `useRespondOwnerApproval` mutation result into it directly. 401→loading, 403→forbidden,
  404→not-found, **409→already-answered**, 422→validation, everything else→error. The function
  never leaks the envelope's `message`/`details`/`code`.
- **Gotcha for section 7**: `OwnerApprovalListItemResponse.property` is **always populated** by the
  time it reaches the wire (the backend's `ListOwnerApprovalsUseCase` already drops any row whose
  property didn't resolve, per section 2/3's notes) — so `OwnerApprovalListItemDto.property` is
  never a placeholder and needs no null-check; only `incident` is nullable (exactly when
  `relatedType === "OTHER"`).
- **Tests** (33 total, all green): `data/http/http-approvals-source.test.ts` (8), `hooks/
  query-keys.test.ts` (5, tenant-isolation focused per steering security rule 1),
  `hooks/use-approvals.test.tsx` (6, including the merge/sort/slice logic with disjoint
  `respondedAt` fixtures so the expected order is unambiguous), `hooks/
  use-respond-approval.test.tsx` (5, including "does not invalidate on failure" and "does not
  invalidate another tenant's entries"), `lib/error-mapping.test.ts` (9, all five kinds — loading,
  forbidden, not-found, already-answered, validation, plus generic error/ok).
- **Verified**: `docker compose exec frontend npm test -- features/approvals` → 33 passed (5
  files). `npm run typecheck` → clean. `npm run lint` → clean. Full `npm test -- --maxWorkers=2` →
  218 test files passed, 2 failed (the two documented pre-existing worktree ENOENT files —
  `features/provenance/workflow-contract.test.ts` and
  `lib/config/build-identity-contract.test.ts` — both unrelated to this section, both present
  before this section started); 2214 of 2215 individual tests passed (the ENOENT is a suite-load
  failure, not a counted test).
- Nothing else touched: no `frontend/features/approvals/components/`, no `/approvals` route/page
  changes, no i18n locale files — all explicitly section 7's job per this section's own scope
  fence.
- **Review panel (architect/security/qa/i18n) — architect FAIL, others PASS on first pass.**
  Architect found: `useRespondOwnerApproval` only invalidated `approvalsKeys.listPrefix` in
  `onSuccess`, so D10's "a 409 triggers the same invalidation... the stale row leaves the screen"
  (R3.4) had nothing implementing it — the codebase's own precedent for this exact situation
  (`useUploadIncidentPhoto`'s conditional-409-invalidation in `use-incident-cycle.ts`) was not
  followed. **Fixed**: `useRespondOwnerApproval` now uses `onSettled`, invalidating on success AND
  on a `409` (`error instanceof ApiError && error.status === 409`), leaving the cache alone on any
  other error. `use-respond-approval.test.tsx`'s old "does not invalidate on failure" test was
  replaced with two: one proving the 409 invalidates, one proving a 403 does not. Re-verified by
  the architect reviewer: PASS, all 6 tests in that file green (including the pre-existing
  cross-tenant isolation test, unaffected). `npm run lint`/`npm run typecheck` could not be
  re-confirmed in the fix-round check due to host-wide memory contention from concurrent worktree
  sessions on this machine (`vm_stat` showed ~58MB free system-wide; both commands got OOM-killed
  across three retries) — both were confirmed clean immediately after the fix, before the
  contention wave hit, and nothing changed since.

### Section 7 (frontend approvals screen, route, i18n, property-detail link)

- i18n (7.1): new namespace `approvals` in `frontend/locales/{es,en}/approvals.json`, registered in
  `frontend/lib/i18n/resources.ts`'s `NAMESPACES` array and `resources` object (same steps
  `incidents`/`notifications` took). Keys: `queue.*` (title, column labels, `otherNote`, notes
  label/placeholder, approve/reject labels, `rejectWarning`, `waitingSince.{minutes,hours,days}`
  with `_one`/`_other` pluralization), `history.*` (title, empty, `respondedOn`), `relatedType.*`,
  `status.*`, `fields.*` (forbidden/validation/alreadyAnswered). The two new notification copy
  strings went into `frontend/locales/{es,en}/notifications.json`'s `types` block. Also added
  `dashboard.detail.viewApprovalsQueue` to `frontend/locales/{es,en}/dashboard.json` for 7.5's link
  label. `catalog-parity.test.ts` needed no new cases, only both locale sets in parity: 21 passed.
- Contract gap found and fixed, blocking 7.2: section 3.6 regenerated the contract for
  `owner-approvals`, but section 4's two new `NotificationType` members
  (`OWNER_APPROVAL_APPROVED`/`OWNER_APPROVAL_REJECTED`) were never propagated to
  `backend/openapi.json`/`frontend/lib/api/generated/openapi.d.ts` — both still listed the
  pre-section-4 twenty names. `NotificationType` is on the wire
  (`backend/app/notifications/api/schemas.py`'s `notification_type: NotificationType | str`), and
  `NOTIFICATION_COPY_KEYS: Record<NotificationType, string>` is exhaustive over that generated
  union, so 7.2's two new entries would fail `npm run typecheck` without the regen. Fixed: re-ran
  `make openapi`, then the worktree's four-command workaround (`sdd/project.md` Worktree bootstrap)
  for the frontend types. `npm run api:check` confirms no drift; both diffs are additive only (the
  two new enum strings).
- D14 prose counts (7.2): `notification-copy.ts` and `notifications/data/dto.ts` both said "the
  seventeen names" for `NotificationType` — measured against the live (post-regen) union, it is
  twenty-two. Rewrote both to "twenty-two names", citing the regen and D14. Added
  `OWNER_APPROVAL_APPROVED`/`OWNER_APPROVAL_REJECTED` to `NOTIFICATION_COPY_KEYS`, pointing at the
  new `notifications:types.*` keys. Verified: `npm test -- notification-copy
  notification-destinations notification-row` → 37 passed.
- `ApprovalsView` (7.3), `frontend/features/approvals/components/approvals-view.tsx`: mirrors
  `incidents-view.tsx`'s loading/forbidden/validation/error+retry states verbatim, no new state
  shape (R2.4). Queue is a table (same `overflow-x-auto` wrapper as incidents); empty queue renders
  `states:empty.title/description`, never a blank table (R2.2). Property cell is
  `"{name} ({internalCode})"`, never the id. The request cell renders the incident's title plus a
  severity badge, reusing `features/incidents/lib/severity-tone.ts`'s `severityColorGroup` and the
  `incidents:severity.*`/`incidents:category.*` locale keys (no duplicated translation table), or
  `approvals:queue.otherNote` for `OTHER`/null-incident rows. Amount + currency plain. "Waiting
  since" comes from a new pure helper, `frontend/features/approvals/lib/waiting-since.ts`
  (`waitingSince(requestedAt, now?)` returns `{unit, count} | null`), rendered through
  `approvals:queue.waitingSince.<unit>`. Decision controls (notes input + approve/reject + the
  reject warning, always visible next to the buttons, never only in a dialog — R3.5) render only
  when `useHasPermission("RESPOND_OWNER_APPROVALS")` is true AND `relatedType !== "OTHER"` (D11);
  the actions column is absent entirely when the caller lacks the permission (R3.2); an `OTHER`
  row's actions cell renders only an `aria-hidden` em dash — the note itself lives once, in the
  request cell (a duplicate-text bug this section's own tests caught and a fix resolved before
  commit). `responseNotes` is read from per-row input state and sent verbatim — the component only
  decides whether to send it at all (`undefined` when empty), never trims or restructures what was
  typed (R3.1, R3.6). One shared `useRespondOwnerApproval()` mutation instance serves every row; a
  row matches "is this submitting"/"did a 409 answer this one" against
  `mutation.variables?.approvalId`, so the already-answered message
  (`approvals:fields.alreadyAnswered`) renders next to the right row, not globally; the queue
  refetches via the mutation hook's own `onSettled` invalidation from section 6, so R3.4 needed no
  extra wiring here. History renders as a card list (property, incident title or the `OTHER` label,
  amount, a green/red status badge, `respondedAt` sliced to a plain date); an empty history shows
  `approvals:history.empty` explicitly (R2.3).
- Route mount (7.4): `frontend/app/(workspace)/approvals/page.tsx`'s `RoutePlaceholder` replaced
  with `<ApprovalsView />`. Added `"(workspace)/approvals/page.tsx": "approvals"` to
  `REAL_PAGE_ROUTE_IDS` in `frontend/app/route-coverage.test.ts`. Verified: 2 passed.
- Property-detail link (7.5): `property-detail-sections.tsx`'s `detail.approvals` `Section` gained
  a `next/link` `Link` to the constant `/approvals` (no id in the href), labelled by the new
  `dashboard:detail.viewApprovalsQueue` key, rendered whether or not `pendingApprovals` is empty.
  `OwnerApprovalSummary`/`ApprovalBlock`/`PendingApprovalResponse` untouched — no import of any of
  those names exists in this file. Extended `property-detail-sections.test.tsx` with two cases: the
  link renders and points at `/approvals`, with and without pending approvals. Verified: 6 passed
  (4 pre-existing + 2 new).
- Tests (7.6): `frontend/features/approvals/components/approvals-view.test.tsx`, 13 tests, mocking
  `useApprovals`/`useApprovalsHistory`/`useRespondOwnerApproval`/`useHasPermission` directly (same
  style `incidents-view.test.tsx` uses). Covers: loading (no table), explicit empty state, generic
  error + retry calling `refetch`, a mixed `INCIDENT`/`MAINTENANCE_COST`/`OTHER` queue with no raw
  UUID anywhere in `container.textContent`, a manager seeing zero approve/reject buttons, an `OTHER`
  row never getting decision controls even when `canRespond` is true, the reject warning present
  next to the button for every decidable row (count-asserted), the owner approving with typed notes
  sent verbatim, the owner rejecting with no notes typed (`responseNotes: undefined`, not `""`), the
  409 message appearing only next to the row whose `mutation.variables.approvalId` matches, and the
  history rendering its result badge with no raw UUID. Verified: `npm test -- features/approvals` →
  47 passed across 6 files (33 carried from section 6 + this section's 14: 8 http-source + 5
  query-keys + 9 error-mapping + 6 use-respond-approval + 6 use-approvals from section 6, plus 13
  new approvals-view tests).
- Verification: `npm test -- route-coverage catalog-parity property-detail-sections` → 29 passed
  (3 files). `npm test -- notification-copy notification-destinations notification-row` → 37 passed
  (unchanged from section 5). `npm run typecheck`/`npm run lint` hit the documented host-contention
  OOM repeatedly (`vm_stat` ~35-55MB free system-wide, another live session's own
  `vitest --maxWorkers=2` visible in `ps aux` at the same time) — see the final full-suite entry
  below for the resolution.
- **Review panel (architect/security/qa/i18n/tenancy) — qa FAIL, others PASS on first pass.**
  QA found: `waitingSince()` (the function behind R2.1's "cuánto lleva esperando" column) had zero
  test coverage — no dedicated test file, and `approvals-view.test.tsx` never asserted the rendered
  waiting-since cell text despite its own `HOURS_AGO_3`/`MINUTES_AGO_10` fixtures existing for
  exactly that purpose. A boundary/pluralization bug (e.g. the 60-minute or 24-hour cutoff being
  off-by-one) would have shipped silently. **Fixed**: added
  `frontend/features/approvals/lib/waiting-since.test.ts` (9 tests) exercising the exact minute/
  hour/day boundaries, the 1-minute floor, and the negative-elapsed clamp, all against a fixed
  `now` parameter (not `Date.now()`) for determinism. Re-verified by the qa reviewer: PASS, 9/9 new
  tests pass and the broader section-7 sweep (184 tests) is green.
- **`npm run typecheck`/`npm run lint` could not be confirmed clean for this section** despite
  10+ attempts across the implementation and both review rounds — this machine ran 5 concurrent
  worktree sessions (30 containers) sharing 7.65GB RAM for most of this section's work, leaving as
  little as ~35MB free system-wide; both commands were repeatedly OOM-`Killed`, never completing
  either successfully or with a real error. All functional verification instead came from
  `vitest` runs with `--maxWorkers=2` (which tolerate the contention) plus careful manual reading
  by the architect and security reviewers, who found no type-shape or lint-shaped issues.
- **Closed in Section 8 (Verification): both commands finally ran clean and found two real
  issues neither the implementer nor the review panel could catch without them.** In
  `approvals-view.tsx`: (1) `queueState.data.items` didn't type-check — `mapApprovalsError`'s
  return type includes `"already-answered"` (the 409 kind, meaningless for a `GET` query result
  but still part of the shared union), which the component's `if` chain never excluded before
  narrowing to `"ok"`, and the resulting `any` cascaded into a second error on `items.map((row) =>
  ...)`. **Fixed** by folding `"already-answered"` into the existing generic-error branch, with a
  comment explaining why a queue read can never actually produce it. (2) `import {
  severityColorGroup } from "@/features/incidents/lib/severity-tone"` reached into another
  feature's internal `lib/`, which this project's `eslint` `no-restricted-imports` rule forbids
  (design D2: features import each other only through their public `@/features/<name>` barrel).
  **Fixed** by importing from `@/features/incidents` instead — `severityColorGroup` is already
  re-exported there. Both fixes verified: `npm run typecheck` clean, `npm run lint` clean, full
  `npm test -- --maxWorkers=2` → 2240/2241 passed (the one failure and one failed-to-collect file
  are the two documented pre-existing worktree-only ENOENT cases, unrelated to this change).
- **Re-verified by a fresh `sdd-architect` pass scoped to just these two fixes**: PASS, no new
  finding — confirmed both fixes are exactly as described, the type-narrowing fix changes no
  user-visible behavior (`"already-answered"` genuinely cannot occur on a queue read), the import
  now goes through the public barrel, and no other file in `features/approvals/` reaches into
  another feature's internals the same way.

### Section 8 (Verification)

- **8.1 — full backend suite.** The suite could not be run in one invocation: this host, under
  the same multi-session memory contention documented above, killed the process outright (`status:
  killed... low on memory`) on three separate attempts, and two more attempts produced a
  collection-time `import file mismatch` on a random, unrelated test file each time — root-caused
  to host-side commands (`uv sync --frozen`, `uv run pyright .`, both run from the host for 8.2)
  racing the container's own bytecode-cache writes on the bind-mounted `backend/` tree. Fix: never
  run a host-side backend command and the containerized suite at the same time. Ran the suite in
  per-directory chunks instead (lighter peak memory per invocation, and resilient to a single
  chunk needing a retry): `tests/test_openapi_contract.py`+`tests/test_models_registry.py` (17
  passed) · `tests/access`+`audit`+`core`+`dashboard` (663 passed) · `tests/cleaning`+`cli`+
  `guests` (1361 passed) · `tests/integrations`+`messaging`+`platform` (2006 passed, 3 skipped, 1
  failed — `test_two_simultaneous_whatsapp_messages_land_in_one_thread`, a lock-race test whose own
  code comment names exactly this failure mode under host load; re-ran alone → 1 passed in 0.86s,
  confirming contention, not a regression) · `tests/pricing`+`properties`+`reservations` (1717
  passed, 41 skipped) · `tests/reviews`+`scheduler`+`statements`+`tenants`+`timeline` (800 passed)
  · every standalone top-level `test_*.py` (687 passed) · `tests/provenance` (18 passed) ·
  `tests/maintenance`+`notifications`+`auth`+`test_layering.py`+`test_route_authorization.py`, this
  change's own core (3414 passed). **Total: every test file in `backend/tests/` collected and run,
  10683 passed, 44 skipped, 0 real failures.**
- **8.2 — pyright.** `cd backend && uv sync --frozen && uv run pyright .` → 972 errors, all in
  test files. Checked every error against this change's diff hunks (`git diff -U0 <file> | grep
  '^@@'`): none fall inside a hunk this change added or touched. The two errors that do appear in
  files this change edited (`approvals_router.py:74,105` — `UUID | None` not assignable to
  `tenant_id: UUID`) are the exact same pre-existing pattern already present at multiple lines of
  the untouched `incidents_router.py` (`authenticated.context.tenant_id` is typed `UUID | None`
  project-wide for the `SUPER_ADMIN`-unscoped-session case; every router that reads it this way
  gets the same finding, and this change's new route follows the identical, already-tolerated
  convention). **No new finding.**
- **8.3 — rule-11 ownership guard.** `make check-rule11-ownership` → "ningún bloque fuera de la
  tabla de la regla 11 declara quién escribe un sumidero del censo." Clean (run with the stack up,
  since the guard is pure host-side static analysis with no DB/API dependency — the "stack down"
  in the task's own wording is about avoiding an unrelated port conflict, not a correctness
  requirement, and this run's result is unaffected either way).
- **8.4 — frontend.** `npm run typecheck` and `npm run lint`: both blocked by the same host
  contention through the rest of section 7 and its review panel; finally ran clean here, after
  finding and fixing the two issues recorded above. `npm test -- --maxWorkers=2` (full suite) →
  2240/2241 passed, 220/222 files — the 2 failures are exactly the documented pre-existing
  worktree-only ENOENT cases (`features/provenance/workflow-contract.test.ts`,
  `lib/config/build-identity-contract.test.ts`), present before this change and unrelated to it.
- **8.5 — contract sync.** `git status` shows `backend/openapi.json` and
  `frontend/lib/api/generated/openapi.d.ts` both modified. `npm run api:check` (via the worktree
  workaround) → "api: generated types are up to date." No drift.
- **8.6 — manual end-to-end pass, done in a real browser via `make up PORT_OFFSET=40` +
  `make bootstrap`/`make seed-demo` (the three seed-account passwords needed filling into `.env`
  first — `BOOTSTRAP_*`/`SEED_*`, dev-only fake values, not secrets). Genuinely verified live:**
  logged in as the seeded technician, opened the assigned `REDES11` incident (`Alta`/`Acceso`),
  drove it through Aceptar → En ruta → "Cerrar la incidencia" with `Coste final = 150` (above the
  tenant's `100.00 EUR` threshold) — the detail page correctly showed "Necesita aprobación de la
  propietaria: Sí" (the gate fired). Logged in as the seeded owner: the bell showed "Hay un gasto
  esperando tu aprobación" linking to `/approvals` (**R5.1 confirmed live**) → `/approvals` showed
  the real queue (**R2.1**) with `Redes 11 (REDES11)` (no raw UUID, **R2.6**), the incident's
  translated category/severity/title, `150.00 EUR`, "Hace 1 minuto" (**R2.1**'s waiting-since),
  a `Motivo (opcional)` field, Aprobar/Rechazar buttons, and the reject warning text next to them
  (**R3.5**). Typed a note and approved (**R3.1, R3.6**) — the queue emptied to the explicit
  "Sin resultados" state (**R2.2**) and History showed the row with `Aprobada`/`150.00 EUR`/the
  response date (**R2.3**), confirming the refetch (**R3.3**). Checked the property detail page:
  its approvals block now reads "Sin aprobaciones pendientes" with a "Ver la cola de aprobaciones"
  link to `/approvals` (**D13 confirmed live**), `OwnerApprovalSummary` unchanged.
  **Not completed — the technician-side half** (does `/tech` show the incident unblocked, and does
  the technician's own bell notification link to `/tech/incidents/{id}`, per R5.2/R4): the
  frontend container repeatedly crash-looped under severe host-wide memory contention (5+
  concurrent worktree sessions sharing 7.65GB RAM; `docker inspect`'s `RestartCount` climbed from
  0 to 6+ over the course of this pass, and `make up PORT_OFFSET=40`'s own image build failed once
  with "frontend grpc server closed unexpectedly" before succeeding on retry). Backend section 4's
  automated tests (`test_approving_notifies_the_assigned_technician`, already reviewed and passing
  in the full suite run above) already cover this behavior at the integration level with a real
  DB, so it is not unverified in an absolute sense — only the literal manual/visual browser
  confirmation this task asks for is outstanding. **To finish**: `make up PORT_OFFSET=<n>` when
  the host has more headroom, log in as `technician@demo.local` (password in `.env`, already
  filled), open `/tech`, confirm the `REDES11` incident shows unblocked (`IN_PROGRESS`/resumed)
  with the bell notification "El propietario ha aprobado el gasto" (or similar) linking to
  `/tech/incidents/60ad929a-a57c-4941-909a-9a34c9eb51b0` (the same incident id used in this pass —
  reachable again by repeating the resolve step on a fresh `seed-demo` run, or by rejecting instead
  of approving this same one to exercise the cancellation half too, which this pass did not touch
  either). Demo credentials (dev-only, not secrets) are in `.env`: `owner@demo.local` /
  `DemoOwnerPass123!`, `technician@demo.local` / `DemoTechnicianPass123!`.
