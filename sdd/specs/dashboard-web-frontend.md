# Dashboard Web (Frontend)

## Purpose

The read-only presentation layer of the owner/manager dashboard (PRD §9): the
property-cards overview (`/dashboard`, §9.1) and the property detail page
(`/properties/[id]`, §9.2) with its per-property timeline (§10). It renders
inside the existing WorkspaceShell and consumes all data through a typed
data-access boundary (`DashboardDataSource`) whose only implementation today is a
mock with fixed data for the two dev properties (REDES11, PAJARITOS8). The
aggregate backend it was shaped against **now exists** — `dashboard-api` shipped
the four read endpoints (see `specs/dashboard-api.md`) — so what remains is the
swap itself: replacing the mock at the composition point with an HTTP
implementation, which is `dashboard-web`'s half and changes no UI, hook or query
key.

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

### Property timeline (§10)

- WHEN the timeline renders, THE SYSTEM SHALL show its entries in the immutable
  order the data source returns them, each in the active locale, with its
  localized actor and severity labels.
- THE SYSTEM SHALL offer filtering by event type, actor, and severity; the
  selected filters are threaded into the tenant-scoped query key so each
  combination is cached distinctly, and the event-type options are derived from an
  unfiltered companion query so they never collapse to the selected type.
- THE SYSTEM SHALL hold the timeline filter selections as lightweight UI state in
  Zustand and SHALL NOT store timeline entries (server state) there; filters reset
  when the property changes.

### Swappable data source (`DashboardDataSource`)

- THE SYSTEM SHALL define a typed `DashboardDataSource` interface whose methods
  return DTOs replicating the real API contract (PRD §23 data envelope, error
  envelope surfaced as `ApiError`, ISO-8601 UTC dates), aligned with the routes
  `dashboard-api` now serves: `GET /api/v1/dashboard/properties` (the cards
  collection), `/api/v1/properties/{id}/dashboard`, `/api/v1/properties/{id}/state`
  and `/api/v1/timeline/{property_id}`.
- THE SYSTEM SHALL resolve the data source through a single composition point, so
  that the current `MockDashboardSource` (fixed REDES11/PAJARITOS8 data, isolated
  in a dedicated module) can be replaced by an HTTP implementation without
  changing the UI, the hooks, or the query keys.
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

### Quality

- WHEN the frontend is verified, THE SYSTEM SHALL pass type-check, lint, the
  colocated test suite, and a production build without a running backend.

## Explicit debt (ASSUMPTION)

- The mock stands in for the app's own aggregate dashboard backend, which
  `dashboard-api` delivered (roadmap `dashboard-api`, `specs/dashboard-api.md`);
  replacing `MockDashboardSource` with an HTTP implementation at the composition
  point is tracked debt owned by roadmap `dashboard-web`, marked `ASSUMPTION` in
  code. This deliberately inverted the API-first norm for this slice — the
  inversion is now resolved on the backend side and outstanding only on the
  frontend's.
- `tenantId` comes from a single centralized dev constant (`DEV_TENANT_ID`) until
  session-derived tenancy exists (roadmap `auth-tenancy`); it is a non-sensitive
  placeholder, not a credential.
- The timeline renders fixed data until the HTTP swap. Real-time streaming is
  still absent on both sides: `dashboard-api` delivered the timeline as a
  filtered, paginated **read**, and explicitly left push (WebSocket/SSE) out of
  scope, so PRD §9.2's "tiempo real" is not met by either half yet.

## Key files

- `frontend/features/dashboard/data/` — `dto.ts` (§23-shaped DTOs),
  `dashboard-source.ts` (the interface), `index.ts` (composition point),
  `mock/{fixtures,mock-dashboard-source}.ts` (the sole, isolated implementation).
- `frontend/features/dashboard/hooks/` — `query-keys.ts` (tenant-scoped keys),
  `use-dashboard-data.ts` (`useDashboardCards`/`usePropertyDetail`/
  `usePropertyTimeline` + `retryPolicy`).
- `frontend/features/dashboard/components/` — `property-card.tsx`,
  `dashboard-view.tsx`, `detail/{property-detail-view,property-detail-sections,
  property-timeline}.tsx`.
- `frontend/features/dashboard/lib/` — `state-color.ts` (PRD §9.1 map),
  `format.ts` (localized dates); `state/use-timeline-filters-store.ts` (UI-only
  Zustand filters); `index.ts` (feature public entry).
- `frontend/app/(workspace)/dashboard/page.tsx`,
  `frontend/app/(workspace)/properties/[id]/page.tsx` — compose the feature.
- `frontend/locales/{es,en}/dashboard.json`, registered in
  `frontend/lib/i18n/resources.ts`; `frontend/lib/config/constants.ts`
  (`DEV_TENANT_ID`).
