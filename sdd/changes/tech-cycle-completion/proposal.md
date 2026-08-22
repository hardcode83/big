# Proposal: tech-cycle-completion

## Why

PRD §6 concede al rol `TECHNICIAN` seis capacidades y PRD §12 enumera once cosas que su UI
enseña. El módulo `maintenance` entregó el ciclo hasta `RESOLVED`, pero dejó cuatro huecos que
no son de frontend y que `tech-app` no puede tapar desde el navegador:

1. **No existe `reject`.** PRD §6 dice «aceptar/rechazar tickets» y sólo hay `accept`. `cancel`
   no sirve de sustituto: es del `PROPERTY_MANAGER` (`_INCIDENT_MANAGE`) y lleva la incidencia a
   un terminal, mientras que rechazar la devuelve al manager para que la reasigne.
2. **No hay campo ETA**, que PRD §12 pide explícitamente en la UI del técnico. No hay columna en
   `Incident` (PRD §7.13).
3. **No hay materiales.** PRD §6 y §12 piden «añadir coste y materiales» y sólo existe
   `final_cost`.
4. **«En ruta» está a medio declarar.** `TimelineEventType.TECHNICIAN_EN_ROUTE` existe en el
   vocabulario y `sdd/specs/maintenance.md` § Estado dice literalmente que nadie lo escribe («no
   hay transición "en ruta" en el ciclo entregado»), mientras `start` (`ACCEPTED → IN_PROGRESS`)
   escribe `TECHNICIAN_STARTED`.

Origen: entrada de roadmap `tech-cycle-completion`, separada de `tech-app` el 2026-08-19 con el
censo completo en [`sdd/roadmap/tech-app.md`](../../roadmap/tech-app.md). Referencias del PRD:
§6 (rol `TECHNICIAN`), §7.13 (`Incident`), §12 (flujo y UI del técnico).

**Corrección de la premisa de la entrada de roadmap, verificada en el código.** La entrada dice
que si `start` pasa a significar «en ruta», «el evento huérfano se retira — no se deja». Medido:
`TECHNICIAN_STARTED` tiene **dos** escritores, no uno —
`StartIncidentUseCase` y `ResumeWorkUseCase`, ambos en
`backend/app/maintenance/application/use_cases.py` (`_STEP` de cada uno) —, así que reasignar el
significado de `start` **no deja ningún miembro huérfano** y no hace falta retirar nada del enum
ni migrar el tipo `timeline_event_type` de PostgreSQL. El hueco que hay que cerrar es el
contrario y sigue en pie: `TECHNICIAN_EN_ROUTE` es el que no tiene escritor.

## What changes

El técnico gana la operación que le falta y los dos campos que le faltan, y el ciclo deja de
tener un miembro de vocabulario sin escritor. Después de este change: `POST
/api/v1/incidents/{id}/reject` devuelve al manager una incidencia `ASSIGNED` o `ACCEPTED`
liberando el asignatario y cancelando su plazo de SLA; la operación que hoy se llama `start`
pasa a ser `en-route` y escribe `TECHNICIAN_EN_ROUTE`, con `resume_work` conservando
`TECHNICIAN_STARTED`; `incidents` gana dos columnas nuevas — `eta_at` (marca de tiempo, que el
técnico fija al aceptar o al ponerse en ruta y que pertenece a la asignación vigente) y
`materials` (texto acotado que el técnico teclea al cerrar, junto a `final_cost`) —, ambas
visibles en `IncidentResponse`. `AUDITABLE_FIELDS["INCIDENT"]` pasa de doce a trece campos con
`eta_at`; `materials` queda **fuera** por construcción, y entra en el censo de sumideros de la
regla 11 de `steering/security.md` bajo la excepción 3. El contrato publicado
(`backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts`) se regenera en el mismo PR.

## Requirements

### R1 — El técnico rechaza el ticket

**As a** técnico asignado, **I want** rechazar una incidencia que no puedo atender, **so that**
vuelva al manager para reasignación en lugar de quedarse parada a mi nombre o cerrarse en falso.

Acceptance criteria:

1. THE SYSTEM SHALL añadir a la tabla de transiciones de `Incident` la operación `reject`, con
   orígenes admitidos `ASSIGNED` y `ACCEPTED` y destino `CLASSIFIED`, declarada por **nombre de
   operación** como el resto de la tabla.
2. WHEN el técnico asignado rechaza la incidencia, THE SYSTEM SHALL poner
   `assigned_technician_id` a `NULL`, pasar la incidencia a `CLASSIFIED` y actualizar
   `updated_at`, dejándola así en el conjunto de orígenes que `assign` ya admite.
3. WHEN se rechaza la incidencia, THE SYSTEM SHALL cancelar el plazo de SLA pendiente de la
   notificación `TECHNICIAN_ASSIGNED` sobre esa incidencia: un rechazo es una respuesta, así que
   nadie llega tarde (mismo criterio que `cleaning` R5.1).
4. WHEN se rechaza la incidencia, THE SYSTEM SHALL notificar al `PROPERTY_MANAGER` del tenant
   dejando su `NotificationLog`, y esa notificación NEVER SHALL llevar plazo de SLA.
5. IF el tenant no tiene ningún `PROPERTY_MANAGER` activo, THEN THE SYSTEM SHALL registrar el
   hecho y continuar sin fallar, dejando el rechazo aplicado — el mismo criterio que R4 de
   `maintenance` aplica a la aprobación sin destinatario.
6. THE SYSTEM SHALL exponer la operación en `POST /api/v1/incidents/{incident_id}/reject`, bajo
   `EXECUTE_INCIDENTS`, y SHALL permitirla al técnico asignado y al `PROPERTY_MANAGER`, igual que
   el resto del ciclo (spec `maintenance` R6).
7. THE SYSTEM NEVER SHALL permitir rechazar a un técnico que no sea el asignado, y esa negativa
   SHALL ser indistinguible de «no existe»: el **mismo `404` con el mismo cuerpo** que para una
   incidencia inexistente o de otro tenant (spec `maintenance` R8).
8. IF la incidencia está en cualquier otro estado, THEN THE SYSTEM SHALL rechazar la operación
   con el error que ya distingue R1 de `maintenance` — `IncidentAlreadyClosedError` en terminal,
   `IncidentBlockedByPendingApprovalError` en `AWAITING_OWNER_APPROVAL`,
   `InvalidIncidentTransitionError` en el resto — y NEVER SHALL escribir ningún campo.
9. THE SYSTEM SHALL escribir un `TimelineEvent` del rechazo con título constante y `metadata`
   sólo con identificadores. `TimelineEventType` no tiene hoy un miembro para ello, así que este
   change lo añade, con el precedente de `GUEST_CHECKIN_COMPLETED`, que `guest-portal-api` ya
   añadió fuera de la lista de PRD §7.8.

> `ASSUMPTION`: el destino `CLASSIFIED` no lo dice el PRD. Se elige porque es el origen desde el
> que `assign` reparte y porque no es terminal. Y `assigned_technician_id` se **limpia** en vez
> de conservarse — al revés que `cleaning`, donde la tarea rechazada es terminal y la columna es
> el registro de quién dijo que no: aquí la incidencia sigue viva y una incidencia `CLASSIFIED`
> con asignatario sería una fila que miente. Quién rechazó queda en el `AuditLog`, que ya audita
> `assigned_technician_id`, y en el evento de timeline.

### R2 — «En ruta» tiene escritor, y ningún miembro del vocabulario se queda sin él

**As a** técnico, **I want** avisar de que voy de camino, **so that** el manager y la propietaria
sepan que la incidencia está en marcha, que es lo que PRD §12 pone como botón propio.

Acceptance criteria:

1. THE SYSTEM SHALL renombrar la operación `start` a `en_route`, conservando exactamente sus
   orígenes (`ACCEPTED`) y su destino (`IN_PROGRESS`), que es lo que el diagrama de flujo de
   PRD §12 declara literalmente: «Técnico en ruta → status IN_PROGRESS».
2. WHEN el técnico se pone en ruta, THE SYSTEM SHALL escribir el `TimelineEvent`
   `TECHNICIAN_EN_ROUTE`, con título constante y `metadata` sólo con identificadores.
3. THE SYSTEM SHALL exponer la operación en `POST /api/v1/incidents/{incident_id}/en-route`, y
   `POST /api/v1/incidents/{incident_id}/start` NEVER SHALL seguir existiendo en el contrato
   publicado: la operación se renombra, no se duplica.
4. THE SYSTEM SHALL conservar `resume_work` (`WAITING_EXTERNAL_PARTS → IN_PROGRESS`) escribiendo
   `TECHNICIAN_STARTED`, de modo que ese miembro del vocabulario **sigue teniendo escritor** y no
   hay nada que retirar del enum ni del tipo `timeline_event_type` de PostgreSQL.
5. THE SYSTEM SHALL dejar en `sdd/specs/maintenance.md` § Estado **ninguna** afirmación de que
   `TECHNICIAN_EN_ROUTE` no tiene escritor: la viñeta que hoy lo dice se borra al archivar.
6. THE SYSTEM NEVER SHALL disparar transición de estado de la propiedad por ponerse en ruta,
   igual que hoy no la dispara `start` (spec `maintenance` R7).

### R3 — El campo ETA

**As a** manager o propietaria, **I want** ver cuándo dice el técnico que llega, **so that** pueda
avisar al huésped sin llamar a nadie.

Acceptance criteria:

1. THE SYSTEM SHALL añadir a `incidents` una columna `eta_at` `TIMESTAMPTZ` **nullable**, y SHALL
   exponerla en `IncidentResponse`.
2. THE SYSTEM SHALL aceptar `eta_at` como campo **opcional** en el cuerpo de `accept` y en el de
   `en-route`, y NEVER SHALL aceptarlo en ninguna otra ruta del módulo.
3. WHEN el cuerpo trae un `eta_at`, THE SYSTEM SHALL escribirlo sustituyendo al anterior; IF el
   cuerpo no lo trae, THEN THE SYSTEM SHALL dejar el valor anterior intacto.
4. IF el `eta_at` recibido es **estrictamente anterior** al instante de la petición, THEN THE
   SYSTEM SHALL rechazarlo con `MaintenanceValidationError` y NEVER SHALL escribir nada.
5. WHEN un manager (re)asigna la incidencia, THE SYSTEM SHALL poner `eta_at` a `NULL`: la ETA
   pertenece a la **asignación vigente** y no a la incidencia, exactamente como `assignment_note`
   (spec `maintenance` R5).
6. THE SYSTEM SHALL rechazar campos desconocidos en los dos cuerpos, manteniendo el
   `extra="forbid"` que el módulo ya aplica.

### R4 — Los materiales

**As a** técnico, **I want** declarar qué materiales he puesto al cerrar, **so that** el coste
final tenga una explicación y no sea un número suelto.

Acceptance criteria:

1. THE SYSTEM SHALL añadir a `incidents` una columna `materials` de texto **nullable**, acotada a
   **2000 caracteres en el DDL y en el esquema de petición**, con recorte de espacios, y SHALL
   exponerla en `IncidentResponse`.
2. THE SYSTEM SHALL aceptar `materials` como campo **opcional** en el cuerpo de `resolve`, junto
   al `final_cost` que ese cuerpo ya exige, y NEVER SHALL aceptarlo en ninguna otra ruta.
3. THE SYSTEM SHALL escribir `materials` **también** cuando el cierre abra la segunda puerta de
   aprobación de R4 de `maintenance`: el técnico declaró el gasto, y perder su descripción porque
   el importe supere el umbral obligaría a teclearlo dos veces.
4. THE SYSTEM NEVER SHALL derivar `final_cost` de `materials` ni validar el uno contra el otro:
   `final_cost` sigue siendo el único número, y las dos puertas de aprobación no cambian.
5. THE SYSTEM SHALL declarar `materials` en la tabla de sumideros de texto en claro de
   `sdd/steering/security.md` (regla 11), con su propia fila, bajo la **excepción 3** (lo teclea
   una persona autenticada con `EXECUTE_INCIDENTS` sobre una incidencia que ya es suya), y SHALL
   recalcular contra la tabla los cuatro recuentos de su cabecera (columnas, filas, excepciones y
   vivas) en lugar de incrementarlos de memoria.
6. THE SYSTEM SHALL hacer que ese contrato sea **estructural y no prosa**: `materials` queda fuera
   de `AUDITABLE_FIELDS["INCIDENT"]`, de modo que nombrarla en un `ChangeSet` levante
   `AuditContractError` en las dos formas (`diff()` y `redacted()`), y su texto NEVER SHALL viajar
   al `metadata` del `TimelineEvent` de la resolución. Es el contrato de `incidents.assignment_note`,
   calcado.

### R5 — Auditoría, contrato publicado y guardián del censo

**As a** quien mantenga el módulo, **I want** que los campos nuevos entren en las mismas defensas
que los existentes, **so that** no se abra un hueco que sólo se descubra tres changes después.

Acceptance criteria:

1. THE SYSTEM SHALL añadir `eta_at` a `AUDITABLE_FIELDS["INCIDENT"]`, que pasa de doce a **trece**
   campos: es una marca de tiempo, no texto libre, así que entra por el mismo criterio que
   `resolved_at`.
2. WHEN se rechaza una incidencia o se escribe un `eta_at`, THE SYSTEM SHALL escribir su
   `AuditLog` y su `TimelineEvent` **en la misma transacción** que el cambio, nombrando como actor
   al usuario que ejecuta la operación (spec `maintenance` R9).
3. THE SYSTEM SHALL mantener verde el guardián automático del censo,
   `backend/tests/maintenance/test_free_text_sink_contract.py`, y SHALL extenderlo para que cubra
   `incidents.materials` con el mismo criterio con el que hoy cubre `title`/`description`.
4. THE SYSTEM SHALL mantener verde `backend/tests/test_rule11_ownership.py`: la propiedad del
   sumidero nuevo se declara **sólo** en la tabla de `steering/security.md`, y ningún documento de
   este change afirma quién escribe la columna.
5. THE SYSTEM SHALL regenerar y commitear `backend/openapi.json` (con `make openapi`) y
   `frontend/lib/api/generated/openapi.d.ts` en el mismo PR
   (`steering/documentation.md`, spec `api-contract`).
6. THE SYSTEM SHALL entregar la migración de Alembic de las dos columnas nuevas y del miembro
   nuevo de `timeline_event_type`, y NEVER SHALL requerir migrar dato existente: las dos columnas
   nacen `NULL` y ninguna fila de timeline cambia de tipo.

## Out of scope

- **La UI del técnico.** Las once cosas de PRD §12 se pintan en `tech-app`, que es la entrada
  `[FE]` que depende de ésta. Aquí no se toca `frontend/app/(field)/tech/`.
- **Las fotos del incidente** (antes/después): son de `incident-photos`, la otra entrada `[BE]`
  que salió del mismo reparto.
- **La dirección, las instrucciones de acceso y las notas del manager**: las entregó
  `tech-incident-context` en `GET /api/v1/incidents/{id}/context`, ya archivado.
- **`Expense` y las liquidaciones** (PRD §7.23, §12 «TimelineEvent + Expense creado»): son de
  `revenue-statements`. `materials` es texto del técnico, no una partida contable, y R4.4 lo deja
  explícito.
- **Reasignación automática tras un rechazo.** El rechazo devuelve la incidencia a `CLASSIFIED` y
  ahí la coge un manager. `cleaning` tomó la misma decisión para su propio rechazo.
- **Expiración de la ETA y escalado por ETA incumplida.** `eta_at` se guarda y se muestra; no
  entra en la maquinaria de SLA, que sigue derivando su plazo de la severidad (spec `maintenance`
  R5).
- **`AuditLog` de la transición de estado de la propiedad** y **`tenant-scoping-enumeration-guard`**:
  los dos huecos que `sdd/specs/maintenance.md` § Estado ya declara como candidatos con nombre
  propio, y que este change no ensancha ni cierra.
- **`audit_changes_repository_guard`**: la revalidación de `audit_logs.changes` en el repositorio
  es su propia entrada de roadmap.

## Affected specs

- `sdd/specs/maintenance.md` — R1 (tabla de transiciones: `reject` nuevo, `start` → `en_route`),
  R5 (la ETA se limpia al asignar), R6 (el ciclo del técnico gana `reject`), R8 (rutas: catorce en
  total, y `IncidentResponse` gana dos campos), R9 (`AUDITABLE_FIELDS` a trece campos, el evento
  de timeline nuevo) y § Estado (se borra la viñeta de `TECHNICIAN_EN_ROUTE` sin escritor).
- `sdd/specs/timeline-state-machine.md` — el miembro nuevo de `TimelineEventType` y su renderizado
  ES/EN.
- `sdd/specs/api-contract.md` — las rutas nuevas y la renombrada en el contrato publicado.
- `sdd/steering/security.md` — fila nueva en el censo de sumideros de la regla 11
  (`incidents.materials`) y los cuatro recuentos de su cabecera, recalculados contra la tabla.

## Preguntas abiertas para `/sdd:design`

1. **Si `resume_work` debe seguir escribiendo `TECHNICIAN_STARTED`.** Es lo que hace que nada
   quede huérfano (R2.4), pero deja un timeline donde «el técnico ha empezado» sólo aparece
   *después* de una espera de piezas. La alternativa es que `resume_work` no escriba evento, como
   `wait_for_parts` — y entonces sí habría que retirar el miembro.
2. **Si `materials` debe salir del listado paginado.** `properties.access_notes` pagó ese precio
   por su excepción 6; `IncidentResponse` sirve hoy listado y detalle con el mismo esquema, así
   que exponerla la pone también en el listado. R4.1 lo asume; el design debe confirmarlo o
   partir el esquema.
3. **Si el rechazo necesita miembro propio de `NotificationType`.** Hoy no hay ninguno que sirva
   (`TECHNICIAN_NO_RESPONSE` es del escalado de SLA, no de un rechazo explícito).
