# Design: tech-cycle-completion

## Context

El ciclo del técnico vive entero en `backend/app/maintenance/`. La tabla de transiciones es
`Incident._TRANSITIONS` en `domain/entities.py` —declarada **por nombre de operación**, con
`_check_transition` validando sin mutar—, y los cuatro pasos que conduce el técnico son
subclases de `_TechnicianStepUseCase` (`application/use_cases.py:1582`) que se diferencian
sólo en una tupla `_STEP = (método de la entidad, acción de auditoría, evento de timeline |
None)`. El acotamiento por fila —el `404` indistinguible de R8— lo da una única corrutina de
módulo, `_load_incident_in_scope` (`use_cases.py:427`), y la persistencia pasa por
`_MUTABLE_INCIDENT_COLUMNS` (`infrastructure/repositories.py:57`), una lista blanca de
columnas actualizables.

Lo medido en el código, que confirma las dos premisas del proposal: `TECHNICIAN_STARTED`
tiene **dos** escritores (`StartIncidentUseCase` y `ResumeWorkUseCase`, ambos por su `_STEP`)
y `TECHNICIAN_EN_ROUTE` **ninguno** — aparece sólo en `timeline/domain/enums.py:48` y en el
catálogo de renderizado `timeline/domain/rendering.py:179`. `POST /incidents/{id}/start` no
tiene consumidor: nada bajo `frontend/`, ni `app/cli/seed_demo.py`, ni `app/scheduler/`
la llama; sus únicas menciones vivas son el router, sus dependencias y `docs/maintenance.md:42`.
Y `cancel` es `MANAGE_INCIDENTS` (`incidents_router.py:436`, `ManageDep`), así que no le sirve
al técnico como sustituto del rechazo.

Los sitios que este change tiene que tocar fuera del módulo son cuatro y están todos
inventariados: `AUDITABLE_FIELDS["INCIDENT"]` (`audit/domain/value_objects.py:324`, doce
campos), las acciones de `audit/domain/actions.py`, el enum y el catálogo ES/EN del timeline,
y el censo de sumideros de `sdd/steering/security.md` con sus dos guardianes automáticos
(`backend/tests/maintenance/test_free_text_sink_contract.py` y
`backend/tests/test_rule11_ownership.py`).

## Decisions

### D1 — `reject` es un paso más de `_TechnicianStepUseCase`, no un caso de uso aparte

**Chosen:** `RejectIncidentUseCase(_TechnicianStepUseCase)` con
`_STEP = ("reject", audit_actions.INCIDENT_REJECTED, TimelineEventType.TECHNICIAN_REJECTED)`
y un `_after_step` que cancela el plazo de SLA y notifica al manager. La mezcla ya da
gratis lo que R1.6, R1.7 y R1.8 piden: `_load_incident_in_scope` produce el `404`
indistinguible para el técnico que no es el asignado, y `_check_transition` produce los tres
errores que R1.8 distingue sin escribir ningún campo. `AcceptIncidentUseCase` ya demuestra
que un paso puede traerse colaboradores propios (`notifications`) y cancelar el plazo desde
`_after_step`; el rechazo hace lo mismo más una notificación.

Rejected: un `RejectIncidentUseCase(_IncidentFlowBase)` escrito a mano — repetiría la carga,
la comprobación de alcance, la auditoría y el timeline, que es lo que la mezcla existe para
no duplicar por quinta vez.

### D2 — Lo que el rechazo limpia: los **tres** campos de la asignación vigente

**Chosen:** `Incident.reject(now)` pone a `NULL` `assigned_technician_id`, `eta_at` **y**
`assignment_note`, y transiciona a `CLASSIFIED`. R1.2 nombra sólo el primero, pero los tres
pertenecen a la asignación y no a la incidencia: `assignment_note` ya lo declara así
`tech-incident-context` D7 («la nota pertenece a la asignación en vigor»), y R3.5 lo declara
de `eta_at`. Una incidencia `CLASSIFIED`, sin asignatario, que conserve la nota que el manager
escribió para el técnico que dijo que no —o la hora a la que ese técnico dijo que llegaría—
es la misma «fila que miente» que el `ASSUMPTION` de R1 rechaza para `assigned_technician_id`.

Quién rechazó no se pierde: va en el `AuditLog` (que sí audita `assigned_technician_id`, con
su valor anterior) y en el `metadata` del `TimelineEvent`.

Rejected: limpiar sólo `assigned_technician_id`, la letra de R1.2 — deja dos campos huérfanos
que el siguiente `assign` sobrescribiría de todos modos, con la ventana intermedia mintiendo.
Rejected: conservar los tres como registro, la decisión de `cleaning` — allí la tarea
rechazada es **terminal** y la columna es el registro de quién dijo que no; aquí la incidencia
sigue viva y se va a reasignar.

### D3 — El `notification_type` del rechazo es una constante de texto, no un miembro de `NotificationType`

**Chosen:** `NOTIFICATION_TYPE_INCIDENT_REJECTED = "INCIDENT_REJECTED"` en
`maintenance/domain/notifications.py`, escrito en la columna `String(100)` tal cual. Es
exactamente lo que hace `guests` con `LEGAL_REGISTRATION_FAILED`
(`guests/application/use_cases.py:576`), y por sus mismas tres razones: `NotificationType`
son los dieciséis nombres canónicos de PRD §14 y éste no es uno; la columna es texto libre
desde `domain-foundation-financial`, así que **no hay migración**; y `escalation_for` devuelve
`None` para un tipo que no reconoce, que es literalmente el «sin plazo de SLA y sin escalado»
que R1.4 exige — obtenido por construcción en vez de por una omisión que alguien pueda
rellenar.

Rejected: añadir `INCIDENT_REJECTED` a `NotificationType` — ensancha un enum cuyo contrato es
«los nombres exactos de §14» y obliga a decidir su política de escalado en
`notifications/domain/escalation.py`, decisión que este change no tiene base para tomar.

Esto responde la OQ3 del proposal.

### D4 — `start` se renombra a `en_route`, y `resume_work` conserva `TECHNICIAN_STARTED`

**Chosen:** el renombrado es total y en un solo sentido — `Incident.start` → `Incident.en_route`,
la clave `"start"` de `_TRANSITIONS` → `"en_route"`, `StartIncidentUseCase` →
`EnRouteIncidentUseCase` con `_STEP = ("en_route", INCIDENT_STARTED, TECHNICIAN_EN_ROUTE)`,
`get_start_incident_use_case` → `get_en_route_incident_use_case`, y la ruta
`POST /incidents/{id}/start` → `POST /incidents/{id}/en-route`. No queda alias ni ruta doble
(R2.3).

`ResumeWorkUseCase` **no cambia**: sigue escribiendo `TECHNICIAN_STARTED`. Además de ser lo
que R2.4 pide, es lo que hace la decisión reversible al coste correcto: PostgreSQL **no puede
retirar una etiqueta de un enum** —está escrito en el docstring de
`e7a3c419d82b_guest_portal_api.py`, que por eso ni siquiera la quita en su `downgrade`—, así
que dejar `TECHNICIAN_STARTED` sin escritor no significa «borrar un miembro» sino «dejar
código muerto que la base de datos no deja limpiar».

La consecuencia asumida, dicha en vez de ocultada: en el camino normal (`accept` → `en-route`
→ `resolve`) el timeline ya no dice nunca «el técnico ha empezado» — dice «técnico en
camino», que es exactamente lo que PRD §12 pinta. `TECHNICIAN_STARTED` pasa a significar «el
técnico reanudó tras esperar piezas», y su etiqueta ES/EN actual («El técnico ha empezado» /
«Technician started») **no se toca**: el timeline es inmutable y hay filas históricas escritas
por `start` a las que esa etiqueta sí describe.

Rejected: que `resume_work` no escriba evento, como `wait_for_parts` — dejaría el miembro sin
escritor y no se puede retirar, que es el hueco que este change viene a cerrar, no a mover.
Rejected: dejar `start` como alias de `en-route` durante una transición — no hay consumidor
que proteger (medido: cero), y un alias en el contrato publicado es deuda que nadie retira.

Esto responde la OQ1 del proposal.

### D5 — El diff auditado de un paso se **deriva**, sobre tres campos permitidos

**Chosen:** `_TechnicianStepUseCase` fotografía tres campos antes de mutar
—`_STEP_AUDITED_FIELDS = ("status", "assigned_technician_id", "eta_at")`— y construye el
`ChangeSet` con los que hayan cambiado. Hace falta porque los pasos dejan de tener todos el
mismo diff: el rechazo mueve `assigned_technician_id` y `accept`/`en_route` pueden mover
`eta_at`, mientras hoy la mezcla escribe `.diff("status", …)` y nada más.

Los tres campos están en `AUDITABLE_FIELDS["INCIDENT"]` (`eta_at` entra por R5.1), así que la
derivación no puede colarse fuera de la lista blanca; y `assignment_note` queda **fuera de la
tupla a propósito**, porque nombrarlo levanta `AuditContractError` — el contrato que
`test_free_text_sink_contract.py` fija. Para los cuatro pasos actuales sin ETA el resultado es
byte a byte el de hoy: `status` cambia en toda transición, y ningún otro de los tres se mueve.

Rejected: un `ChangeSet` escrito a mano en cada subclase — cuatro copias de la misma lista
blanca, y la quinta es la que se olvida un campo.
Rejected: derivar sobre *todos* los campos auditables (doce/trece) — convierte una fila de
auditoría en un volcado y pierde la intención de cada acción.

### D6 — `eta_at`: se valida en la entidad, se limpia en `assign` y en `reject`

**Chosen:** el cuerpo de `accept` y de `en-route` es un **único** esquema compartido,
`IncidentEtaRequest`, con un solo campo `eta_at: datetime | None = None` y
`extra="forbid"`; el parámetro del router es opcional (`payload: IncidentEtaRequest | None =
None`), así que un `POST .../accept` sin cuerpo sigue funcionando igual que hoy. Un esquema y
no dos porque el conjunto de campos es idéntico y duplicarlo pondría el «sólo estas dos rutas»
de R3.2 en dos sitios.

La validación de R3.4 vive en la **entidad**, en un ayudante privado `_apply_eta(eta_at, now)`
que llaman `accept` y `en_route` **después** de `_check_transition` y antes de `_transition`:
una regla («una ETA no puede estar en el pasado») pertenece a `domain/` por
`steering/backend-architecture.md`, y ese orden es el que R1 exige — transición comprobada
antes de escribir nada, y `MaintenanceValidationError` sin escribir nada si la ETA es mala.
`_apply_eta` exige además una marca **con zona horaria** (`tzinfo is None or utcoffset() is
None` → `MaintenanceValidationError`), la comprobación que `properties`, `timeline`, `auth` y
`cleaning` ya hacen en sus bordes, porque sin ella la comparación con `now` revienta como
`TypeError` y sale por el `500` genérico.

R3.3 («si el cuerpo no lo trae, deja el valor anterior intacto») cae sola: `eta_at=None`
significa «no lo trae» y `_apply_eta` retorna sin tocar nada. `assign` la pone a `NULL`
incondicionalmente (R3.5), junto a `assignment_note`, que ya se escribe así; `reject` también
(D2).

Rejected: validar en el esquema de pydantic — el instante de referencia es `now_utc()` del
router, y una regla de negocio en un DTO deja al caso de uso no-HTTP (`seed_demo`, tests) sin
ella.
Rejected: `eta_at` como campo de un `PATCH` de triaje — R3.2 la ata a las dos operaciones que
el técnico ejecuta, y el triaje es del manager.

### D7 — `materials`: opcional que **preserva**, no que sustituye

**Chosen:** `materials` es opcional en el cuerpo de `resolve` y, cuando viene, se escribe;
cuando no viene, se deja lo que hubiera. Es el mismo criterio que R3.3 fija para `eta_at`, y
aquí es **lo que hace verdadera a R4.3**: el cierre que abre la segunda puerta de aprobación
escribe `materials` y aparca la incidencia; cuando la propietaria aprueba, el técnico repite
el cierre — y si ese segundo cuerpo llegara sin `materials` con la semántica «operación
completa» de `assign`, borraría en silencio lo que R4.3 acaba de proteger.

Mecánicamente: `materials` viaja como argumento opcional por palabra clave a
`Incident.resolve(...)` **y** a `Incident.require_owner_approval(...)`, exactamente como ya
viaja `final_cost` a las dos — que es la simetría correcta, porque `materials` es la
explicación de ese número (R4.4: ninguno se deriva ni se valida contra el otro).

El acotamiento: `MAX_MATERIALS = 2000` en `maintenance/domain/entities.py`, importado por
`api/schemas.py` y espejado en el DDL (`String(2000)`). Vive ahí y no en el esquema porque es
la regla que `cleaning/api/schemas.py` ya cita por escrito — el módulo que posee la columna
posee su cota, y un `2000` literal en el DTO es una copia que nadie mantiene. El campo se
anota `MultiLineText` (`app/core/storable_text.py`) con `str_strip_whitespace=True` y
`min_length=1`: recorta espacios, rechaza el `U+0000` y el sustituto suelto que si no salen
por un `500` sin declarar, y hace que «sin materiales» se diga **omitiendo el campo** y no
mandando `""`.

Rejected: semántica de «operación completa» como en `assign` — rompe R4.3 en el camino de la
aprobación, que es justo el que R4.3 nombra.
Rejected: `materials` como lista estructurada de partidas — es `Expense` y
`revenue-statements`, fuera de alcance por el propio proposal.

### D8 — `materials` y `eta_at` se quedan en `IncidentResponse`, listado incluido

**Chosen:** los dos campos entran en `IncidentResponse`, que es el esquema que sirven a la vez
el detalle y los `items` del listado paginado. `properties.access_notes` pagó salir del
listado por la **excepción 6** —una nota sobre cómo se entra en una vivienda, que además
`GET /api/v1/guest/info/{token}` devuelve verbatim a un portador anónimo—; `materials` es
**excepción 3** y su audiencia es exactamente la que ya lee `title`, `description` y
`ai_summary` en ese mismo listado, con `READ_INCIDENTS` y, si es técnico, sólo sus propias
filas. Partir el esquema no quitaría lectores: duplicaría `IncidentResponse` y le quitaría a
la lista del técnico —lo que `tech-app` va a pintar— la única columna que explica el coste.

Rejected: `IncidentListItem` sin los dos campos + `IncidentResponse` con ellos — dos esquemas,
dos `from_domain`, y un delta de exposición de cero.

Esto responde la OQ2 del proposal.

### D9 — Una sola revisión de Alembic: dos columnas y una etiqueta de enum

**Chosen:** una revisión encadenada tras `b3f5d1c8a047` con tres sentencias: dos
`op.add_column` nullable y sin `server_default`, y un
`ALTER TYPE timeline_event_type ADD VALUE IF NOT EXISTS 'TECHNICIAN_REJECTED'`. Es la forma
que ya está probada dos veces en este repo — `b9d24e70c1af_incident_assignment_note.py` para
la columna, `e7a3c419d82b_guest_portal_api.py` para la etiqueta— y las dos traen su
razonamiento hecho: `ADD COLUMN … NULL` sin default no reescribe la tabla en PostgreSQL 16, y
`ALTER TYPE … ADD VALUE` **no** necesita `autocommit_block()` porque la restricción de
PostgreSQL 12+ es sobre *usar* la etiqueta en la transacción que la añade, y esta revisión no
escribe ninguna fila de timeline (envolverla costaría la atomicidad de `alembic upgrade head`,
porque `alembic/env.py` abre una transacción para toda la tanda).

El `downgrade` quita las dos columnas y **deja la etiqueta**, con el motivo escrito: PostgreSQL
no sabe quitar un valor de un enum, y `alembic downgrade base` tira el tipo entero en la
revisión que lo creó. La cadena del proyecto es estrictamente lineal y
`tests/test_migrations.py` la recorre en los dos sentidos, así que la revisión se encadena, no
se bifurca.

Rejected: dos revisiones (columnas / enum) — la cadena lineal y el test que la recorre hacen
que dos revisiones cuesten el doble sin comprar nada; nada aquí depende de nada.

**Corregido en `/sdd:run` (2026-08-22): el padre es `b3f5d1c8a047`, no `b9d24e70c1af`.** Este
diseño se escribió nombrando `b9d24e70c1af` como cabeza de la cadena, y para cuando llegó la
implementación ya no lo era: `cleaner-incident-report` archivó `b3f5d1c8a047` —cuyo
`down_revision` **es** `b9d24e70c1af`— el mismo día. Encadenar tras el que decía la letra
habría producido **dos cabezas**, que es exactamente lo que este párrafo prohíbe («la cadena
del proyecto es estrictamente lineal … así que la revisión se encadena, no se bifurca»). La
decisión no cambia; el SHA sí, y consta porque una cabeza medida vale más que una citada.

### D10 — El censo de la regla 11 y sus **dos** guardianes

**Chosen:** `incidents.materials` entra en la tabla de `sdd/steering/security.md` con fila
propia bajo la excepción 3, y los cuatro números de su cabecera se recuentan **contra la
tabla**: hoy dice veinte columnas, veintisiete filas, seis excepciones y veinte vivas;
contadas una a una salen 20/27/6/20, así que con la fila nueva quedan **21 columnas, 28 filas,
6 excepciones y 21 vivas** (R4.5).

Los dos tests que hay que mover, y son dos y no uno:

1. `backend/tests/maintenance/test_free_text_sink_contract.py` — `SINK_COLUMNS` pasa de tres a
   cuatro. Eso arrastra: la aserción de anchura del DDL, las dos pruebas de que nombrar la
   columna en un `ChangeSet` levanta `AuditContractError` en `diff()` **y** en `redacted()`
   (R4.6), la de exclusión por ausencia y no por `REDACTED_FIELDS`, y el mapa `offenders` del
   censo de escritores, que ganará `materials` en los módulos donde ya aparecen las otras tres.
   El `assert len(AUDITABLE_FIELDS[...]) == 12` pasa a `13` (R5.1) — el propio comentario del
   test dice que la cifra está ahí para que el decimotercero sea un acto deliberado.
2. `backend/tests/test_rule11_ownership.py` — `SINK_TERMS` gana `"incidents.materials"`,
   cualificada con su tabla como `incidents.assignment_note`. No es opcional: el eje «sumidero»
   de ese guardián se alimenta de esa tupla, así que una columna que el censo gobierna y la
   tupla no es exactamente el punto ciego que su residual 3 describe.

Y la disciplina de R5.4, que no la vigila ningún test aquí —`sdd/changes/` está excluido del
guardián entero, por diseño—: este documento **no** dice quién escribe la columna. Lo dice la
tabla.

Rejected: declarar `materials` bajo la forma estructurada por defecto — sería falso; es texto
libre de 2000 caracteres que se guarda tal cual, y una fila del censo que miente es peor que
una columna sin censar (es la corrección que ya se llevó `owner_approvals.response_notes`).

### D11 — Nada de esto mueve la propiedad, y la ETA no genera evento de timeline

**Chosen:** ni `reject` ni la escritura de una ETA llaman a `_fire_trigger`. R7 de la spec de
`maintenance` ya dice que asignar, aceptar, empezar, esperar y reanudar no disparan nada, y
por la misma razón: la avería sigue ahí. `en_route` hereda literalmente lo que hacía `start`
(R2.6). La ETA tampoco escribe evento propio: PRD §10 no tiene miembro para «hora estimada» y
el hito ya lo cuenta el evento del paso que la trae —`TECHNICIAN_ACCEPTED` o
`TECHNICIAN_EN_ROUTE`—; es la misma decisión, escrita, que `wait_for_parts` tomó al no
escribir ninguno.

El único evento nuevo es `TECHNICIAN_REJECTED`, con título constante
(`"Technician rejected the incident"`) y `metadata` de sólo identificadores:
`{"incident_id": …, "technician_id": <el asignatario anterior>}`. La mezcla lo permite con un
gancho `_timeline_extra` que lee la foto previa de D5 — necesario porque para cuando se
escribe el evento la entidad ya tiene el campo a `NULL`.

**Corregido en `/sdd:run` (2026-08-22): por qué `_timeline_extra` devuelve `None` cuando no hay
asignatario.** La primera redacción de este gancho justificaba esa rama diciendo que «un
`PROPERTY_MANAGER` puede conducir el paso para desatascar» una incidencia sin asignar, y eso es
falso: `reject` sólo admite `ASSIGNED` y `ACCEPTED`, y a las dos se llega por `assign`, que
siempre escribe un asignatario. Los paneles de arquitectura **y** de QA levantaron la
contradicción por separado, y los dos concluyeron que la rama era inalcanzable y podía
retirarse. **También es falso.** `incidents.assigned_technician_id` lleva
`ondelete="SET NULL"`, así que borrar la cuenta del técnico deja la incidencia en `ASSIGNED`
con el asignatario a `NULL` — medido contra la base de datos, no razonado. La rama se queda,
con el motivo real escrito y con un test que lo ejerce; sin ella el evento escribiría
`"None"` en una tabla que nadie puede redactar después.

Rejected: un trigger `INCIDENT_REJECTED` en `PropertyStateMachine` — no existe fila de política
para él, y la propiedad no cambia porque cambie quién arregla la avería.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Dominio de mantenimiento | `backend/app/maintenance/domain/entities.py` | `Incident.eta_at`, `Incident.materials` y `MAX_MATERIALS`; `_TRANSITIONS` gana `reject` (`ASSIGNED`,`ACCEPTED` → `CLASSIFIED`) y renombra `start` → `en_route`; métodos `reject()`, `en_route()`, `_apply_eta()`; `accept(eta_at=…)`, `resolve(materials=…)`, `require_owner_approval(materials=…)`; `assign()` limpia `eta_at` |
| | `backend/app/maintenance/domain/notifications.py` | `NOTIFICATION_TYPE_INCIDENT_REJECTED` y el constructor `incident_rejection_notification(...)`, sin `sla_deadline_at`, `related_type=RELATED_TYPE_INCIDENT` apuntando a la incidencia |
| Aplicación | `backend/app/maintenance/application/use_cases.py` | `_TIMELINE_TITLES` gana `TECHNICIAN_EN_ROUTE` y `TECHNICIAN_REJECTED`; `_TechnicianStepUseCase` gana `_TAKES_ETA`, `_STEP_AUDITED_FIELDS`, el diff derivado (D5) y el gancho `_timeline_extra`; `StartIncidentUseCase` → `EnRouteIncidentUseCase`; nuevo `RejectIncidentUseCase`; `AcceptIncidentUseCase._TAKES_ETA = True`; `AssignIncidentUseCase` difunde `eta_at` cuando cambia; `ResolveIncidentUseCase` pasa `materials` por sus dos ramas |
| Infraestructura | `backend/app/maintenance/infrastructure/models.py` | `eta_at: TIMESTAMPTZ NULL`, `materials: String(2000) NULL` |
| | `backend/app/maintenance/infrastructure/repositories.py` | `_MUTABLE_INCIDENT_COLUMNS` += `eta_at`, `materials`; `_to_incident` los rehidrata |
| API | `backend/app/maintenance/api/schemas.py` | `IncidentEtaRequest` (nuevo, compartido por `accept` y `en-route`); `ResolveIncidentRequest` += `materials`; `IncidentResponse` += `eta_at`, `materials` (y su `from_domain`) |
| | `backend/app/maintenance/api/incidents_router.py` | `POST /{id}/reject` (`ExecuteDep`); `/{id}/start` → `/{id}/en-route`; cuerpo opcional en `accept` y `en-route` |
| | `backend/app/maintenance/api/dependencies.py` | `get_en_route_incident_use_case` (renombrado), `get_reject_incident_use_case` (nuevo, con `users` y `notifications`) |
| Auditoría | `backend/app/audit/domain/actions.py` | `INCIDENT_REJECTED` + su entrada en `ALL_ACTIONS` |
| | `backend/app/audit/domain/value_objects.py` | `AUDITABLE_FIELDS["INCIDENT"]` += `eta_at` → trece campos |
| Timeline | `backend/app/timeline/domain/enums.py` | `TECHNICIAN_REJECTED` |
| | `backend/app/timeline/domain/rendering.py` | Entrada ES/EN de `TECHNICIAN_REJECTED` (un test recorre el enum, así que su ausencia rompe la suite) |
| Migración | `backend/alembic/versions/<rev>_tech_cycle_completion.py` | Dos columnas + la etiqueta de enum (D9) |
| Contrato publicado | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | Regenerados en el mismo PR (R5.5) |
| Steering | `sdd/steering/security.md` | Fila de `incidents.materials` + los cuatro recuentos de cabecera (D10) |
| Tests | `backend/tests/maintenance/` | `test_entities.py`, `test_use_cases.py`, `test_api_incidents.py`, `test_api_authorization.py`, `test_repositories.py`, `test_models.py`, `test_notifications.py`, `test_free_text_sink_contract.py` |
| | `backend/tests/test_rule11_ownership.py`, `backend/tests/test_route_authorization.py`, `backend/tests/test_migrations.py`, `backend/tests/timeline/` | `SINK_TERMS`, el allowlist de rutas, la anchura real en el DDL + el ciclo down/up sobre filas existentes, y el catálogo ES/EN |

Al **archivar** (no en implementación): `sdd/specs/maintenance.md` (R1, R5, R6, R8, R9 y el
borrado de la viñeta de § Estado que dice que `TECHNICIAN_EN_ROUTE` no tiene escritor),
`sdd/specs/timeline-state-machine.md`, `sdd/specs/api-contract.md` (94 → 95 operaciones, 83 →
84 autenticadas, trece → **catorce** rutas de `maintenance`), `docs/maintenance.md` (su tabla
de rutas cita `/start` en la línea 42) y los dos diagramas de `docs/diagrams/` —ver Risks.

## Data & interfaces

**Esquema** — `incidents`, dos columnas aditivas, ambas `NULL` al nacer y sin backfill:

| Columna | Tipo | Nulable | Notas |
|---|---|---|---|
| `eta_at` | `TIMESTAMPTZ` | sí | Pertenece a la asignación vigente: `assign` y `reject` la ponen a `NULL` |
| `materials` | `VARCHAR(2000)` | sí | Cota en el DDL **y** en el esquema de petición; sumidero de la regla 11 |

**Enum de PostgreSQL** — `timeline_event_type` gana `TECHNICIAN_REJECTED`. Ninguna fila
existente cambia de valor (R5.6).

**API** — la tabla de transiciones queda así (las tres filas que cambian, en negrita):

| Operación | Orígenes | Destino |
|---|---|---|
| … | | |
| `accept` | `ASSIGNED` | `ACCEPTED` |
| **`reject`** | **`ASSIGNED`, `ACCEPTED`** | **`CLASSIFIED`** |
| **`en_route`** (era `start`) | `ACCEPTED` | `IN_PROGRESS` |
| `resume_work` | `WAITING_EXTERNAL_PARTS` | `IN_PROGRESS` |
| … | | |

Rutas: `POST /api/v1/incidents/{incident_id}/reject` (nueva, `EXECUTE_INCIDENTS`) y
`POST /api/v1/incidents/{incident_id}/en-route` (renombrada desde `/start`, mismo permiso).
El módulo pasa de trece a catorce rutas; el contrato entero, de 94 a 95 operaciones, ninguna
anónima —el allowlist de `tests/test_route_authorization.py` sigue con sus once entradas.

Cuerpos:

```
IncidentEtaRequest      { eta_at?: datetime }              # accept, en-route — cuerpo opcional
ResolveIncidentRequest  { final_cost: Decimal, materials?: str }
IncidentResponse        { …, eta_at: datetime | null, materials: str | null }
```

Los tres con `extra="forbid"`, que es lo que hace de R3.2 y R4.2 («en ninguna otra ruta») un
`422` y no una convención.

**Errores** — sin códigos nuevos: `reject` fuera de orden sale por el mapa que ya existe (`409`
para las tres excepciones de transición, `404` para fuera de alcance), y la ETA en el pasado o
sin zona horaria por `MaintenanceValidationError` → `422 VALIDATION_ERROR`.

**Config/entorno** — ninguna variable nueva.

## Risks & mitigations

- **La renombrada es una rotura del contrato publicado.** Mitigación: está medido que no hay
  consumidor —ni `frontend/`, ni CLI, ni scheduler; sólo el router, sus dependencias y la
  tabla de `docs/maintenance.md`—, y `tech-app`, que sería el primero, aún no existe y depende
  de este change. Se renombra ahora, que es el único momento barato.
- **Los dos diagramas de `docs/diagrams/` quedan obsoletos, y por criterios distintos.** El ER
  (`2026-08-22_autohost-er-entidades.png`) porque `incidents` gana dos columnas — sin clave
  ajena, así que sus 76 relaciones no se mueven y sí sus 416 columnas. Y el de secuencia
  (`2026-08-15_autohost-secuencia-mantenimiento.png`) porque **sí** cambia un paso del ciclo
  que dibuja: `steering/architecture.md` declara que ese PNG no se regeneró en
  `cleaner-incident-report` precisamente porque aquél «añade una puerta de entrada nueva, no un
  paso nuevo del ciclo» — éste renombra un paso y añade otro, que es el caso contrario.
  Mitigación: tarea de archivado explícita, y regenerarlos **sin abrir los PNG** (~140k de
  contexto cada uno).
- **El diff auditado derivado (D5) podría cambiar en silencio lo que se audita hoy.**
  Mitigación: `status` cambia en toda transición y los otros dos sólo se mueven en operaciones
  nuevas, así que los cuatro pasos actuales producen el mismo `ChangeSet`; los tests de
  auditoría existentes de `test_use_cases.py` son la red y no se relajan.
- **La comparación de la ETA con `now` puede reventar por naïve/aware.** Mitigación: la
  comprobación explícita de `tzinfo`/`utcoffset` en `_apply_eta`, con test directo sobre la
  entidad, siguiendo el patrón de `properties/domain/state_resolution.py`.
- **El censo de la regla 11 puede quedarse corto sin ponerse rojo.** Mitigación: los dos
  guardianes de D10 se mueven en la **misma** tarea que la fila del censo, no después.
- **Observación fuera de alcance, para que conste y no se lea como cobertura**:
  `incidents.assignment_note` —sumidero vivo desde `tech-incident-context`— **no** pasa por
  `storable_text`, así que un `U+0000` en esa nota sale hoy como `500` sin declarar.
  `materials` sí lo lleva desde el primer día. Retrofitear `assignment_note` es un cambio de
  contrato de una ruta que este change no toca; queda como candidato de roadmap
  (`assignment-note-storable-text`).

## Open questions

Ninguna abierta. Las dos que este diseño levantó se resolvieron en el gate del 2026-08-22, las
dos por la opción recomendada:

1. **Qué limpia el rechazo** → los **tres** campos de la asignación vigente
   (`assigned_technician_id`, `eta_at`, `assignment_note`), por encima de la letra estricta de
   R1.2, que sólo nombra el primero. Es **D2**, y la razón es la del propio `ASSUMPTION` de R1:
   una incidencia `CLASSIFIED` sin dueño que conserve la nota escrita para quien dijo que no —o
   la hora que ese técnico prometió— es una fila que miente. Quién rechazó no se pierde: va en
   el `AuditLog`, que audita `assigned_technician_id` con su valor anterior, y en el `metadata`
   del `TimelineEvent`.
2. **Tope superior de la ETA** → **no lo hay**. R3.4 sólo prohíbe el pasado; `TIMESTAMPTZ` no
   desborda, así que una fecha absurda es un dato feo y no un fallo, y un horizonte sería
   política de producto que el PRD no declara. Recogido en **D6**.

Las tres preguntas abiertas del `proposal.md` quedan resueltas en el propio diseño: la 1 en
**D4** (`resume_work` conserva `TECHNICIAN_STARTED`), la 2 en **D8** (`materials` sigue en el
listado) y la 3 en **D3** (sin miembro nuevo de `NotificationType`).
