# Design: cleaner-incident-report

## Context

Las dos mitades que este change une ya existen y no se conocen. En `maintenance`,
`ReportIncidentUseCase` (`backend/app/maintenance/application/use_cases.py:463`) hace los tres
writes de un alta —entidad, `AuditLog` vía `_AuditWriter`, `TimelineEvent`— en una transacción,
admite cualquier `IncidentSource`, resuelve `property_id` dentro del tenant y **no tiene ruta**;
su docstring dice literalmente que se quitaron `reservation_id` y `reported_by_user_id` porque
«arrastraban la misma precondición sin descargar y hoy no tienen llamante», y que quien traiga el
primero «añade el parámetro **junto con** la búsqueda que lo hace seguro». Su único llamante hoy es
`backend/app/cli/seed_demo.py:932`.

En `cleaning`, `cleaner-task-context` dejó el molde de una superficie de limpiadora:
`GetCleaningTaskContextUseCase` (`backend/app/cleaning/application/use_cases.py:1085`) carga la
tarea dentro del tenant, la acota con `CleaningActor.restrict_to_cleaner_id` (`:511-527`, derivado
del rol **persistido**), resuelve la propiedad dentro del tenant y responde
`CleaningTaskNotFoundError` en los cuatro casos, indistinguibles. Las catorce rutas de tarea viven en
`backend/app/cleaning/api/tasks_router.py` con `_actor()` y `ExecuteDep` ya construidos, y
`backend/app/cleaning/api/errors.py` mapea el dominio al envoltorio de PRD §23.

El puente entre módulos también tiene precedente **escrito como norma**:
`backend/app/messaging/domain/ports.py:129` declara `IncidentReportingPort` y dice que el puerto
vive en el módulo consumidor y `maintenance` aporta el implementador, «que es la dirección que
quiere la regla de dependencia: `application/` depende de un puerto de su **propio** `domain/`,
nunca de los casos de uso de otro módulo». `cleaning` ya tiene ese puente en la otra dirección
(`BlockingIncidentQuery`, `backend/app/cleaning/domain/ports.py:28`).

Lo que no existe: la columna `incidents.cleaning_task_id`, ninguna ruta de alta fuera del portal y
del pipeline, y la fila del censo de la regla 11 para un escritor autenticado de
`incidents.title`/`description`.

## Decisions

### D1 — La ruta cuelga de la tarea, en el router que ya existe

**Chosen:** `POST /api/v1/cleaning-tasks/{task_id}/incidents` como decimoquinta ruta de
`backend/app/cleaning/api/tasks_router.py`, `status_code=201`, puerta `ExecuteDep`
(`EXECUTE_CLEANING_TASKS`, que hoy tiene sólo `CLEANER` — `auth/domain/policy.py:176`). El actor y
su IP se construyen con el `_actor()` de ese módulo, que es el que ya alimenta `audit_logs.actor_ip`.

Con esto R1.2 es cierta por construcción: el sujeto de la ruta es la tarea, y las once rutas de
`/api/v1/incidents` siguen sin un `POST` de creación.

Rejected: una ruta bajo `/api/v1/incidents` — rompería R1.2 y la cláusula `NEVER SHALL` de
`specs/maintenance.md` R8. Un `incidents_router.py` nuevo dentro de `cleaning` — sería un segundo
módulo para el mismo recurso (`/cleaning-tasks/{id}/…`), duplicando `_actor()` y las `*Dep`.
Montarla en `maintenance` sobre el path de cleaning — el prefijo miente sobre qué router la sirve y
reabre la negativa de R8.

### D2 — Puerto en `cleaning`, implementador en `maintenance`

**Chosen:** `cleaning/domain/ports.py` declara `TaskIncidentReportingPort`, y `maintenance` aporta
el implementador; el cableado vive en `cleaning/api/dependencies.py`, la única capa con derecho a
conocer los dos módulos. Es la norma que `messaging/domain/ports.py:129` ya escribió para este
mismo caso, palabra por palabra.

Firma (sin `source`, que lo sella el escritor — R3.1):

```python
async def report(
    self, *, tenant_id: uuid.UUID, property_id: uuid.UUID, cleaning_task_id: uuid.UUID,
    report: IncidentReport, actor_user_id: uuid.UUID, ip: str | None, now: datetime,
) -> IncidentReportedAcknowledgement: ...
```

Rejected: que `cleaning/application/use_cases.py` importe `ReportIncidentUseCase` directamente —
contradice una norma escrita, y es la dependencia que `BlockingIncidentQuery` evitó en la otra
dirección. Reutilizar `IncidentReportingPort` de `messaging` — un puerto de otro dominio consumidor,
sin `cleaning_task_id` y con `reservation_id` que aquí no existe.

### D3 — El implementador **delega**; no duplica los tres writes

**Chosen:** `CleanerIncidentReporter`, en `maintenance/application/use_cases.py`, recibe
`ReportIncidentUseCase` por constructor, sella `IncidentSource.CLEANER` y le pasa el resto. Es lo
que R3.7 exige: el alta genérica «existe precisamente para esto y SHALL extenderse, no duplicarse».
No se llama `…UseCase` a propósito — no es una operación de negocio nueva, es el adaptador que casa
el puerto de `cleaning` con el escritor de `maintenance`.

Rejected: escribir un `ReportCleanerIncidentUseCase` con sus propios tres writes — es lo que hizo
`messaging` (justificado allí porque `reporter_token_hash` no existía) y exactamente lo que R3.7
prohíbe aquí. Poner `source` en la firma del puerto — el sello dejaría de ser del escritor (R3.1) y
`cleaning` podría pedir cualquier fuente.

### D4 — `ReportIncidentUseCase` gana dos parámetros opcionales, con su precondición descargada

**Chosen:** dos parámetros keyword-only con default `None`:

- `reported_by_user_id: uuid.UUID | None` — R3.3. La precondición que lo dejó fuera el 2026-08-16
  («arrastraba la misma precondición sin descargar») **está descargada aquí**: el valor sale del
  token verificado, así que el usuario ya está resuelto dentro del tenant por
  `auth/api/dependencies.py`, que además relee el rol de la fila en cada petición.
- `cleaning_task_id: uuid.UUID | None` — R4.3. Descargada por composición: el id es el de una tarea
  que el llamante ya resolvió con `tenant_id` explícito (D5).

Los dos defaults `None` dejan `seed_demo.py` y cualquier llamante futuro exactamente como están, y
mantienen R4.2 (la columna es opcional para las incidencias que no nacen de una limpieza).

Rejected: derivar `reported_by_user_id` de `actor.user_id` — «quien reporta» y «quien actúa» son dos
conceptos, y unificarlos cambiaría en silencio lo que escribe el seed de demo. Inyectar un
`CleaningTaskRepository` en `maintenance` para que verifique la tarea — crea la dependencia
`maintenance → cleaning` por una precondición que el llamante ya satisfizo, y `BlockingIncidentQuery`
existe precisamente para no tener que hacer eso.

### D5 — Quién resuelve la tarea y la propiedad, y por qué hay dos `properties.get`

**Chosen:** `ReportTaskIncidentUseCase` en `cleaning/application/use_cases.py`, calcado de
`GetCleaningTaskContextUseCase`:

1. `tasks.get(tenant_id, task_id)` → `None` ⇒ `CleaningTaskNotFoundError`;
2. `restrict_to_cleaner_id` distinto de `task.assigned_cleaner_id` ⇒ el mismo error;
3. `task.assert_incident_reportable(actor.user_id)` (D6);
4. `properties.get(tenant_id, task.property_id)` → `None` ⇒ el mismo error;
5. `self._incidents.report(...)` con `property_id=task.property_id`.

Los cuatro caminos de R2.3 responden `404 NOT_FOUND` con el mismo cuerpo.

**El orden decide un caso que R2.3 y R2.5 se disputan, y conviene decirlo en vez de dejarlo
implícito** (panel de sección 5, 2026-08-19): una tarea **propia**, terminal, cuyo `property_id`
no resuelve dentro del tenant cumple los dos criterios a la vez. Como el paso 3 va antes que el
4, gana el `409`. Es la resolución correcta y no un accidente del orden: para llegar hasta ahí
el llamante ya ha pasado los pasos 1 y 2, así que la tarea es suya y el `409` no le enseña nada
que no tuviera. Invertirlo sí costaría algo — un `404` en ese punto obligaría a resolver la
propiedad antes de la puerta de estado, y entonces el `409` de una tarea ajena volvería a ser
alcanzable, que es justo lo que el orden `_require_assignee`-antes-de-`_require_status` cierra
dentro de la entidad. R2.3 quedó anotada con esta precedencia. La comprobación de
propiedad que `ReportIncidentUseCase` hace por su cuenta **se queda**: es una precondición que el
puerto `IncidentRepository` declara como del llamante y que sirve a los demás llamantes; el coste es
un `SELECT` que en esta ruta nunca falla.

Rejected: dejar que salte la de `maintenance` — devuelve `MaintenanceValidationError` ⇒ `422`, un
cuerpo distinguible de los otros tres casos, que es la sonda de existencia que R2.3 cierra. Un
`JOIN` propio tarea+propiedad — sería el segundo sitio donde se escribe el scope de tenant (norma de
`dashboard-api` D2), y la composición es más estricta.

### D6 — La puerta de estado es una regla de dominio, por inclusión

**Chosen:** en `cleaning/domain/entities.py`, junto a `LIVE_STATUSES`:

```python
INCIDENT_REPORTABLE_STATUSES = frozenset({ASSIGNED, ACCEPTED, IN_PROGRESS})
```

y un método `CleaningTask.assert_incident_reportable(cleaner_id)` que reusa `_require_assignee`
antes de `_require_status`, en ese orden y por el motivo que ese docstring ya explica: un `409` que
describe el estado de una tarea ajena confirma que existe. `InvalidCleaningTransitionError` ya mapea
a `409 CONFLICT` en `cleaning/api/errors.py`, así que R2.5 no necesita excepción nueva.

**Por inclusión y no por exclusión**, al contrario que `OPEN_INCIDENT_STATUSES` en `maintenance`: es
una superficie de **escritura** del rol menos privilegiado, y un estado que se añada mañana no debe
volverse reportable por omisión. Los tres que quedan fuera de la lista de R2.5 son:

- `CREATED` — nadie se la ha entregado, así que no hay «durante checklist»; y para el único rol que
  tiene el permiso es un `404` antes de ser un `409`, porque `assigned_cleaner_id` es `NULL`.
- `PENDING_REVIEW` y `FAILED` — valores del enum **sin ningún escritor** en el flujo (`complete()`
  va directo a `COMPLETED` con `validation_status = PASSED`), así que quedan fuera por construcción.

La asimetría con la subida de fotos (sólo `IN_PROGRESS`) es deliberada: una foto es evidencia del
checklist y sólo existe mientras se trabaja; una caldera rota es un hecho del piso que la limpiadora
se encuentra al abrir la puerta, antes de pulsar «empezar».

Rejected: definir el conjunto por exclusión de los tres terminales — deja `PENDING_REVIEW`/`FAILED`
reportables sin que nadie lo haya decidido. La puerta en el caso de uso — es una regla, y
`steering/backend-architecture.md` la manda a `domain/`.

### D7 — Un `title`/`description` que la base de datos pueda guardar: un solo hogar

**Chosen:** promover a `backend/app/core/storable_text.py` el guardián `_storable_text` y sus dos
alias (`SingleLineText`, `MultiLineText`) que hoy son privados de
`guests/api/portal_schemas.py:58-147`, y promover con ellos los dos máximos
(`MAX_INCIDENT_TITLE = 300`, `MAX_INCIDENT_DESCRIPTION = 5000`) a
`maintenance/domain/entities.py`, que es el módulo dueño de la columna — el mismo argumento por el
que `CONVERSATION_INCIDENT_TITLES` vive ahí. Los dos esquemas de petición importan de esos dos
sitios.

Esto no es limpieza opcional: sin el guardián, un `title` con `U+0000` o con un surrogate suelto
llega a asyncpg y sale un `500` sin declarar, que es el fallo exacto que el panel de sección 7 de
`guest-portal-api` midió dos veces sobre estas dos columnas. Nuestra ruta es el segundo escritor
humano de las mismas columnas, con `min_length=1` y strip como única defensa.

Rejected: redeclarar el guardián en `cleaning/api/schemas.py` — tres copias de un guardián cuyo
razonamiento son 40 líneas ganadas a base de paneles. Importar el privado de otro módulo de `api/` —
`cleaning/api` no tiene por qué conocer `guests/api`.

### D8 — El acuse: un value object del puerto, con `status` tipado

**Chosen:** el puerto devuelve
`IncidentReportedAcknowledgement(id: uuid.UUID, status: IncidentStatus, created_at: datetime)`,
declarado junto al puerto en `cleaning/domain/ports.py`, y `TaskIncidentReportedResponse` en
`cleaning/api/schemas.py` lo mapea a los tres campos de R4.4 — espejo del
`IncidentReportedResponse` del portal (`guests/api/portal_schemas.py:324`), con un test que fija el
conjunto exacto (R4.5).

Importar `IncidentStatus` en el puerto **no** es lo que `BlockingIncidentQuery` evitó: aquél
devolvió un booleano para no importar el **agregado** `Incident` por un sí/no. Un enum es un valor
sin comportamiento, y es lo que hace que la operación aparezca en `openapi.json` con el mismo
esquema que la del portal en vez de con un `string` suelto.

Rejected: devolver `Incident` — mete el agregado de otro dominio en `cleaning`. Devolver sólo el
`uuid` y poner `"OPEN"` literal en la ruta — la ruta afirmaría un estado que no ha leído. `status:
str` — el contrato del frontend perdería el enum sin ganar nada.

### D9 — El censo de la regla 11: **excepción 3**, ensanchada; y el guardián, por importación

**Chosen (censo):** dos filas nuevas en la tabla de `sdd/steering/security.md` §«Sumideros de texto
en claro» —una para `incidents.title` y otra para `incidents.description`, escritor «la
**limpiadora** (persona autenticada, desde su propia tarea)»— bajo la **excepción 3**, cuyo
enunciado se ensancha para nombrarlas, igual que `messaging-ai` lo ensanchó para
`messages.content`. Dos filas y no una: la granularidad de esa tabla ya es por columna y por
escritor, y es lo que hizo `seed-data-demo-extension` con el mismo par y el mismo contrato. El
recuento de la cabecera pasa de «Dieciocho columnas, **veintitrés filas**» a **veinticinco filas**;
las dieciocho columnas y las «dieciséis vivas» no se mueven, porque este change no añade ninguna
columna al censo (`cleaning_task_id` es un UUID con clave ajena, no texto libre).

La excepción 3 y no la 2: la 2 declara como escritor a **quien reporta desde el portal** —un
anónimo de internet— y dice de sí misma que «no autoriza a un escritor nuestro»; la 3 es
literalmente «lo que teclea una persona autenticada con RBAC… sobre su propio ámbito», que es una
limpiadora con `EXECUTE_CLEANING_TASKS` describiendo el piso que está limpiando. Y una excepción 6
por parecido es lo que el párrafo de cierre de la regla 9 prohíbe.

**Chosen (guardián):** `backend/tests/maintenance/test_free_text_sink_contract.py` gana una
**quinta cláusula de puerta**: un módulo entra también si **importa** `app.cleaning.domain.ports`
(el módulo que declara el puerto), leído del AST y no como subcadena. Hacía falta porque el llamante
que este change estrena es exactamente el hueco que ese docstring predijo — «un llamante tipado sólo
contra un alias de protocolo que no menciona ninguno de los cuatro nombres»— y él mismo dice que la
respuesta entonces «es el grafo de importación y no otra subcadena». La cláusula admite además
`properties/application/use_cases.py`, `cleaning/application/evidence.py` y `scheduler/tasks.py`,
que no escriben ninguna de las dos columnas: el conjunto de infractores no se mueve y la puerta
queda más estrecha gratis, que es el mismo argumento con el que entró la cláusula del puerto.

Con esa puerta, el módulo que nombra las columnas en posición de escritura se allowlistea con su
contrato escrito: `cleaning/api/schemas.py`. Y el mapeo petición→dominio vive en ese esquema
(`ReportTaskIncidentRequest.to_report() -> IncidentReport`), de modo que `tasks_router.py` no
nombra **`title`** en posición de escritura.

> **Corregido el 2026-08-22 contra la medición (paneles de las secciones 7 y 3-4).** Este párrafo
> decía dos cosas que resultaron falsas, y las dos habrían mandado al siguiente revisor a buscar
> algo que no está:
>
> 1. **«los dos módulos… `cleaning/application/use_cases.py` y `cleaning/api/schemas.py`».** Sólo
>    el esquema nombra las columnas; el caso de uso pasa `report=report` y no nombra ninguna, así
>    que allowlistearlo habría sido una entrada para un no-infractor —y el propio docstring del
>    guardián dice que una allowlist que tiene que nombrarlo todo no prueba nada—. Además ya
>    estaba gateado de antes, por contener la subcadena `IncidentRepository`.
> 2. **«el router se queda fuera por construcción… no nombra `title` ni `description`».**
>    `tasks_router.py` tiene **quince** `description=`, todos metadatos de ruta de FastAPI: el
>    mismo falso positivo que el fichero del guardián ya documenta para los dos routers de
>    `maintenance`. Lo que lo mantiene fuera de la lista es que **ninguna cláusula lo gatea**, no
>    dónde pusimos el mapeo. Mover el mapeo sigue valiendo la pena — saca el `title=`, que sí
>    sería una escritura real — pero la afirmación fuerte no era cierta.
>
> Y la cláusula **no** admite `scheduler/tasks.py`, que no importa el puerto: admite
> `cleaning/application/evidence.py` y `properties/application/use_cases.py`, ninguno de los cuales
> escribe las columnas, así que el argumento de «más estrecha gratis» se sostiene con dos módulos
> en vez de tres. Todo ello medido con el matcher del propio guardián y fijado en
> `test_the_fifth_clause_admits_three_modules_and_moves_no_offender`.

Rejected: añadir `TaskIncidentReportingPort` como sexta subcadena — es la erosión que ese docstring
lleva tres rondas documentando, y no atraparía al router. Cierre transitivo del grafo de
importación — arrastra `main.py`, la CLI y casi todos los routers (cualquiera con `description=` de
metadatos de FastAPI), convirtiendo la allowlist en ruido.

### D10 — La columna, su migración y su fila de auditoría

**Chosen:** `IncidentModel.cleaning_task_id: Mapped[uuid.UUID | None]` con
`ForeignKey("cleaning_tasks.id", ondelete="RESTRICT")` y `default=None` — la misma postura que
`property_id` y `reservation_id` en esa tabla, y no el `SET NULL` de `reported_by_user_id`, que es la
postura de las FK hacia `User` (`specs/domain-foundation-ops.md:32`). Migración Alembic con
`down_revision = "e7a3c419d82b"` (cabeza única hoy), añadiendo columna y FK; nada que rellenar,
porque toda fila existente queda `NULL` (R4.2). Sin índice nuevo: este change no introduce ninguna
consulta por esa columna.

`AUDITABLE_FIELDS["INCIDENT"]` gana `cleaning_task_id` (pasa de once campos a doce) y el `ChangeSet`
del alta lo difunde, junto a `source` y `status`, **cuando lo hay**.

> **Enmienda del 2026-08-19 (panel de secciones 3-4, aceptada).** Esa última coletilla no estaba:
> la redacción original ponía «cuando la hay» sólo en la mitad del `TimelineEvent`, de modo que
> leída al pie de la letra pedía dos reglas distintas para el mismo valor. Se implementó
> condicional en las dos mitades y el arquitecto pidió que el diseño lo dijera, en vez de dejar
> la desviación sin registrar. El motivo es que `ChangeSet.diff` **siempre** inserta la clave, así
> que la llamada incondicional estamparía `{"old": null, "new": null}` en la fila de auditoría de
> toda incidencia del portal del huésped, del pipeline de mensajería y del comando de siembra
> —cuatro fuentes que nunca pueden tener una limpieza detrás— y `audit_logs` es append-only, así
> que ese nulo no se podría quitar después. Lo fija
> `tests/maintenance/test_report_incident.py::test_the_audit_row_omits_the_key_entirely_when_there_is_no_task`. Es un identificador, no texto: R5.2 sigue intacta.
El `metadata` del `TimelineEvent` gana la misma clave cuando la hay — sólo identificadores, la
disciplina que D10 de `maintenance` fijó.

Rejected: no auditar el vínculo — la fila de auditoría de una incidencia registra contra qué se
ancló (`reservation_id` está ahí por eso), y «durante qué limpieza» es el ancla equivalente.
`ondelete="SET NULL"` — perdería el vínculo justo cuando alguien borra la tarea, que es cuando más
importa.

### D11 — R6 no cambia una línea de código

**Chosen:** la tercera cláusula de `CleaningTask.complete()` se queda como está
(`has_unresolved_critical(tenant_id, property_id)`), y el mensaje de `BlockingIncidentError` ya
cumple R6.3: es la constante «An unresolved CRITICAL incident blocks completing this cleaning», sin
id, sin título y sin descripción. Lo que R6 aporta es **prosa declarada** (la incidencia nace
`MEDIUM` — `Incident.severity` por defecto — así que no bloquea en el momento; sólo la bloquea si el
job de clasificación la sube a `CRITICAL`) y **un test de recorrido completo** (R6.4): la limpiadora
reporta, el clasificador la sube a `CRITICAL`, y su `complete()` responde `409`.

Rejected: estrechar la cláusula a la tarea — fuera de alcance por decisión del gate de `/sdd:new`, y
relajaría un invariante de cierre existente.

### D12 — Dónde **no** se puede escribir la atribución del sumidero

**Chosen:** ni `sdd/specs/cleaner-incident-report.md` (que nacerá al archivar) ni `docs/cleaning.md`
declaran quién escribe `incidents.title`/`description`: `backend/tests/test_rule11_ownership.py`
recorre `sdd/`, `docs/`, `backend/app/`, `backend/alembic/versions/` y `backend/tests/` y se pone en
rojo cuando un bloque nombra el sumidero **y** atribuye su escritor fuera de la tabla de
`security.md`. La spec y la doc describen el acotamiento (`min_length`, máximos, strip, storable) y
**enlazan** a la regla 11; la propiedad vive sólo en la tabla. `sdd/changes/` está excluido entero,
así que este documento puede decirlo.

**Addendum del 2026-08-19 (panel de sección 2, desviación acordada con el usuario).** Este
guardián tenía un falso negativo estructural, y conviene que conste porque D12 se apoya en su
verde: `_python_blocks` construía los bloques con `lstrip("#")`, que deja los dos puntos de
Sphinx, de modo que una frase repartida en dos líneas de un comentario `#:` quedaba como
«`…this module is\n: the writer of …`» y ninguna de las trece expresiones de
`OWNERSHIP_PATTERNS` casaba: `\s+` no acepta un `:`. Resultado: la cadena que el guardián
persigue **literalmente** llevaba desde `messaging-ai` en
`backend/app/maintenance/domain/entities.py` y el test la certificaba ausente. No es el residuo
de paráfrasis que su propio docstring documenta —era su vocabulario exacto sin ver—. Reparado
en la tarea 2.2, con el radio de impacto medido antes de tocarlo: exactamente un bloque nuevo
en `app/`, `tests/` y `alembic/versions/`.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Dominio `cleaning` | `backend/app/cleaning/domain/entities.py` | `INCIDENT_REPORTABLE_STATUSES` + `CleaningTask.assert_incident_reportable()` (D6) |
| Dominio `cleaning` | `backend/app/cleaning/domain/ports.py` | `TaskIncidentReportingPort`, `IncidentReport`, `IncidentReportedAcknowledgement` (D2, D8) |
| Aplicación `cleaning` | `backend/app/cleaning/application/use_cases.py` | `ReportTaskIncidentUseCase` (D5) |
| API `cleaning` | `backend/app/cleaning/api/schemas.py` | `ReportTaskIncidentRequest` (`extra="forbid"`, strip, `min_length=1`, máximos, storable) + `to_report()` + `TaskIncidentReportedResponse` (D7, D8, D9) |
| API `cleaning` | `backend/app/cleaning/api/tasks_router.py` | la ruta `POST /{task_id}/incidents`, `201`, `ExecuteDep`, `_INCIDENT_REPORT_RESPONSES` (404/409/422) (D1) |
| API `cleaning` | `backend/app/cleaning/api/dependencies.py` | `get_report_task_incident_use_case`, que construye el implementador de `maintenance` (D2) |
| Aplicación `maintenance` | `backend/app/maintenance/application/use_cases.py` | `CleanerIncidentReporter` + los dos parámetros de `ReportIncidentUseCase` + `cleaning_task_id` en `ChangeSet` y en el `metadata` del timeline (D3, D4, D10) |
| Dominio `maintenance` | `backend/app/maintenance/domain/entities.py` | `Incident.cleaning_task_id`; `MAX_INCIDENT_TITLE`/`MAX_INCIDENT_DESCRIPTION` (D7, D10) |
| Infra `maintenance` | `backend/app/maintenance/infrastructure/models.py`, `repositories.py` | la columna y su FK; `add()` y el mapeo fila→entidad la llevan (D10) |
| Auditoría | `backend/app/audit/domain/value_objects.py` | `cleaning_task_id` en `AUDITABLE_FIELDS["INCIDENT"]` (D10) |
| Core | `backend/app/core/storable_text.py` (nuevo), `backend/app/guests/api/portal_schemas.py` | el guardián y sus alias pasan a tener un solo hogar (D7) |
| Migración | `backend/alembic/versions/<rev>_cleaner_incident_report.py` | columna + FK, `down_revision = "e7a3c419d82b"` (D10) |
| Contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | regenerados y commiteados en el mismo PR (R1.5) |
| Tests | `backend/tests/cleaning/test_task_incident_api.py`, `test_task_incident_use_case.py` (nuevos), `test_entities.py`, `test_errors.py` | ruta, caso de uso, la puerta de estado como unit test, aislamiento entre tenants |
| Tests | `backend/tests/maintenance/test_free_text_sink_contract.py` | quinta cláusula + dos entradas de allowlist (D9) |
| Tests | `backend/tests/maintenance/test_report_incident.py`, `tests/cleaning/test_task_lifecycle.py` | los dos parámetros nuevos; el recorrido de R6.4 |
| Steering | `sdd/steering/security.md` | dos filas, el recuento y el enunciado de la excepción 3 (D9) |
| Docs | `docs/cleaning.md`, `docs/maintenance.md`, `docs/diagrams/` | cómo se opera la ruta; el ER se regenera (Risks) |

## Data & interfaces

**Esquema.** Una columna: `incidents.cleaning_task_id UUID NULL REFERENCES cleaning_tasks(id) ON
DELETE RESTRICT`. Ningún backfill, ningún índice, ningún cambio de tipo.

**Ruta.** `POST /api/v1/cleaning-tasks/{task_id}/incidents` · Bearer JWT ·
`EXECUTE_CLEANING_TASKS`.

- Petición: `{"title": str, "description": str}`, `extra="forbid"`, ambos con strip previo,
  `min_length=1`, `max_length` 300 y 5000, y el guardián de storable-text.
- `201`: `{"id": uuid, "status": IncidentStatus, "created_at": datetime}` — tres campos, y ninguno más.
- `401`/`403` del router; `404 NOT_FOUND` (los cuatro casos de R2.3, cuerpo idéntico);
  `409 CONFLICT` (tarea en estado no reportable); `422 VALIDATION_ERROR` (cuerpo inválido). Todos con
  el envoltorio `{error:{code,message,details}}`.

**Sin variables de entorno nuevas, sin config nueva, sin strings de UI** (la UI es de `cleaner-app`).

**Logs.** `task_id` e `incident_id`; nunca el texto reportado (R5.4).

## Risks & mitigations

- **El test de aislamiento no puede fallar sobre una sesión marcada.** El listener de
  `app/core/db.py` filtra por tenant hasta el `select` de una columna, así que un test de aislamiento
  escrito sobre la sesión marcada pasa siempre. El de esta ruta se escribe sobre una sesión **sin
  marcar** para demostrar que el `404` cross-tenant lo produce el código y no el listener.
- **Regenerar el contrato del frontend no funciona tal cual en un worktree.** `npm run api:generate`
  falla por las rutas que el script resuelve dos niveles por encima de `scripts/`; hay que usar la
  salida verificada de `sdd/project.md` (`docker compose cp` + los dos enlaces) y `api:check` para
  confirmar. Es el mismo filo que rompió `main` en el change `cleaning`.
- **El diagrama ER queda obsoleto.** Se genera desde la metadata de SQLAlchemy, y una columna con
  clave ajena es una relación más: 31 entidades y **76** relaciones (74 pares de tablas distintos).
  Hay que regenerarlo con `/sdd:diagram`, borrar `2026-08-11_autohost-er-entidades.png` y actualizar
  el párrafo del recuento en `sdd/steering/architecture.md`. **Sin abrir el PNG** (regla 11 de las
  reglas compartidas: mirarlo cuesta ~140k de contexto). El de secuencia de mantenimiento
  (`2026-08-15_…`) sólo se regenera si enumera las superficies de creación; el único modo de saberlo
  sin leerlo es que la tarea lo decida a partir de lo que `maintenance` documentó al generarlo.
- **La spec de `maintenance` afirma tres cosas que este change vuelve falsas** y hay que reescribir
  al archivar, además de la fila RBAC y el `NEVER SHALL` de R7: «SHALL NOT aceptar `reservation_id`
  ni `reported_by_user_id`», «auditar sobre `INCIDENT` exactamente **once** campos», y la
  enumeración de cláusulas del guardián del censo. R7.4 (grep de la redacción vieja) las cubre sólo
  si se busca por las tres redacciones, no por una.
- **Dos `SELECT` de la misma propiedad por alta** (D5). Coste asumido y medido en una fila; el
  alternativo es un cuerpo de error distinguible.
- **El `409` de R2.5 y el `409` de R6.3 llegan del mismo mapeo.** Son `InvalidCleaningTransitionError`
  y `BlockingIncidentError`, dos filas distintas de `_MAPPING` con mensajes distintos; el test de
  R6.4 asierta el mensaje, no sólo el código, para que no se confundan.

## Open questions

**Las tres se resolvieron en el gate de `/sdd:design` del 2026-08-19, las tres como recomendaba este
documento.** Quedan escritas con su alternativa rechazada, no borradas: lo que se decidió aquí es
parte del contrato que `/sdd:tasks` tiene que ejecutar.

1. **¿Tocar `guests/` para dar un solo hogar al guardián de storable-text y a los dos máximos
   (D7)?** — **Resuelto: promover.** El guardián y sus alias van a `app/core/storable_text.py` y los
   dos máximos a `maintenance/domain/entities.py`, con `guests/api/portal_schemas.py` importando de
   los dos sitios. Rechazado: redeclararlo en `cleaning` (una tercera copia de 40 líneas ganadas a
   base de paneles) y prescindir del guardián (deja vivo el `500` sin declarar).
2. **¿Quinta cláusula del guardián del censo por importación, o sexta subcadena (D9)?** —
   **Resuelto: por importación** de `app.cleaning.domain.ports`, leída del AST. Rechazado: gatear
   por el nombre del puerto (la erosión que ese docstring lleva tres rondas documentando, y deja el
   router fuera) y el cierre transitivo del grafo (arrastra `main.py`, la CLI y casi todos los
   routers, y convierte la allowlist en ruido).
3. **¿`cleaning_task_id` en `AUDITABLE_FIELDS["INCIDENT"]` (D10)?** — **Resuelto: sí, doceavo
   campo**, con la reescritura del «exactamente once campos» de `specs/maintenance.md` R9 que eso
   arrastra. Rechazado: dejarlo fuera, que deja el alta de la limpiadora con una fila de auditoría
   que no dice contra qué tarea se abrió — lo único que la distingue de las demás altas.
