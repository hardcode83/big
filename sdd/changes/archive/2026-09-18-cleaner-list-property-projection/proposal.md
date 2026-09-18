# Proposal: cleaner-list-property-projection

## Why

`GET /api/v1/cleaning-tasks` devuelve `property_id` como UUID pelado en cada fila de
`CleaningTaskListItemResponse` (`backend/app/cleaning/api/schemas.py:286-334`). `/cleaner` no puede
pintar el nombre ni el código de la vivienda sin él, así que `useCleanerTaskContexts`
(`frontend/features/cleaner/hooks/use-cleaner-tasks.ts:116-131`) dispara un `GET
/cleaning-tasks/{id}/context` por fila — hasta `per_page` peticiones extra por página renderizada.

Es un riesgo ya medido y anotado, no uno nuevo: el design de `cleaner-app` lo dejó como riesgo
residual (D4, §Risks) — mitigado en el cliente por deduplicación de TanStack, reaprovechamiento del
detalle y degradación por fila, pero **no eliminado**, porque la salida real no está del lado del
cliente: *"la salida real es que `GET /api/v1/cleaning-tasks` proyecte `property_name` y
`property_internal_code` en cada fila — `cleaning-assign-preconditions` ya añadió
`assignment_blocked_by` al item del listado, así que la forma está"*. El mismo design lo encargó
explícitamente a `/sdd:archive` como candidato de roadmap `[BE]`, `needs: cleaner-app`, tamaño S —
exactamente esta entrada.

La forma a copiar ya existe dos veces en el código, no solo en el precedente citado:

1. **El propio dominio `cleaning`** ya resuelve un campo derivado del listado con una consulta
   batched por página, nunca por fila: `ListCleaningTasksUseCase.execute`
   (`backend/app/cleaning/application/use_cases.py:1744-1800`) reúne los `property_id` distintos de
   la página y hace **una** llamada a `PropertyRepository.states_for(tenant_id, property_ids)` para
   calcular `assignment_blocked_by`. `test_the_listing_reads_the_property_states_once_per_page`
   (`backend/tests/cleaning/test_tasks_api.py:1182-1235`) fija esa cardinalidad con un test.
2. **El dominio `reservations`** ya proyecta exactamente estos dos campos —`property_name` y
   `property_internal_code`— en su listado, con el mismo principio y sin necesitar un puerto nuevo:
   `ListReservationsUseCase.execute` (`backend/app/reservations/application/use_cases.py:442-499`)
   llama a `PropertyRepository.list_for_ids(tenant_id, property_ids)`, cuyo propio docstring
   (`backend/app/properties/domain/repositories.py:192-223`) dice que es *"el batch de lectura que
   el listado usa para poblar `property_name` y `property_internal_code`"*. No hace falta un método
   de repositorio nuevo: éste ya existe y ya sirve para este propósito exacto en otro dominio.

A diferencia de `incident-list-property-projection` (la entrada gemela sobre `/tech`), el contexto de
limpieza que hoy sirve `GET /cleaning-tasks/{id}/context`
(`CleaningTaskContextResponse`/`CleaningTaskContext`, `backend/app/cleaning/domain/read_models.py:35-57`)
no lleva `access_notes` ni ningún otro sumidero de la regla 11 de `steering/security.md` — sus once
campos son nombre/código de vivienda, dirección, timezone y horarios de checkout. No hay, por tanto,
una excepción 6 que recortar aquí: proyectar `property_name`/`property_internal_code` en el listado
no amplía lo que ya es de lectura general para quien puede ver la tarea.

Entrada de roadmap: `cleaner-list-property-projection` (`needs: cleaner-app`, `size: S`, `kind: tech`).

## What changes

`GET /api/v1/cleaning-tasks` proyecta `property_name` y `property_internal_code` en cada fila de
`CleaningTaskListItemResponse`, resueltos con una única llamada batched a
`PropertyRepository.list_for_ids` por página — el mismo principio que ya usa `assignment_blocked_by`
en el mismo endpoint, y el mismo método de repositorio que ya usa el listado de `reservations`. Esto
cierra el N+1 **en el origen** (el dato ya viaja en la respuesta que `/cleaner` ya pide), no en el
cliente — la mitigación del lado del cliente que `cleaner-app` D4 ya tiene sigue donde está.

**No se toca el frontend.** El roadmap etiqueta esta entrada `[BE]` a propósito: `cleaner-app` D4 ya
mitigó el síntoma en el cliente, y el patrón de este proyecto para "el backend ya sirve el dato y la
pantalla lo consume" es una segunda entrada `[FE]` separada (ver `reservation-property-identity` →
`reservations-identity-web`). Que `/cleaner` deje de llamar a `/context` por fila queda fuera de esta
entrada.

## Requirements

### R1 — El listado lleva la identidad de la vivienda

**As a** cliente del API (hoy `/cleaner`), **I want** que cada fila del listado de tareas de limpieza
incluya el nombre y el código interno de su vivienda, **so that** no tenga que pedirlos aparte por
fila.

Acceptance criteria:

1. WHEN se solicita `GET /api/v1/cleaning-tasks`, THE SYSTEM SHALL devolver en cada fila
   `property_name` y `property_internal_code`, tomados de la vivienda que referencia
   `property_id`.
2. THE SYSTEM SHALL llevar estos dos campos **solo** en el item del listado
   (`CleaningTaskListItemResponse`) y no en `CleaningTaskResponse`, siguiendo el mismo criterio de
   forma que ya fija `assignment_blocked_by` (`sdd/specs/cleaning.md`): el campo es aditivo y ningún
   cliente existente se rompe por su llegada.
3. IF `property_id` no resuelve a ninguna vivienda visible para el tenant (dato inconsistente,
   nunca esperado en operación normal), THEN THE SYSTEM SHALL devolver `property_name` y
   `property_internal_code` como `null` en esa fila en vez de fallar la petición completa —fails
   open, el mismo criterio que ya aplica `assignment_blocked_by` cuando el estado de la vivienda no
   resuelve.
4. THE SYSTEM SHALL cubrir con test que la fila del listado sigue sin filtrar campos que no le
   correspondan (mismo test de no-fuga que ya existe para `notes`).

### R2 — El cierre del N+1 es una consulta por página, no por fila

**As a** operador del sistema, **I want** que resolver la identidad de la vivienda de una página de
tareas cueste una consulta fija, **so that** paginar no escale el coste con el número de filas.

Acceptance criteria:

1. WHEN se listan tareas de limpieza, THE SYSTEM SHALL resolver `property_name` y
   `property_internal_code` de todas las filas de la página con **una sola** llamada batched a
   `PropertyRepository.list_for_ids`, acotada a los `property_id` distintos de esa página.
2. THE SYSTEM SHALL reutilizar `PropertyRepository.list_for_ids` (puerto e implementación ya
   existentes) y SHALL NOT introducir un método de repositorio nuevo para este propósito.
3. THE SYSTEM SHALL cubrir con test que esa llamada ocurre exactamente una vez por página, con el
   conjunto exacto de `property_id` distintos de las filas devueltas — mismo criterio que
   `test_the_listing_reads_the_property_states_once_per_page` ya fija para `assignment_blocked_by`.

### R3 — El contrato publicado y sus consumidores quedan sincronizados

**As a** quien integra o consume el contrato, **I want** que el cambio de forma del listado se
refleje donde el contrato se declara y se deriva, **so that** no haya contrato publicado desfasado
del código.

Acceptance criteria:

1. WHERE el esquema de `CleaningTaskListItemResponse` cambia de forma, THE SYSTEM SHALL regenerar
   `backend/openapi.json` en el mismo Pull Request, conforme a `steering/documentation.md`.
2. THE SYSTEM SHALL mantener el campo aditivo — ningún campo existente de
   `CleaningTaskListItemResponse` cambia de nombre, tipo ni obligatoriedad.

## Out of scope

- **Que `/cleaner` deje de llamar a `GET /cleaning-tasks/{id}/context` por fila.** Es la mitad `[FE]`
  del arreglo, que este proyecto trata como una entrada de roadmap propia (precedente:
  `reservation-property-identity` → `reservations-identity-web`) y que no es candidata todavía. El
  riesgo residual que deja: `/cleaner` seguirá emitiendo las mismas peticiones de contexto por fila
  hasta que esa segunda entrada consuma los campos nuevos.
- **Los demás campos de `CleaningTaskContextResponse`** (dirección, timezone, horarios de checkout):
  siguen siendo exclusivos del contexto por tarea, no del listado.
- **Ampliar `PropertyRepository.list_for_ids`** o cualquier otro puerto de `properties`: el método
  que hace falta ya existe y ya se usa para este propósito exacto en `reservations`.
- **`incident-list-property-projection`**, la entrada gemela sobre `/tech`: tiene su propia decisión
  pendiente sobre la excepción 6 de la regla 11 (`access_notes`) que no aplica aquí, y es propiedad
  de otra sesión en curso.

## Affected specs

- `sdd/specs/cleaning.md` — la sección que documenta la forma de `CleaningTaskListItemResponse`
  gana los dos campos nuevos.
- `sdd/specs/cleaner-app.md` — la entrada de "Known limitations" que nombra este N+1 y remite a esta
  entrada de roadmap se actualiza para reflejar que el lado `[BE]` ya está cerrado (el lado `[FE]`
  sigue abierto, ver Out of scope).
