# Dashboard Web (Frontend)

## Purpose

The read-only presentation layer of the owner/manager dashboard (PRD §9): the
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
  regions in this priority order: operational state, open incidents, next
  action, reservation and guest, cleaning, and last event.
- WHEN cards with different amounts of content are shown in the same grid, THE
  SYSTEM SHALL keep their headers, primary regions, and detail links visually
  aligned without hiding required values or introducing horizontal overflow.
- WHEN the viewport is desktop, tablet, or mobile, THE SYSTEM SHALL reflow the
  card grid and its internal content while preserving the same hierarchy and
  readable wrapping in the active locale.
- WHEN a user navigates the card with a keyboard, THE SYSTEM SHALL preserve
  native semantics, a visible focus indicator, and the localized accessible
  name of the property-detail link.

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
- `tenantId` comes from a single centralized dev constant (`DEV_TENANT_ID`) until
  session-derived tenancy exists (roadmap `auth-tenancy`); it is a non-sensitive
  placeholder, not a credential.
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
- `frontend/features/dashboard/lib/` — `format.ts` (localized dates),
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
  `frontend/lib/i18n/resources.ts`; `frontend/lib/config/constants.ts`
  (`DEV_TENANT_ID`).
