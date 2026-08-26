# Tasks: blocked-transition-response-ids

## Scope dependency

Esta change es **prerequisito** para que `blocked-transitions-web` §5 (mutaciones: cancel
cleaning task, resolve incident) pueda arrancar: hasta que `BlockedTransitionResponse`
no lleve `cleaning_task_id` e `incident_id`, los hooks del frontend quedan tipados contra
campos que la respuesta no trae y typecheck se pone rojo. La desbloquea, no la implementa
— `blocked-transitions-web` retoma su propia rama cuando este PR esté mergeado en `main`.

## 1. Schema extension — dos ids opcionales en `BlockedTransitionResponse` <!-- panel: PASS 2026-08-26 -->

- [x] 1.1 En `backend/app/properties/api/schemas.py`, añadir a `BlockedTransitionResponse`
      (`líneas 413-417`) dos campos opcionales: `cleaning_task_id: uuid.UUID | None = None`
      e `incident_id: uuid.UUID | None = None`, debajo de `due_since` y antes del cierre
      del modelo. Confirmar que `extra="forbid"` no los rechaza — están declarados, no
      extra. [R1.1]
- [x] 1.2 Test unitario: instanciar `BlockedTransitionResponse` con los seis campos
      originales + ambos ids en `None`, verificar serialización JSON con `null` literal
      (no cadena vacía, no `"null"`, no `0`). Mismo test con uno de los ids poblado y el
      otro en `None`. Fichero: `backend/tests/properties/test_blocked_transition_response.py`
      (nuevo, alineado con el resto de tests de `properties/`). [R1.2, R1.3, R1.4]

## 2. Plumbing — los ids llegan a `BlockedTransitionRow` <!-- panel: PASS 2026-08-26 -->

- [x] 2.1 En `backend/app/properties/application/use_cases.py`, ampliar el dataclass
      `BlockedTransitionRow` (`línea 442`) con dos campos opcionales: `cleaning_task_id:
      uuid.UUID | None = None` e `incident_id: uuid.UUID | None = None`. **No tocar
      `BlockedTransition`** (la entidad de dominio se queda pura — propuesta §Out of scope).
      [R1.1, R2]
- [x] 2.2 En `backend/app/properties/application/use_cases.py`, dentro de
      `ListBlockedTransitionsUseCase` (línea 455 en adelante), invocar un nuevo método
      `resolve_action_ids(rows, tenant_id, now)` antes del sort. La signatura devuelve un
      mapeado `(property_id, blocking_state) → (cleaning_task_id | None, incident_id |
      None)`. **Una sola pasada batch** sobre las filas por tenant (R3.4: prohibido N+1).
      [R3.1, R3.2, R3.4]
- [x] 2.3 Implementar el resolver en `backend/app/properties/application/action_id_resolver.py`
      (nuevo). Recibe `tenant_id` y la tupla de `(property_id, blocking_state)` y devuelve
      el par de ids. Reglas:
      - si `blocking_state ∈ {AWAITING_CLEANING, CLEANING_IN_PROGRESS, CLEANING_SCHEDULED}`
        → consulta `cleaning_tasks` por `(tenant_id, property_id, status=OPEN)` y devuelve
        `(cleaning_task_id, None)`;
      - en otro caso → consulta `incidents` por `(tenant_id, property_id, status=OPEN)` y
        devuelve `(None, incident_id)`.
      Sin dos lookups por fila (R2.5: prohibido poblar ambos ids para la misma fila).
      **Nunca** aceptar `tenant_id` desde el caller — viene del token verificado en el
      router y se inyecta, no se lee de path/body/query (R3.3, `extra="forbid"`). [R2.1,
      R2.2, R2.3, R2.4, R2.5, R3.1, R3.2, R3.3]

## 2b. Section 2 unit tests (added after QA review)

- [x] 2b.1 `backend/tests/properties/test_action_id_resolver.py` — 13 tests covering
      partition (R2.5), family routing (parametrized over the three cleaning states),
      population with/without live data (R2.1-R2.4), tenant_id forwarding (R3.1, R3.2),
      batch discipline (R3.4 — mixed / single-family / empty). [R2, R3]

## 3. Población — `from_row` mapea los ids a la respuesta <!-- panel: PASS 2026-08-26 -->

- [x] 3.1 En `backend/app/properties/api/schemas.py`, modificar
      `BlockedTransitionResponse.from_row` (`línea 425`) para pasar los dos ids desde la
      fila al schema. Verificar que el `build` de `BlockedTransitionPageResponse` (línea
      447) los propaga sin cambios. [R2]
- [x] 3.2 Test de integración: con un tenant sembrado y una vivienda en
      `CLEANING_IN_PROGRESS` con su tarea abierta, `GET /api/v1/blocked-transitions` con
      token del tenant devuelve `cleaning_task_id == <id de la tarea>` y `incident_id ==
      null`. Mismo test con una vivienda en `MAINTENANCE_REQUIRED` con su incidencia
      abierta: `incident_id == <id de la incidencia>` y `cleaning_task_id == null`.
      Fichero: `backend/tests/properties/test_blocked_transitions_api.py` (extendido,
      al final del archivo — la proposal decía un fichero nuevo bajo `tests/api/`, pero
      el directorio no existe y mantener los tests del mismo endpoint juntos conserva
      los fakes y seeders; amendment §3.2 cerrado por el panel §3 de QA, finding 2).
      Los dos tests "populated" están parametrizados sobre `LIVE_STATUSES` /
      `OPEN_INCIDENT_STATUSES` para fijar el filtro SQL del puerto (`steering/testing.md`
      rechaza valores aleatorios dentro de `@pytest.mark.parametrize`; aquí son listas
      literales cerradas). [R2.1, R2.2]

## 4. Aislamiento por tenant — tests cross-tenant <!-- panel: PASS 2026-08-26 -->

- [x] 4.1 Test cross-tenant para `cleaning_task_id`: sembrar dos tenants (A y B), cada
      uno con una vivienda en `CLEANING_IN_PROGRESS` y su tarea abierta. `GET
      /api/v1/blocked-transitions` con token del tenant A devuelve una fila cuyo
      `cleaning_task_id` es el de la tarea del tenant A, **nunca** el del B. Mismo test
      con token del B → id del B. Fichero: `backend/tests/properties/test_action_id_isolation.py`
      (nuevo, junto al resto de tests de aislamiento). [R4.1]
- [x] 4.2 Test análogo para `incident_id`: dos tenants con sendas viviendas en estado
      de incidencia e incidencia abierta cada uno. El id que devuelve cada uno es el
      propio. [R4.2]
- [x] 4.3 Test negativo: vivienda del tenant A en `CLEANING_IN_PROGRESS`, pero la tarea
      que la desbloquearía está **en el tenant B** (escenario cross-tenant en la fila).
      La respuesta devuelve `cleaning_task_id == null` y la fila sigue listándose (no se
      oculta la fila por la ausencia de tarea cross-tenant). [R4.3]
- [x] 4.4 Test del guard `extra="forbid"`: una petición con `?tenant_id=<otro>` o con
      `tenant_id` en el body es rechazada con `422` por el schema de request. La
      respuesta nunca usa ese valor; sólo el del token. [R4.4]
- [x] 4.5 Test de batch único: instrumentar el resolver con un contador de invocaciones
      (`unittest.mock.patch` sobre los repositorios de `cleaning_tasks` y `incidents`)
      y verificar que para una página de 50 filas el resolver hace **una** llamada por
      tabla, no 50. Si el resolver hace 1 + 1 (una por tabla por tenant por página), el
      test pasa; si hace N+1, falla con un mensaje que nombre el coste. [R3.4]

## 5. Regeneración del contrato — backend y frontend a la vez <!-- panel: PASS 2026-08-26 -->

- [x] 5.1 Regenerar `backend/openapi.json` con el comando declarado en `sdd/project.md`
      (`docker compose exec backend ...` o `make openapi` — verificar el exacto). El
      schema `BlockedTransitionResponse` debe listar los dos campos nuevos como
      opcionales. Commitear el JSON en este PR (regla de `steering/documentation.md`:
      "regenerar y commitearlo en el mismo PR"). [R5.1, R5.3]
- [x] 5.2 Regenerar `frontend/lib/api/generated/openapi.d.ts` con `cd frontend && npm
      run api:generate` (la regla `steering/documentation.md` añadida el 2026-08-08 tras
      `cleaning` lo exige como "la otra mitad del mismo puente"). Verificar que los dos
      campos aparecen como `string | null` (o `string | undefined`) en el tipo generado
      — no como `string` requerido. Si no aparecen, el workflow `frontend-api-contract`
      lo detectará en CI; aquí se verifica manualmente antes de subir. [R5.1]
- [x] 5.3 Si los workflows `api-contract` y `frontend-api-contract` fallan en el PR,
      NO mergear hasta que estén verdes. Ambos son parte del certificado del cambio —
      el workflow del backend falla si `openapi.json` no coincide con el código; el del
      frontend falla si `openapi.d.ts` no deriva del `openapi.json`. [R5.2]

## 6. Verification <!-- panel: PASS 2026-08-26 -->

- [x] 6.1 Suite completa del backend pasa:
      `docker compose exec backend uv run pytest`
      (o el comando exacto declarado en `sdd/project.md` para el stack parado). La suite
      verde debe incluir los cinco tests nuevos de §3 y §4. [R4, R5]
- [x] 6.2 Lint/typecheck del backend pasa: el comando que `sdd/project.md` declare
      (típicamente `ruff check backend/` + `mypy backend/` o equivalente). Ningún warning
      nuevo en los ficheros tocados. [R1]
- [x] 6.3 Lint/typecheck del frontend pasa: `cd frontend && npm run api:check` para
      confirmar que el árbol generado coincide con `openapi.json`, y `npm test` para la
      suite del frontend (incluye el chequeo de `api:check` en su pipeline). Ninguna
      regresión en los dos. [R5.1]
- [x] 6.4 Manual: con el stack levantado en dev (ver §Worktree bootstrap de
      `sdd/project.md`: `make up`), llamar a `GET /api/v1/blocked-transitions` con un
      token válido y verificar en el JSON que `cleaning_task_id` y `incident_id`
      aparecen como claves en cada fila, con `null` cuando no apliquen y con un UUID
      cuando sí. Documentar el comando curl y la respuesta observada en la descripción
      del commit de implementación (no en el PR — el PR no lleva payloads de dev). [R1,
      R2]