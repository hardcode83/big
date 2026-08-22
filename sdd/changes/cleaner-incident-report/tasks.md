# Tasks: cleaner-incident-report

Orden pensado para que el sistema siga verde después de cada sección: primero la columna y el
esquema (nadie la escribe todavía), luego el escritor de `maintenance`, luego el dominio y la
aplicación de `cleaning`, y sólo al final la ruta que lo une todo.

Comandos del proyecto (`sdd/project.md`): la suite corre **dentro de Docker**
(`docker compose exec backend uv run pytest`); con el stack parado,
`docker compose run --rm backend uv run pytest`. Este change vive en un worktree enlazado, así que
`make up` no publica puertos y `cd frontend && npm run api:generate` **no funciona tal cual**: hay
que usar la salida verificada de `sdd/project.md` (ver 8.2).

## 1. La columna `incidents.cleaning_task_id` y su auditoría <!-- panel: PASS 2026-08-19 -->

- [x] 1.1 Añadir `cleaning_task_id: Mapped[uuid.UUID | None]` a `Incident` en
  `backend/app/maintenance/domain/entities.py`, con `default=None`, y a `IncidentModel` en
  `backend/app/maintenance/infrastructure/models.py` con
  `ForeignKey("cleaning_tasks.id", ondelete="RESTRICT")` y `nullable=True` — la misma postura que
  `property_id` y `reservation_id` en esa tabla, **no** el `SET NULL` de `reported_by_user_id`.
  Propagarla en `backend/app/maintenance/infrastructure/repositories.py` en `add()` y en el mapeo
  fila→entidad. Test en `backend/tests/maintenance/test_models.py` / `test_repositories.py`: una
  incidencia sin tarea persiste con `NULL` y se relee como `None`; una con tarea la conserva en el
  round-trip. [R4.1, R4.2] (D10)
- [x] 1.2 Crear la migración Alembic `backend/alembic/versions/<rev>_cleaner_incident_report.py`
  con `down_revision = "e7a3c419d82b"` (cabeza única verificada hoy), que añade la columna y su FK.
  Sin backfill y sin índice: toda fila existente queda `NULL` y este change no consulta por esa
  columna. Verificar `alembic upgrade head` y `alembic downgrade -1` contra la base del worktree.
  [R4.1, R4.2] (D10)
- [x] 1.3 Añadir `cleaning_task_id` a `AUDITABLE_FIELDS["INCIDENT"]` en
  `backend/app/audit/domain/value_objects.py` — pasa de once campos a doce. Actualizar el test que
  fija ese conjunto en `backend/tests/` (el que hoy asierta los once) para que exija los doce, de
  modo que el cambio sea deliberado. Es un identificador, no texto: R5.2 sigue intacta. [R4.1, R5.2]
  (D10)

## 2. `title`/`description` con un solo hogar <!-- panel: PASS 2026-08-19 -->

- [x] 2.1 Crear `backend/app/core/storable_text.py` promoviendo desde
  `backend/app/guests/api/portal_schemas.py` el guardián `_storable_text` y sus dos alias
  (`SingleLineText`, `MultiLineText`), públicos ya en su nuevo hogar. Mover
  `MAX_INCIDENT_TITLE = 300` y `MAX_INCIDENT_DESCRIPTION = 5000` a
  `backend/app/maintenance/domain/entities.py`, que es el módulo dueño de la columna (mismo
  argumento que `CONVERSATION_INCIDENT_TITLES`). Dejar `portal_schemas.py` importando de los dos
  sitios, **sin cambiar su comportamiento observable**. Test: los casos que hoy cubren el guardián
  en `backend/tests/guests/` siguen verdes y se añade su equivalente en un test de `core` para
  `U+0000` y un surrogate suelto. [R5.1] (D7)

- [x] 2.2 **(Desviación acordada en el gate del 2026-08-19, panel de sección 2.)** Reparar
  `_python_blocks` en `backend/tests/test_rule11_ownership.py`: `lstrip("#")` dejaba los dos
  puntos de Sphinx, así que toda frase repartida en dos líneas de un bloque `#:` se leía como
  «`…this module is\n: the writer of …`» y `\s+` no casa con un `:`. El guardián daba por
  ausente su **propia** cadena buscada, presente literal en
  `backend/app/maintenance/domain/entities.py` desde `messaging-ai`. No es el residuo de
  paráfrasis que `test_what_this_guard_does_not_catch` ya documenta. Medido antes de tocar
  nada: con los dos puntos quitados aparece **exactamente un** bloque nuevo en `app/`,
  `tests/` y `alembic/versions/`. Reescrita esa frase para conservar su argumento —el catálogo
  vive junto a la entidad porque un llamante con vocabulario propio haría inaplicable la forma
  cerrada— y remitir la atribución al censo. [R5.3] (D12)

## 3. El escritor de `maintenance` <!-- panel: PASS 2026-08-19 -->

- [x] 3.1 Añadir a `ReportIncidentUseCase`
  (`backend/app/maintenance/application/use_cases.py:463`) dos parámetros **keyword-only con default
  `None`**: `reported_by_user_id: uuid.UUID | None` y `cleaning_task_id: uuid.UUID | None`.
  Escribirlos en la entidad, difundirlos en el `ChangeSet` del alta junto a `source` y `status`, y
  añadir `cleaning_task_id` al `metadata` del `TimelineEvent` **sólo cuando lo hay** (identificadores
  y nada más). Actualizar el docstring que hoy explica por qué esos parámetros no existían: la
  precondición queda descargada por el llamante. Los defaults dejan `backend/app/cli/seed_demo.py`
  exactamente como está. Tests en `backend/tests/maintenance/test_report_incident.py`: con y sin los
  dos parámetros; el timeline no lleva la clave cuando no hay tarea. [R3.3, R4.3, R5.2] (D4, D10)
- [x] 3.2 Añadir `CleanerIncidentReporter` en el mismo módulo: recibe `ReportIncidentUseCase` por
  constructor, **sella `IncidentSource.CLEANER`** y delega el resto. No duplica los tres writes y no
  se llama `…UseCase` a propósito. Test en `backend/tests/maintenance/test_incident_writer.py` (o
  nuevo): el `source` no es un parámetro y no se puede pedir otro; el alta sale `OPEN` sin
  `category`, `severity`, `ai_summary` ni `ai_classification`; sin actor no comitea nada.
  [R3.1, R3.2, R3.5, R3.6, R3.7] (D3)

## 4. Dominio de `cleaning`: la puerta de estado y el puerto <!-- panel: PASS 2026-08-19 -->

- [x] 4.1 (TDD — `domain/` con invariante real) En
  `backend/app/cleaning/domain/entities.py`, definir **por inclusión**
  `INCIDENT_REPORTABLE_STATUSES = frozenset({ASSIGNED, ACCEPTED, IN_PROGRESS})` y
  `CleaningTask.assert_incident_reportable(cleaner_id)`, que llama `_require_assignee` **antes** de
  `_require_status` (un `409` sobre una tarea ajena confirmaría que existe) y lanza
  `InvalidCleaningTransitionError`, ya mapeada a `409`. Escribir primero el test en
  `backend/tests/cleaning/test_entities.py` cubriendo los seis estados restantes —`CREATED`,
  `PENDING_REVIEW`, `FAILED`, `COMPLETED`, `REJECTED`, `CANCELLED`— y el orden assignee-antes-que-
  estado. [R2.5] (D6)
- [x] 4.2 Declarar en `backend/app/cleaning/domain/ports.py` el puerto `TaskIncidentReportingPort`
  con la firma del design (`tenant_id`, `property_id`, `cleaning_task_id`, `report`,
  `actor_user_id`, `ip`, `now`; **sin `source`**) y los dos value objects que lo acompañan:
  `IncidentReport` y `IncidentReportedAcknowledgement(id, status: IncidentStatus, created_at)`. El
  puerto vive en el módulo consumidor y `maintenance` aporta el implementador, que es la norma que
  `backend/app/messaging/domain/ports.py:129` ya escribió. [R3.1, R4.4] (D2, D8)

## 5. El caso de uso de `cleaning` <!-- panel: PASS 2026-08-22 -->

- [x] 5.1 Añadir `ReportTaskIncidentUseCase` en
  `backend/app/cleaning/application/use_cases.py`, calcado de `GetCleaningTaskContextUseCase`, con
  los cinco pasos de D5 en ese orden: `tasks.get(tenant_id, task_id)` →
  `restrict_to_cleaner_id` (derivado del rol **persistido** de `CleaningActor`, nunca de la
  petición) → `assert_incident_reportable` → `properties.get(tenant_id, task.property_id)` →
  `self._incidents.report(..., property_id=task.property_id)`. Los cuatro caminos de fallo de R2.3
  responden `CleaningTaskNotFoundError`, indistinguibles. `tenant_id` explícito en cada método de
  repositorio. Log con `task_id` e `incident_id`, **nunca el texto reportado**.
  [R1.1, R1.4, R2.2, R2.3, R2.4, R3.4, R4.3, R5.4] (D5)
- [x] 5.2 Tests del caso de uso en `backend/tests/cleaning/test_task_incident_use_case.py` (nuevo):
  camino feliz; los cuatro `404` (inexistente, otro tenant, otra limpiadora, propiedad que no
  resuelve) con el mismo tipo de error; el `409` por estado terminal; que `property_id` sale de la
  tarea y no de la petición. **El test cross-tenant se escribe sobre una sesión sin marcar**, porque
  el listener de `app/core/db.py` filtra por tenant y sobre sesión marcada no puede fallar (Risks).
  [R2.2, R2.3, R2.4, R3.4]

## 6. La superficie HTTP <!-- panel: PASS 2026-08-22 -->

- [x] 6.1 En `backend/app/cleaning/api/schemas.py`, añadir `ReportTaskIncidentRequest` con
  `extra="forbid"` y **exactamente dos campos**, `title` y `description`, con strip previo,
  `min_length=1`, `max_length` 300 y 5000 importados de `maintenance/domain/entities.py` y el
  guardián de `app/core/storable_text.py`; y `TaskIncidentReportedResponse` con los **tres** campos
  de R4.4. El mapeo petición→dominio vive aquí (`to_report() -> IncidentReport`), no en el router.
  [R1.3, R4.4, R5.1] (D7, D8, D9)
- [x] 6.2 Test en `backend/tests/cleaning/test_task_incident_api.py` (nuevo) que **fija el conjunto
  exacto de campos** de petición y de respuesta: rechaza `property_id`, `reservation_id`,
  `tenant_id`, `source`, `category`, `severity`, `status`, `assigned_technician_id` y cualquier campo
  de coste con `422`; y la respuesta no lleva `category`, `severity`, `ai_summary`,
  `ai_classification`, `reported_by_guest_token` ni el `description` de vuelta. Añadir uno es un acto
  deliberado, no una deriva. [R1.3, R1.4, R4.4, R4.5]
- [x] 6.3 Añadir la ruta `POST /{task_id}/incidents` como decimoquinta de
  `backend/app/cleaning/api/tasks_router.py`, `status_code=201`, puerta `ExecuteDep`
  (`EXECUTE_CLEANING_TASKS`, sin permiso nuevo), actor e IP con el `_actor()` del módulo, y
  `_INCIDENT_REPORT_RESPONSES` declarando 404/409/422 con el sobre `{error:{code,message,details}}`
  de PRD §23. El router **no nombra `title` ni `description`** en posición de escritura (D9).
  [R1.1, R1.2, R1.6, R2.1] (D1)
- [x] 6.4 Cablear en `backend/app/cleaning/api/dependencies.py` el
  `get_report_task_incident_use_case`, que construye `CleanerIncidentReporter` sobre
  `ReportIncidentUseCase` de `maintenance` — la capa de `api/` es la única con derecho a conocer los
  dos módulos. [R3.7] (D2)
- [x] 6.5 Tests de ruta en `backend/tests/cleaning/test_task_incident_api.py`: `201` con el acuse;
  `403` **antes de tocar la base de datos** para un llamante sin `EXECUTE_CLEANING_TASKS`
  (`PROPERTY_MANAGER` tiene `MANAGE_CLEANING_TASKS`, no éste); `401` sin token; los cuatro `404` con
  **cuerpo idéntico**, incluido el cross-tenant sobre sesión sin marcar; `409` sobre tarea terminal;
  y que la incidencia creada tiene `source = CLEANER`, `reported_by_user_id` del token,
  `reported_by_guest_token` a `NULL` y `cleaning_task_id` de la ruta. [R1.1, R1.6, R2.1, R2.3, R2.5,
  R3.1, R3.3, R4.3]

## 7. El censo de la regla 11 y su guardián <!-- panel: PASS 2026-08-22 -->

- [x] 7.1 Ensanchar la **quinta cláusula de puerta** de
  `backend/tests/maintenance/test_free_text_sink_contract.py`: un módulo entra también si **importa**
  `app.cleaning.domain.ports`, leído del **AST** y no como subcadena. Allowlistear con su contrato
  escrito los dos módulos que nombran las columnas en posición de escritura —
  `cleaning/application/use_cases.py` y `cleaning/api/schemas.py`— y comprobar que la cláusula admite
  además `properties/application/use_cases.py`, `cleaning/application/evidence.py` y
  `scheduler/tasks.py` sin mover el conjunto de infractores. [R5.3] (D9)
- [x] 7.2 Añadir al censo de `sdd/steering/security.md` §«Sumideros de texto en claro» **dos filas**
  —`incidents.title` e `incidents.description`, escritor «la limpiadora (persona autenticada, desde
  su propia tarea)»— bajo la **excepción 3**, ensanchando su enunciado para nombrarlas. Actualizar el
  recuento de la cabecera de **veintitrés a veinticinco filas**; las «dieciocho columnas» y las
  «dieciséis vivas» **no se mueven** (`cleaning_task_id` es un UUID con FK, no texto libre). Y
  actualizar la enumeración de cláusulas del guardián que esa sección describe. [R5.3] (D9)
- [x] 7.3 Comprobar que `backend/tests/test_rule11_ownership.py` sigue verde **con el
  guardián ya reparado en 2.2** (antes de esa reparación su verde no probaba la
  afirmación de esta tarea, que es justo lo que la levantó): la atribución del
  sumidero vive **sólo** en la tabla de `security.md`; ni `docs/` ni las specs pueden declarar quién
  escribe esas columnas, sólo describir el acotamiento y enlazar a la regla 11. [R5.2, R5.3] (D12)

## 8. Contrato de API <!-- panel: PASS 2026-08-22 -->

- [x] 8.1 Regenerar `backend/openapi.json` con `make openapi` y commitearlo en este mismo PR: la
  operación nueva con su esquema de petición y de respuesta y sus respuestas de error. [R1.5, R1.6]
- [x] 8.2 Regenerar `frontend/lib/api/generated/openapi.d.ts` y commitearlo. `npm run api:generate`
  **no funciona tal cual en un worktree enlazado**; usar la salida verificada de `sdd/project.md`:
  `docker compose exec -T frontend mkdir -p /backend` → `docker compose cp backend/openapi.json
  frontend:/backend/openapi.json` → `docker compose exec -T frontend ln -sfn /app /frontend` →
  `docker compose exec -T frontend npm run api:generate`, y confirmar con `api:check` por la misma
  vía. Es el filo que rompió `main` en el change `cleaning`. [R1.5]

## 9. El acoplamiento con el cierre de la tarea (R6) <!-- panel: PASS 2026-08-22 -->

- [x] 9.1 Verificar que **no se toca una línea** de la tercera cláusula de
  `CleaningTask.complete()`: sigue siendo `has_unresolved_critical(tenant_id, property_id)`, acotada
  a la propiedad. Comprobar que el mensaje de `BlockingIncidentError` ya cumple R6.3 — la constante
  «An unresolved CRITICAL incident blocks completing this cleaning», sin id, sin título y sin
  descripción — y dejar un test que lo fije como constante para que nadie le añada el identificador.
  [R6.1, R6.3] (D11)
- [x] 9.2 Test de recorrido completo en `backend/tests/cleaning/test_task_lifecycle.py`: la
  limpiadora reporta (la incidencia nace `MEDIUM` y **no bloquea en el momento**, así que su
  `complete()` pasa), el clasificador la sube a `CRITICAL`, y el `complete()` siguiente responde
  `409`. **Asertar el mensaje y no sólo el código**, porque el `409` de R2.5
  (`InvalidCleaningTransitionError`) y el de R6.3 (`BlockingIncidentError`) llegan del mismo mapeo.
  [R6.2, R6.4] (Risks)

## 10. Documentación y reescritura de lo que las specs afirman <!-- panel: PASS 2026-08-22 -->

- [x] 10.1 Grepear por **todo el árbol** —`backend/app/` (docstrings), `backend/tests/`, `docs/`,
  `sdd/specs/`, `sdd/steering/`— las **tres** redacciones que este change vuelve falsas, no una:
  (a) «`CLEANER`, `SUPER_ADMIN` | nada de este módulo» y «NEVER SHALL exponer estas rutas al rol
  `CLEANER`»; (b) «SHALL NOT aceptar `reservation_id` ni `reported_by_user_id`»; (c) «auditar sobre
  `INCIDENT` exactamente **once** campos». Corregir en el sitio todo lo que esté **fuera de
  `sdd/specs/`** (docstrings de `ReportIncidentUseCase`, `docs/`), y dejar la lista literal de
  ocurrencias en `sdd/specs/` anotada en el propio change para que `/sdd:archive` las reescriba.
  [R7.1, R7.2, R7.4]
- [x] 10.2 Actualizar `docs/maintenance.md` y `docs/cleaning.md`: la ruta nueva y cómo se opera, la
  enumeración de superficies que crean incidencias —hoy «la anónima del portal del huésped, el
  pipeline de mensajería y el comando `make seed-demo`»— para incluir ésta, y el acoplamiento
  declarado de R6.2. **Sin atribuir el sumidero de texto libre** (7.3). [R6.2, R7.3]
- [x] 10.3 Regenerar el diagrama ER con `/sdd:diagram` (**sin abrir el PNG** — cuesta ~140k de
  contexto): pasa a 31 entidades y **76** relaciones (74 pares de tablas distintos). Borrar
  `docs/diagrams/2026-08-11_autohost-er-entidades.png` y actualizar el párrafo del recuento en
  `sdd/steering/architecture.md`. Decidir si `2026-08-15_autohost-secuencia-mantenimiento.png`
  necesita regenerarse a partir de **lo que `maintenance` documentó al generarlo** (si enumera las
  superficies de creación), sin abrirlo. [R7.3] (Risks)
- [x] 10.4 Comprobar el resto del checklist de `steering/documentation.md`: no hay variables de
  entorno nuevas, no hay strings de UI (la UI es de `cleaner-app`), no cambia el arranque local ni la
  estructura de carpetas → el README raíz no se toca. Dejarlo verificado explícitamente, no asumido.

  **Verificado el 2026-08-22, punto por punto y contra el árbol, no por memoria:**

  - **`.env.example`** — sin cambios. El change no lee ninguna variable nueva: ni la ruta, ni el
    caso de uso, ni el esquema tocan `settings`. `git diff .env.example` vacío.
  - **Strings de UI / `locales/`** — ninguno. Lo único que cambia bajo `frontend/` es
    `lib/api/generated/openapi.d.ts`, que es artefacto generado (tarea 8.2), no texto. La pantalla
    la pone `cleaner-app`, que declara este change en su `needs`.
  - **Arranque local** — intacto. Ningún target nuevo de `Makefile`, ningún servicio nuevo de
    compose, ninguna migración que exija un paso manual (`migrate` corre `alembic upgrade head`
    solo).
  - **README raíz — no se toca, y el motivo es verificable**: su §Estructura enumera **dominios**
    (`backend/app/<dominio>/`) y cuáles tienen las cuatro capas. Este change no añade dominio y no
    mueve el juego de capas de ninguno: `cleaning` y `maintenance` ya tenían las cuatro. Los dos
    ficheros nuevos que no son de dominio —`app/core/storable_text.py` y el paquete
    `backend/tests/core/`— no aparecen en esa enumeración ni en ninguna otra del README, que no
    lista el contenido de `app/core/` ni los paquetes de test.
  - **`docs/<capability>.md`** — hechas en 10.2: `docs/maintenance.md` (la ruta nueva, la fila RBAC
    de la limpiadora, la enumeración de fuentes de creación y el acoplamiento de R6.2) y
    `docs/cleaning.md` (el párrafo que decía que las incidencias no se podían crear todavía).
  - **`docs/diagrams/`** — hecho en 10.3: ER regenerado desde la metadata
    (`2026-08-22_autohost-er-entidades.png`, 31 entidades / 78 columnas con clave ajena / 74 pares),
    el `2026-08-11_...` borrado, y la referencia y el recuento de `steering/architecture.md`
    corregidos. El de secuencia de mantenimiento se decidió **no** regenerar, con el criterio
    escrito allí.
  - **Contrato de API** — hecho en 8.1 y 8.2, y con test: `test_openapi_contract.py` y
    `api:check` en verde.

## 11. Verification

- [x] 11.1 Suite completa verde: `docker compose exec backend uv run pytest` (o
  `docker compose run --rm backend uv run pytest` con el stack parado), desde **este** worktree —
  `backend` monta el código por bind-mount, así que el stack del principal probaría otro árbol.
- [x] 11.2 Contrato sin deriva: `make openapi` no deja diff, y `api:check` por la vía de 8.2 tampoco.
- [x] 11.3 Migración de ida y vuelta contra la base del worktree: `alembic upgrade head` y
  `alembic downgrade -1` limpios.
- [x] 11.4 Comprobación manual del flujo de punta a punta con `make up PORT_OFFSET=<n>` (un worktree
  no publica puertos sin él): login como limpiadora del seed, `POST` sobre una tarea suya
  `IN_PROGRESS` → `201` con los tres campos; el mismo `POST` sobre una tarea de otra limpiadora →
  `404` con cuerpo idéntico al de una tarea inexistente; sobre una `COMPLETED` → `409`; y la
  incidencia aparece en el listado del manager con `source = CLEANER` y su `cleaning_task_id`.
