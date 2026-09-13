# Design: hardening-release

## Context

`frontend/` ya usa Playwright, pero solo como **motor de navegador de Vitest** (`@vitest/browser-playwright`, `frontend/vitest.config.ts`): el proyecto `browser` renderiza una composición aislada en Chromium para medir `scrollWidth` (`test:layout`, `shell-topbar-overflow-360`). No existe `@playwright/test` como dependencia, ni `playwright.config.ts`, ni un directorio `e2e/` — no hay ningún test que navegue varias páginas, cambie de sesión/rol o hable con el backend real.

`sdd/steering/testing.md` (líneas 12, 17-18) ya declara el contrato: E2E solo en login, ciclo de limpieza completo y ciclo de incidencia; DoD `#28.18` (tenant isolation por módulo) y `#28.19` (todas las transiciones de la state machine, incluidas las inválidas) testeados. `backend/tests/**` ya tiene un fichero de aislamiento (`test_isolation.py`/`test_tenant_isolation.py`) en **10** directorios de dominio (`auth`, `dashboard`, `maintenance`, `messaging`, `notifications`, `platform`, `properties`, `reservations`, `reviews`, `tenants` — medido el 2026-09-13; `test_redis_worker_isolation.py` no está scopado a un dominio) y `backend/tests/properties/test_state_machine.py` — la brecha no es "no hay tests", es que nadie ha confirmado que los **18** directorios de dominio de negocio bajo `backend/app/` (conteo directo del árbol, excluyendo `cli`/`core`/`provenance`/`scheduler`; ni los 19 de `README.md:311` ni los 17 de `sdd/steering/architecture.md`, esta última anterior a la incorporación de `platform`) y todas las transiciones estén realmente cubiertas.

CI ya tiene el patrón de tres jobs condicionales (`*-detect` / `*-suite` / consolidador) en `backend-tests.yml` y `frontend-tests.yml`, verificado por `scripts/check-detect-surface.py` (detectores `compose`, `frontend`, `rule11`). El runner self-hosted (`[self-hosted, dev]`) tiene 4 agentes concurrentes en la misma VM (`RUNBOOK.md` §6.2); `backend-tests.yml` ya publica Postgres/Redis en puertos fijos (`127.0.0.1:5432`/`6379`) como servicio de Actions, aceptando el riesgo de colisión entre dos ejecuciones concurrentes de sí mismo — es el mismo riesgo, no uno nuevo, el que `e2e-tests` hereda al usar el stack de `docker-compose.yml` (que también fija esos puertos).

## Decisions

### D1 — Framework E2E: `@playwright/test`, proyecto nuevo y separado de Vitest

**Chosen:** añadir `@playwright/test` como devDependency de `frontend/`, con su propio `frontend/playwright.config.ts` y specs en `frontend/e2e/*.spec.ts`. Corre con `npx playwright test` (o `npm run test:e2e`), nunca dentro de `vitest.config.ts`. Es el runner pensado para navegación multi-página y multi-sesión (login como distintos roles en la misma corrida), que el modo browser de Vitest no cubre — ese modo renderiza un componente aislado, no una app completa contra un backend real.

Rejected: extender el proyecto `browser` de Vitest para E2E — mezclaría dos unidades de prueba distintas (un componente vs. un flujo de usuario completo) en la misma config, y el modo browser de Vitest no tiene primitivas de multi-page/multi-context que el flujo de limpieza (manager reasigna, limpiadora acepta) necesita.

`playwright.config.ts` fija `use: { baseURL: 'http://localhost:3000' }` y un `globalSetup` que hace una petición HTTP directa a `http://localhost:8000/health` (backend, sin pasar por el proxy same-origin del frontend) **antes** de que corra cualquier spec: si no responde, aborta con un mensaje explícito ("el stack no está arriba — corre `make up` primero"), en vez de dejar que cada test falle por separado con un timeout de navegación genérico (R1.2). No es `/api/v1/health` — esa ruta no existe: `/health` está deliberadamente montado FUERA de `API_V1_PREFIX` (`backend/app/main.py`, comentario junto a `@app.get("/health")`), porque es el mismo endpoint que ya usa el healthcheck del contenedor en `docker-compose.yml`. Corregido durante `/sdd:run` (task 1.3) tras verificarlo contra el código real; ver `tasks.md`, Implementation Notes de la sección 1.

### D2 — Contra el stack real de `make up`, sin orquestación nueva

**Chosen:** la suite E2E asume el stack levantado por `make up` (postgres, redis, backend, worker, beat, frontend — igual que un desarrollador local) y navega contra `http://localhost:3000`. En CI, el job `e2e-tests-suite` hace `make up`, espera salud, siembra los datos mínimos (D3) y corre `npx playwright test`; el `worker` de Celery tiene que estar arriba porque la clasificación de incidencias (`classify_incidents`) y, según cómo la implemente `run`, la creación de `CleaningTask` al checkout dependen de un job async — confirmar contra el código real durante `/sdd:run`, no asumido aquí. Teardown con `make down` en un paso `if: always()`.

Rejected: levantar los servicios uno a uno con `docker compose` sueltos en el workflow (duplicaría lo que `make up` ya resuelve — overlay de worktree, `.env`, migración) — nunca aplica aquí porque el runner **no** es un worktree enlazado (es el checkout normal del runner self-hosted), así que `make up` corre en su modo "principal" tal cual.

Rejected: puertos por-runner derivados de `RUNNER_NAME` para evitar colisión entre corridas concurrentes — mecanismo nuevo para un riesgo que `backend-tests.yml` ya acepta hoy con sus puertos fijos 5432/6379 (dos corridas concurrentes de `backend-tests` ya podrían chocar entre sí en la misma VM); introducirlo solo para `e2e-tests` sería resolver a medias un problema que ya existe en el resto del CI, no una necesidad de este change. Mismo `concurrency: group: e2e-tests-${{ github.ref }}` que los otros dos workflows — no elimina el riesgo entre PRs distintos, pero es la postura ya aceptada del proyecto y queda fuera de alcance arreglarla aquí.

### D3 — Datos: `make bootstrap` + `make seed-demo`, más fixtures de API por test

**Chosen:** el job siembra una vez con los comandos que ya existen (`make bootstrap`, `make seed-demo` — crean tenant, roles y el dataset de PRD §27) y cada spec de Playwright crea por API, en su propio `test.beforeAll`, lo que necesita más allá del seed (p. ej. una `CleaningTask` pendiente para el rol correcto, si el seed no deja una en el estado exacto que el test necesita). Los tests navegan y actúan por UI — el dato de partida se prepara por API para que el test mida el flujo bajo prueba, no la fontanería de datos.

Rejected: crear todos los datos de partida por UI (p. ej. dar de alta la propiedad y la reserva desde el navegador antes de cada test) — cada spec pagaría el coste completo de flujos ya cubiertos por otros specs/tests de integración, sin verificar nada nuevo.

### D4 — CI: `e2e-tests.yml`, mismo patrón de tres jobs

**Chosen:** nuevo workflow `.github/workflows/e2e-tests.yml` con el mismo patrón que `backend-tests.yml`/`frontend-tests.yml`: `e2e-tests-detect` (siempre corre, decide por diff), `e2e-tests-suite` (condicional), `e2e-tests` (consolidador, `if: always()`, es el contexto marcable). Superficie de detección: `backend/**`, `frontend/**`, `docker-compose.yml`, `Makefile`, `frontend/e2e/**`, este propio workflow. Se añade un detector `e2e` a `scripts/check-detect-surface.py` (mismo mecanismo que `frontend_surface()`) para que el invariante detect-surface ⊇ suite-input-surface se compruebe también aquí — sin él, la garantía fail-closed de R1.3 quedaría sin verificar para este workflow nuevo.

Rejected: añadir los específicos E2E como un job más dentro de `frontend-tests.yml` — el arranque del stack completo (backend+worker+beat+postgres+redis) es una dependencia mucho más pesada que `npm ci`, y mezclarla forzaría a `frontend-tests` (rápido, sin stack) a esperar por algo que hoy no necesita.

### D5 — Auditoría del DoD: documento nuevo, no comentarios sueltos

**Chosen:** `docs/dod-audit.md` — una tabla por ítem de PRD §28 (los 20), con su evidencia (test/archivo/comando) o el hueco cerrado en este mismo change. Las dos filas obligatorias del proposal (`#28.18`, `#28.19`) llevan detalle: una tabla de los 18 directorios de dominio de negocio bajo `backend/app/` (conteo directo, ver Context) con su fichero de test de aislamiento — y, de paso, la corrección de la cifra desactualizada en `README.md:311` (19, con un roster que ya no incluye `statements`) o `sdd/steering/architecture.md` (17) —, y una tabla de las transiciones de `PropertyStateMachine` (válidas e inválidas) con su test. Vinculado desde `README.md` (sección DoD, si no existe, se añade una línea).

Rejected: dejar la auditoría como hallazgos sueltos en el PR — se pierde en cuanto el PR se archiva; un documento versionado es lo que permite a una lectura futura no re-auditar desde cero (motivo explícito del R5.3 del proposal).

## Changes by area

| Area | Files | Change |
|---|---|---|
| Frontend E2E | `frontend/package.json`, `frontend/playwright.config.ts` (nuevo), `frontend/e2e/login.spec.ts`, `frontend/e2e/cleaning.spec.ts`, `frontend/e2e/incident.spec.ts`, `frontend/e2e/fixtures/*.ts` | Nueva dependencia `@playwright/test`; nuevo script `test:e2e`; tres specs (R2-R4) |
| CI | `.github/workflows/e2e-tests.yml` (nuevo), `scripts/check-detect-surface.py` | Workflow de 3 jobs; nuevo detector `e2e` |
| Backend tests | `backend/tests/<dominio>/test_isolation.py` (los que falten), `backend/tests/properties/test_state_machine.py` | Cerrar huecos reales que la auditoría de D5 encuentre |
| Documentación | `docs/dod-audit.md` (nuevo), `README.md` | Auditoría §28 y referencia desde el README |

## Data & interfaces

Ninguno nuevo en el backend (ni schema ni endpoint): los specs E2E consumen la API pública ya existente para su fixture de datos y la UI para el flujo bajo prueba. `frontend/package.json` gana `@playwright/test` como devDependency y el script `test:e2e`.

## Risks & mitigations

- **Flakiness de E2E contra un stack real** (timing de Celery, sondeo de mensajería): usar `expect.poll`/`waitFor` de Playwright sobre el estado observable (UI o API), nunca `sleep` fijo; si un flujo depende de un job periódico, dispararlo a mano con los comandos ya existentes (`make sim-advance`, `make pms-sync`) en vez de esperar al scheduler real.
- **Coste/duración**: arrancar el stack completo (~similar a `make up` local) añade minutos al PR frente a `backend-tests`/`frontend-tests`; mitigado por ser condicional (D4) igual que los otros dos.
- **Colisión de puertos entre corridas concurrentes en el mismo runner**: riesgo ya aceptado por `backend-tests.yml` (D2); no se introduce mitigación nueva aquí, por ser un problema preexistente del CI y no de este change.
- **La auditoría de D5 encuentra más huecos de los esperados** (p. ej. un dominio de los 18 sin ningún test de aislamiento): si el hueco es grande, tratarlo como una nueva tarea de `tasks.md` con su propio test, no como hallazgo de review sin cerrar.

## Open questions

Ninguna: los cinco requisitos del proposal tienen decisión (D1-D5) y ninguna depende de un juicio que solo el humano pueda hacer — la política de concurrencia de CI (D2) sigue el precedente ya establecido por `backend-tests.yml`/`frontend-tests.yml` en vez de abrir una decisión nueva.
