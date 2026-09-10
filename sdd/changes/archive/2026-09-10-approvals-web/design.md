# Design: approvals-web

## Context

`maintenance` shipped the owner-approval **write** side and declared the read side absent on
purpose: `backend/app/maintenance/api/approvals_router.py:3-8` says so in its module docstring,
`backend/app/auth/domain/policy.py:66-67` repeats it inside the `Permission` enum, and
`sdd/specs/maintenance.md:588` records it as a limitation («Ensancharlo es de quien traiga su
bandeja»). The only projection of an approval that exists today is `OwnerApprovalSummary`
(`maintenance/domain/value_objects.py:124`), read by `OwnerApprovalReader.list_pending_for_property`
for one property's dashboard card. `frontend/app/(workspace)/approvals/page.tsx` is a
`RoutePlaceholder`, the route id `approvals` is already registered
(`frontend/features/shell/navigation/route-registry.ts:202`), and
`frontend/features/notifications/lib/notification-destinations.ts` has an empty `technician` row
whose justifying comment («until `tech-app` delivers `/tech/incidents/[id]`») is false — that page
exists.

What the change plugs into already exists and is followed rather than reinvented: the
paginated-listing shape of `GET /api/v1/incidents`
(`maintenance/api/incidents_router.py:113-143` + `IncidentPageResponse`), the read-model
construction of `maintenance/domain/read_models.py` (`IncidentContext`, pure Python, mapped to the
wire in `api/schemas.py`), the batch property resolver
`PropertyRepository.list_for_ids` (`properties/domain/repositories.py:192`), the channel fan-out
`dispatch_and_persist` (`notifications/application/channel_dispatch.py:117`), and on the frontend
the `features/incidents/` mould (`data/http` source → `hooks` over TanStack Query → components)
with the partial RBAC mirror of `frontend/lib/auth/permissions.ts`.

Two facts measured during this design change what the proposal assumed, and both are recorded
below: `owner_approvals.response_notes` is **not** guarded by `storable_text` (D12), and
`OwnerApproval(related_type=OTHER)` — written live by `revenue-statements` — **cannot be answered
at all** by the existing respond route (OQ1).

## Decisions

### D1 — A new permission, `READ_OWNER_APPROVALS`, for the owner and the manager

**Chosen:** add `Permission.READ_OWNER_APPROVALS` to `app/auth/domain/policy.py`, bundled as
`_OWNER_APPROVAL_READ`, and grant it to `TENANT_OWNER` and `PROPERTY_MANAGER` only. R1.4 asks for
exactly that set, and no existing permission has it: `RESPOND_OWNER_APPROVALS` is the owner's alone
(`policy.py:_OWNER_APPROVAL_RESPOND`, and `RespondOwnerApprovalUseCase` re-checks the role), so it
excludes the manager R1.4 requires.

Rejected: reuse `READ_INCIDENTS` — measured false, `_INCIDENT_EXECUTE` contains it and
`UserRole.TECHNICIAN` holds `_INCIDENT_EXECUTE`, so the technician would see the tenant's whole
expense queue. Rejected: reuse `RESPOND_OWNER_APPROVALS` for the read too — it would leave the
manager unable to see why the flow is stopped, which R1.4 and R2.1 both name.

Both prose declarations of the deliberate absence are **rewritten, not deleted and not ignored**
(R1.6): the docstring of `approvals_router.py` and the `RESPOND_OWNER_APPROVALS` comment block in
`policy.py`. `sdd/specs/maintenance.md:588` is the archive's job.

### D2 — The list is a read model, and it carries no free text

**Chosen:** a frozen dataclass `OwnerApprovalListItem` in
`app/maintenance/domain/read_models.py` (beside `IncidentContext`), projected onto the wire by
`OwnerApprovalListItemResponse` / `OwnerApprovalPageResponse` in `maintenance/api/schemas.py`.
Neither `reason` nor `response_notes` is a field of it — the same reason `OwnerApprovalSummary`
records for the dashboard, and the property that makes this change add **no reader** of a rule-11
sink.

Fields (R1.3): `id`, `related_type`, `status`, `amount`, `currency`, `requested_at`,
`responded_at`, an optional `incident` block (`id`, `title`, `category`, `severity`) and a
`property` block (`id`, `name`, `internal_code`).

Rejected: returning the `OwnerApproval` entity — it carries both free-text columns and would put
the owner's own justification on a wire nobody asked for it on. Rejected: widening
`OwnerApprovalSummary` — it is the dashboard's contract, which the proposal puts out of scope.

**`incidents.title` on this payload adds no row to the rule-11 census.** The audience is
unchanged: `TENANT_OWNER` and `PROPERTY_MANAGER` both hold `READ_INCIDENTS` and already read that
column on `GET /api/v1/incidents` and `/incidents/{id}`. A census row is owed when a sink reaches a
**new** audience, and this one does not.

### D3 — `currency` is a declared constant, because the column does not exist

**Chosen:** `owner_approvals` has no currency column, so the projection carries
`OWNER_APPROVAL_CURRENCY = "EUR"`, a module constant of `maintenance/domain/read_models.py`,
declared as such in its docstring. The tenant threshold it derives from is literally
`owner_approval_threshold_eur` (`tenants/domain/entities.py:151`), so EUR is not a guess.

Rejected: importing `app.dashboard.domain.financials.DEFAULT_CURRENCY` — a sideways dependency
between two domains' `domain/` layers, which `steering/backend-architecture.md` forbids. Rejected:
omitting `currency` — R1.3 asks for it. Rejected: adding a column — that is a schema decision for
whoever brings multi-currency, and `revenue-statements` already records that `OwnerStatement` has
no `currency` column either.

### D4 — Two queries per page, not a cross-domain JOIN and not N+1

**Chosen:** `OwnerApprovalReader` gains `list_for_tenant(tenant_id, filters, page, per_page) ->
OwnerApprovalPage`. Its SQLAlchemy implementation joins `owner_approvals` to `incidents` — **both
tables of `maintenance`** — with a LEFT OUTER JOIN gated on `related_type != OTHER`, so one
statement yields the approval and its incident columns. The use case then resolves the property
names for the page in one more statement via `PropertyRepository.list_for_ids`, keyed by
`approval.property_id`, exactly as `reservation-property-identity` D2 established.

Rejected: joining `PropertyModel` inside the maintenance reader — a repository of one domain
reaching into another domain's model. Rejected: `properties.get` per row — 20 extra statements per
page for a screen that exists to be opened often. Rejected: resolving the incident with
`IncidentRepository.get` per row — same objection, and the two tables are the same module's.

A property that does not resolve inside the tenant is **absent** from `list_for_ids` (its own
docstring); such a row is dropped from the page and logged under
`maintenance.owner_approval_property_unresolved`, the shape `GetIncidentContextUseCase` already
uses for the same anomaly. It is a crossed pointer, not a normal state.

### D5 — Default `PENDING`; order is a function of what was asked for

**Chosen:** `status` is a single optional query parameter. Absent, the listing returns **only
`PENDING`** (R1.2). Ordering follows the semantics of the answer, not one fixed clause:

* `PENDING` → `requested_at ASC, id ASC` — a to-do list, the discipline
  `OwnerApprovalReader.list_pending_for_property` already declares (R1.1).
* any answered status → `responded_at DESC, id DESC` — a history, which is what R2.3 asks to show.

Rejected: one fixed `requested_at ASC` for every status — the «últimas respondidas» of R2.3 would
then be on the last page. Rejected: a repeatable `status` parameter so the history is one request —
the shared `ApiClient.query` type is
`Record<string, string | number | boolean | null | undefined>` (`frontend/lib/api/client.ts:104`)
and admits no arrays; widening it is monorepo tooling and not this capability's (the same call
`dashboard-api` made about `generate-api-types.mjs`). The frontend pays a second request instead —
see D9.

### D6 — Two new `NotificationType` members, not one

**Chosen:** `OWNER_APPROVAL_APPROVED` and `OWNER_APPROVAL_REJECTED`, each with its own builder in
`maintenance/domain/notifications.py` (`owner_approval_approved_notification` /
`owner_approval_rejected_notification`), subject and body a constant plus `incident_id`,
`property_id` and `approval_id` — the closed form R4.4 requires and every sibling in that module
already keeps.

**Two and not one. This amended R4.2, and the amendment is already in `proposal.md`** (approved at
the design gate on 2026-09-05, OQ2) — so the spec written at archive inherits «dos tipos, uno por
resultado» and not a `SHALL` that was never built. The
technician's inbox renders its text from the **type alone**:
`frontend/features/notifications/lib/notification-copy.ts` maps `NotificationType → i18n key`, and
`subject`/`body` are deliberately not even on `NotificationDto`. A single
`OWNER_APPROVAL_ANSWERED` could therefore only ever render one sentence, and R4.1 requires the
notification to say **whether the expense was approved or rejected**. This is the same reasoning —
and the same shape — as `incident_critical_notification` / `incident_high_notification`, which
`maintenance` D4 kept as two constructors rather than one parameterised by severity. See OQ2.

Neither member carries `sla_deadline_at`, and neither gets an `escalation_for` rule: nobody is
late for reading an outcome, and a deadline with no escalation policy would mark a row breached
and escalate to nobody — the reason already written into `owner_approval_notification` and
`incident_rejection_notification`.

Both are members of the enum rather than bare string constants like
`NOTIFICATION_TYPE_INCIDENT_REJECTED`: only enum members are visible to the AST census of
`backend/tests/notifications/test_writer_census.py`, and both of these have a writer from day one,
so `WITH_WRITER` grows by two.

### D7 — The technician is told inside the transaction that already exists

**Chosen:** `RespondOwnerApprovalUseCase` gains the same three collaborators
`TriageIncidentUseCase` and `ClassifyIncidentUseCase` already take — `users: UserRepository`,
`notifications: NotificationLogRepository`, `configs: TenantConfigRepository` — and writes the row
through `dispatch_and_persist(...)` **before** its existing `await self._uow.commit()`. R4.5 is
then structural: there is no window in which the answer is recorded and the notice is not.

Recipient is `incident.assigned_technician_id`, resolved with `users.get(tenant_id, …)`. `None`
assignee, or a user that does not resolve, writes nothing and fails nothing (R4.3) — logged under
`maintenance.owner_approval_answer_without_recipient`, the shape `_notify_owner` already uses for
the mirror case.

Going through `dispatch_and_persist` and not building the `IN_APP` row by hand is what keeps the
proposal's out-of-scope line true: the channels are whatever `notification-channel-routing`
resolves from the tenant's own flags, and this change decides nothing about WhatsApp or email.

A **rejection** notifies too, and that is the point of R4: the incident is cancelled and the
technician has to stop, which is as much news as being unblocked.

Rejected: a separate «notify» use case — it would need its own transaction, which is the window
R4.5 exists to close. Rejected: writing the row in the router — the use case is reachable from a
job or a command, and only one caller goes through `require()`.

### D8 — R5.1 gets a second destinations table keyed by notification type

**Chosen:** `notification-destinations.ts` gains
`NOTIFICATION_TYPE_DESTINATIONS: Record<ShellProfile, Partial<Record<string, () => string>>>` with
one populated cell, `workspace: { OWNER_APPROVAL_REQUIRED: () => "/approvals" }`.
`notificationHref` takes the notification type as a new first-class argument and consults this
table **before** the `related_type` one; everything else is unchanged. The `Object.hasOwn`
prototype guard and the `startsWith("/")` check apply to the new table too — they were found by a
security panel and copying the lookup without them would reopen the same hole.

Rejected: changing `owner_approval_notification` to write `related_type = "owner_approval"` — it
would break the invariant three builders of that module share («everything this module notifies
about one incident is reachable by one query»), it would leave rows already written pointing at
the incident, and `/approvals` takes no id, so the polymorphic pair buys nothing here. Rejected:
an `if` in `notification-row.tsx` — the single-table shape is exactly what R6.4 of
`notifications-inbox-web` bought.

R5.2 is then a one-cell fill on the existing table: `technician: { incident: (id) =>
`/tech/incidents/${id}` }`, with the false comment deleted. That covers the two new types of D6 as
well, since both write `related_type = "incident"`. R5.4 leaves `cleaner` empty and R5.3's
invariant is untouched — a type with no override falls through to the `related_type` table, and a
row with either half of the pair missing still yields `null`.

### D9 — `/approvals` is one screen with two lists, over the `features/incidents/` mould

**Chosen:** a new `frontend/features/approvals/` with `data/dto.ts`,
`data/http/http-approvals-source.ts`, `hooks/query-keys.ts`, `hooks/use-approvals.ts`,
`hooks/use-respond-approval.ts` and `components/approvals-view.tsx`;
`app/(workspace)/approvals/page.tsx` stops being a `RoutePlaceholder` and mounts the view.

The queue is one `useQuery` with no status filter. The history (R2.3) is a `useQueries` over
`[{status: "APPROVED"}, {status: "REJECTED"}]` with `perPage: 5`, merged and re-sorted by
`respondedAt` descending, sliced to five — correct by construction, because each branch already
returns its own five most recent. `useQueries` is the pattern `useIncidentContexts` and
`useIncidentsPages` already use in this codebase; it is the price of D5's single-valued filter.

Loading, empty and error states reuse the `states:` namespace and the exact shapes of
`incidents-view.tsx` (R2.4), including its retry button. The empty queue renders
`states:empty.*`, not a headerless table (R2.2). No UUID is ever painted (R2.6): the row shows the
property's name and internal code, the incident's translated category and severity, its title, the
amount with its currency and a relative «waiting since» derived from `requested_at`.

Rejected: two routes (`/approvals` and `/approvals/history`) — the route registry has one
descriptor and R2.3 asks for a short history, not a second surface. Rejected: fetching the whole
list and splitting client-side — it would page a to-do list against a history.

### D10 — The decision, and how the client is gated

**Chosen:** `useRespondOwnerApproval` posts to `POST /api/v1/owner-approvals/{id}/respond`
(unchanged) and invalidates the approvals list prefix on success, so the queue and the history both
refresh (R3.3). `Permission` in `frontend/lib/auth/permissions.ts` gains
`RESPOND_OWNER_APPROVALS`, granted to `TENANT_OWNER` only, and the approve/reject controls render
behind `useHasPermission("RESPOND_OWNER_APPROVALS")` — the manager sees the queue and no buttons
(R3.2). The mirror stays what its docstring says it is: a UX hint, never the authority.

`response_notes` is an optional free-text field of the row's decision form, sent verbatim (R3.1,
R3.6). The reject control carries the warning of R3.5 **in the interface, next to the button** —
that rejecting cancels the incident and is not reversible from this screen — rather than only in a
confirmation dialog's body, because R3.5 says «en la propia interfaz».

R3.4: a `409 CONFLICT` (`OwnerApprovalAlreadyAnsweredError`, mapped in
`maintenance/api/errors.py:45`) is mapped by a feature-local `error-mapping.ts` to a translated
«ya respondida» message and triggers the same invalidation, so the stale row leaves the screen
instead of sitting there. Every other status falls to the generic error copy.

### D11 — `OTHER` approvals are listed and are not offered a decision

**Chosen:** the listing returns every approval of the tenant, `related_type = OTHER` included —
R1.1 says «las aprobaciones de su tenant» and hiding rows would make the queue lie about what is
pending. The **decision controls are offered only for `INCIDENT` and `MAINTENANCE_COST`**, and an
`OTHER` row renders with a translated note saying the expense is answered elsewhere.

This is not fastidiousness: measured during this design, `RespondOwnerApprovalUseCase` loads
`self._incidents.get(tenant_id, approval.related_id)` before anything else and raises
`IncidentNotFoundError` → **404** when it is `None`. For an `OTHER` approval `related_id` is an
`Expense` id, so the answer route cannot serve it at all — which contradicts
`sdd/specs/revenue-statements.md:294` and the module docstring of
`statements/application/reconciliation.py`, both of which state that the owner answers those
through this route. No test exercises it: the reconciliation tests seed `status`/`responded_at`
straight into the database. Fixing it is `revenue-statements`' and is out of this change's scope
(the proposal says so); painting a button that 404s would replace one dead end with another.

Approved at the design gate on 2026-09-05 (OQ1, option (a)). Its consequence is an obligation, not
a shrug: **`/sdd:archive` adds a roadmap entry `expense-approval-response`** that owns the fix,
naming the measurement above and the two documents that today claim the opposite
(`sdd/specs/revenue-statements.md:294` and the module docstring of
`statements/application/reconciliation.py`) — both of which the archive corrects, since a spec that
promises a route which 404s is worse than a declared gap.

### D12 — `response_notes` gets the `storable_text` guard this screen makes reachable

**Chosen:** `RespondOwnerApprovalRequest.response_notes` becomes
`Annotated[MultiLineText, Field(max_length=MAX_RESPONSE_NOTES)] | None = None`. `MultiLineText` is
already imported in that very file for `materials` and `content`.

It is plain `str` with `max_length` today, so a `U+0000` or a lone surrogate reaches asyncpg and
returns an **undeclared 500** — the failure `app/core/storable_text.py` exists to stop, measured
twice by the panels of `guest-portal-api`. R3.6 makes this screen the first writer of that column
from a browser, which is what turns a latent hole into a reachable one. Note that
`sdd/specs/maintenance.md` currently claims `incidents.assignment_note` is «el único sumidero de
texto libre vivo del módulo declarado como `str` con `max_length` a secas»; that is false of
`response_notes` today and true again once this lands — the spec sentence is the archive's to
correct.

Slightly beyond the literal acceptance criteria and recorded as such rather than smuggled: it is
one line, it is in the column R3.6 names, and leaving it would ship a screen whose reason field can
500.

### D13 — The property detail's approvals block gets a link, and nothing else

**Chosen:** `frontend/features/dashboard/components/detail/property-detail-sections.tsx` gains a
single `Link` to `/approvals` under its approvals block. Approved at the design gate on 2026-09-05
(OQ3). That block is where the owner first learns something is pending, and today it is the only
surface that says so — with no way out of it.

`OwnerApprovalSummary`, `ApprovalBlock` and `PendingApprovalResponse` are **untouched**, which is
what keeps this inside the proposal's out-of-scope line («Puede enlazar a `/approvals`, pero su
contrato no se toca»). No id crosses into the href: the link is the constant `/approvals`, so R2.6's
no-raw-UUID rule is satisfied by construction, and the queue's own ordering decides what the owner
sees first.

Rejected: deep-linking to a specific approval (`/approvals#<id>`) — it would put a UUID in the URL
for a screen whose whole content is the queue, and R2.3's history makes anchoring ambiguous once
the row is answered.

### D14 — Prose counts are recounted, never incremented

Adding two enum members touches four places that state a **number** of notification types:
`notifications/domain/enums.py` («The sixteen types of PRD §14» — about the PRD's list, still
true), `frontend/features/notifications/lib/notification-copy.ts` and
`frontend/features/notifications/data/dto.ts` (both say «seventeen names», already stale — the enum
has twenty today), and `backend/tests/notifications/test_writer_census.py` (`WITH_WRITER`, «Fifteen»).
Each is re-measured against `NotificationType` at the moment of the change and rewritten with the
counted figure; none is incremented from what it says now. `sdd/specs/access-notifications.md`
(«dieciocho») is the archive's.

## Changes by area

| Area | Files | Change |
|---|---|---|
| RBAC | `backend/app/auth/domain/policy.py` | `Permission.READ_OWNER_APPROVALS`, bundle `_OWNER_APPROVAL_READ`, granted to `TENANT_OWNER` and `PROPERTY_MANAGER`; the «no listing, no `READ_OWNER_APPROVALS`» comment rewritten (D1, R1.6) |
| RBAC tests | `backend/tests/auth/test_policy.py`, `backend/tests/test_route_authorization.py` | the new permission's role set and the new route's guard |
| Maintenance domain | `backend/app/maintenance/domain/read_models.py` | new `OwnerApprovalListItem`, `OwnerApprovalIncidentRef`, `OwnerApprovalPropertyRef`, `OwnerApprovalPage`, `OWNER_APPROVAL_CURRENCY` (D2, D3) |
| Maintenance domain | `backend/app/maintenance/domain/repositories.py` | `OwnerApprovalReader.list_for_tenant(...)` + `OwnerApprovalFilters` (D4, D5) |
| Maintenance domain | `backend/app/maintenance/domain/notifications.py` | two builders for the answer notification (D6) |
| Maintenance infra | `backend/app/maintenance/infrastructure/repositories.py` | `SqlAlchemyOwnerApprovalReader.list_for_tenant` — the outer join and the two orderings (D4, D5) |
| Maintenance app | `backend/app/maintenance/application/use_cases.py` | new `ListOwnerApprovalsUseCase` (reader + `PropertyRepository.list_for_ids`); `RespondOwnerApprovalUseCase` gains `users`/`notifications`/`configs` and writes the technician's row before its commit (D4, D7) |
| Maintenance API | `backend/app/maintenance/api/approvals_router.py` | `GET ""` with `page`/`per_page`/`status`; module docstring rewritten (D1, D5, R1.6) |
| Maintenance API | `backend/app/maintenance/api/schemas.py` | `OwnerApprovalListItemResponse`, `OwnerApprovalPageResponse`; `response_notes` gains `MultiLineText` (D2, D12) |
| Maintenance API | `backend/app/maintenance/api/dependencies.py` | wiring for the list use case and the three new collaborators of the respond use case |
| Notifications | `backend/app/notifications/domain/enums.py` | `OWNER_APPROVAL_APPROVED`, `OWNER_APPROVAL_REJECTED` (D6) |
| Notifications tests | `backend/tests/notifications/test_writer_census.py` | both new members into `WITH_WRITER`, count re-measured (D6, D14) |
| Contract | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | regenerated together — `steering/documentation.md`, both halves of the bridge |
| FE i18n | `frontend/locales/{es,en}/approvals.json`, `frontend/lib/i18n/resources.ts` | new `approvals` namespace in both locales (R2.5) |
| FE i18n | `frontend/locales/{es,en}/notifications.json` | copy for the two new types |
| FE notifications | `frontend/features/notifications/lib/notification-destinations.ts` + test | type-keyed override table, `technician.incident` filled, false comment deleted (D8, R5.1, R5.2) |
| FE notifications | `frontend/features/notifications/components/notification-row.tsx` | passes `notification.type` to `notificationHref` |
| FE notifications | `frontend/features/notifications/lib/notification-copy.ts`, `data/dto.ts` | two entries in the exhaustive `Record`; the stale «seventeen» recounted (D14) |
| FE RBAC | `frontend/lib/auth/permissions.ts` + test | `RESPOND_OWNER_APPROVALS`, `TENANT_OWNER` only (D10) |
| FE feature | `frontend/features/approvals/**` (new) | dto, http source, query keys, `use-approvals`, `use-respond-approval`, `error-mapping`, `approvals-view` (D9, D10, D11) |
| FE route | `frontend/app/(workspace)/approvals/page.tsx`, `frontend/app/route-coverage.test.ts` | real page; `"(workspace)/approvals/page.tsx": "approvals"` added to `REAL_PAGE_ROUTE_IDS` |
| FE dashboard | `frontend/features/dashboard/components/detail/property-detail-sections.tsx` + test | a `Link` to `/approvals` under the approvals block; no contract touched (D13) |
| Docs | `docs/maintenance.md`, `.env.example` (no change expected) | the new route and the two notification types, per `steering/documentation.md` |

## Data & interfaces

**No schema change and no migration.** `owner_approvals` is read as it stands; the two new
`NotificationType` members land on a `String(100)` column that has been free text since
`domain-foundation-financial`, which is why the enum needs none (its own docstring).

`GET /api/v1/owner-approvals` — permission `READ_OWNER_APPROVALS`.

| Parameter | Type | Default |
|---|---|---|
| `page` | int, `ge=1 le=MAX_PAGE` | 1 |
| `per_page` | int, `ge=1 le=MAX_PER_PAGE` | 20 |
| `status` | `OwnerApprovalStatus \| None` | absent → `PENDING` only |

```
OwnerApprovalPageResponse { items[], total, page, per_page }
OwnerApprovalListItemResponse {
  id: UUID
  related_type: OwnerApprovalRelatedType
  status: OwnerApprovalStatus
  amount: Decimal            # the module's own convention (IncidentResponse.estimated_cost)
  currency: str              # "EUR", a declared constant — D3
  requested_at: datetime
  responded_at: datetime | null
  incident: { id, title, category, severity } | null   # null for related_type OTHER
  property: { id, name, internal_code }
}
```

`403` without the permission, with the shared `ErrorEnvelope` and no hint about whether any
approval exists (R1.5) — inherited from `require()` and `AUTHENTICATED_RESPONSES`, not restated.

`POST /api/v1/owner-approvals/{approval_id}/respond` is unchanged in shape; only
`response_notes`' validation tightens (D12), which is a `422` where a `500` used to be.

No new configuration and no new environment variable.

**No diagram.** The maintenance sequence already has one
(`docs/diagrams/2026-08-23_autohost-secuencia-mantenimiento.png`), regenerated under the discipline
`steering/architecture.md` describes at length; a second drawing of the same flow would be the
divergence that essay warns about, and nothing here changes the state machine it shows.

## Risks & mitigations

* **The `OTHER` row is a dead end this change makes visible.** Today those approvals are invisible;
  after this they are on screen with no way to answer them. Mitigated by D11 — no button, an
  explicit translated note — and by the roadmap entry `expense-approval-response` that D11 obliges
  the archive to write. What is **not** mitigated, and is the point of writing the entry: the
  expense loop of `revenue-statements` stays open until somebody takes it.
* **`RespondOwnerApprovalUseCase` grows to thirteen collaborators** — the nine of
  `_IncidentFlowBase`, its own `approvals`, and the three of D7 (counted against the constructors,
  not carried over from another change's figure). The same cost
  `ClassifyIncidentUseCase` accepted and recorded for the same reason (R4.5 wants the write inside
  the existing transaction). If it grows again, the thing to extract is the
  incident+audit+timeline trio, not the notification — the note that class already carries.
* **Two new enum members reach an exhaustive frontend `Record`.** That is the mitigation, not the
  risk: a missing translation fails `npm run typecheck`, a CI gate. The failure mode to watch is the
  opposite one — forgetting `frontend/locales/en/notifications.json` while adding the `es` half,
  which the i18n reviewer and `catalog-parity.test.ts` catch.
* **Contract drift.** The endpoint is new, so `make openapi` **and** the frontend's
  `npm run api:generate` must both be committed; in a worktree the second needs the four-command
  workaround in `sdd/project.md`, because the documented command does not run here.
* **Ordering on `responded_at`.** No index exists on it. Two flats produce tens of rows, so the plan
  is a sort over a tenant-scoped set; recorded rather than pre-optimised, and the page is bounded by
  `MAX_PER_PAGE`.
* **The manual pass needs an assigned incident.** The proposal's `ASSUMPTION` holds: `assign` has no
  UI caller yet, so the end-to-end walk starts from `make bootstrap` / `seed_demo` or the CLI. R4 is
  untestable by hand without it, and its automated coverage does not depend on that.

## Open questions

**All three were resolved at the design gate on 2026-09-05 (Jose). None is open.** They are kept
here with their answer rather than deleted, because two of them changed a document elsewhere and
the third owes the archive a task.

**OQ1 — `OwnerApproval(OTHER)` cannot be answered by any route, and this change is what makes it
visible.** Measured, not suspected: `RespondOwnerApprovalUseCase` resolves an incident from
`related_id` before anything else and 404s when there is none, while `revenue-statements` writes
`OwnerApproval(OTHER, related_id=expense.id)` live from `CreateExpenseUseCase` and its own spec
(`sdd/specs/revenue-statements.md:294`) states that the owner answers it through exactly that
route. Three options were weighed: **(a)** list them, no button, a translated note, and a new
roadmap entry that owns the fix; **(b)** exclude `OTHER` from the listing entirely, which keeps
today's silence and makes the queue incomplete; **(c)** widen this change to make the respond route
handle `OTHER`, which the proposal puts out of scope and which pulls `Expense` semantics into
`maintenance.application` — the coupling `revenue-statements` D4 deliberately avoided.
**Resolved: (a)** — D11, plus the `expense-approval-response` roadmap entry and the two document
corrections that D11 hands to `/sdd:archive`.

**OQ2 — R4.2 said «un `NotificationType` propio»; D6 needs two.** The inbox renders its text from
the type alone, so one member cannot say whether the expense was approved or rejected, which R4.1
requires. **Resolved: two types** (`OWNER_APPROVAL_APPROVED`, `OWNER_APPROVAL_REJECTED`), and
**R4.2 of `proposal.md` has been amended accordingly** — the amendment is in the proposal, not only
here, so the living spec written at archive cannot inherit a `SHALL` nobody built.

**OQ3 — should the property detail's approvals block link to `/approvals`?** The proposal's
out-of-scope says it *may* («Puede enlazar a `/approvals`, pero su contrato no se toca»), and no
acceptance criterion asks for it. **Resolved: yes, the link and nothing else** — D13.
