# Tasks: reservation-manual-guest-resolution

## 1. Contrato de identidad y resolver compartido <!-- panel: PASS 2026-09-10 receipt:5e3af2fc -->

- [x] 1.1 Definir la entrada tipada de identidad manual y el contrato de aplicación del servicio `ResolveOrCreateGuest` en `backend/app/guests/application/`; conservar email normalizado como único criterio automático, crear Guest solo cuando no haya coincidencia y no actualizar ningún campo al reutilizarlo [R1, R2, R5]
- [x] 1.2 Implementar `ResolveOrCreateGuest` usando `GuestRepository`, con creación de `full_name` validado, email/teléfono/idioma normalizados y selección determinista `created_at, id` cuando existan duplicados históricos [R1, R2]
- [x] 1.3 Añadir tests unitarios del resolver en `backend/tests/guests/` para reutilización por email, creación sin coincidencia, ausencia de email, no matching por nombre/teléfono, preservación de datos del Guest reutilizado y duplicados históricos sin merge [R1, R2, R5]

## 2. Exclusión transaccional PostgreSQL <!-- hard --> <!-- panel: PASS 2026-09-10 receipt:7d304c7f -->

- [x] 2.1 Declarar el port estrecho de exclusión `(tenant_id, normalized_email)` sin importar SQLAlchemy/PostgreSQL desde `domain/` o `application/`, y preparar su fake para tests [R3]
- [x] 2.2 Implementar el adapter PostgreSQL en `backend/app/guests/infrastructure/` con `pg_advisory_xact_lock` sobre la transacción existente; ejecutar el lock inmediatamente antes del segundo `find_by_email` y `add`, y omitirlo para email ausente [R3]
- [x] 2.3 Implementar y testear la clave estable con UUID canónico + `"\0"` + email normalizado, SHA-256 y primeros 8 bytes big-endian con signo de 64 bits; no usar `hash()` de Python ni valores dependientes del proceso [R3]
- [x] 2.4 Añadir integración/wiring del adapter a las dependencias de Guest, reservations e integrations sin crear una conexión o una UoW paralela [R3]
- [x] 2.5 Añadir tests de concurrencia con dos sesiones PostgreSQL que demuestren bloqueo, visibilidad posterior al commit y obtención del mismo `guest_id`, incluyendo aislamiento entre tenants [R3]

## 3. Alta manual atómica <!-- hard --> <!-- panel: PASS 2026-09-10 receipt:cf33e0b9 -->

- [x] 3.1 Añadir el modelo `guest` opcional y la validación de exclusión mutua en `backend/app/reservations/api/schemas.py`: `guest_id` o `guest`, nunca ambos; cubrir en `backend/tests/reservations/` que solo `guest_id` es válido, solo `guest` es válido, ninguno es válido y permite reserva guest-less, y `guest_id + guest` responde `422` sin escrituras [R4]
- [x] 3.2 Implementar las validaciones explícitas de `guest` —`full_name` trimado de 1–300 caracteres, email opcional trim/lowercase, teléfono normalizado, idioma `es|en` con default `es`— y mantener tests de contrato en `backend/tests/reservations/` para los cuatro casos de combinación anteriores, además de tests de 422 y ausencia de escrituras para cada campo inválido [R4]
- [x] 3.3 Integrar `ResolveOrCreateGuest` en `CreateReservationUseCase` en `backend/app/reservations/application/use_cases.py`, manteniendo el `guest_id` existente, la comprobación tenant-scoped y el camino guest-less [R1, R2, R4]
- [x] 3.4 Garantizar que Guest creado, Reservation y `RESERVATION_CREATED_MANUAL` compartan la UoW y el único commit del caso de uso; añadir tests de rollback conjunto ante fallo de cada etapa [R3]
- [x] 3.5 Verificar en `backend/app/reservations/api/router.py` el permiso `MANAGE_RESERVATIONS`; mapear los errores de contrato/validación al envelope 422 existente cuando corresponda, mantener el 404 existente para `guest_id` inexistente o fuera del tenant y dejar los fallos del adapter PostgreSQL/advisory lock en la política interna de errores de infraestructura, sin filtrar SQL, claves de lock ni detalles de implementación [R4]

## 4. Integración de ingest sin semántica duplicada <!-- hard --> <!-- panel: PASS 2026-09-10 receipt:970a8abd -->

- [x] 4.1 Revisar todos los call sites productivos de creación/resolución de Guest y registrar en tests o wiring que `ReservationIngestor._link_guest` es el writer conocido que adopta el resolver; mantener fuera el Guest Portal sin email y el seed controlado [R3, R5]
- [x] 4.2 Sustituir únicamente la política duplicada de `_link_guest` en `backend/app/integrations/application/ingest.py` por `ResolveOrCreateGuest`, conservando DTO mapping, defaults, guest-less rows y reporting específico de ingest [R1, R2, R3]
- [x] 4.3 Añadir tests de integración en `backend/tests/integrations/` para reutilización/no duplicación, no actualización de Guests existentes, tenant isolation y comportamiento de filas sin email [R1, R2, R3]
- [x] 4.4 Verificar que el advisory lock se adquiere lo más tarde posible, inmediatamente antes del segundo `find_by_email`/`add`, que no se adquiere si no hay email y que no se libera manualmente al terminar la resolución; al ser transaction-scoped permanece hasta el commit/rollback de la UoW exterior, sin introducir commits intermedios. Añadir observabilidad del tiempo de espera con métricas/logging únicamente técnicos: no registrar email normalizado, nombre, teléfono ni ninguna otra PII del Guest, respetando las reglas de seguridad existentes [R3]

## 5. Contrato publicado y especificaciones <!-- panel: PASS 2026-09-10 receipt:44240b41 -->

- [x] 5.1 Actualizar los errores, response mapping y wiring necesarios para que la respuesta de creación conserve `guest_id` nullable o resuelto y los clientes actuales que envían solo `guest_id` sigan funcionando [R4]
- [x] 5.2 Regenerar `backend/openapi.json` con `make openapi` y `frontend/lib/api/generated/openapi.d.ts` con `cd frontend && npm run api:generate`; verificar que ambos artefactos describen el nuevo request y sus restricciones [R4]
- [x] 5.3 Dejar documentada dentro de `sdd/changes/reservation-manual-guest-resolution/` la información de archivado necesaria para actualizar posteriormente `sdd/specs/reservations.md` y `sdd/specs/domain-foundation-core.md`, incluyendo contrato manual, resolución application-level, selección histórica determinista y ausencia deliberada de UNIQUE/merge; indicar también si procede crear o actualizar una futura `sdd/specs/ingest.md`. No modificar `sdd/specs/` durante `/sdd:run` [R2, R3, R4, R5]

## 6. Verification

- [x] 6.1 Ejecutar la suite backend completa: `docker compose run --rm backend uv run pytest`
- [x] 6.2 Ejecutar pyright backend: desde `backend`, `uv sync --frozen` y `uv run pyright .`; verificar que el change no introduce diagnósticos nuevos frente al baseline Pyright existente
- [x] 6.3 Verificar el contrato frontend: `cd frontend && npm run api:check`
- [x] 6.4 Ejecutar la guardia de ownership documental por los cambios en `sdd/`: `make check-rule11-ownership`
- [x] 6.5 Revisar el diff final y confirmar que no hay migración UNIQUE, merge histórico, Guest Portal, guest-management ni `reservation-create-web` dentro del change

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->

- `ManualGuestIdentityInput` is the normalized application input; it trims/validates `full_name`, canonicalizes optional email/phone, and restricts language to `es|en`.
- `ResolveOrCreateGuest.execute` returns a `guest_id`, depends only on the existing `GuestRepository`, and never saves or mutates a reused Guest.
- `GuestRepository.find_by_email` remains the owner of historical duplicate selection (`created_at`, then `id`); section 1 adds no resolution/exclusion port and performs no merge.
- Focused verification: `pytest tests/guests/test_guest_resolution.py tests/guests/test_repositories.py -q` — 28 passed; focused Pyright — 0 errors.
- `GuestEmailExclusion` is a domain port; `PostgresGuestEmailExclusion` receives only the caller-owned `AsyncSession` and never commits or opens a parallel transaction.
- Resolver ordering is first lookup, advisory lock, second lookup, then add; absent email bypasses both lookup and lock, and historical duplicate choice remains in `GuestRepository.find_by_email`.
- Advisory key vector uses canonical UUID text + `chr(0)` byte separator + normalized email, SHA-256 first eight bytes as signed big-endian int64; no Python process hash.
- Production manual-reservation, CSV/PMS ingest, CLI sync and scheduled sync composition roots inject the PostgreSQL adapter; controlled seed remains outside this writer path.
- `docker compose run --rm backend uv run pytest tests/guests/test_guest_resolution.py tests/guests/test_guest_email_exclusion.py tests/integrations/test_import_csv.py tests/integrations/test_sync.py tests/reservations/test_use_cases.py -q` — 71 passed.
- `docker compose run --rm backend uv run pytest tests/guests/test_guest_email_exclusion.py -q` — 5 passed, including two-session PostgreSQL blocking, post-commit visibility and tenant isolation.
- `docker compose run --rm backend uv run pyright app/guests/domain/ports.py app/guests/application/resolution.py app/guests/infrastructure/postgres_guest_email_exclusion.py app/integrations/application/ingest.py app/integrations/application/use_cases.py app/reservations/application/use_cases.py app/reservations/api/dependencies.py app/integrations/api/dependencies.py app/integrations/cli/pms_sync.py app/scheduler/tasks.py` — 0 errors.
- `docker compose run --rm backend uv run pytest tests/test_layering.py tests/guests/test_guest_email_exclusion.py -q` — 1524 passed.
- Remediation: `ResolveOrCreateGuest` and `ReservationIngestor` require caller-injected `GuestEmailExclusion`; production roots use `PostgresGuestEmailExclusion`, unit tests use explicit fakes.
- Remediation: ingest trims `guest_email` before presence testing and fallback identity; whitespace-only contact data remains guest-less.
- Verification remediation: `backend/tests/guests/test_guest_resolution.py` now checks the required `exclusion` constructor parameter via `inspect.signature`, preserving the contract without a statically invalid call.
- Verification evidence: `docker compose run --rm backend uv run pytest tests/guests/test_guest_resolution.py -q` — 8 passed; focused Pyright for resolver and test — 0 errors; full Pyright remains baseline-blocked at 957 errors.
- Remediation: `CreateReservationUseCase` now requires the transactional exclusion and constructs `ResolveOrCreateGuest` from the caller-owned guest repository; Section 3 remains responsible for invoking it with request identity.
- `ManualGuestRequest` enforces trim/normalization and guest-vs-guest_id exclusivity before the use case, preserving the existing VALIDATION_ERROR envelope.
- `CreateReservationUseCase` resolves guest blocks before Reservation creation and passes the resolved id through the existing tenant-scoped guest check; guest_id-only and guest-less paths remain unchanged.
- Focused verification: `docker compose run --rm backend uv run pytest tests/reservations/test_api.py tests/reservations/test_use_cases.py tests/reservations/test_atomicity.py -q` — 66 passed.
- Focused Pyright: `docker compose run --rm backend uv run pyright app/reservations/api/schemas.py app/reservations/application/use_cases.py` — 0 errors; router baseline still reports 5 pre-existing tenant-nullability findings.
- `git diff --check` — passed; router declares existing `MANAGE_RESERVATIONS` dependency and existing reservation error handlers preserve 422/404/internal envelopes.
- Authorization/error contract verification: `docker compose run --rm backend uv run pytest tests/test_route_authorization.py tests/reservations/test_api.py -q` — 51 passed.
- Remediation: Section 3 API invalid guest payloads assert unchanged Guest and Reservation counts; tenant-scoped email reuse and absent/blank-email identity non-matching are covered end to end.
- Remediation: Section 3 real-Postgres creation failures at reservation write, timeline write, and commit stages assert Guest, Reservation, and Timeline rollback together.
- Section 4 writer inventory is recorded on `ReservationIngestor`: ingest adopts the resolver; Guest Portal's no-email creation and controlled demo seed remain outside this policy.
- Section 4 ingest delegates `_link_guest` to `ResolveOrCreateGuest`, preserving DTO defaults, guest-less rows, reservation mapping, and ingest reporting.
- Section 4 integration coverage verifies email reuse without duplication, no updates to reused Guest contact fields, tenant isolation, and whitespace-only email guest-less rows.
- Section 4 advisory-lock telemetry records only technical wait duration; no Guest identifiers or contact PII are logged, and the adapter neither commits nor releases the transaction-scoped lock.
- Focused verification: `docker compose run --rm backend uv run pytest tests/integrations/test_sync.py tests/integrations/test_import_csv.py tests/guests/test_guest_email_exclusion.py -q` — 41 passed.
- Focused Pyright: `docker compose run --rm backend uv run pyright app/guests/infrastructure/postgres_guest_email_exclusion.py app/integrations/application/ingest.py app/integrations/application/use_cases.py app/integrations/cli/pms_sync.py app/scheduler/tasks.py` — 0 errors; `git diff --check` passed.
- Rule 11 ownership guard: `make check-rule11-ownership` — passed.
- Section 5.1 compatibility/error verification: `docker compose run --rm --no-deps -T backend uv run pytest tests/reservations/test_api.py tests/reservations/test_use_cases.py tests/reservations/test_atomicity.py tests/test_route_authorization.py -q` — 92 passed.
- Section 5.2 generation: `make openapi` — passed; `cd frontend && npm run api:generate` — host failed with missing `openapi-typescript`, then documented container workaround passed.
- Section 5.2 contract verification: `docker compose run --rm --no-deps -T backend uv run pytest tests/test_openapi_contract.py -q` — 14 passed after one transient Docker socket permission failure and escalated retry.
- Section 5.2 remediation: `ManualGuestRequest` now publishes full-name length, language enum, and non-semantic email/phone normalization descriptions; `tests/test_openapi_contract.py` asserts the published constraints; focused reservation/contract suite — 86 passed; frontend `npm run api:check` — passed.
- Verification: full backend suite `docker compose run --rm backend uv run pytest` — 10940 passed, 44 skipped; host `uv sync --frozen && uv run pyright .` unavailable because `uv` is not installed, container `uv sync --frozen && uv run pyright .` — 957 baseline errors; host `npm run api:check` lacks `openapi-typescript`, documented frontend-container workaround — PASS; `make check-rule11-ownership` — PASS; final forbidden-path scan and `git diff --check` — PASS.
- Verification adjustment authorized by user: baseline checkout at `bdd548f2fce57027d78122b88b0f985ef5cffd1` and current tree both report 957 Pyright errors with version 1.1.411; the only change-introduced diagnostic was fixed in `tests/guests/test_guest_resolution.py:29`, and the current full comparison introduces zero new diagnostics.
- Section 5.3 archive notes: `sdd/changes/reservation-manual-guest-resolution/archive-notes.md` records deferred living-spec updates; `sdd/specs/` remained unchanged.
