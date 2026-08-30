# Dashboard Web (Frontend)

## Purpose

The presentation layer of the owner/manager dashboard (PRD §9): the
property-cards overview (`/dashboard`, §9.1), the property detail page
(`/properties/[id]`, §9.2) with its per-property timeline (§10), and the
standalone timeline screen (`/timeline`), which mounts that same timeline over a
property chosen in a selector. It renders
inside the existing WorkspaceShell and consumes all data through a typed
data-access boundary (`DashboardDataSource`). The aggregate backend it was shaped
against **now exists** — `dashboard-api` shipped the four read endpoints (see
`specs/dashboard-api.md`) — and the runtime uses `HttpDashboardSource` at the
composition point. It maps the three responses consumed by the UI from their
generated `snake_case` contract to the feature's `camelCase` DTOs without
changing the UI, hooks or query keys.

The screen is a read surface **except** for one region: the property card's
blocked-transitions section, which since `blocked-transitions-web` lets a
`PROPERTY_MANAGER` cancel the cleaning or resolve the incident that is holding up
the next check-in. Those two writes go to the `cleaning` and `maintenance`
endpoints; the four `dashboard-api` routes this feature reads remain read-only,
and `/properties/[id]` and `/timeline` still mutate nothing.

## Requirements

### Property cards overview (`/dashboard`)

- WHEN a user opens `/dashboard`, THE SYSTEM SHALL render one property card per
  property returned by the data source, each showing the property code, the
  operational state with its PRD §9.1 color, the current-or-next reservation
  reference, guest name, check-in and check-out, cleaning status, open-incident
  count, the next required action with its responsible party, and the last-event
  label with its time.
- WHILE the cards query is pending, THE SYSTEM SHALL render the shared loading
  state (`aria-busy` status), and IF it fails THEN THE SYSTEM SHALL render the
  shared error state (`role="alert"`) with a retry that re-runs the query, never
  exposing raw error detail.
- IF the data source returns zero properties, THEN THE SYSTEM SHALL render the
  shared empty state, visually distinct from the error and loading states.
- THE SYSTEM SHALL NOT compute operational state, colors, or the next action in
  the component: those are rendered as provided by the data source (the backend
  is the source of truth).
- WHEN a property card is rendered, THE SYSTEM SHALL present its visual and DOM
  regions in this priority order: operational state, open incidents, blocked
  transitions, next action, reservation and guest, cleaning, and last event.
- WHEN cards with different amounts of content are shown in the same grid, THE
  SYSTEM SHALL keep their headers, primary regions, and detail links visually
  aligned without hiding required values or introducing horizontal overflow.
- WHEN the viewport is desktop, tablet, or mobile, THE SYSTEM SHALL reflow the
  card grid and its internal content while preserving the same hierarchy and
  readable wrapping in the active locale.
- WHEN a user navigates the card with a keyboard, THE SYSTEM SHALL preserve
  native semantics, a visible focus indicator, and the localized accessible
  name of the property-detail link.

#### Blocked transitions on the card

The clock-vs-state mismatches `celery-jobs.md` §Desajustes serves over
`GET /api/v1/blocked-transitions` are painted where the owner and the manager
already look. Until this section existed the endpoint had no consumer, and a
stalled property stayed stalled until a guest wrote.

- WHEN a property of the tenant has one or more current blocked transitions, THE
  SYSTEM SHALL render them inside that property's card as a labelled
  `<section>`, ordered by `due_since` ascending with a deterministic tie-break on
  `reservation_id` and then `trigger`, so two stalls emitted in the same hour do
  not swap places between renders.
- THE SYSTEM SHALL mount `useBlockedTransitions()` **once** per `/dashboard` view
  and slice its `Map<propertyId, stalls>` per card, and SHALL NOT call it inside
  `PropertyCard`: N cards issue one request, not N.
- THE SYSTEM SHALL take `tenantId` from the authenticated session inside the hook
  and SHALL NOT accept it as a parameter — a parameter is an override of the
  isolation in the wrong direction — keeping the key tenant-scoped as
  `['tenant', tenantId, 'blocked-transitions', page]`.
- THE SYSTEM SHALL render `trigger` and `blocking_state` as the canonical literals
  the backend emits, in a monospaced `<code>`, without translating them, without a
  parallel label catalog, and without a colour derived from their value; any colour
  on the card still comes from the single `PropertyOperationalState` map in
  `components/property-state-badge.tsx`.
- THE SYSTEM SHALL format `due_since` with `Intl.DateTimeFormat` in the active
  locale (date + time), and IF the value is not a parseable timestamp THEN SHALL
  render the raw string — never throwing `RangeError` inside the render loop and
  never printing the Unix epoch for a null-ish value. The guard lives in the
  feature's shared `lib/format.ts`, so the property detail sections and the
  property timeline inherit it rather than keeping a private formatter.
- THE SYSTEM SHALL lay the row out so a wrap can never strand a separator at the
  end of a line: the canonical literals occupy one row, the date and the action
  another, and the remaining separator shares a non-wrapping box with the literal
  it introduces.
- WHILE the property has no current blocked transition and the query succeeded, THE
  SYSTEM SHALL render no section, no badge and no empty state: the card is exactly
  as it was before this feature.
- WHILE the stalls query is pending, THE SYSTEM SHALL omit the section and keep the
  rest of the card rendering.
- IF the stalls query fails, THEN THE SYSTEM SHALL render the localized error
  inside the card's own stalls section — keeping its heading, painting no action
  button, and preferring the error over stale rows — and SHALL NOT escalate to the
  page-level error state: an outage of this section never hides the cards, and an
  empty card would be indistinguishable from "this property has no blockers".
- THE SYSTEM SHALL name, in one line of body copy under the list, the 30-day
  `candidate_window` the backend applies, and SHALL NOT promise exhaustiveness
  ("all properties", "real time", "complete"). That line is **not** a link: the
  application serves no `/docs` route, so the operational detail lives in
  `docs/properties.md` and is reached outside the app.

##### What action a row offers

- THE SYSTEM SHALL decide the action of a row from a single declared matrix
  `trigger × blocking_state → ActionKind | null` (`stalls/lib/action-map.ts`) and
  SHALL NOT distribute `if (state === …)` checks across components. A cell absent
  from the matrix resolves to `null`: informative, without action.
- THE SYSTEM SHALL keep the `ClockTrigger` union closed and guarded at compile time
  (`Exclude<ClockTrigger, keyof typeof ACTION_MATRIX>` having to resolve to
  `never`), so a fourth trigger in the contract fails type-check instead of quietly
  resolving to `null`. Operational states are deliberately **not** exhaustive there:
  `null` is the right answer for a state that admits no action.
- WHEN a row resolves to `cancel-cleaning`, THE SYSTEM SHALL offer the cancel
  button only WHERE the session holds `MANAGE_CLEANING_TASKS` **and** the row
  carries a `cleaning_task_id`; WHEN it resolves to `resolve-incident`, only WHERE
  the session holds `EXECUTE_INCIDENTS` **and** the row carries an `incident_id`.
- THE SYSTEM SHALL NEVER paint a button whose call would answer `403`. The
  permission is read from the partial UI mirror (`lib/auth/permissions.ts`), so a
  `TENANT_OWNER` — who sees the whole section with her `READ_PROPERTIES` — is
  offered no button at all.
- THE SYSTEM SHALL take both ids from the row the backend served and SHALL NOT
  derive them: a row whose id the backend could not resolve offers no action rather
  than a wrong one.

##### Confirming an action

- WHEN a cancellation is confirmed, THE SYSTEM SHALL call
  `POST /api/v1/cleaning-tasks/{task_id}/cancel` with the mandatory non-empty
  `reason` (bounded at 500 characters with a visible counter, submit disabled while
  empty); WHEN a resolution is confirmed, THE SYSTEM SHALL call
  `POST /api/v1/incidents/{incident_id}/resolve` with the required `final_cost`,
  validated as a positive decimal. Neither SHALL synthesize a field the API already
  knows from the URL or the session.
- THE SYSTEM SHALL run both mutations with `retry: false` and, `onSettled`, SHALL
  invalidate the tenant's `blocked-transitions` prefix **plus** every bucket the
  write could have moved: cleaning tasks, dashboard cards and property timeline for
  the cancellation; incidents list, incidents detail, dashboard cards and property
  timeline for the resolution. Invalidating the stalls alone makes the row vanish
  under a stale operational badge.
- THE SYSTEM SHALL NOT patch the cache optimistically: a `resolve` whose amount
  crosses the approval threshold lands in `AWAITING_OWNER_APPROVAL` rather than
  `RESOLVED` (`maintenance.md` R4), so the server's answer is the only truth about
  where the incident went.
- WHEN a mutation fails, THE SYSTEM SHALL choose the localized message by HTTP
  **status** — `403` says the permission is gone (retrying grants nothing), `409`
  says the state moved on (a guest is already in, or somebody resolved it first),
  and any other status falls back to the per-action generic that names the action —
  and SHALL NEVER render `ApiError.message`, which is technical and English-only.
  There is no `401` branch: the HTTP client's one-shot refresh owns that path.
- WHILE a mutation is in flight, THE SYSTEM SHALL keep the dialog mounted with the
  typed value intact, disable the submit, and reject a second submit dispatched
  inside the same React frame through a ref cleared in `onSettled` —
  `mutation.isPending` only flips on the next commit and cannot close that window.
- THE SYSTEM SHALL keep each mutation hook in the feature that owns the mutated
  resource (`features/cleaning`, `features/incidents`) and each dialog in the
  screen that opens it (`features/dashboard/stalls/components/`).

### Property detail (`/properties/[id]`)

- WHEN a user opens `/properties/[id]`, THE SYSTEM SHALL render, for that
  property, the detail sections of PRD §9.2 (reservation, guest, access state,
  cleaning state, open incidents with severity, financial summary, notes, pending
  approvals, last-cleaning photos) and the property timeline.
- WHEN the data source rejects the detail request with a §23 404, THE SYSTEM
  SHALL render a localized "not found" state within the shell chrome; any other
  failure renders the error state with retry.
- WHERE last-cleaning photos are shown, THE SYSTEM SHALL use the URL provided by
  the data source and SHALL NOT construct a storage URL in the client.
- THE SYSTEM SHALL keep the detail page read-only: no mutations (approvals,
  assignments, or state changes) are performed.

### Timeline screen (`/timeline`)

- WHEN a user opens `/timeline`, THE SYSTEM SHALL render a property selector whose
  options are exactly the properties returned by `useDashboardCards()`, each valued
  by `propertyId` and labelled by `propertyCode`, introducing no new endpoint and no
  new `DashboardDataSource` method.
- WHILE no property is selected, THE SYSTEM SHALL render the shared empty state with
  its own "choose a property" copy and SHALL NOT mount the timeline, so no request to
  `GET /api/v1/timeline/{property_id}` is emitted. Not mounting the component is what
  guarantees this, rather than disabling the hook. THE SYSTEM SHALL NOT autoselect a
  first property: with N properties any automatic choice is arbitrary, and the first
  paint must not fetch a feed nobody asked for.
- WHEN a property is selected, THE SYSTEM SHALL mount the same `PropertyTimeline`
  component that `/properties/[id]` renders, introducing no second entry list, no
  second timeline hook and no second filter store — so everything the timeline gains
  is inherited by the property-detail section without touching it.
- THE SYSTEM SHALL hold the selection **in memory only**, as the pair
  `{ tenantId, propertyId }` in a Zustand store, and NEVER SHALL write it to
  `localStorage`, `sessionStorage`, a cookie or the URL: a `property_id` identifies a
  tenant and none of those are tenant-scoped.
- THE SYSTEM SHALL honour a stored selection only WHILE its `tenantId` equals the
  authenticated tenant, and otherwise treat it as no selection. Signing out clears
  neither the Zustand stores nor the query cache, so a bare `propertyId` would survive
  a logout followed by a login as another tenant in the same tab and fetch a foreign
  property — a 404 indistinguishable from "does not exist", which is not retried and
  so fails silently.
- WHEN the user changes property, THE SYSTEM SHALL reset the active filters and the
  page.
- WHILE the properties query is pending or has failed, THE SYSTEM SHALL render the
  shared loading and error states, the latter with a retry that re-runs the query and
  never exposing raw error detail.
- THE SYSTEM SHALL keep the route a Server Component that resolves `generateMetadata`
  from `routeMetadata("timeline")` and imports `TimelineView` from the feature barrel,
  never from an internal path; the client boundary lives inside `TimelineView`.
- THE SYSTEM SHALL export `TimelineView` from the feature barrel and SHALL keep
  `PropertyTimeline` internal to the feature: `/timeline` reaches it through
  `TimelineView`, so exporting it as well would be public API nothing imports.

### Property timeline (§10)

- WHEN the timeline renders, THE SYSTEM SHALL show its entries in the immutable
  order the data source returns them, each in the active locale, with its
  localized actor and severity labels.
- THE SYSTEM SHALL offer filtering by event type, actor, severity and date range;
  the selected filters are threaded into the tenant-scoped query key so each
  combination is cached distinctly.
- THE SYSTEM SHALL populate the event-type filter from the closed 47-value
  vocabulary `TIMELINE_EVENT_TYPES`, typed off the generated
  `components["schemas"]["TimelineEventType"]` union, and SHALL NOT derive the
  options from the entries a query happened to return — a derived list is wrong as
  soon as the results are paginated, and it cost one extra HTTP request per render.
  A compile-time guard (`Exclude<TimelineEventType, (typeof
  TIMELINE_EVENT_TYPES)[number]>` having to resolve to `never`) SHALL fail
  type-check if the contract enum grows.
- THE SYSTEM SHALL resolve every event-type label through its declared
  `timeline.eventType.<TYPE>` key, present in both locales, and NEVER SHALL use the
  raw enum literal as visible fallback text.
- IF a selected filter combination matches no entry, THEN THE SYSTEM SHALL render
  the timeline empty state: 18 of the 47 types have no production writer, so an
  empty page is a correct answer rather than a failure.
- THE SYSTEM SHALL hold the timeline filter selections as lightweight UI state in
  Zustand and SHALL NOT store timeline entries (server state) there; filters reset
  when the property changes.

#### Pagination

- THE SYSTEM SHALL request a fixed page size of 20, sent explicitly as `per_page`
  instead of relying on the server default so the cache key declares the page size
  the cached envelope describes, and SHALL NOT expose the page size in the
  interface; only `page` is navigated.
- WHEN the `TimelinePageResponse` envelope reports `total_pages > 1`, THE SYSTEM
  SHALL render a labelled `<nav>` giving the position from an interpolated key
  ("page X of Y") with previous/next controls disabled at the bounds, reading
  `page` and `total_pages` from the envelope rather than from the store; WHERE
  there is a single page it renders no control at all.
- WHEN a type, actor, severity or committed-range filter changes, THE SYSTEM SHALL
  return to page 1 **in the same store mutation that changes the filter**, so no
  query is ever issued for a stale page of a newly selected filter.
- WHERE a date-range draft is inverse, THE SYSTEM SHALL leave the page untouched:
  the page reset exists because the result set changed, so a draft that commits
  nothing moves nothing.
- THE SYSTEM SHALL navigate discrete pages, each filter combination (page included)
  being its own TanStack Query entry, and SHALL NOT accumulate pages into a single
  cache entry nor mirror timeline entries in Zustand.

#### Date range

- THE SYSTEM SHALL render independent, optional "from" and "to" date inputs over a
  `YYYY-MM-DD` draft held in the filter store, promoting it to the contract
  `from`/`to` pair only while the draft is valid.
- WHEN a range is committed, THE SYSTEM SHALL send a timezone-qualified instant —
  `from` at the start and `to` at the end (`23:59:59.999`) of the chosen **local**
  day, serialized with a `Z` offset. The range is inclusive at both ends, the
  backend rejects a naive datetime with a 422, and the local day is the one the
  list itself formats, so asking for a day and seeing the previous one would
  contradict the screen.
- IF the "to" day precedes the "from" day, THEN THE SYSTEM SHALL render a localized
  field error (`role="alert"`, wired through `aria-invalid` and `aria-describedby`
  on both inputs) and SHALL NOT emit a request: the committed pair does not move, so
  the query key does not change and neither an invalid request nor a collateral
  "valid" one is issued.

#### Free-text safety

- THE SYSTEM SHALL render `TimelineEntry.title` and `TimelineEntry.description` as
  React-escaped interpolated text and NEVER SHALL pass either through
  `dangerouslySetInnerHTML`, `innerHTML` or a markdown renderer — `description` is
  the only operator-authored free text on an append-only table.
- THE SYSTEM SHALL show `title` exactly as the server composed it from its own
  catalog and SHALL NOT re-translate it in the client.
- THE SYSTEM SHALL keep the audience unchanged: the timeline lives behind
  `READ_PROPERTIES`, held only by `TENANT_OWNER` and `PROPERTY_MANAGER`, and no
  reader role is added.

### Swappable data source (`DashboardDataSource`)

- THE SYSTEM SHALL define a typed `DashboardDataSource` interface whose methods
  return DTOs replicating the real API contract (PRD §23 data envelope, error
  envelope surfaced as `ApiError`, ISO-8601 UTC dates), aligned with the routes
  `dashboard-api` now serves: `GET /api/v1/dashboard/properties` (the cards
  collection), `/api/v1/properties/{id}/dashboard`, `/api/v1/properties/{id}/state`
  and `/api/v1/timeline/{property_id}`.
- THE SYSTEM SHALL implement the cards, property detail and property timeline
  methods with the shared authenticated `ApiClient`, preserving pagination
  metadata and item order, propagating its `ApiError` unchanged, and serializing
  only defined timeline filters as `event_type`, `severity`, `actor_type`, `from`,
  `to`, `page` and `per_page`.
- THE SYSTEM SHALL explicitly map generated HTTP response fields to feature DTOs,
  preserve nullable values and ISO-8601 strings, convert decimal financial values
  to numbers while preserving `null`, and use photo URLs supplied by the backend
  without constructing storage URLs in the frontend.
- THE SYSTEM SHALL resolve the data source through a single composition point, so
  that `HttpDashboardSource` is resolved instead of the isolated
  `MockDashboardSource` without changing the UI, the hooks, or the query keys.
- THE SYSTEM SHALL keep components and hooks dependent only on the interface and
  the composition point; none imports the mock implementation or its fixtures
  (enforced by a boundary test).

### Server-state access

- WHEN a dashboard surface consumes data, THE SYSTEM SHALL route it through
  TanStack Query v5 with a tenant-scoped query key (`['tenant', tenantId,
  resource, ...]`, non-empty `tenantId`).
- WHEN a query fails with a 4xx client error (e.g. a 404), THE SYSTEM SHALL NOT
  retry it, so the localized error/not-found state appears immediately; transient
  (5xx / network) failures are retried briefly.

### Internationalization and operational-state colors

- WHEN any dashboard string is rendered, THE SYSTEM SHALL resolve it through
  react-i18next keys present in both `locales/es` and `locales/en` (the
  `dashboard` namespace); backend-localized dynamic values (reservation reference,
  guest name, timeline text, next-action label, cleaning status) are rendered as
  data.
- THE SYSTEM SHALL NOT extend that rule to the canonical literals of the
  blocked-transitions section (`trigger`, `blocking_state`): the backend emits them
  without prose on purpose, and a translation catalog for them would be a second
  vocabulary to keep in sync with the contract.
- THE SYSTEM SHALL map each canonical `PropertyOperationalState` to its exact PRD
  §9.1 color group (green/blue/amber/red/gray), exhaustively over the state union,
  falling back to gray for an unrecognized value.
- THE SYSTEM SHALL keep that map in **one** place in the tree — the cross-cutting
  `components/property-state-badge.tsx`, which owns both halves (state → colour
  group and colour group → Tailwind classes) and the gray fallback — and SHALL NOT
  keep a copy inside this feature. `PropertyCard` consumes the component; the
  feature no longer has a `lib/state-color.ts`.
- THE SYSTEM SHALL type that shared component on the generated
  `components["schemas"]["PropertyOperationalState"]` union and NEVER SHALL type it
  on the hand-written union of `features/dashboard/data/dto.ts`, so that extracting
  it does not leave one feature depending on another's internals.
- THE SYSTEM SHALL give the shared component the signature `{ state, label }`: it
  owns the colour and receives the label already translated, so it carries no i18n
  namespace of its own and each consuming screen resolves the eleven labels from
  the `dashboard` namespace where they live.
- THE SYSTEM SHALL export from that component the runtime list
  `PROPERTY_OPERATIONAL_STATES`, derived from the colour map's keys rather than
  transcribed, so a consumer that offers the states as options inherits the
  compiler's exhaustiveness instead of silently omitting a twelfth state.

**El alcance de esa unicidad es la tabla de `PropertyOperationalState`, no «los
colores del árbol».** `features/cleaning/lib/task-status.ts` mantiene una tercera
tabla con los mismos valores Tailwind, y queda fuera a propósito: indexa otro enum
(`CleaningTaskStatus`) y PRD §9.1 fija colores para el estado de la vivienda, no
para el de la tarea.

### Quality

- WHEN the frontend is verified, THE SYSTEM SHALL pass type-check, lint, the
  colocated test suite, and a production build without a running backend.

## Explicit debt (ASSUMPTION)

- `MockDashboardSource` remains available only as isolated test support. The
  runtime uses the shared authenticated HTTP source; it does not synthesize data,
  calculate operational state or colors, translate backend data, or call the
  separate property-state endpoint.
- Real-time streaming is still absent on both sides: `dashboard-api` delivers the
  timeline as a filtered, paginated **read**, and explicitly leaves push
  (WebSocket/SSE) out of scope, so PRD §9.2's "tiempo real" is not met yet.
- The timeline's page controls, the range inputs and the property selector are
  declared inside the feature and shared with nothing. That matches the tree —
  `features/properties/.../properties-view.tsx` and
  `features/reservations/.../reservations-view.tsx` each carry their own page
  navigation and no shared one exists — so a third copy is consistent rather than
  novel. Extracting one would touch two archived features and is a refactor
  decision no entry has taken yet.
- The global cross-property timeline of PRD §23 does not exist: the backend serves
  one property at a time (`dashboard-api.md`), which is why `/timeline` asks for a
  property instead of listing everything.

## Key files

- `frontend/features/dashboard/data/` — `dto.ts` (§23-shaped DTOs),
  `dashboard-source.ts` (the interface), `index.ts` (composition point),
  `http/http-dashboard-source.ts` (the runtime implementation), and
  `mock/{fixtures,mock-dashboard-source}.ts` (isolated test support).
- `frontend/features/dashboard/hooks/` — `query-keys.ts` (tenant-scoped keys),
  `use-dashboard-data.ts` (`useDashboardCards`/`usePropertyDetail`/
  `usePropertyTimeline` + `retryPolicy`).
- `frontend/features/dashboard/components/` — `property-card.tsx`,
  `dashboard-view.tsx`, `detail/{property-detail-view,property-detail-sections,
  property-timeline}.tsx`, `timeline/timeline-view.tsx` (the `/timeline` screen:
  selector + the shared timeline).
- `frontend/features/dashboard/stalls/` — the blocked-transitions section:
  `data/` (`dto.ts` aliasing `BlockedTransitionResponse`, `stalls-source.ts`,
  `http/http-stalls-source.ts`, `mock/mock-stalls-source.ts`, and `index.ts` as the
  composition point), `hooks/` (`query-keys.ts`, `use-blocked-transitions.ts`),
  `lib/` (`action-map.ts` — the `trigger × blocking_state` matrix and its
  compile-time trigger guard; `stalls-error.ts` — HTTP status → locale key),
  `components/` (`blocked-transitions-section.tsx`, `cancel-cleaning-dialog.tsx`,
  `resolve-incident-dialog.tsx`) and `index.ts`, the barrel the card consumes.
- `frontend/features/cleaning/hooks/use-cancel-cleaning-task.ts` and
  `frontend/features/incidents/hooks/use-resolve-incident.ts` — the two mutations
  the card's dialogs run, each living with the resource it writes.
- `frontend/features/dashboard/lib/` — `format.ts` (localized dates, guarded
  against an unparseable timestamp),
  `timeline-event-types.ts` (the closed 47-value vocabulary and its compile-time
  exhaustiveness guard), `timeline-range.ts` (`startOfDayIso`, `endOfDayIso`,
  `isInverseRange` — the only arithmetic on this screen and where the 422 trap is);
  `state/use-timeline-filters-store.ts` (UI-only Zustand filters, including `page`
  and the range draft) and `state/use-timeline-property-store.ts` (the in-memory
  `{ tenantId, propertyId }` selection); `index.ts` (feature public entry, exporting
  `DashboardView`, `PropertyDetailView` and `TimelineView`).
- `frontend/components/property-state-badge.tsx` — the single PRD §9.1 colour map
  (`STATE_COLOR_GROUP`, `STATE_BADGE_CLASS`, `stateColorGroup()`,
  `PROPERTY_OPERATIONAL_STATES`), shared with the `/properties` index
  (`properties-crud.md`).
- `frontend/app/(workspace)/dashboard/page.tsx`,
  `frontend/app/(workspace)/properties/[id]/page.tsx`,
  `frontend/app/(workspace)/timeline/page.tsx` — compose the feature.
- `frontend/locales/{es,en}/dashboard.json`, registered in
  `frontend/lib/i18n/resources.ts`; `frontend/lib/config/constants.ts`.
