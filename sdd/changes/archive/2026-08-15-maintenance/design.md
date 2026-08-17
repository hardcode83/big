# Design: maintenance

## Context

`backend/app/maintenance/` es hoy un dominio a medias: tiene `domain/` (entidades `Incident` y
`OwnerApproval` como *dataclasses* planas, enums, los value objects de proyección de
`dashboard-api`, y `repositories.py` con `IncidentReader`/`OwnerApprovalReader` de solo lectura más
un `IncidentRepository.add` de un método), `infrastructure/` (los dos modelos SQLAlchemy, tablas ya
migradas) y un `application/use_cases.py` con **un** caso de uso, `ReportGuestIncidentUseCase`, que
`guest-portal-api` puso ahí. No tiene `api/`, no tiene `ports.py`, no tiene `exceptions.py`, y
`UserRole.TECHNICIAN` sólo lleva `_SELF_SERVICE` en `backend/app/auth/domain/policy.py:223`.

Lo que sí existe y este change consume en vez de reconstruir: `PropertyStateMachine`
(`backend/app/properties/domain/state_machine.py`) con sus disparadores `INCIDENT_HIGH` /
`INCIDENT_CRITICAL` / `INCIDENT_RESOLVED` y el `ContextualStateResolver.after_incident_resolution`
que los resuelve; la maquinaria de SLA de `notifications`
(`list_sla_breach_candidates` / `mark_breached` / `cancel_sla_deadline`, más el `dispatch_notifications`
que `access-notifications` dejó vivo y que mueve `PENDING → SENT`); la política de escalado con
`TECHNICIAN_ASSIGNED → SLA_BREACH → PROPERTY_MANAGER` ya escrita
(`backend/app/notifications/domain/escalation.py:58-62`); `AuditLogFactory`/`ChangeSet` con su
allowlist; el vocabulario de `TimelineEventType`, que **ya cubre el flujo entero**
(`INCIDENT_CLASSIFIED`, `TECHNICIAN_ASSIGNED`, `TECHNICIAN_ACCEPTED`, `TECHNICIAN_STARTED`,
`INCIDENT_RESOLVED`, `INCIDENT_CANCELLED`, `OWNER_APPROVAL_REQUIRED`, `OWNER_APPROVED_EXPENSE`,
`OWNER_REJECTED_EXPENSE`); y el módulo `cleaning`, que es el gemelo estructural de todo esto y del
que se copia la forma (mixin de transición, `CleaningActor`, `errors.py`, `dependencies.py`).

El módulo espejo para casi todas las decisiones es `cleaning`: mismo triple reparto de permisos,
mismo ciclo asignar→aceptar→ejecutar→cerrar, mismo cruce con la máquina de estados. Donde este
diseño se aparta de `cleaning`, lo dice y da el motivo.

## Decisions

### D1 — El puerto de clasificación vive en `maintenance` y su adaptador de desarrollo también

**Elegido:** `IncidentClassifier` como `Protocol` de **un solo método** en
`backend/app/maintenance/domain/ports.py` (fichero nuevo, junto a `repositories.py`, exactamente el
reparto que hace `cleaning` entre `ports.py` y `repositories.py`), con un value object
`IncidentClassification(category, severity, summary, confidence: Decimal)` en
`domain/value_objects.py`. El adaptador determinista de desarrollo,
`RuleBasedIncidentClassifier`, va en `backend/app/maintenance/infrastructure/classifier.py`.

Es la decisión que el usuario ya tomó en el gate de `/sdd:new` y que el código confirma: **no existe
ningún `AIAdapter` ni `MockAIAdapter` en el repositorio** — la única aparición del nombre es una
frase de docstring en `backend/app/cleaning/api/tasks_router.py:323` que se lo asigna a
`messaging-ai`. Colgar de un adaptador inexistente serializaría dos entradas del roadmap que la
frontera declara paralelas.

Un puerto de un método por rol es lo que prescribe `steering/backend-architecture.md`
(«puertos pequeños y por rol… divide por consumidor real»), y es el mismo tamaño que
`guest-portal-api` le dio a `IncidentRepository.add`.

Rejected: reutilizar/inventar un `AIAdapter` compartido en `app/integrations/` — hoy no existe, y
crearlo aquí es escribir la frontera de `messaging-ai` desde fuera.
Rejected: clasificar con reglas embebidas en el caso de uso, sin puerto — viola PRD §3.3 y deja
`messaging-ai` sin sitio donde enchufar el proveedor real.

**Dónde irá el adaptador real**: `app/integrations/`, implementando este mismo puerto. El
adaptador determinista se queda en `maintenance/infrastructure/` porque no habla con ningún sistema
externo y no es compartido; `steering/backend.md` reserva `app/integrations/` para *adapters
externos compartidos*.

### D2 — La clasificación la conduce un job de Celery, no la petición que crea la incidencia

**Elegido:** un job `classify_incidents` en `app/scheduler/tasks.py` con su cadencia en
`app/scheduler/schedule.py`, que recoge incidencias en `OPEN` sin clasificar y las pasa por
`ClassifyIncidentUseCase`; más una ruta manual `POST /incidents/{id}/classify` para que un manager
la fuerce.

Tres razones, y la primera es de seguridad: el único escritor de `incidents` en `OPEN` es hoy
**una petición anónima desde internet** (el portal del huésped). Enganchar la invocación del puerto
a esa petición es exactamente la forma que la regla 12(d) de `steering/security.md` prohíbe —
«la re-lectura por API desacoplada del volumen de peticiones» — y con un adaptador de IA real
detrás del puerto sería un coste por petición que un tercero no autenticado decide. Segunda: R1.6
(«nunca perderla») sale gratis con un job que vuelve a recoger lo que sigue en `OPEN`, y caro con
un `try/except` en línea. Tercera: la maquinaria ya está — `celery-jobs` dejó `CADENCES`, el lock
por job y el patrón de idempotencia.

Rejected: clasificar dentro de `ReportGuestIncidentUseCase` — además de lo anterior, obligaría a
este change a modificar el camino que `guest-portal-api` posee.
Rejected: sólo la ruta manual, sin job — R1.2 dice «WHEN una incidencia está en `OPEN`, THE SYSTEM
SHALL invocar ese puerto», no «cuando alguien lo pida».

### D3 — Qué distingue «pendiente de clasificar» de «clasificada» y de «fallida» (R1.2, R1.3, R1.6)

**Elegido:** el par (`status`, `ai_classification`) lleva los tres estados, sin columna nueva:

| Situación | `status` | `category`/`severity` | `ai_classification` |
|---|---|---|---|
| Recién creada | `OPEN` | defaults (`OTHER`/`MEDIUM`) | `NULL` |
| Clasificada con confianza suficiente | `CLASSIFIED` | los del adaptador | el resultado |
| Confianza por debajo del umbral (R1.3) | `OPEN` | defaults | el resultado, con su `confidence` |
| El adaptador falló (R1.6) | `OPEN` | defaults | `NULL` |

El candidato del job es por tanto `status = OPEN AND ai_classification IS NULL`. Eso da las dos
propiedades que las tres cláusulas piden a la vez: **un fallo se reintenta** en el siguiente tick, y
**una confianza baja no se reintenta en bucle** — porque un adaptador determinista devolvería la
misma confianza baja para siempre y el job giraría en vacío. Y satisface literalmente R1.3: la
incidencia queda distinguible de una ya clasificada (`status` sigue en `OPEN`) y de una recién
creada (`ai_classification` está puesta).

Rejected: una columna `classification_attempted_at` — resuelve lo mismo y añade una migración a una
tabla que ya tiene el sitio donde escribirlo.

### D4 — `ai_summary` y `ai_classification` son sumideros de texto en claro y este change fija su contrato

**Elegido:** declararlos en el censo de la regla 11 de `steering/security.md` (que hoy enumera
nueve columnas) con **forma estructurada por defecto** — la regla general, no la excepción 2 — y
hacerla cumplir en el contrato del puerto: **el `summary` que devuelve un adaptador no puede ser un
eco de `title` ni de `description`**. El adaptador determinista lo cumple por construcción: su
`summary` sale de un vocabulario cerrado por categoría, no del texto de entrada.
`ai_classification` guarda sólo valores cerrados y números (`category`, `severity`, `confidence`,
`adapter`, `classified_at`).

Esto hay que decirlo porque la excepción 2 de la regla 11 —la que autoriza prosa cruda en
`incidents.title`/`description`— se concede explícitamente *«porque el valor no es nuestro y no lo
hemos ido a buscar»*, y añade: *«No autoriza a un escritor nuestro… una clasificación automática
que quiera meter un código, una contraseña o un número de documento en estos campos cae bajo la
forma estructurada por defecto»*. `ai_summary` lo escribe nuestro clasificador **a partir de** texto
que tecleó un anónimo: sin este contrato, un adaptador de IA real que parafrasee la descripción del
huésped copia su número de documento a una columna que nadie había declarado.

Lo mismo, y por el mismo motivo, para `owner_approvals.reason`, que lo escribe nuestro código
(constante + identificadores, la disciplina de `app/cleaning/domain/notifications.py`).

`owner_approvals.response_notes` es **el caso distinto y esta decisión lo tenía mal**: lo teclea la
propietaria autenticada, así que no hay forma estructurada que darle — es prosa sobre su propio
dinero. Va bajo una **excepción nombrada propia**, la 3 de la regla 11, concedida por la misma
propiedad del escritor que la 2 (*el valor no es nuestro y no lo hemos ido a buscar*). La primera
redacción del censo la declaró «estructurada» junto a las otras tres; lo levantó el panel de
seguridad de las secciones 7-8, y una fila del censo que promete lo que su escritor no cumple es
peor que una columna sin censar.

Ninguna de las cuatro se propaga: no entran en `AUDITABLE_FIELDS` (D6) ni en `metadata` de timeline.

Rejected: extender la excepción 2 a `ai_summary` — la excepción dice de sí misma que no cubre a un
escritor nuestro, y ampliarla sería reabrir el criterio que ya falló dos redacciones.

**Refuerzo durante `/sdd:run` (panel de seguridad de la sección 6, 2026-08-15): el contrato también
se comprueba donde se escribe, no sólo donde se documenta.** Esta decisión lo fijaba «en el contrato
del puerto», y eso resultó ser un docstring más un adaptador que lo cumplía: `IncidentClassification.summary`
es un `str` sin restringir, así que el día que entre un proveedor real que parafrasee, el número de
documento del huésped aterriza en `ai_summary`. `Incident.classify` descarta ahora un `summary` que
comparta una tirada de ocho caracteres o más con `title`/`description` — la longitud está elegida
contra los **valores** que enumera la regla 3 (un DNI, un IBAN, un código), no contra el parecido de
la prosa. Se descarta el campo y no la clasificación: R1.6 dice que una incidencia no se pierde
porque un adaptador se porte mal. Esto no sustituye a la condición de admisión que debe escribir la
tarea 9.1 en el censo; la respalda.

### D5 — Las mutaciones viven en la entidad `Incident`, con su tabla de transiciones

**Elegido:** `Incident` deja de ser una *dataclass* pasiva y gana métodos que protegen la invariante
(`classify`, `set_triage`, `require_owner_approval`, `resume_after_approval`, `assign`, `accept`,
`start`, `wait_for_parts`, `resume_work`, `resolve`, `cancel`), con una tabla `_TRANSITIONS`
privada. Los campos siguen siendo públicos porque `ReportGuestIncidentUseCase` y la máquina de
estados los leen, pero **ningún caso de uso escribe `status` directamente**.
`OwnerApproval` gana `answer(...)`, que rechaza responder dos veces.

Es lo que manda `steering/backend-architecture.md` («la invariante vive aquí, no en el router ni en
el caso de uso») y es el sitio donde R4.4 se cumple una vez en lugar de en cinco endpoints. Excepción
declarada de la sección «cuándo simplificar»: `maintenance` deja de ser un dominio sin invariante
real en el momento en que tiene un ciclo de vida.

Rejected: validar el orden en los casos de uso — cinco copias de la misma tabla, y R4.4 pide
rechazar «cualquier transición fuera del orden declarado».

### D6 — Vocabulario de auditoría y ensanche de `AUDITABLE_FIELDS` (R6.1, R6.2)

**Elegido:** añadir a `app/audit/domain/actions.py` la entidad `ENTITY_OWNER_APPROVAL` y las
acciones `INCIDENT_CLASSIFIED`, `INCIDENT_TRIAGED`, `INCIDENT_ASSIGNED`, `INCIDENT_ACCEPTED`,
`INCIDENT_STARTED`, `INCIDENT_WAITING_PARTS`, `INCIDENT_RESOLVED`, `INCIDENT_CANCELLED`,
`OWNER_APPROVAL_REQUESTED`, `OWNER_APPROVAL_ANSWERED`.

**Corrección durante `/sdd:run` (panel de arquitectura de la sección 6, 2026-08-15): son doce, no
diez.** Con las diez, dos operaciones se quedaban sin verbo propio y acababan escribiendo
`INCIDENT_TRIAGED`: aparcar la incidencia en la segunda puerta de D11 (el coste real desbordó el
umbral) y devolverla al flujo cuando la propietaria aprueba. Ninguna de las dos es un triaje —nadie
está corrigiendo una categoría—, así que quien leyera el rastro entendería mal quién hizo qué. Se
acuñan `INCIDENT_AWAITING_APPROVAL` e `INCIDENT_RESUMED`. La única reutilización que se mantiene es
la declarada: `ResumeWorkUseCase` comparte `INCIDENT_STARTED` con `StartIncidentUseCase`, porque
reanudar el trabajo *es* trabajar.

El comentario que hoy explica su ausencia
(`actions.py:199-204`: «no hay `INCIDENT_CLASSIFIED`/`_ASSIGNED`/`_RESOLVED` aquí porque nada las
ejecuta todavía») se sustituye, no se borra: ahora las ejecuta este change, que es exactamente la
puerta que ese párrafo describe.

`AUDITABLE_FIELDS["INCIDENT"]` pasa de `{source, status, reservation_id}` a añadir
`category`, `severity`, `assigned_technician_id`, `owner_approval_required`, `estimated_cost`,
`approved_cost`, `final_cost`, `resolved_at`. **Sin `title`, sin `description`, sin `ai_summary` y
sin `ai_classification`** (R6.2 y D4). `AUDITABLE_FIELDS["OWNER_APPROVAL"]` es
`{status, amount, related_type, responded_by, responded_at}` — sin `reason` ni `response_notes`.

**Corrección durante `/sdd:run` (panel de seguridad de la sección 4, 2026-08-15): se retira
`approved_cost_applied`.** Esta decisión lo incluía como «el hecho de que el importe aprobado se
llevó a la incidencia», y no es una columna de `owner_approvals`. El propio `ChangeSet` declara
para qué sirve una entrada del allowlist —«an audited diff may only name a real, non-sensitive
column of the entity: an invented name is how a caller writes an arbitrary payload — including a
secret — into `audit_logs.changes` under a harmless-looking key»—, así que un nombre sin columna
es un hueco de tipo libre en un sumidero de la regla 11: `.diff("approved_cost_applied", None,
approval.response_notes)` habría metido el texto de la propietaria justo por donde D6 dice que no
pasa. El hecho no se pierde: vive en `INCIDENT.approved_cost`, que sí es columna real y sí está en
el allowlist.

Actor: el usuario que ejecuta (R6.4). La clasificación **automática** del job no tiene usuario, así
que su fila va con `actor_user_id = NULL` y `actor_ip = NULL`, por el mismo motivo que da la segunda
excepción nombrada de la regla 9 sobre su propio caso (*«estas filas van sin actor… el comando no
tiene identidad que registrar»*).

**Corrección durante `/sdd:run` (panel de seguridad de la sección 4, 2026-08-15): eso era un
parecido, no un precedente.** La regla 9 dice de ese razonamiento que «**no es un criterio
reutilizable**» y que ampliarlo se hace «con una entrada nueva y nombrada aquí, aprobada en el
design del change que la pida». Este design la aprueba; faltaba escribirla en el steering, y la
escribió la tarea **9.1b**: es hoy la **cuarta excepción nombrada** de la regla 9, y no se pide por
cadencia como la segunda sino porque **no existe el actor** — al job lo dispara el reloj. Acotada a
`INCIDENT_CLASSIFIED` y sólo desde el job; `_AuditWriter` rechaza sin actor cualquier otra acción
del flujo.

**Es un matiz declarado sobre R6.4**, aprobado en el gate de `/sdd:design` (2026-08-15): R6.4 dice
«nombrar como actor al usuario que ejecuta la transición», y cuando la ejecuta el job no hay
usuario. Se audita igualmente, sin actor, en vez de dejar fuera de `audit_logs` la operación que
fija la severidad de la que cuelgan el SLA, la aprobación y el estado de la propiedad. Lo que R6.4
prohíbe —una fila que reclame a la vez un usuario y un portador de token— lo impide
`AuditLogFactory` por construcción, y en el timeline lo impide `TimelineEventFactory`, que sólo
admite `actor_user_id` con actor `USER` (`services.py:43-46`). Rejected: sembrar una cuenta `SYSTEM`
por tenant que firme lo automático — inventa una identidad que nadie ejercita y hay que crearla en
cada entorno.

### D7 — La recomposición del estado de la propiedad, y el contexto que hace falta para pedirla

**Elegido:** un `_IncidentTransitionMixin` en `application/`, calcado de
`_TaskTransitionMixin` (`app/cleaning/application/use_cases.py:513-598`): construye
`PropertyStateChangeRequest`, llama a `PropertyStateMachine.evaluate`, persiste
`PropertyStateTransition` + `TimelineEvent` + `Property` en la misma transacción, y **nunca** escribe
`current_operational_state` por su cuenta.

Lo que este diseño añade sobre el gemelo de `cleaning` es **qué hay que meter en el contexto**, y no
es obvio: `ContextualStateResolver.after_incident_resolution`
(`state_resolution.py:116-123`) cae, si no queda ninguna incidencia activa, en
`_contextual_reservation_cleaning`, que lee `context.cleaning_tasks` **y** `context.reservations`.
Es decir, resolver un `INCIDENT_RESOLVED` necesita en el contexto:

1. **todas** las incidencias no terminales de la propiedad (no sólo la que se resuelve),
2. las reservas de la ventana,
3. las tareas de limpieza vivas de la propiedad.

Sin (3), una propiedad con limpieza pendiente saldría de `MAINTENANCE_REQUIRED` a `VACANT_READY` en
vez de a `AWAITING_CLEANING`. Para (1) se amplía `IncidentReader` con
`list_active_for_property(tenant_id, property_id) -> Sequence[Incident]` — entidades, no
`IncidentSummary`, porque la máquina lee `severity`/`status`/`tenant_id`/`property_id`. Para (2) se
reutiliza el puerto `ReservationRepository` de `reservations.domain`, como ya hace `cleaning`. Para
(3), `maintenance` declara su **propio puerto estrecho** en `ports.py`,
`LiveCleaningTaskQuery.list_live_for_property`, con adaptador en `maintenance/infrastructure/` —
que es la construcción simétrica y exacta de lo que `cleaning` hizo al revés con
`BlockingIncidentQuery` (`app/cleaning/domain/ports.py:29`) para leer `incidents`.

Rejected: importar `CleaningTaskRepository` entero desde `maintenance` — repositorio de otro
agregado raíz, y `maintenance` sólo necesita un método de lectura.
Rejected: no pasar tareas de limpieza y aceptar el destino equivocado — es un estado operacional
falso en el dashboard, que es el producto entero.

### D8 — Un disparador de severidad que la política no admite se registra y se tolera; no falla la operación

**Elegido:** el mixin captura `NoOperationalStateChangeError` e `InvalidStateTransitionError` de
los disparadores `INCIDENT_HIGH`/`INCIDENT_CRITICAL`, deja un `logger.warning` y **sigue**: la
incidencia queda clasificada.

**Corrección durante `/sdd:run` (DESIGN-CONFLICT del panel de arquitectura de la sección 6,
2026-08-15): `IncompatibleTransitionContextError` sale de esa lista.** Esta decisión la incluía, y
resultó ser un punto ciego, no tolerancia: la máquina levanta esa excepción **sólo** cuando nuestro
código se contradice a sí mismo —una severidad que no casa con el disparador que derivamos de ella,
una incidencia terminal cuando dijimos que estaba activa, un `source_entity_id` que falta del
contexto que construimos nosotros—, y ninguno de esos casos es un hueco de la matriz. Se cobró su
primera víctima dentro del propio change: `list_active_for_property` excluye los estados terminales,
así que la incidencia recién resuelta no estaba en el contexto, `_source_incident` la rechazaba, y
la tolerancia se tragaba el rechazo — la propiedad se quedaba en `MAINTENANCE_REQUIRED` en silencio.
Lo encontraron los tests de la sección 6, no la revisión. `cleaning` traza esta misma raya y por el
mismo motivo (*«this is our bug and must surface as a 500»*). Es el patrón que
`_fire_cleaner_assigned` ya estableció (`use_cases.py:399-410`): «la tarea existe y está asignada;
sólo el estado de la propiedad no se movió. No es motivo para deshacer».

Hace falta decirlo porque la matriz tiene huecos reales. Estados fuente que **no** admiten cada
disparador hoy:

| Disparador | Sin entrada desde |
|---|---|
| `INCIDENT_HIGH` | `CLEANING_SCHEDULED`, `MAINTENANCE_REQUIRED`, `BLOCKED_BY_OWNER`, `OUT_OF_SERVICE` |
| `INCIDENT_CRITICAL` | `VACANT_READY`, `CRITICAL_INCIDENT`, `BLOCKED_BY_OWNER`, `OUT_OF_SERVICE` |

De esos, tres son correctos como están (`MAINTENANCE_REQUIRED`+HIGH y `CRITICAL_INCIDENT`+CRITICAL
son no-ops; `BLOCKED_BY_OWNER`/`OUT_OF_SERVICE` ya paran todo por decisión humana). **Dos son
omisiones y este change las cierra** (decidido en el gate de `/sdd:design`, 2026-08-15) — con su
test de aceptación y su test de rechazo cada una, que es lo que DoD §28.19 exige a toda transición:

- `VACANT_READY` + `INCIDENT_CRITICAL` → `CRITICAL_INCIDENT`. Hoy una avería crítica en un piso
  vacío y listo lo deja en `VACANT_READY`, es decir, reservable.
- `CLEANING_SCHEDULED` + `INCIDENT_HIGH` → `MAINTENANCE_REQUIRED`. `CLEANING_SCHEDULED` admite
  `INCIDENT_CRITICAL` y no `INCIDENT_HIGH`; todos los demás estados de limpieza admiten los dos.

La tolerancia de arriba sigue en pie de todos modos: cierra los huecos conocidos, no promete que no
queden otros, y el estado operacional es una proyección — la incidencia es el registro.

### D9 — `INCIDENT_RESOLVED` debe admitir también la incidencia cancelada

**Elegido:** ampliar la precondición de `PropertyStateMachine._validate_trigger_preconditions`
(`state_machine.py:247-248`) de `status is RESOLVED` a `status in {RESOLVED, CANCELLED}`.

Sin esto, R2.5 deja la propiedad colgada: una incidencia CRITICAL lleva la propiedad a
`CRITICAL_INCIDENT`, la propietaria rechaza el gasto, la incidencia pasa a `CANCELLED` — y no hay
ningún disparador que saque a la propiedad de ahí (`OWNER_MANAGER_UNBLOCKED` sale de
`BLOCKED_BY_OWNER`, no de aquí).

Y no es una licencia que este change se tome: **el resolver ya cuenta con ello**.
`after_incident_resolution` filtra las incidencias activas con
`status not in (RESOLVED, CANCELLED)` (`state_resolution.py:118`), o sea, ya trata una cancelada
como resuelta a efectos de recomponer el estado. Lo único que lo impide es el guard de la
precondición.

Rejected: un disparador `INCIDENT_CANCELLED` nuevo — duplicaría destino y resolver de
`INCIDENT_RESOLVED` para distinguir dos hechos que la propiedad vive igual.

### D10 — Qué transición conduce cada evento de timeline, y el que falta

**Elegido:** se usan sólo `TimelineEventType` existentes, y resulta que dan para todo el flujo:

| Operación | `TimelineEventType` | Actor |
|---|---|---|
| Clasificación (job) | `INCIDENT_CLASSIFIED` | `AI` |
| Clasificación/corrección manual | `INCIDENT_CLASSIFIED` | `USER` |
| Se pide aprobación | `OWNER_APPROVAL_REQUIRED` | `USER` (o `SYSTEM` si la abre el cierre) |
| Aprobada / rechazada | `OWNER_APPROVED_EXPENSE` / `OWNER_REJECTED_EXPENSE` | `USER` |
| Asignación | `TECHNICIAN_ASSIGNED` | `USER` |
| Aceptación | `TECHNICIAN_ACCEPTED` | `USER` |
| `ACCEPTED → IN_PROGRESS` | `TECHNICIAN_STARTED` | `USER` |
| Resolución | `INCIDENT_RESOLVED` | `USER` |
| Cancelación | `INCIDENT_CANCELLED` | `USER` |

`TECHNICIAN_EN_ROUTE` **queda sin usar y a propósito**: `IncidentStatus` no tiene un estado «en
ruta» (R4.1 no lo pide) y el timeline es *append-only*, así que escribir un evento que afirma un
desplazamiento que el sistema no observa es una afirmación que ya no se puede retirar.

`WAITING_EXTERNAL_PARTS` **no tiene tipo de evento y no se inventa uno** (decidido en el gate de
`/sdd:design`, 2026-08-15): la espera de piezas se registra en el `status` de la incidencia y en su
fila de `AuditLog`, y no en el timeline. El vocabulario de `TimelineEventType` es el del PRD §10, y
`guest-portal-api` sólo lo amplió cuando el hito no era describible con ninguno de los existentes;
aquí el hito lo describe el propio estado. Coste asumido: el timeline no explica por sí solo por qué
una incidencia lleva días abierta — eso se ve en la incidencia.

Disciplina heredada de `ReportGuestIncidentUseCase`: **título constante y `metadata` sólo con
identificadores** (`incident_id`, `property_id`, y `owner_approval_id`/`technician_id` cuando
aplique). Nada de `title`, `description` ni `ai_summary` en el evento (D4).

Actor `AI` para la clasificación automática: `TimelineActorType.AI` existe, y `TimelineEventFactory`
sólo admite `actor_user_id` cuando el actor es `USER` (`services.py:43-46`), así que la fila no
puede reclamar un usuario que no hay — que es literalmente lo que R6.4 prohíbe.

### D11 — La aprobación del propietario: dos puertas distintas, distinguidas por `related_type`

**Elegido:** el enum `OwnerApprovalRelatedType` ya trae `INCIDENT` y `MAINTENANCE_COST`, y este
diseño los usa como las dos puertas del PRD §12, lo que evita añadir cualquier columna:

- **Puerta del presupuesto (R2.1).** Un manager fija `estimated_cost` sobre una incidencia
  `CLASSIFIED`. Si supera `TenantConfig.owner_approval_threshold_eur`: `OwnerApproval` en `PENDING`
  con `related_type = INCIDENT`, `owner_approval_required = True`, incidencia a
  `AWAITING_OWNER_APPROVAL`. Aprobada → `approved_cost = amount` y vuelta a **`CLASSIFIED`**, que es
  «el flujo de asignación» de R2.4. Rechazada → `CANCELLED` (R2.5).
- **Puerta del coste real (R4.3).** El técnico resuelve con un `final_cost` que supera el umbral y
  no está cubierto por un `OwnerApproval` aprobado. Se escribe `final_cost`, se crea un
  `OwnerApproval` con `related_type = MAINTENANCE_COST` y la incidencia va a
  `AWAITING_OWNER_APPROVAL` **sin** `resolved_at`. Aprobada → vuelve a **`IN_PROGRESS`** y el
  técnico reintenta el cierre. Rechazada → `CANCELLED`.

Así el estado al que se vuelve tras un `APPROVED` se **deriva** del `related_type` de la aprobación,
sin guardar en ningún sitio «de dónde venía». «Cubierto por una aprobación aprobada» =
`approved_cost is not None and final_cost <= approved_cost`.

Rejected: auto-resolver la incidencia al aprobar el coste real — sería el sistema cerrando un parte
que el técnico no cerró; el `resolved_at` dejaría de significar «lo dio por terminado».
Rejected: una columna `resume_status` — el `related_type` ya la contiene.
Rejected: `EXPIRED` y un `updated_at` en `owner_approvals` — fuera de alcance por el proposal, y el
docstring del modelo (`infrastructure/models.py:67-74`) deja la decisión a quien traiga la
expiración.

### D12 — SLA sobre la maquinaria de `notifications`, sin construir una segunda (R3.2)

**Elegido:** `maintenance/domain/notifications.py` (constructores puros, calcado de
`cleaning/domain/notifications.py`) con `RELATED_TYPE_INCIDENT = "incident"` y dos constructores:

- `technician_assignment_notification(...)` → `notification_type = TECHNICIAN_ASSIGNED`,
  `status = PENDING`, `related_type/related_id` apuntando a la incidencia, y
  `sla_deadline_at = now + minutes` donde `minutes` sale de una función pura
  `sla_minutes_for(severity, config)` que mapea `CRITICAL/HIGH/MEDIUM/LOW` a los cuatro campos de
  `TenantConfig`.
- `owner_approval_notification(...)` → `OWNER_APPROVAL_REQUIRED`, **sin `sla_deadline_at`**: nadie
  ha definido un plazo para la propietaria y un plazo sin escalado definido sólo produce ruido
  (`escalation_for` devolvería `None`).

Aceptar (R3.3) y reasignar (R3.5) llaman a
`cancel_sla_deadline(related_type="incident", related_id=incident.id, notification_type="TECHNICIAN_ASSIGNED")`,
que ya devuelve «cero filas es normal».

El escalado ya está escrito y no hay que tocarlo:
`TECHNICIAN_ASSIGNED → SLA_BREACH → PROPERTY_MANAGER`
(`escalation.py:58-62`), con su nota de que `PhoneAdapter` no existe. **Y esta vez el plazo sí
funciona de punta a punta**, al contrario que cuando `cleaning` lo escribió: aquella deuda
(`list_sla_breach_candidates` exige `status = SENT` y las filas nacen `PENDING`) la pagó
`access-notifications` con `dispatch_notifications`, que ya mueve `PENDING → SENT`.

### D13 — Permisos: el reparto triple de `cleaning`, con la excepción que R4.5 pide

**Elegido:** cuatro permisos nuevos en `app/auth/domain/policy.py`:

| Permiso | `TENANT_OWNER` | `PROPERTY_MANAGER` | `TECHNICIAN` | `CLEANER` / `SUPER_ADMIN` |
|---|---|---|---|---|
| `READ_INCIDENTS` | ✔ | ✔ | ✔ | — |
| `MANAGE_INCIDENTS` | — | ✔ | — | — |
| `EXECUTE_INCIDENTS` | — | ✔ | ✔ | — |
| `RESPOND_OWNER_APPROVALS` | ✔ | — | — | — |

`EXECUTE_INCIDENTS` **sí** lo tiene el manager, y ahí este diseño se aparta de `cleaning` (donde
`EXECUTE_CLEANING_TASKS` es de la limpiadora y de nadie más): R4.5 dice literalmente «un
`PROPERTY_MANAGER` sí puede, para desatascar». La restricción de asignatario no la lleva entonces el
permiso sino el rol, en un `IncidentActor.restrict_to_technician_id` calcado de
`CleaningActor.restrict_to_cleaner_id` (`use_cases.py:502-510`): devuelve el id si el rol es
`TECHNICIAN` y `None` si no, y va directo al filtro del repositorio — que es lo que resuelve R5.3 sin
que ningún router pueda olvidarlo. `require()` acepta un solo permiso
(`auth/api/dependencies.py:430`), así que esto es además la única forma de expresarlo.

`RESPOND_OWNER_APPROVALS` sólo para `TENANT_OWNER` (R2.6). **No se añade un
`READ_OWNER_APPROVALS`** ni una ruta de listado: el dashboard ya las expone por propiedad
(`OwnerApprovalReader.list_pending_for_property`) y la notificación de R2.3 avisa; `policy.py`
declara en su cabecera que el catálogo sólo lleva «los permisos que este change realmente aplica».

`SUPER_ADMIN` no recibe nada, por el motivo que ese fichero ya documenta dos veces (sus poderes son
globales y `saas-cross-tenant` decide qué es acceso entre tenants).

### D14 — Superficie de API

**Elegido:** router `app/maintenance/api/incidents_router.py` con `prefix="/incidents"`, más
`approvals_router.py` con `prefix="/owner-approvals"`; ambos bajo `API_V1_PREFIX`, con
`errors.py` propio registrado en `main.py` como los ocho que ya hay.

| Ruta | Permiso | Qué hace |
|---|---|---|
| `GET /incidents` | `READ_INCIDENTS` | Listado paginado `?page&per_page`, filtros `status`/`severity`/`property_id`. Un `TECHNICIAN` sólo ve las suyas (R5.3) |
| `GET /incidents/{id}` | `READ_INCIDENTS` | Detalle. Un `TECHNICIAN` no asignado recibe el mismo `404` que una desconocida |
| `POST /incidents/{id}/classify` | `MANAGE_INCIDENTS` | Fuerza el paso por el puerto (D2) |
| `PATCH /incidents/{id}` | `MANAGE_INCIDENTS` | Triaje: `category`, `severity`, `estimated_cost` (R1.4, R2.1) |
| `POST /incidents/{id}/assign` | `MANAGE_INCIDENTS` | Asigna o reasigna técnico (R3.1, R3.5) |
| `POST /incidents/{id}/accept` | `EXECUTE_INCIDENTS` | R4.1 |
| `POST /incidents/{id}/start` | `EXECUTE_INCIDENTS` | `ACCEPTED → IN_PROGRESS` |
| `POST /incidents/{id}/wait-parts` | `EXECUTE_INCIDENTS` | `IN_PROGRESS → WAITING_EXTERNAL_PARTS` |
| `POST /incidents/{id}/resume` | `EXECUTE_INCIDENTS` | `WAITING_EXTERNAL_PARTS → IN_PROGRESS` |
| `POST /incidents/{id}/resolve` | `EXECUTE_INCIDENTS` | Exige `final_cost` (R4.2); puede abrir la segunda puerta de D11 |
| `POST /incidents/{id}/cancel` | `MANAGE_INCIDENTS` | Terminal desde cualquier estado no terminal (R4.4); la propiedad se recompone |
| `POST /owner-approvals/{id}/respond` | `RESPOND_OWNER_APPROVALS` | `APPROVED`/`REJECTED` + `response_notes` (R2.4, R2.5) |

**`cancel` se añadió durante `/sdd:run` y son doce rutas, no once** (levantado por el panel de
arquitectura de las secciones 7-8, 2026-08-15). Esta tabla no lo tenía, y su ausencia **no era una
decisión** como sí lo es la de `POST /incidents`: la tarea 6.11 manda `CancelIncidentUseCase`, la
tabla `_TRANSITIONS` de D5 declara `cancel` desde todo estado no terminal, y R4.4 cuenta con él, así
que el caso de uso estaba aprobado y sólo le faltaba la puerta. Un módulo con `api/` completa y un
caso de uso sin ruta es código muerto, y la operación es real: una incidencia duplicada o un reporte
falso hay que poder cerrarlos sin inventar un coste final. Va bajo `MANAGE_INCIDENTS` —cancelar es
administrar, no ejecutar— y dispara `INCIDENT_RESOLVED` por el mixin, que es lo que D9 hizo posible.

**No hay `POST /incidents`**: el proposal no pide una vía de alta desde el panel (R5.1 pide listado
y detalle), y las fuentes de creación que faltan tienen dueño declarado — el portal ya crea,
`messaging-ai` traerá el intent y `LOCK_ALERT` está fuera de alcance. Se dice explícitamente porque
es la ausencia más visible de la tabla.

`assign` es `POST` y no `PATCH` como en `cleaning`: aquí la asignación abre un plazo de SLA y
notifica, o sea es una operación, no una edición de campo; el `PATCH` queda para el triaje.

Los estados terminales, los conflictos de orden y el cruce con `PropertyStateMachine` se traducen a
la envoltura de PRD §23 con la misma tabla exhaustiva que `cleaning/api/errors.py`: `404` para
inexistente/otro tenant/no-asignada-a-este-técnico, `409` para transición inválida y para incidencia
bloqueada por aprobación pendiente, `422` para validación.

### D15 — Aislamiento y RBAC verificables (regla 1 y 2 de `security.md`)

**Elegido:** todos los métodos de repositorio llevan `tenant_id` explícito, como declara la cabecera
de `maintenance/domain/repositories.py` («el parámetro es el mecanismo autoritativo y los criterios
del cargador global de `app/core/db.py` son sólo la red»). R3.4 (el asignatario debe ser
`TECHNICIAN` **y** del tenant) se resuelve leyendo el usuario por `UserRepository` dentro del tenant,
como hace `AssignCleaningTaskUseCase`. R5.4 —ni `CLEANER` ni portador de token de huésped— se cumple
por construcción: `CLEANER` no tiene ninguno de los cuatro permisos, y el portador de token de
huésped no llega nunca a `require(...)`, que sólo acepta el `AuthenticatedRequest` del JWT de
usuario; ambas cosas llevan test propio.

Los tests de aislamiento tienen que correr **sobre una sesión no marcada con tenant**: sobre una
marcada, el listener global de `app/core/db.py` filtra y el test no puede fallar aunque el código
esté mal.

### D16 — Contrato y documentación (R5.5)

**Elegido:** `make openapi` regenera `backend/openapi.json`, y el artefacto derivado del frontend
`frontend/lib/api/generated/openapi.d.ts` se regenera y commitea en el mismo PR — las dos mitades
que `steering/documentation.md` exige desde que `cleaning` rompió `main`. En un worktree el comando
documentado (`cd frontend && npm run api:check`) **no funciona**; la salida verificada está en
`sdd/project.md` (copiar `openapi.json` al contenedor, symlink `/frontend → /app`, y
`npm run api:generate`). Además: `docs/maintenance.md` nuevo (capability operativa) y el README raíz,
que gana un módulo con `api/`.

## Changes by area

| Área | Ficheros | Cambio |
|---|---|---|
| Dominio maintenance | `app/maintenance/domain/entities.py` | `Incident` gana su tabla de transiciones y sus métodos; `OwnerApproval` gana `answer()` (D5) |
| | `app/maintenance/domain/ports.py` **(nuevo)** | `IncidentClassifier`, `LiveCleaningTaskQuery` (D1, D7) |
| | `app/maintenance/domain/value_objects.py` | `IncidentClassification`; proyecciones de listado/detalle para el API |
| | `app/maintenance/domain/repositories.py` | `IncidentReader.list_active_for_property` y `.list(...)` paginado; `IncidentRepository.get/save`; `OwnerApprovalRepository` (D7, D11) |
| | `app/maintenance/domain/notifications.py` **(nuevo)** | Constructores + `sla_minutes_for` (D12) |
| | `app/maintenance/domain/sla.py` o dentro de `notifications.py` | Mapa severidad → campo de `TenantConfig` |
| | `app/maintenance/domain/exceptions.py` **(nuevo)** | Jerarquía `MaintenanceDomainError` |
| Aplicación | `app/maintenance/application/use_cases.py` | `_IncidentTransitionMixin`, `_AuditWriter`, `IncidentActor` y los casos de uso de R1-R4 (D5, D7, D11) |
| Infraestructura | `app/maintenance/infrastructure/classifier.py` **(nuevo)** | `RuleBasedIncidentClassifier` determinista (D1, D4) |
| | `app/maintenance/infrastructure/repositories.py` | Adaptadores SQLAlchemy de los puertos nuevos |
| API | `app/maintenance/api/{__init__,incidents_router,approvals_router,schemas,errors,dependencies}.py` **(nuevos)** | D14 |
| | `app/main.py` | Registro de los dos routers y del manejador de errores |
| Auth | `app/auth/domain/policy.py` | Cuatro permisos y su reparto (D13) |
| Audit | `app/audit/domain/actions.py`, `value_objects.py` | Acciones, entidad y ensanche del allowlist (D6) |
| Properties | `app/properties/domain/state_machine.py` | Precondición `RESOLVED`→`{RESOLVED, CANCELLED}` (D9) y dos entradas nuevas de `_POLICY` (D8) |
| Scheduler | `app/scheduler/tasks.py`, `schedule.py` | Job `classify_incidents` con su cadencia y su lock (D2) |
| Steering | `sdd/steering/security.md` | Censo de la regla 11: `incidents.ai_summary`/`ai_classification`, `owner_approvals.reason`/`response_notes` (D4) |
| Tests | `backend/tests/maintenance/**`, `backend/tests/properties/` | Unit de dominio (TDD, invariante real), integración de repos y endpoints, aislamiento, y las transiciones nuevas de la máquina |
| Contrato/docs | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts`, `docs/maintenance.md`, `README.md` | D16 |

## Data & interfaces

**Migraciones: ninguna.** Las dos tablas ya existen con todas las columnas que este flujo escribe
(`incidents` con los tres costes, `assigned_technician_id`, `owner_approval_required`, `resolved_at`,
`ai_summary`, `ai_classification`; `owner_approvals` con `status`, `responded_at`, `responded_by`,
`response_notes`). Es la consecuencia buscada de que `domain-foundation-ops`/`-financial` las
modelaran enteras, y de que `EXPIRED`/`updated_at` estén fuera de alcance.

**Puerto nuevo (D1):**

```python
class IncidentClassifier(Protocol):
    async def classify(self, *, title: str, description: str) -> IncidentClassification: ...

@dataclass(frozen=True)
class IncidentClassification:
    category: IncidentCategory
    severity: IncidentSeverity
    summary: str        # vocabulario del adaptador, nunca eco de la entrada (D4)
    confidence: Decimal  # 0..1, se compara con TenantConfig.ai_confidence_threshold
```

**Puerto de contexto (D7):**

```python
class LiveCleaningTaskQuery(Protocol):
    async def list_live_for_property(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID
    ) -> Sequence[CleaningTask]: ...
```

**Ciclo de vida de `IncidentStatus`** (todo lo demás se rechaza con `409`, R4.4):

```
OPEN ──clasificar──▶ CLASSIFIED ──asignar──▶ ASSIGNED ──aceptar──▶ ACCEPTED
 │                       │                                             │
 │ (confianza baja       │ estimated_cost > umbral                     ▼
 │  o fallo: sigue       ▼                                        IN_PROGRESS ◀──┐
 │  en OPEN)      AWAITING_OWNER_APPROVAL ──APPROVED──▶ CLASSIFIED     │  │      │
 │                       │                                            │  └──────┘
 │                       └──REJECTED──▶ CANCELLED                     │  WAITING_EXTERNAL_PARTS
 │                                                                    ▼
 └──── (cualquier no terminal) ──cancelar──▶ CANCELLED           RESOLVED
                                                        (o AWAITING_OWNER_APPROVAL
                                                         si final_cost > umbral, D11)
```

**Config/env:** ninguna variable nueva. Todos los umbrales y plazos salen de `TenantConfig`
(`owner_approval_threshold_eur`, `ai_confidence_threshold`, `sla_{critical,high,medium,low}_minutes`),
que ya existen con sus defaults del PRD §11. La cadencia del job nuevo entra en `CADENCES`.

**Contrato:** rutas de D14 en `backend/openapi.json` y en el `.d.ts` derivado.

## Risks & mitigations

- **Tocar `properties/domain/state_machine.py` desde `maintenance`.** Son dos cosas: una precondición
  (D9) y dos entradas de política (D8). DoD §28.19 exige que toda transición esté testeada, así que
  cada una entra con su test de aceptación y su test de rechazo. Mitiga que ninguno de los dos
  inventa criterio: D9 alinea el guard con lo que `state_resolution.py:118` ya hace, y D8 cierra dos
  asimetrías de la propia matriz.
- **Contexto incompleto en `after_incident_resolution`.** Es el riesgo funcional principal (D7): si
  falta cualquiera de las tres colecciones, el destino es plausible y equivocado, y no falla nada.
  Mitiga un test por rama del resolver (limpieza viva, reserva activa, próxima reserva hoy, próxima
  reserva futura, nada) conducido desde el caso de uso real, no desde el resolver.
- **El job de clasificación girando en vacío o pisando trabajo.** Lo acota D3 (el candidato deja de
  serlo en cuanto tiene `ai_classification`) y el lock por job que `celery-jobs` ya provee.

  **Se materializó, por una vía que este riesgo no anticipaba, y lo encontró la comprobación manual
  de la tarea 10.5 — no la suite.** `ai_classification` estaba declarada `JSONB` sin
  `none_as_null=True`, y SQLAlchemy convierte un `None` **asignado al atributo** en `'null'` de JSON
  en vez de en `NULL` de SQL. El escritor asigna todos los campos a propósito, así que toda
  incidencia creada por un llamante real quedaba con `'null'::jsonb` — y `IS NULL` no casa con eso.
  El job veía **cero** candidatos siempre, con la suite entera en verde: los fixtures construyen
  `IncidentModel(...)` sin nombrar la columna, así que a ellos les tocaba el default y sí era NULL.
  La lección es del tipo de test, no del job: **un fixture y el escritor real pueden discrepar sobre
  lo que llega a la base de datos**, y sólo un camino que use el escritor lo enseña. Los dos tests
  de regresión de `tests/maintenance/test_repositories.py` van por esa vía.
- **Un adaptador de IA real filtrando texto del huésped a `ai_summary`.** Es el riesgo que D4 cierra
  por contrato; el adaptador determinista lo cumple por construcción, pero el contrato tiene que
  estar escrito en `steering/security.md` **antes** de que llegue el proveedor real, no después.
- **Tests de aislamiento que no pueden fallar.** Riesgo conocido del proyecto: sobre sesión marcada
  el listener global filtra hasta el `select` de una columna. Los tests de la regla 1 corren sobre
  sesión sin marcar (D15).
- **Regenerar el contrato desde el worktree.** El comando documentado falla ahí; se usa la salida
  verificada de `sdd/project.md` y se comprueba con `api:check` dentro del contenedor.
- **`TECHNICIAN` sin usuarios en el entorno.** `app/cli/bootstrap.py` y el seed de PRD §27 deciden
  qué cuentas existen; si no hay ningún técnico, R3 no se puede ejercitar a mano. Los tests traen
  los suyos por fixture; el seed de demo es de `seed-data-demo-extension`, que declara
  `needs: maintenance` justamente por esto.

## Open questions

Ninguna abierta. Las cuatro que este diseño levantó se resolvieron en el gate de `/sdd:design`
(2026-08-15) y viven ya en la decisión que gobierna cada una, no aquí:

| Pregunta | Resuelta en | Decisión |
|---|---|---|
| Actor de la clasificación automática frente a R6.4 | **D6** | Se audita sin actor (`actor_user_id`/`actor_ip` a `NULL`), timeline con actor `AI`. Sin cuenta `SYSTEM` inventada |
| Los dos huecos de `_POLICY` | **D8** | Se añaden `VACANT_READY`+`INCIDENT_CRITICAL` y `CLEANING_SCHEDULED`+`INCIDENT_HIGH`, con sus tests de aceptación y de rechazo |
| `WAITING_EXTERNAL_PARTS` sin evento de timeline | **D10** | No se inventa un `TimelineEventType`; queda en `status` + `AuditLog` |
| Diagrama SVG del ciclo | — | No se genera: el diagrama de texto de *Data & interfaces* y la tabla de transiciones ya lo dicen, y ningún diagrama de `docs/diagrams/` queda obsoleto por este change |
