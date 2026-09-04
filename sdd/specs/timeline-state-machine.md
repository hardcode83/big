# Timeline state machine

## Purpose

Esta capacidad aplica de forma determinista la política de estado operacional de
una propiedad y construye las evidencias correlacionadas para su timeline. Recibe
todo el contexto como datos explícitos y permanece en el dominio: no lee reloj,
base de datos, red ni servicios externos, ni persiste o muta la propiedad.

**Dónde se persisten sus eventos**: el puerto `TimelineEventRepository`
(`app/timeline/domain/repositories.py`) y su adaptador SQLAlchemy los añaden a
`timeline_events`, y los escribe cada capacidad que muta algo — la primera fue
`reservations` (ver `specs/reservations.md`). El puerto expone únicamente `add`, que es la
regla "nunca se editan eventos pasados" expresada en una firma, y rechaza un `metadata` que
la columna `JSONB` no pueda almacenar. Construir el evento sigue siendo exclusivamente
competencia de la fábrica que esta capacidad define.

**Dónde se leen**: desde `dashboard-api` (2026-08-09) el timeline dejó de ser sólo escritura y
tiene superficie de lectura — el endpoint `GET /api/v1/timeline/{property_id}` y el último
evento por propiedad que alimenta las cards. `dashboard-activity-feed` (2026-09-04) añadió un
tercer método, `list_for_tenant`: una página de eventos de **todas** las propiedades del
tenant, mismo orden (`created_at DESC`, `id DESC` como desempate) y mismos filtros que
`list_for_property`, sin `property_id`. **Ninguna de estas lecturas se añadió a
`TimelineEventRepository`**: viven en un `Protocol` aparte, `TimelineEventReader`, en el mismo
fichero. Es Interface Segregation, pero sobre todo es lo que conserva la propiedad que el
párrafo anterior describe: que `add` sea el único método del escritor es lo que hace visible
la inmutabilidad en una firma, y colgarle lectores la habría cambiado por un fichero más
corto. Un test lo fija: los métodos del escritor son exactamente `{add}` y son disjuntos de
los del lector. El *qué devuelve* cada lectura, con sus filtros, su orden y su localización,
está en [`dashboard-api.md`](dashboard-api.md).

**Quién la conduce**: desde `celery-jobs` esta política tiene ejecutor. Su
`AdvancePropertyStatesUseCase` (`app/properties/application/use_cases.py`) es el primer y
único escritor de `current_operational_state` y de `property_state_transitions`: pregunta a
`PropertyStateMachine` por cada reserva candidata, y cuando acepta persiste el estado, la
transición y el `TimelineEvent` en una sola transacción con el `correlation_id` que esta
capacidad produce. La política sigue sin tocar reloj, base de datos ni red — lo que cambió es
que ya no evalúa en el vacío (ver `specs/celery-jobs.md`).

**Qué no es una transición de estado de propiedad**: `access-notifications` trajo la máquina de
estados del `AccessRecord` y la del registro legal de la reserva, y ninguna de las dos pasa por
aquí. La regla «un único lugar donde ocurren las transiciones» habla del estado operacional de la
*propiedad*; el ciclo de vida de un acceso o de una presentación ante SES.Hospedajes es de su
entidad, vive en ella y no toca `current_operational_state`. Lo que sí comparten es la fábrica:
sus eventos (`ACCESS_CODE_PENDING`, `ACCESS_CODE_MANUAL_ADDED`, `ACCESS_CODE_CREATED_EXTERNAL`,
`ACCESS_CODE_DELIVERED`, `LEGAL_REGISTRATION_SUBMITTED`) se construyen por ella como cualquier
otro. Revocar y expirar un acceso **no** escriben evento: PRD §15 no declara ninguno y la fila de
`AuditLog` es la que lo registra.

## Requirements

### Estados canónicos y autoridad única

- WHEN se evalúa una solicitud, THE SYSTEM SHALL aceptar y producir únicamente
  los estados de `PropertyOperationalState`.
- WHEN el origen, trigger, destino solicitado o precondición no coincide con la
  matriz de transición aprobada, THE SYSTEM SHALL rechazar la solicitud sin
  modificar entradas ni producir evidencias de éxito.
- WHEN el destino coincide con el estado actual, THE SYSTEM SHALL rechazarlo como
  ausencia de cambio operacional.
- WHEN la solicitud depende del tiempo, THE SYSTEM SHALL recibir un instante de
  referencia explícito.

### Triggers operacionales

- WHEN se soliciten cambios de reservas, limpieza, incidencias, bloqueo,
  fuera-de-servicio, reactivación o desbloqueo, THE SYSTEM SHALL validar el
  trigger semántico, su entidad fuente y sus precondiciones antes de evaluar la
  transición.
- WHEN una operación manual requiera actor, THE SYSTEM SHALL exigir un actor
  `USER` con `user_id` y un motivo no vacío; la autorización RBAC SHALL permanecer
  fuera del dominio.
- WHEN se desbloquee `BLOCKED_BY_OWNER`, THE SYSTEM SHALL exigir destino explícito
  y validar ese destino contra el contexto actual; no SHALL restaurar un estado
  histórico automáticamente.
- **Los tres triggers de incidencia dejaron de ser código inalcanzable el 2026-08-15**: hasta
  `maintenance` nadie los disparaba, y por eso `MAINTENANCE_REQUIRED` y `CRITICAL_INCIDENT` eran
  estados inalcanzables en producción. Quien los dispara ahora es el flujo de incidencias
  ([`maintenance.md`](maintenance.md)), y ejercitarlos con datos reales destapó **dos omisiones
  de la matriz**, corregidas en el mismo change:
  - `VACANT_READY` admitía `INCIDENT_HIGH` pero no `INCIDENT_CRITICAL`, así que una avería
    crítica en un piso vacío y listo lo dejaba **reservable**. THE SYSTEM SHALL producir
    `CRITICAL_INCIDENT` desde `VACANT_READY` ante `INCIDENT_CRITICAL`.
  - `CLEANING_SCHEDULED` admitía `INCIDENT_CRITICAL` pero no `INCIDENT_HIGH`, mientras
    `AWAITING_CLEANING` y `CLEANING_IN_PROGRESS` admitían los dos. THE SYSTEM SHALL producir
    `MAINTENANCE_REQUIRED` desde `CLEANING_SCHEDULED` ante `INCIDENT_HIGH`.
- IF el trigger es `INCIDENT_RESOLVED`, THEN THE SYSTEM SHALL exigir que la incidencia fuente esté
  `RESOLVED` **o `CANCELLED`**, y NEVER SHALL tratar la cancelación como un contexto incompatible.
  `ContextualStateResolver.after_incident_resolution` ya filtraba las activas por
  `status not in (RESOLVED, CANCELLED)`, así que sólo esta guarda distinguía las dos; sin la
  corrección, una propietaria que rechaza el presupuesto cancela la incidencia y **deja la
  propiedad varada** en `CRITICAL_INCIDENT`, porque no queda nada que la saque.
- WHERE la propiedad está en `BLOCKED_BY_OWNER` o `OUT_OF_SERVICE`, THE SYSTEM SHALL rechazar
  todo trigger de incidencia: no existe fila de política desde esos dos estados, y esa negativa
  es deliberada — un piso retirado no cambia de estado porque alguien reporte una avería.

- WHEN una limpieza viva se cancela, THE SYSTEM SHALL admitir `CLEANING_CANCELLED` desde
  `AWAITING_CLEANING`, `CLEANING_SCHEDULED` y `CLEANING_IN_PROGRESS`, exigir que la tarea fuente
  quede en `CANCELLED`, y resolver el destino **por contexto**, no por una fila fija. Es el trigger
  que le faltaba a `CLEANING_IN_PROGRESS`, cuyas tres únicas salidas eran cerrar la limpieza o
  declarar una incidencia `HIGH`/`CRITICAL` —es decir, un dato falso como mecanismo de desbloqueo—.
- **`CLEANING_ASSIGNMENT_EXPIRED` se retiró el 2026-08-23**, y esto queda escrito para que el
  siguiente lector no lo reintroduzca como si fuera un olvido. Estaba en el enum, tenía su fila
  (`CLEANING_SCHEDULED → AWAITING_CLEANING`) y su guarda de estados esperados, y **nadie lo
  emitía**: ni `CADENCES`, ni `DAILY_JOBS`, ni ningún caso de uso. Las cuatro razones de retirarlo
  en vez de escribirle un emisor:
  1. **La necesidad operativa ya está cubierta**: una asignación sin respuesta escala al manager
     por el SLA de `check_sla_breaches` con `TenantConfig.sla_medium_minutes`. El trigger no
     añadía un aviso, añadía una **desasignación automática**.
  2. **Esa desasignación es política de producto nueva**, que `cleaning` dejó fuera de alcance a
     propósito: quitarle la tarea a una limpiadora que aún podría aceptar no es la reparación de
     un trigger huérfano.
  3. **Su guarda ya contradecía su nombre**: aceptaba `{ASSIGNED, ACCEPTED}`, y una tarea
     `ACCEPTED` es exactamente una asignación **respondida**.
  4. **Existe una salida humana y auditada** que hace ese trabajo: la cancelación de
     `MANAGE_CLEANING_TASKS`, con motivo, `AuditLog` y `TimelineEvent`
     ([`cleaning.md`](cleaning.md)).
  Retirarlo no costó migración —`PropertyStateTrigger` no es columna de ninguna tabla, viaja como
  **texto** dentro del JSON de `metadata`— y THE SYSTEM SHALL NOT reconstruir un trigger desde
  datos almacenados por ningún camino de lectura, afirmado por un test que recorre `app/` entero
  buscando las cuatro formas de rehacer el enum. WHERE alguna vez gane su política, SHALL entrar
  **con su emisor en el mismo commit**.
- THE SYSTEM SHALL mantener el catálogo de triggers **cerrado y afirmado por un test**: es lo que
  convierte retirar un miembro en un cambio que falla en vez de en una divergencia silenciosa.
- THE SYSTEM SHALL derivar de `_POLICY` tanto los estados origen de un trigger
  (`source_states_for`) como sus destinos (`destination_states_for`), sin una segunda copia de la
  matriz en ninguna parte.
- THE SYSTEM SHALL contestar «¿vence este trigger?» por separado de «¿es legal esta transición?»:
  `is_due` valida la petición y sus precondiciones temporales **sin consultar `_POLICY`**, y
  devuelve falso —no error— cuando la hora no ha llegado. Un fallo del llamante (petición
  inválida, contexto de otro tenant) SHALL seguir escapando como error: `is_due` no es un
  tragadero de excepciones. Existe porque preguntar «el calendario exigía esto y el estado no lo
  admite» es imposible con `evaluate`, que responde a las dos cosas a la vez; su consumidor es la
  detección de desajustes de [`celery-jobs.md`](celery-jobs.md).

**La matriz es sensible al orden, y quien reproduce hechos tiene que fijarlo.** Se revisó al
archivar `seed-data-demo-extension` (2026-08-17) y **no hizo falta cambiar `_POLICY`**; lo que sí
quedó demostrado es una propiedad suya que conviene tener escrita. Aplicar los mismos disparadores
en distinto orden no da el mismo recorrido: sembrar una incidencia `HIGH` antes que las estancias
deja la vivienda en `MAINTENANCE_REQUIRED`, y el par `(MAINTENANCE_REQUIRED,
CHECKIN_WINDOW_OPENED)` **no existe en la matriz**, así que las transiciones de estancia siguientes
se rechazan una a una. El estado final coincide, cinco transiciones se pierden y el timeline queda
vacío — el fallo silencioso perfecto, porque quien traga el rechazo lo registra como aviso y sigue.
Se deduce de ahí un requisito para cualquier llamante que reproduzca hechos pasados en lote:

- WHERE un llamante aplique varios triggers sobre la misma propiedad en una sola ejecución, THE
  SYSTEM SHALL exigir que los aplique en el **orden cronológico de los hechos** que representan, y
  ese orden SHALL ser parte del contrato del llamante y no una consecuencia accidental de su código.
  La máquina no puede defenderse sola: cada transición es válida o inválida por sí misma y ninguna
  sabe cuál venía antes.

### Resolución contextual y precedencia

- WHEN se resuelva una incidencia, THE SYSTEM SHALL aplicar exactamente esta
  precedencia: incidencia activa `CRITICAL`, incidencia activa `HIGH`, limpieza
  `IN_PROGRESS`, limpieza `CREATED`/`ASSIGNED`/`ACCEPTED`, reserva activa,
  próxima reserva hoy, próxima reserva futura y, finalmente, `VACANT_READY`.
  **Los dos escalones de limpieza se ejercitan con datos reales desde `cleaning`**
  (2026-08-07): hasta entonces nadie escribía en `cleaning_tasks`, así que la
  precedencia veía siempre «sin limpieza pendiente» y esas dos ramas —y con ellas
  las cinco transiciones de limpieza de la política— nunca se recorrían fuera de
  los tests. El conjunto de estados que cuentan como limpieza viva vive ahora en
  un solo sitio (`LIVE_STATUSES`), y el índice parcial que lo usa se compara con
  él en un test para que no puedan divergir.
- WHEN no exista incidencia `CRITICAL`, THE SYSTEM SHALL producir
  `MAINTENANCE_REQUIRED` si existe una incidencia `HIGH` activa.
- WHEN se valide un destino contextual explícito, THE SYSTEM SHALL rechazarlo si
  no es el estado derivado por la precedencia del contexto entregado.
- WHEN el contexto sea de otro tenant o propiedad, sea incompleto, ambiguo o
  contenga reservas activas incompatibles, THE SYSTEM SHALL producir un error de
  dominio explícito.
- WHEN una limpieza se complete, THE SYSTEM SHALL producir únicamente
  `READY_FOR_NEXT_GUEST`, `AWAITING_CHECKIN` o `VACANT_READY`; una reserva activa
  en ese punto SHALL ser contexto incompatible y no SHALL producir
  `OCCUPIED_ESTIMATED`.
- WHEN una limpieza se **cancele**, THE SYSTEM SHALL resolver el destino por la misma precedencia
  contextual pero **sin** los dos escalones de incidencia, y una estancia activa SHALL producir
  `OCCUPIED_ESTIMATED` en vez de ser contexto incompatible. **La asimetría con la cláusula anterior
  es deliberada y es la razón de ser del trigger**: cerrar una limpieza con el huésped dentro
  afirmaría que el piso quedó listo y es correcto negarse, mientras cancelarla sólo afirma que ese
  trabajo no se hará, y negarse ahí es lo que dejaba la vivienda congelada hasta que el calendario
  la liberase. Los estados de incidencia se excluyen porque una avería no la resuelve —ni la
  inventa— cancelar una limpieza; para eso está `INCIDENT_RESOLVED`.
- WHEN un desbloqueo solicite `CLEANING_SCHEDULED`, THE SYSTEM SHALL exigir que la
  precedencia no requiera un estado de incidencia y que exista exactamente una
  tarea `ASSIGNED` o `ACCEPTED`.

### Tiempo local y DST

- WHEN se materialice una hora local con la zona de la propiedad, THE SYSTEM SHALL
  rechazar una hora inexistente durante el salto de primavera.
- WHEN una hora local sea repetida durante el salto de otoño, THE SYSTEM SHALL
  exigir una zona consciente y `fold=0` o `fold=1` para seleccionar explícitamente
  la ocurrencia; no SHALL normalizar silenciosamente.
- WHEN una hora no sea ambigua, THE SYSTEM SHALL evaluarla de forma determinista
  y comparar instantes efectivos en UTC.

### Resultado de transición y timeline

- WHEN una transición sea aceptada, THE SYSTEM SHALL devolver conjuntamente un
  `PropertyStateTransition` y un `TimelineEvent` de tipo
  `PROPERTY_STATE_CHANGED`.
- WHEN se construyan ambas evidencias, THE SYSTEM SHALL conservar tenant,
  propiedad, estados, actor, motivo, instante y `correlation_id` compartidos, y
  SHALL construir metadata independiente sin referencias mutables compartidas.
- IF cualquiera de las dos evidencias no puede construirse, THEN THE SYSTEM SHALL
  fallar de forma all-or-nothing y no SHALL devolver evidencia parcial.
- WHEN se repita una evaluación con entradas idénticas, THE SYSTEM SHALL producir
  el mismo resultado lógico sin mutar la solicitud ni el contexto.

### Factory de eventos

- WHEN `TimelineEventFactory.create` reciba datos, THE SYSTEM SHALL validar en
  runtime UUIDs, enums, campos obligatorios, fecha consciente, metadata y la
  coherencia entre `actor_type` y `actor_user_id`.
- WHEN `TimelineEventFactory.property_state_changed` reciba una transición,
  trigger o evidencia inválida, THE SYSTEM SHALL rechazarla con
  `TimelineEventValidationError`; no SHALL escapar `KeyError`, `ValueError` ni
  errores genéricos de entrada.
- WHEN se acepten datos de timeline, THE SYSTEM SHALL usar los tipos de dominio
  reales y no SHALL convertir strings UUID arbitrarios ni introducir validación de
  infraestructura.
- WHERE una capacidad emite eventos que no son `PROPERTY_STATE_CHANGED`, THE SYSTEM SHALL
  construirlos igualmente con `TimelineEventFactory.create`, que es la única vía. Los cuatro
  eventos de mensajería —`GUEST_MESSAGE_RECEIVED`, `AI_RESPONSE_SENT`,
  `AI_ESCALATED_TO_HUMAN` y `HUMAN_RESPONSE_SENT`— ganaron escritor con
  [`messaging-ai.md`](messaging-ai.md) el 2026-08-16; hasta entonces el enum los declaraba sin
  que nadie los escribiera. **Los dos de pricing hicieron lo mismo el 2026-08-18** con
  [`revenue-pricing.md`](revenue-pricing.md): `PRICE_RECOMMENDATION_CREATED` lo emite el
  generador, y **sólo cuando la fila se crea** —una regeneración que actualiza no pone nada en
  el timeline, así que en régimen estacionario es una fila por vivienda y día en vez de
  sesenta—, y `PRICE_UPDATED_EXTERNAL` lo emite la transición a `APPLIED_EXTERNAL`, que es el
  registro de que una persona publicó ese precio fuera del sistema. **`TECHNICIAN_EN_ROUTE` ganó el
  suyo el 2026-08-22** con [`maintenance.md`](maintenance.md), al renombrarse la transición `start`
  a `en_route`; el mismo ciclo añadió `TECHNICIAN_REJECTED` al vocabulario **ya con escritor**, de
  modo que el total subió a 47 miembros mientras los declarados sin escritor bajaron a 18.
- WHERE el evento apunta a una fila que un `ON CONFLICT DO UPDATE` pudo reescribir, THE SYSTEM
  SHALL tomar su identificador de lo que **devuelve la sentencia** y no de una lectura previa.
  En la rama de conflicto la fila guardada conserva su propio `id`, así que un evento construido
  desde la lectura previa apuntaría a ninguna fila — y siendo `timeline_events` append-only, ese
  puntero colgado sería permanente.
- WHERE el evento procede de un mensaje de huésped, THE SYSTEM SHALL llevar **título
  constante** e identificadores y enums cerrados en `metadata`, y NEVER SHALL copiar en él el
  contenido del mensaje. El motivo es estructural: `timeline_events` es append-only, así que una
  palabra que escribió el huésped no podría redactarse después.

### Pureza y verificación

- WHEN se importe esta capacidad, THE SYSTEM SHALL depender únicamente de código
  de dominio y tipos de contrato existentes; no SHALL importar SQLAlchemy,
  FastAPI, Pydantic, Celery, Redis ni adaptadores externos.
- WHEN se verifique la matriz, THE SYSTEM SHALL cubrir cada relación válida y
  destinos inválidos relevantes, incluidas variantes multidestino, determinismo,
  correlación y ausencia de mutación, mediante tests unitarios sin base de datos ni
  red.

## Key files

- `backend/app/properties/domain/state_machine.py` — autoridad de evaluación y
  matriz de triggers.
- `backend/app/properties/domain/state_resolution.py` — precedencia contextual,
  validación de destinos y política temporal.
- `backend/app/properties/domain/value_objects.py` — solicitudes, actores,
  contexto y resultado correlacionado.
- `backend/app/properties/domain/transition_enums.py` — triggers semánticos.
- `backend/app/timeline/domain/repositories.py` — `TimelineEventRepository` (sólo `add`, la
  inmutabilidad expresada en una firma) y, separado, `TimelineEventReader` (la lectura que
  añadió `dashboard-api`).
- `backend/app/timeline/domain/services.py` — `TimelineEventFactory` y eventos de
  cambio de estado.
- `backend/app/timeline/domain/value_objects.py` — contrato de entrada del factory.
- `backend/app/timeline/domain/exceptions.py` — errores estables de validación.
- `backend/tests/properties/` y `backend/tests/timeline/` — verificación unitaria
  exhaustiva de la política y del factory.
