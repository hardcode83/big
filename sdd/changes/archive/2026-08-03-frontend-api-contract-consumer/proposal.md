# Proposal: frontend-api-contract-consumer

## Why

`frontend/lib/api/client.ts` devuelve `unknown` deliberadamente porque el consumidor todavía no
usa el contrato OpenAPI que el backend ya versiona en `backend/openapi.json`. Eso deja sin
garantía estática la forma de las respuestas y permite que el contrato y el código TypeScript
deriven silenciosamente. Este change cierra esa frontera consumiendo exclusivamente el artefacto
OpenAPI existente, sin alterar el backend ni inventar una integración funcional con endpoints.

## What changes

El frontend incorporará un flujo reproducible para derivar tipos TypeScript desde
`backend/openapi.json`, versionará el resultado generado y lo integrará en `frontend/lib/api/`.
El transporte HTTP dejará de exponer `unknown` como tipo deliberado en su API pública, manteniendo
sus puntos de extensión de autenticación, manejo de errores y `fetch` inyectable. Un gate de CI
regenerará los tipos y fallará con un diagnóstico reproducible si no coinciden con el contrato
versionado. Las superficies de UI seguirán sin conectarse a endpoints reales.

## Requirements

### R1 — Tipos derivados del contrato versionado

**As a** frontend developer, **I want** to generate TypeScript types from the versioned
`backend/openapi.json`, **so that** the frontend's API shape has one authoritative source.

Acceptance criteria:

1. WHEN the documented generation command runs against `backend/openapi.json`, THE SYSTEM SHALL
   produce the TypeScript type artifact used by `frontend/lib/api/`.
2. THE SYSTEM SHALL use exactly one official OpenAPI-to-TypeScript generator for this change, with
   its version pinned in the frontend dependency manifest and lockfile; the concrete tool choice
   SHALL be decided during Design.
3. WHEN a developer performs a clean installation, THE SYSTEM SHALL obtain the same generator
   version and produce the same generated output; THE SYSTEM SHALL not generate types by
   introspecting a running backend, calling an endpoint, or maintaining a second hand-written API
   schema.

### R2 — Cliente API tipado

**As a** frontend developer, **I want** the centralized API client to use the generated types,
**so that** request and response shapes are checked at compile time.

Acceptance criteria:

1. WHEN a caller uses the public API client contract, THE SYSTEM SHALL expose generated OpenAPI
   types instead of an intentional `unknown` response type.
2. THE SYSTEM SHALL preserve the existing transport boundaries: base URL joining, injectable
   `fetch`, header and unauthorized hooks, JSON serialization, 204 handling, and `parseApiError`.
3. THE SYSTEM SHALL not add endpoint-specific business logic, real dashboard integration, token
   persistence, or backend coupling to the client.
4. THE SYSTEM SHALL not create endpoint-specific wrappers such as `ReservationsApi`, `CleaningApi`,
   or `UserApi`, nor repositories, domain services, or other endpoint wrappers; the scope SHALL end
   at `OpenAPI → generated types → generic HTTP client`.

### R3 — Detección reproducible de deriva

**As a** reviewer, **I want** CI to compare regenerated types with the versioned artifact,
**so that** stale generated code cannot merge silently.

Acceptance criteria:

1. WHEN a Pull Request is opened or updated, or code is pushed to `main`, THE SYSTEM SHALL run a
   CI gate that regenerates the types from the committed OpenAPI contract.
2. IF the regenerated output differs from the versioned generated artifact, THEN THE SYSTEM SHALL
   fail the gate and show the difference together with the exact local regeneration command.
3. THE SYSTEM SHALL use the same versioned generation command locally and in CI, without changing
   `backend/openapi.json` or generating from a different source.

### R4 — Compatibilidad y verificación del frontend

**As a** maintainer, **I want** the typed consumer to preserve the existing frontend behavior,
**so that** adopting the contract does not expand this change into a feature integration.

Acceptance criteria:

1. WHEN the frontend checks run, THE SYSTEM SHALL keep lint, TypeScript typecheck, Vitest tests,
   and production build green.
2. THE SYSTEM SHALL modify existing mocks or fixtures only where required to satisfy the new
   compile-time types, without changing their intended scenarios.
3. THE SYSTEM SHALL not modify backend code, the OpenAPI contract, or existing functional UI
   behavior as part of this change.

### R5 — Flujo documentado y desacoplado

**As a** contributor, **I want** the generation and drift-check commands documented,
**so that** updating the contract consumer is routine and independent of backend runtime access.

Acceptance criteria:

1. THE SYSTEM SHALL document the source contract, generated artifact location, generation command,
   and drift-check command in the repository's developer documentation.
2. THE SYSTEM SHALL keep all generated types and API transport code under the frontend API
   boundary, without importing backend implementation modules.
3. WHEN the documented generation command runs on macOS, Linux, or CI, THE SYSTEM SHALL produce
   exactly the same generated artifacts, byte for byte, independent of platform-specific behavior.

## Out of scope

- Modificar el backend o regenerar/cambiar `backend/openapi.json`.
- Conectar el dashboard u otra superficie de UI a endpoints reales.
- Añadir lógica funcional de negocio, autenticación completa, persistencia de tokens o nuevos
  endpoints.
- Generar SDKs para otros lenguajes o publicar el contrato fuera del repositorio.
- Cambiar mocks existentes salvo los ajustes mínimos necesarios para compilar.
- Convertir el gate en un check obligatorio de protección de rama.
- Absorber el gate general de Vitest/ESLint/typecheck de `frontend-ci`; este change solo añade la
  comprobación específica de deriva contrato↔tipos.

## Affected specs

- `sdd/specs/api-contract.md` — actualizar la sección de consumo para reflejar que el frontend
  deriva y usa los tipos versionados.
- `sdd/specs/frontend-foundation.md` — actualizar la frontera de `lib/api` para sustituir el
  `unknown` deliberado por tipos derivados, manteniendo el transporte genérico.
- `sdd/specs/frontend-api-contract-consumer.md` — *(no existe aún — se creará al archivar)*:
  generación, integración y gate de deriva del consumidor.
