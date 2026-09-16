# Proposal: owner-incident-create

## Why

PRD §12 y DoD §28.8 exigen que la propietaria pueda reportar una incidencia desde el producto. En main existen la entidad, la clasificación, la lista/detalle y las mutaciones de triaje, pero no existe una entrada autenticada para que la propietaria cree una incidencia ni una UI que la exponga. Sin ella, el propietario del piso no puede iniciar desde AutoHostAI un flujo operativo necesario cuando detecta una avería.

## What changes

Añadir el flujo autenticado propietario → nueva incidencia: formulario en la superficie real del dashboard, endpoint backend con autorización y aislamiento por tenant, creación auditable en estado `OPEN`, y actualización de la timeline de la vivienda. La clasificación existente seguirá ejecutándose de forma asíncrona; el change no sustituye el flujo de huésped, limpiadora, conversación ni el triaje posterior.

## Requirements

### R1 — Creación autenticada de incidencia

**As a** TENANT_OWNER, **I want** to report an incident for one of my properties with a title and description, **so that** the operating team can act on a problem I have detected.

Acceptance criteria:

1. WHEN an authenticated owner submits a valid property, title, and description to the incident-creation endpoint, THE SYSTEM SHALL create one incident for the request tenant with source `OWNER` and status `OPEN`, and SHALL return the created incident.
2. IF the property does not belong to the request tenant or the caller is not allowed to operate that property, THEN THE SYSTEM SHALL reject the request without creating or exposing an incident.
3. THE SYSTEM SHALL validate and bound the user-provided text using the existing incident input rules, and SHALL derive the reporter identity and tenant from the authenticated request rather than accepting them from the client.

### R2 — Auditable operational handoff

**As a** property operator, **I want** an owner-created incident to appear in the same operational flow as other incidents, **so that** it can be classified, triaged, assigned, and resolved without a side channel.

Acceptance criteria:

1. WHEN the owner-created incident is committed, THE SYSTEM SHALL write the corresponding audit record and `INCIDENT_CREATED` timeline event atomically within the existing transaction boundary, without prescribing new transaction infrastructure.
2. THE SYSTEM SHALL enter every `OWNER` incident into the existing classification pipeline without source-specific special-casing, and SHALL continue it through the existing operational flow.
3. THE SYSTEM SHALL leave classification to the existing periodic classifier and SHALL not invoke an AI adapter synchronously from the creation request.
4. THE SYSTEM SHALL expose the created incident through the existing incident list/detail and dashboard projections subject to their existing permissions and tenant scoping.

### R3 — Owner-facing entry point

**As a** property owner using the dashboard, **I want** an explicit report-incident action and form, **so that** I can start the incident flow from the mobile dashboard without contacting an external operator.

Acceptance criteria:

1. WHEN the owner opens the report action for an owned property, THE SYSTEM SHALL show fields for the incident title and description, with translated ES/EN labels, validation, loading, success, and error states.
2. WHEN creation succeeds, THE SYSTEM SHALL give the owner a usable confirmation and the created incident identifier or detail destination.
3. IF creation fails, THE SYSTEM SHALL preserve the entered text where safe, show an actionable translated error, and SHALL not present the incident as created.

### R4 — Verificación del flujo completo

**As a** product owner, **I want** the owner incident flow verified at backend, frontend, and E2E boundaries, **so that** the pilot can rely on the complete operational handoff.

Acceptance criteria:

1. THE SYSTEM SHALL have backend verification covering authenticated creation, RBAC, tenant isolation including cross-tenant rejection, `AuditLog`, and `TimelineEvent`.
2. THE SYSTEM SHALL have frontend verification covering the form, validation, success and error states, and safe preservation of entered input.
3. THE SYSTEM SHALL have E2E verification covering `TENANT_OWNER` creates an incident, the incident appears in the existing surface, and it remains available to the normal classification/triage flow.

## Out of scope

- Guest, cleaner, and conversation-based incident creation; those flows already exist in their own changes.
- Manager triage, technician assignment, approvals, messaging, notifications, and incident status tone; they are existing capabilities or separate follow-ups.
- Replacing the periodic classifier or introducing a real AI provider.
- New CI, runner, gate, refactor, or general incident hardening work.

## Affected specs

- `sdd/specs/maintenance.md`
- `sdd/specs/dashboard-web-frontend.md`
- `sdd/specs/auth-tenancy.md`
- `sdd/specs/api-contract.md`
