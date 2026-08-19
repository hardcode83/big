# Tasks: cleaner-task-context

Orden pensado para que el sistema siga verde después de cada sección: la 1 añade dominio
puro y un movimiento sin cambio de comportamiento, la 2 el caso de uso, la 3 la ruta, la 4
el contrato y la documentación. Nada queda a medias entre secciones.

Comandos del proyecto (`sdd/project.md`): la suite corre **dentro del stack del worktree**
(`docker compose exec backend uv run pytest`), y la regeneración del artefacto del frontend
usa el sustituto de cuatro líneas de §Worktree bootstrap, no `cd frontend && npm run
api:generate`.

## 1. Dominio: la proyección y las dos ventanas <!-- panel: PASS 2026-08-18 -->

- [x] 1.1 Crear `backend/app/cleaning/domain/read_models.py` con `CleaningTaskContext`,
  frozen dataclass de los **11 campos** de la tabla de D3 y ningún otro
  (`property_name`, `property_internal_code`, `address_line1`, `address_line2`, `city`,
  `province`, `postal_code`, `country`, `timezone`, `checkout_at`,
  `next_checkin_deadline`). Python puro: sin pydantic ni sqlalchemy — `tests/test_layering.py`
  ya lo exige para todo `app/*/domain/**`. Docstring de módulo al estilo de
  `app/dashboard/domain/read_models.py`: por qué es una lista cerrada y qué reglas dependen
  de que lo siga siendo. [R1.1, R1.2, R1.4, R2.5]
- [x] 1.2 Test que **fija el conjunto de campos** de `CleaningTaskContext` en
  `backend/tests/cleaning/test_task_context_read_model.py`, calcado de
  `tests/guests/test_portal_ports.py:40-89`: una aserción de igualdad sobre
  `__dataclass_fields__` y otra que comprueba que ninguno de los prohibidos está presente
  (`access_notes`, `cleaning_notes`, `emergency_notes`, `wifi_password_encrypted`,
  `has_wifi_password`, `total_amount`, `commission_amount`, `net_amount`, `payment_status`,
  `channel`, `guest_id`, `special_requests`, `internal_notes`). Es la mitigación del riesgo
  «la proyección crece hasta ser el volcado que este change rechaza». [R1.4, R2.5]
- [x] 1.3 (TDD, `steering/testing.md` § TDD en `domain/`) Escribir primero
  `backend/tests/cleaning/test_windows.py` para `resolve_checkout(property, reservation)`:
  devuelve el `end` de `effective_bounds` (o sea `Reservation.check_out_time` con fallback a
  `Property.default_check_out_time`), con zona; y devuelve `None` —no `now`— cuando
  `effective_bounds` lanza `IncompatibleTransitionContextError`. Después implementarla en
  `backend/app/cleaning/domain/windows.py` delegando en
  `app.properties.domain.clock_triggers.effective_bounds`, **sin reimplementar** la
  aritmética DST. [R2.1, R2.4]
- [x] 1.4 (TDD) Ampliar `test_windows.py` para
  `next_arrival_after(property, candidates, anchor, *, exclude_id=None)`: mínimo de los
  `start` de las reservas `CONFIRMED` con `start >= anchor`; salta `exclude_id` cuando se
  pasa y no salta nada cuando es `None`; ignora las que no materializan sus límites;
  `None` cuando no queda ninguna; una llegada `PENDING` no impone deadline. Implementarla en
  `cleaning/domain/windows.py` como la regla de `_next_checkin` **movida** tal cual, con
  `current: Reservation` sustituido por el id de exclusión opcional. Definir ahí también
  `NEXT_ARRIVAL_HORIZON = timedelta(days=14)` (D10) con el comentario de por qué no es el
  `+2d` de `candidate_window`. [R2.2, R2.3]
- [x] 1.5 Hacer que `_effective_checkout` y `_next_checkin`
  (`backend/app/cleaning/application/use_cases.py:1653-1704`) deleguen en
  `domain/windows.py`, y que `process_checkouts` (`use_cases.py:269-271`) pase
  `exclude_id=reservation.id` en vez de la reserva entera. `_effective_checkout` conserva su
  degradación a `now` — es la pista de planificación, y D5 dice explícitamente que la
  proyección **no** la reutiliza. Movimiento sin cambio de comportamiento: los tests
  existentes de `process_checkouts` (`test_provisioning.py`) corren **sin tocarse**; si hay
  que tocarlos, el movimiento cambió algo y hay que volver atrás. [R2.1, R2.2]

## 2. Aplicación: el caso de uso <!-- panel: PASS 2026-08-18 -->

- [x] 2.1 `GetCleaningTaskContextUseCase` en
  `backend/app/cleaning/application/use_cases.py`, componiendo `CleaningTaskRepository`,
  `PropertyRepository` y `ReservationRepository` (D2): carga la tarea con el mismo
  acotamiento que `GetCleaningTaskUseCase` (`tenant_id` + `actor.restrict_to_cleaner_id`,
  `CleaningTaskNotFoundError` en los dos fallos), carga la propiedad **con su `tenant_id`
  explícito** y devuelve `CleaningTaskContext`. Ningún `SELECT` nuevo, ningún adaptador de
  proyección. Si la propiedad no aparece dentro del tenant → `CleaningTaskNotFoundError`.
  [R1.1, R1.2, R3.1, R3.2, R3.3]
- [x] 2.2 Resolución de los dos instantes dentro del caso de uso: con
  `task.reservation_id` informado, `checkout_at = resolve_checkout(property, reservation)` y
  el ancla es ese instante; con `reservation_id is None`, `checkout_at = None` y el ancla es
  `now` (D6). Los candidatos salen de
  `reservations.list_for_properties(tenant_id, [property_id], anchor.date(), (anchor + NEXT_ARRIVAL_HORIZON).date())`
  y `next_checkin_deadline = next_arrival_after(..., exclude_id=task.reservation_id)`.
  [R2.1, R2.2, R2.3]
- [x] 2.3 Tests del caso de uso en
  `backend/tests/cleaning/test_task_context_use_case.py`: tarea con reserva saliente →
  los dos instantes; tarea sin `reservation_id` → `checkout_at is None` y el deadline
  anclado en `now`; sin llegada posterior → deadline `None`; llegada **más allá de los 14
  días** → deadline `None` (fija D10, no lo deja al azar de la ventana); la reserva de la
  propia tarea no se cuenta como llegada; `CLEANER` con la tarea de otra limpiadora →
  `CleaningTaskNotFoundError`; tarea de otro tenant → ídem; **tarea que apunta a la
  propiedad de otro tenant** → ídem (es la fila del riesgo de aislamiento: D2 la cierra por
  composición y hay que demostrarlo); `PROPERTY_MANAGER` y `TENANT_OWNER` → cualquier tarea
  de su tenant. [R2.1, R2.2, R2.3, R3.1, R3.2, R3.3, R3.5]

## 3. API: esquema, cableado y ruta <!-- panel: PASS 2026-08-19 -->

- [x] 3.1 `CleaningTaskContextResponse` en `backend/app/cleaning/api/schemas.py`, espejo
  campo a campo de `CleaningTaskContext` con `model_config = ConfigDict(from_attributes=True)`.
  Sin `exclude_none` en ninguna parte, para que una dirección `NULL` viaje como `null` con
  su clave. [R1.3, R1.4, R2.4, R2.5]
- [x] 3.2 `get_cleaning_task_context_use_case` en
  `backend/app/cleaning/api/dependencies.py`, con los tres repositorios SQLAlchemy ya usados
  en el módulo. Lectura: sin unit of work y sin repositorio de auditoría, como
  `get_list_cleaning_photos_use_case`. [R1.1]
- [x] 3.3 `GET /{task_id}/context` en `backend/app/cleaning/api/tasks_router.py`, sobre
  `ReadDep` (`READ_CLEANING_TASKS`), con `response_model=CleaningTaskContextResponse`,
  `summary`, un `_CONTEXT_RESPONSES` que declara el `404` con `ErrorEnvelope` siguiendo
  `_PHOTO_LISTING_RESPONSES` (`tasks_router.py:482-490`), y una `description` que diga las
  tres cosas: que el conjunto de tareas visibles sale del rol persistido del token y ningún
  parámetro lo ensancha (R4.3); que `checkout_at`/`next_checkin_deadline` son la respuesta
  **de ahora** y no el plan que guardan `scheduled_start`/`scheduled_end`; y que
  `next_checkin_deadline: null` significa «ninguna llegada `CONFIRMED` en los 14 días
  siguientes al ancla» (D10). [R3.4, R3.5, R4.2, R4.3]
- [x] 3.4 Tests de API en `backend/tests/cleaning/test_task_context_api.py` (httpx
  `AsyncClient`, fixtures por rol de `tests/cleaning/conftest.py`): `CLEANER` con su tarea →
  `200` con las 11 claves; una dirección `NULL` viaja como `null` **y la clave está**
  (R1.3 es comportamiento heredado de pydantic, así que lleva test propio); los dos
  instantes salen en ISO 8601 **con offset explícito**; ninguna clave prohibida de R1.4 ni
  de R2.5 aparece en el JSON; `CLEANER` con la tarea de otra limpiadora → `404` con el
  sobre de PRD §23 y código `NOT_FOUND`, **cuerpo idéntico** al de una tarea inexistente;
  tarea de otro tenant → `404` (test de aislamiento obligatorio, `steering/security.md`
  regla 1); rol sin `READ_CLEANING_TASKS` → `403`; `PROPERTY_MANAGER` y `TENANT_OWNER` →
  `200` sobre una tarea que no es suya. [R1.3, R1.4, R2.4, R2.5, R3.1, R3.2, R3.3, R3.4, R3.5, R4.2]

## 4. Contrato y documentación

- [x] 4.1 Regenerar `backend/openapi.json` con `make openapi` y **el artefacto derivado del
  frontend** `frontend/lib/api/generated/openapi.d.ts` con el sustituto de cuatro líneas de
  `sdd/project.md` §Worktree bootstrap (el `cd frontend && npm run api:generate` documentado
  no corre en un worktree enlazado). Los dos van en el mismo PR — son las dos mitades del
  mismo puente (`steering/documentation.md`), y los workflows `api-contract` y
  `frontend-api-contract` comprueban una cada uno. Verificar que la operación aparece con su
  esquema de respuesta enumerado campo a campo y con el `404` declarado. [R4.1, R4.2]
- [x] 4.2 Actualizar `docs/cleaning.md` con la operación nueva: qué devuelve, que el
  conjunto de tareas depende del rol, y **qué significa `null`** en cada uno de los dos
  instantes (`checkout_at`: tarea manual sin reserva saliente, o límites de la estancia no
  materializables; `next_checkin_deadline`: ninguna llegada `CONFIRMED` en 14 días), más la
  distinción plan (`scheduled_*`) vs. respuesta de ahora. No duplicar la spec: enlazar.
  [R4.3]

## 5. Verification

- [x] 5.1 Suite completa verde: `docker compose exec backend uv run pytest` desde el
  worktree (stack propio levantado con `make up`).
- [x] 5.2 `tests/test_layering.py` verde sin excepciones nuevas: `read_models.py` y
  `windows.py` son Python puro y no importan hacia fuera.
- [x] 5.3 Lint/typecheck del backend con el comando del proyecto; sin `type: ignore` nuevos.
  **El proyecto no tiene ese comando**: no hay `ruff` ni `mypy` instalados en el contenedor
  (`uv run ruff` / `uv run mypy` → «Failed to spawn»), ni configuración de ninguno en
  `backend/pyproject.toml`, ni paso de lint en `.github/workflows/backend-tests.yml`, que corre
  migraciones, `alembic check` y `pytest`. Lo que sí se cumple y es verificable: **cero
  `type: ignore` nuevos** en el código de este change. Los diagnósticos de pyright del editor
  sobre los fakes de `test_task_context_use_case.py` (no implementan el `Protocol` entero) son
  los mismos que ya produce `test_photo_listing_use_case.py`, que tampoco los silencia — añadir
  supresiones habría contravenido la segunda mitad de esta tarea.
- [x] 5.4 Contrato sin deriva: `make openapi` no deja diff y el `openapi.d.ts` regenerado
  tampoco (equivalente de `npm run api:check` según §Worktree bootstrap).
- [x] 5.5 Comprobación manual del flujo con el stack del worktree: token de una `CLEANER`
  semilla → `GET /api/v1/cleaning-tasks/{id}/context` de una tarea suya devuelve dirección y
  ventana; la misma llamada sobre una tarea ajena devuelve `404` con el mismo cuerpo que un
  id inventado. Sin puertos publicados en un worktree, se hace desde dentro del contenedor
  (`docker compose exec backend ...`), no desde el navegador del host.
