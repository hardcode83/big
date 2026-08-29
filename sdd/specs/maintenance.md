# Mantenimiento de incidencias

## Purpose

El módulo `maintenance` opera el ciclo de vida completo de una incidencia sobre una propiedad,
desde el `OPEN` que deja cualquier fuente hasta `RESOLVED` o `CANCELLED`: clasificación automática
por un puerto propio, aprobación de la propietaria cuando el gasto supera el umbral del tenant,
asignación a un técnico con su plazo de SLA, el ciclo de transiciones que conduce el técnico, y la
recomposición del estado operacional de la propiedad. Es el único escritor de mutaciones sobre
`incidents` y `owner_approvals`; la **creación** llega desde fuera, hoy por cuatro vías: la
anónima del portal del huésped ([`guest-portal-api.md`](guest-portal-api.md)), desde el 2026-08-16
una conversación cuyo intent es `MAINTENANCE_ISSUE` o `ACCESS_PROBLEM`
([`messaging-ai.md`](messaging-ai.md)), y desde el 2026-08-17 el alta **genérica** que abre
`ReportIncidentUseCase` ([`seed-data-demo.md`](seed-data-demo.md)).

## Requirements

### R1 — El estado de la incidencia y sus transiciones

- THE SYSTEM SHALL reconocer nueve estados de incidencia: `OPEN`, `CLASSIFIED`,
  `AWAITING_OWNER_APPROVAL`, `ASSIGNED`, `ACCEPTED`, `IN_PROGRESS`, `WAITING_EXTERNAL_PARTS`,
  `RESOLVED` y `CANCELLED`.
- THE SYSTEM SHALL tratar `RESOLVED` y `CANCELLED` como los **dos únicos** estados terminales, y
  esa terminalidad SHALL ser estructural: ninguna fila de la tabla de transiciones los admite como
  origen, de modo que no depende de una comprobación que alguien pueda olvidar.
- THE SYSTEM SHALL declarar las transiciones **por nombre de operación**, no por par
  (origen, destino), y SHALL admitir exactamente estas:

  | Operación | Orígenes admitidos | Destino |
  |---|---|---|
  | `classify` | `OPEN` | `CLASSIFIED` |
  | `require_owner_approval` | `CLASSIFIED`, `IN_PROGRESS` | `AWAITING_OWNER_APPROVAL` |
  | `resume_after_approval:INCIDENT` | `AWAITING_OWNER_APPROVAL` | `CLASSIFIED` |
  | `resume_after_approval:MAINTENANCE_COST` | `AWAITING_OWNER_APPROVAL` | `IN_PROGRESS` |
  | `assign` | `CLASSIFIED`, `ASSIGNED`, `ACCEPTED`, `IN_PROGRESS`, `WAITING_EXTERNAL_PARTS` | `ASSIGNED` |
  | `accept` | `ASSIGNED` | `ACCEPTED` |
  | `reject` | `ASSIGNED`, `ACCEPTED` | `CLASSIFIED` |
  | `en_route` | `ACCEPTED` | `IN_PROGRESS` |
  | `wait_for_parts` | `IN_PROGRESS` | `WAITING_EXTERNAL_PARTS` |
  | `resume_work` | `WAITING_EXTERNAL_PARTS` | `IN_PROGRESS` |
  | `resolve` | `IN_PROGRESS` | `RESOLVED` |
  | `cancel` | los siete no terminales | `CANCELLED` |

- IF la incidencia está en un estado terminal, THEN THE SYSTEM SHALL rechazar **toda** operación
  con `IncidentAlreadyClosedError`, y NEVER SHALL modificar nada.
- IF la incidencia está en `AWAITING_OWNER_APPROVAL` y la operación no es `cancel` ni una de las
  dos formas de `resume_after_approval`, THEN THE SYSTEM SHALL rechazarla con
  `IncidentBlockedByPendingApprovalError`: una incidencia parada esperando a la propietaria es un
  caso distinto de una transición fuera de orden, y el llamante puede distinguirlo.
- IF la operación está fuera de orden por cualquier otro motivo, THEN THE SYSTEM SHALL rechazarla
  con `InvalidIncidentTransitionError`.
- THE SYSTEM SHALL comprobar la transición **antes** de escribir ningún campo, de modo que una
  operación rechazada deje la incidencia exactamente como estaba.
- THE SYSTEM SHALL admitir la reasignación (`assign` desde `ASSIGNED`, `ACCEPTED`, `IN_PROGRESS` o
  `WAITING_EXTERNAL_PARTS`) devolviendo la incidencia a `ASSIGNED`.
- WHEN el técnico rechaza la incidencia (`reject`), THE SYSTEM SHALL limpiar los **tres** campos de
  la asignación vigente —`assigned_technician_id`, `eta_at` y `assignment_note`— y devolverla a
  `CLASSIFIED`, que es el origen desde el que `assign` reparte. Una incidencia `CLASSIFIED` con
  asignatario, con ETA o con la nota escrita para quien dijo que no sería una fila que miente; quién
  rechazó no se pierde, porque el `AuditLog` audita `assigned_technician_id` con su valor anterior y
  el evento de timeline lleva el identificador.

  > `ASSUMPTION`: el destino `CLASSIFIED` no lo dice el PRD. Se elige porque es el origen desde el
  > que `assign` reparte y porque no es terminal —lo terminal es `cancel`, que es del manager— y la
  > avería sigue ahí para que la arregle otra persona.

### R2 — Clasificación automática

- THE SYSTEM SHALL declarar en `maintenance` un puerto de clasificación propio, `IncidentClassifier`,
  con **un solo método** `async classify(*, title: str, description: str) -> IncidentClassification`,
  y NEVER SHALL colgar esta capacidad del adaptador de IA de `messaging-ai`.
- THE SYSTEM SHALL exigir que toda clasificación declare el **vocabulario cerrado** del que sale su
  resumen, y SHALL rechazar en construcción una clasificación con confianza fuera de `0..1`, con
  vocabulario vacío, o cuyo `summary` no pertenezca a ese vocabulario. Es la regla 11 de
  `steering/security.md` aplicada en el borde: el tipo no deja construir una clasificación que
  pudiera arrastrar texto reportado hasta `incidents.ai_summary`.
- WHEN se clasifica una incidencia `OPEN`, THE SYSTEM SHALL escribir `ai_classification` **siempre**,
  por encima y por debajo del umbral, con exactamente cinco claves cerradas: `category`, `severity`,
  `confidence`, `adapter` y `classified_at`. NEVER SHALL escribir en ellas texto de la incidencia.
- IF la confianza es **mayor o igual** que `TenantConfig.ai_confidence_threshold`, THEN THE SYSTEM
  SHALL fijar `category`, `severity` y `ai_summary` y pasar la incidencia a `CLASSIFIED`.
- IF la confianza es **estrictamente menor** que el umbral, THEN THE SYSTEM SHALL dejar la
  incidencia en `OPEN` con `category` y `severity` en sus valores por defecto, quedando pendiente de
  triaje humano y distinguible de una ya clasificada.
- THE SYSTEM NEVER SHALL dejar que el clasificador escriba `title` ni `description`.
- WHEN el resumen propuesto comparta **ocho caracteres seguidos** (sin distinguir mayúsculas) con el
  título o la descripción, THE SYSTEM SHALL descartar el resumen dejando `ai_summary` a `NULL`, y
  SHALL aplicar igualmente categoría, severidad y la transición. Un vocabulario cerrado no basta si
  el adaptador puede elegir de él una frase que devuelva lo reportado.
- IF el adaptador de clasificación falla, THEN THE SYSTEM SHALL dejar la incidencia intacta y sin
  confirmar la transacción, registrando `maintenance.classification_failed` con `tenant_id`,
  `incident_id` y el tipo de error, y nunca el texto; la incidencia SHALL volver a entrar en el
  siguiente ciclo, porque no se escribió `ai_classification`.
- THE SYSTEM SHALL entregar un adaptador determinista de desarrollo,
  `RuleBasedIncidentClassifier`, sin estado, sin E/S y sin aleatoriedad: normaliza acentos y
  mayúsculas, casa palabras completas en español e inglés contra una tabla de doce categorías, y
  deriva la confianza del número de aciertos (0 → `0.30`, 1 → `0.80`, ≥2 → `0.95`). La severidad
  sale de una tabla por categoría, nunca de la palabra que casó.
- WHERE el texto no casa ninguna palabra clave, THE SYSTEM SHALL devolver `OTHER` con confianza
  `0.30`, deliberadamente por debajo del umbral por defecto (`0.75`), de modo que lo desconocido
  caiga en triaje humano en lugar de clasificarse mal.

### R3 — El job de clasificación

- THE SYSTEM SHALL ejecutar la clasificación en un job periódico, `classify_incidents`, **cada 5
  minutos**, y NEVER SHALL clasificar dentro de la **petición** que crea la incidencia. Las vías
  que crean incidencias por HTTP son tres: una ruta **anónima desde internet**, un pipeline
  disparado por un webhook, y —desde `cleaner-incident-report`— el alta **autenticada** de la
  limpiadora sobre su propia tarea ([`cleaner-incident-report.md`](cleaner-incident-report.md)).
  Colgar de cualquiera de ellas la llamada al clasificador es lo que prohíbe la regla 12(d) de
  `steering/security.md`, y la tercera no debilita ese argumento: lo que la regla acota es el
  trabajo que un desconocido provoca desde fuera, y las dos primeras siguen siendo la razón por la
  que la clasificación no puede vivir en la petición.
- WHERE la creación no viene de una petición sino de un comando que una persona ejecuta —hoy sólo
  `make seed-demo`—, THE SYSTEM SHALL permitir clasificar en la misma transacción que crea la
  incidencia. Lo que la regla 12(d) acota es el trabajo que un desconocido puede provocar desde
  fuera; un CLI no es esa superficie. La consecuencia buscada es un dataset **estable**: una
  incidencia sembrada en `OPEN` con `ai_classification` a `NULL` la movería el job en su siguiente
  tick, y un dataset que cambia solo no es un dataset.
- THE SYSTEM SHALL seleccionar exactamente las incidencias `OPEN` **y con `ai_classification` a
  `NULL`**, por tenant activo, ordenadas por antigüedad y acotadas por `notification_batch_size`.
  Ese par de condiciones da las dos propiedades que el flujo necesita: una incidencia cuyo adaptador
  falló vuelve a entrar, y una de baja confianza no vuelve —un adaptador determinista respondería lo
  mismo para siempre y el job giraría en vacío.
- THE SYSTEM SHALL tomar un único cerrojo por tarea y ejecutar cada tenant en su propia transacción,
  de modo que un tenant que falle no arrastre a los demás.
- THE SYSTEM SHALL informar por tenant `considered`, `classified`, `low_confidence` y `failed`, en
  cuentas y NEVER SHALL registrar identificadores de incidencia en ese informe.

### R4 — Aprobación de la propietaria: dos puertas

- WHEN el triaje fija un `estimated_cost` **estrictamente mayor** que
  `TenantConfig.owner_approval_threshold_eur` y no cubierto por una aprobación previa, THE SYSTEM
  SHALL crear un `OwnerApproval` `PENDING` con `related_type = INCIDENT`, marcar
  `owner_approval_required` y pasar la incidencia a `AWAITING_OWNER_APPROVAL`.
- WHEN el técnico cierra con un `final_cost` que supera el umbral y **no está cubierto** por
  `approved_cost`, THE SYSTEM SHALL crear un `OwnerApproval` con
  `related_type = MAINTENANCE_COST`, escribir `final_cost`, pasar a `AWAITING_OWNER_APPROVAL` y
  NEVER SHALL resolver la incidencia ni escribir `resolved_at`. Sin esta segunda puerta, estimar 90
  EUR y gastar 500 evitaría la regla de aprobación entera.
- THE SYSTEM SHALL considerar un coste **cubierto** sólo si `approved_cost` existe y es **mayor o
  igual** que el coste final: una aprobación de 450 EUR no estira para una factura de 500 EUR.
- IF el coste es igual o menor que el umbral, o no hay coste, THEN THE SYSTEM SHALL continuar sin
  crear aprobación alguna. El umbral se compara con **mayor estricto**.
- WHEN se abre una aprobación, THE SYSTEM SHALL notificar a la propietaria por el
  `NotificationAdapter` existente dejando su `NotificationLog`; IF el tenant no tiene ninguna
  `TENANT_OWNER` activa, THEN SHALL registrar `maintenance.owner_approval_without_recipient` y
  continuar sin fallar — la incidencia no se pierde por no haber a quién avisar.
- THE SYSTEM SHALL componer el `reason` de la aprobación como una **constante más el id** de la
  incidencia, y NEVER SHALL copiar en él el texto reportado.
- WHEN la propietaria responde, THE SYSTEM SHALL registrar `status`, `responded_at`, `responded_by`
  y `response_notes`.
- IF la respuesta es `APPROVED`, THEN THE SYSTEM SHALL fijar `approved_cost` con el importe de la
  aprobación y devolver la incidencia al punto que marca su `related_type`: `INCIDENT` vuelve a
  `CLASSIFIED` y `MAINTENANCE_COST` vuelve a `IN_PROGRESS`. Aprobar el coste real **no** cierra la
  incidencia: la devuelve al técnico para que repita el cierre, porque cerrarla por él haría que
  `resolved_at` dejara de significar «lo dio por terminado».
- IF la respuesta es `REJECTED`, THEN THE SYSTEM SHALL pasar la incidencia a `CANCELLED` y
  recomponer el estado de la propiedad (`ASSUMPTION`: PRD §12 describe la espera y no dice qué pasa
  al rechazar).
- THE SYSTEM NEVER SHALL permitir responder una aprobación a un rol distinto de `TENANT_OWNER`, ni
  responder dos veces la misma, ni responder una de otro tenant. La segunda respuesta SHALL fallar
  con `OwnerApprovalAlreadyAnsweredError` comprobando que el estado sigue siendo `PENDING`, no que
  `responded_at` esté vacío.
- THE SYSTEM SHALL admitir como respuesta únicamente `APPROVED` y `REJECTED`. `PENDING` y `EXPIRED`
  NEVER SHALL ser respuestas válidas; ningún camino de código escribe `EXPIRED`, y la expiración
  automática queda fuera de esta capability.

### R5 — Asignación y plazo de SLA

- WHEN un manager asigna la incidencia, THE SYSTEM SHALL fijar `assigned_technician_id`, pasar a
  `ASSIGNED` y notificar al técnico con `TECHNICIAN_ASSIGNED`.
- THE SYSTEM SHALL aceptar en el cuerpo de `assign` un `assignment_note` **opcional** acotado a 2000
  caracteres —la nota que el manager le deja al técnico— y SHALL escribirlo **siempre**, de modo que
  reasignar sin nota borra la anterior: pertenece a la asignación vigente y no a la incidencia. El
  permiso, la tabla de transiciones y el `extra="forbid"` del cuerpo no cambian por ella, y la nota
  NEVER SHALL aparecer en `IncidentResponse`. La sirve
  [`tech-incident-context`](tech-incident-context.md), que es también donde vive el resto de su
  contrato.
- THE SYSTEM NEVER SHALL aceptar como asignatario un usuario que no sea `TECHNICIAN` **y** esté
  `ACTIVE` en el tenant del solicitante; el rechazo SHALL ser `InvalidTechnicianError`.
- THE SYSTEM SHALL derivar el plazo de la severidad —`sla_critical_minutes`, `sla_high_minutes`,
  `sla_medium_minutes`, `sla_low_minutes` de `TenantConfig`— y SHALL registrarlo como
  `sla_deadline_at` **sobre la maquinaria de SLA que ya existe** en `notifications`
  (`list_sla_breach_candidates`, `mark_breached`, `cancel_sla_deadline`), sin construir una segunda.
- WHEN el técnico acepta, THE SYSTEM SHALL cancelar el plazo pendiente.
- WHEN el técnico rechaza, THE SYSTEM SHALL cancelar igualmente el plazo pendiente de la
  notificación `TECHNICIAN_ASSIGNED` de esa incidencia: un rechazo **es** una respuesta, así que
  nadie llega tarde.
- WHEN se reasigna una incidencia que ya tenía asignatario, THE SYSTEM SHALL cancelar el plazo del
  anterior antes de abrir el del nuevo.
- WHEN un manager (re)asigna la incidencia, THE SYSTEM SHALL poner `eta_at` a `NULL` sin
  condiciones, por el mismo motivo que reescribe `assignment_note`: la ETA pertenece a la
  **asignación vigente**, no a la incidencia, y el técnico B no hereda la hora que prometió el A.
- WHEN el técnico rechaza, THE SYSTEM SHALL notificar al `PROPERTY_MANAGER` del tenant dejando su
  `NotificationLog` con `notification_type = "INCIDENT_REJECTED"`, y esa notificación NEVER SHALL
  llevar `sla_deadline_at`: no hay plazo que reclamar contra una respuesta ya dada, y el tipo no
  tiene política de escalado, así que un plazo aquí produciría un incumplimiento que no escala a
  nadie. Su asunto y su cuerpo SHALL ser constante más identificadores, sin leer `title`,
  `description`, `ai_summary` ni la nota de asignación.
- IF el tenant no tiene ningún `PROPERTY_MANAGER` activo, THEN THE SYSTEM SHALL registrar el hecho
  y continuar sin fallar, dejando el rechazo aplicado — el mismo criterio que R4 aplica a la
  aprobación sin destinatario.
- THE SYSTEM SHALL apuntar `related_id` de estas notificaciones a la **incidencia**, no a la
  aprobación, con `related_type = "incident"`.
- THE SYSTEM SHALL dejar la notificación de aprobación **sin** `sla_deadline_at`: no hay plazo que
  reclamarle a una propietaria, y en consecuencia `OWNER_APPROVAL_REQUIRED` no tiene política de
  escalado.

### R6 — El ciclo del técnico

- THE SYSTEM SHALL permitir al técnico asignado las transiciones `ASSIGNED → ACCEPTED`,
  `ASSIGNED`/`ACCEPTED → CLASSIFIED` (el rechazo de R1), `ACCEPTED → IN_PROGRESS` (`en_route`),
  `IN_PROGRESS → WAITING_EXTERNAL_PARTS`, `WAITING_EXTERNAL_PARTS → IN_PROGRESS` e
  `IN_PROGRESS → RESOLVED`.
- WHEN el técnico se pone en ruta, THE SYSTEM SHALL escribir el evento de timeline
  `TECHNICIAN_EN_ROUTE`. La operación se llama `en_route`: conserva exactamente los orígenes
  (`ACCEPTED`) y el destino (`IN_PROGRESS`) que tenía cuando se llamaba `start`, y es el movimiento
  que PRD §12 dibuja literalmente como «Técnico en ruta → status IN_PROGRESS».
- THE SYSTEM SHALL conservar `resume_work` (`WAITING_EXTERNAL_PARTS → IN_PROGRESS`) escribiendo
  `TECHNICIAN_STARTED`, de modo que ese miembro del vocabulario sigue teniendo escritor y no hay
  nada que retirar del enum ni del tipo `timeline_event_type` de PostgreSQL.
- THE SYSTEM SHALL aceptar un `eta_at` **opcional** en el cuerpo de `accept` y en el de `en_route`,
  y NEVER SHALL aceptarlo en ninguna otra operación del módulo. WHEN el cuerpo trae un `eta_at`,
  THE SYSTEM SHALL escribirlo sustituyendo al anterior; IF el cuerpo no lo trae, THEN SHALL dejar
  el valor anterior intacto — no hay distinción «ausente contra nulo explícito» que hacer.
- IF el `eta_at` recibido es **estrictamente anterior** al instante de la petición, o llega sin
  `tzinfo` utilizable, THEN THE SYSTEM SHALL rechazarlo con `MaintenanceValidationError` y NEVER
  SHALL escribir nada. El instante límite exacto pasa. La comprobación de zona no es adorno:
  comparar un `now` con offset contra un valor ingenuo levanta `TypeError`, que saldría por la API
  como un `500` sin declarar.
- THE SYSTEM SHALL validar la transición **antes** de la ETA y la ETA **antes** de mover el estado,
  de modo que una operación fuera de orden y una ETA inválida dejen la incidencia intacta por igual.
- WHEN el técnico resuelve, THE SYSTEM SHALL exigir `final_cost`, y —salvo que se abra la segunda
  puerta de aprobación— fijar `resolved_at` y pasar a `RESOLVED`.
- THE SYSTEM SHALL aceptar en el cuerpo de `resolve` un `materials` **opcional** —el texto con que
  el técnico declara qué piezas puso— acotado a 2000 caracteres en el DDL **y** en el esquema de
  petición, con recorte de espacios y sin admitir la cadena vacía. WHEN el cuerpo lo trae, THE
  SYSTEM SHALL escribirlo; IF no lo trae, THEN SHALL preservar el valor anterior.
- THE SYSTEM SHALL escribir `materials` **también** cuando el cierre abra la segunda puerta de
  aprobación de R4: leerlo como «operación completa» borraría en silencio la descripción de un gasto
  precisamente cuando el importe supera el umbral, y obligaría al técnico a teclearla dos veces.
- THE SYSTEM NEVER SHALL derivar `final_cost` de `materials` ni validar el uno contra el otro:
  `final_cost` sigue siendo el único número y las dos puertas de aprobación no cambian por ello.
- THE SYSTEM SHALL rechazar todo coste negativo con `MaintenanceValidationError`.
- THE SYSTEM SHALL permitir también a `PROPERTY_MANAGER` conducir estas transiciones, para
  desatascar; es la única diferencia con limpieza, donde ejecutar es sólo de la limpiadora.
- THE SYSTEM NEVER SHALL permitir conducirlas a un técnico que no sea el asignado, y esa negativa
  SHALL ser indistinguible de «no existe» (ver R8).
- **Quién llama a `resolve` desde la web**: la sección de desajustes de la card del dashboard lo
  ofrece al `PROPERTY_MANAGER` cuando la incidencia es lo que bloquea el check-in; esa pantalla no
  asume que la incidencia acabe en `RESOLVED`, porque la segunda puerta de R4 puede llevarla a
  `AWAITING_OWNER_APPROVAL`. Su comportamiento vive en
  [`dashboard-web-frontend.md`](dashboard-web-frontend.md) §Blocked transitions on the card.

### R7 — Recomposición del estado de la propiedad

- WHEN una clasificación termina en `CLASSIFIED` con severidad `HIGH` o `CRITICAL`, THE SYSTEM SHALL
  disparar `INCIDENT_HIGH` o `INCIDENT_CRITICAL`; con severidad `MEDIUM` o `LOW` NEVER SHALL
  disparar nada.
- WHEN la incidencia se resuelve limpiamente, se cancela, o la propietaria rechaza el gasto, THE
  SYSTEM SHALL disparar `INCIDENT_RESOLVED`.
- THE SYSTEM SHALL recalcular el estado operacional **a través de `PropertyStateMachine`**, y NEVER
  SHALL escribir `current_operational_state` directamente
  ([`timeline-state-machine.md`](timeline-state-machine.md)).
- THE SYSTEM NEVER SHALL disparar nada al triar, asignar, aceptar, empezar, esperar piezas,
  reanudar, ni al abrir cualquiera de las dos puertas de aprobación, ni al aprobarla.
- IF la máquina rechaza la transición por no haber cambio de estado o por no existir fila de
  política —por ejemplo con la propiedad en `BLOCKED_BY_OWNER` u `OUT_OF_SERVICE`—, THEN THE SYSTEM
  SHALL registrar `maintenance.transition_refused` y **mantener el cambio de la incidencia**: la
  incidencia avanza aunque la propiedad no se mueva.
- IF el contexto entregado a la máquina es incompatible, THEN THE SYSTEM SHALL dejar propagar el
  error en lugar de tragárselo: es un defecto de programación, no un estado del negocio.

### R8 — API del módulo, permisos y aislamiento

- THE SYSTEM SHALL exponer dieciséis rutas autenticadas, todas con permiso declarado: quince
  bajo `/api/v1/incidents` (`GET` de listado, `GET` de detalle, `GET` de contexto operativo, `GET` y
  `POST` de fotos, `PATCH`
  de triaje y los `POST` de `classify`, `assign`, `accept`, `reject`, `en-route`, `wait-parts`,
  `resume`, `resolve` y `cancel`) y `POST /api/v1/owner-approvals/{approval_id}/respond`.
- THE SYSTEM SHALL exponer además **una** ruta **anónima** del módulo,
  `GET /api/v1/incident-photos/{photo_id}`, que sirve los bytes de una foto contra su firma HMAC
  porque un `<img src>` no puede mandar `Authorization`. Es la única del módulo sin permiso, cuelga
  de un router propio y no de `incidents_router`, y su capability tiene spec propia
  ([`incident-photos`](incident-photos.md)). Lo que le toca a este módulo es que la ruta existe por
  diff visible en el censo de `ANONYMOUS_ENDPOINTS` y no por descuido.
- THE SYSTEM SHALL exponer el rechazo en `POST /api/v1/incidents/{incident_id}/reject`, bajo
  `EXECUTE_INCIDENTS`, y SHALL permitirlo al técnico asignado y al `PROPERTY_MANAGER`, igual que el
  resto del ciclo. THE SYSTEM NEVER SHALL permitir rechazar a un técnico que no sea el asignado, y
  esa negativa SHALL ser indistinguible de «no existe»: el mismo `404` con el mismo cuerpo que para
  una incidencia inexistente o de otro tenant.
- THE SYSTEM SHALL exponer «en ruta» en `POST /api/v1/incidents/{incident_id}/en-route`, y
  `POST /api/v1/incidents/{incident_id}/start` NEVER SHALL existir en el contrato publicado: la
  operación se renombró, no se duplicó.
- THE SYSTEM SHALL compartir **un solo** esquema de petición entre `accept` y `en-route` —el cuerpo
  es opcional y su único campo es `eta_at`—, de modo que el «en ninguna otra ruta» de la ETA no viva
  en dos sitios que puedan divergir; y SHALL mantener el `extra="forbid"` del módulo en los tres
  cuerpos que este ciclo toca.
- THE SYSTEM SHALL servir el contexto operativo de una incidencia —a qué propiedad va el técnico y
  cómo entra— en `GET /api/v1/incidents/{incident_id}/context`, bajo `READ_INCIDENTS` y con el mismo
  acotamiento por fila que el resto del módulo. Es una capacidad con su propia spec
  ([`tech-incident-context`](tech-incident-context.md)) y no se reenuncia aquí: lo que le toca a este
  módulo es que **no creó permiso nuevo**, que no ensanchó ninguna fila alcanzable, y que
  `IncidentResponse` **no** cambió por su causa.
- THE SYSTEM SHALL servir la **evidencia fotográfica** del trabajo del técnico en
  `POST` y `GET /api/v1/incidents/{incident_id}/photos` —subir bajo `EXECUTE_INCIDENTS`, listar bajo
  `READ_INCIDENTS`—, con el mismo acotamiento por fila que el resto del módulo. Es una capacidad con
  su propia spec ([`incident-photos`](incident-photos.md)) y no se reenuncia aquí: lo que le toca a
  este módulo es que **no creó permiso nuevo** —`ROLE_PERMISSIONS` no se tocó—, que no ensanchó
  ninguna fila alcanzable, que `IncidentResponse` **no** cambió por su causa, y que la subida sólo
  se admite con la incidencia en `IN_PROGRESS` o `WAITING_EXTERNAL_PARTS`, con las **tres** negativas
  de R1 reutilizadas tal cual (`409`, tres mensajes distinguibles) y sin fila nueva en
  `_TRANSITIONS`, porque subir una foto no mueve el estado.
- THE SYSTEM SHALL entender que la negativa de creación de arriba **no la toca** la aparición de esas
  rutas: crean **fotos**, no incidencias. Las superficies que crean incidencias siguen siendo cuatro.
- THE SYSTEM NEVER SHALL exponer una ruta de **creación** de incidencias en este módulo, y esa
  negativa SHALL sobrevivir a la aparición de un alta genérica: `ReportIncidentUseCase` es un caso
  de uso, no una ruta. Las superficies que crean incidencias son cuatro: la anónima del portal del
  huésped, el pipeline de mensajería, el comando `make seed-demo` y el alta de la limpiadora desde
  su propia tarea, que vive **bajo `cleaning`** y no aquí
  ([`cleaner-incident-report.md`](cleaner-incident-report.md)).

**El alta genérica, y la precondición que tiene que descargar ella misma.** Desde el 2026-08-17
`maintenance` ofrece `ReportIncidentUseCase` —`tenant_id`, `property_id`, `source`, `title`,
`description`, `actor`, `now`— junto al `ReportGuestIncidentUseCase` que ya existía. Hace falta
porque el que existía **no puede** crear cualquier incidencia: fija `source=GUEST` y exige
`reservation_id` y `reporter_token_hash`.

- THE SYSTEM SHALL resolver `property_id` **dentro del tenant** antes de escribir nada, rechazando
  con `MaintenanceValidationError` la propiedad que no sea suya. No es defensa en profundidad: las
  claves ajenas de `incidents` son globales y no compuestas con `tenant_id`, así que la base de
  datos aceptaría una incidencia del tenant A colgada de una propiedad del tenant B, y el puerto
  declara esa precondición como algo que **no puede detectar**. El creador del portal la satisface
  *estructuralmente* —sus identificadores salen de la sesión que resolvió el token— y un caso de uso
  abierto a cualquier llamante no tiene nada equivalente.
- THE SYSTEM SHALL exigir actor: el alta no está en el conjunto de acciones que `_AuditWriter`
  exime, así que una creación sin actor se rechaza y no commitea nada.
- THE SYSTEM SHALL NOT aceptar `reservation_id`. Se diseñó y se quitó junto a
  `reported_by_user_id`: arrastraban la misma precondición sin descargar y ninguno tenía llamante.
  La regla que quedó es que quien traiga uno añade el parámetro **junto con** la búsqueda que lo
  hace seguro.
- THE SYSTEM SHALL aceptar `reported_by_user_id` y `cleaning_task_id`, ambos **opcionales** y por
  palabra clave, de modo que ningún llamante existente cambie. Los trajo
  [`cleaner-incident-report`](cleaner-incident-report.md) honrando esa regla y no derogándola: el
  primero viene del token ya verificado, y el segundo de una tarea de limpieza que el llamante
  cargó con `tenant_id` explícito. THE SYSTEM NEVER SHALL derivar uno del otro — «quién reportó» y
  «quién actúa» son dos conceptos, y colapsarlos cambiaría en silencio lo que escribe
  `app/cli/seed_demo.py`.
- THE SYSTEM SHALL admitir cualquier miembro de `IncidentSource`, sin filtro, y SHALL dejar la
  incidencia en `OPEN` sin fijar `category`, `severity` ni `ai_classification` — que es lo que
  mantiene a `classify` como única puerta de salida de `OPEN` (R1).
- THE SYSTEM SHALL escribir la entidad, su `AuditLog` (`INCIDENT_CREATED`) y su `TimelineEvent`
  (`INCIDENT_CREATED`, actor `USER`) en la misma transacción, con un título de timeline constante y
  metadatos que son **sólo identificadores**: ningún texto de quien reporta viaja al timeline.
- THE SYSTEM SHALL aceptar `title` y `description` como `str` sin restringir, y esa apertura SHALL
  entenderse como lo que es: la forma cerrada que la regla 11 de `steering/security.md` exige de un
  escritor nuestro es **disciplina del llamante**, no un invariante del caso de uso. Quien componga
  ahí prosa propia en vez de pasar una constante necesita su propia fila en el censo de sumideros.
  El guardián automático de ese censo vigila desde entonces a quien nombre `ReportIncidentUseCase`
  o el puerto `IncidentRepository`, precisamente porque el primer llamante nuevo vivía fuera de
  `maintenance/` y el censo no se enteró solo.
- WHERE una conversación produce una incidencia, THE SYSTEM SHALL suministrar el implementador
  (`ReportIncidentFromConversationUseCase`) de un puerto que declara `messaging` —nunca al revés—,
  y ese implementador SHALL recibir una `CallerOwnedUnitOfWork` y NEVER SHALL comitear: el único
  commit sigue siendo el del pipeline que la abrió.
- WHERE la incidencia nace de una conversación, THE SYSTEM SHALL crearla `OPEN` con
  `ai_classification` sin fijar, de modo que la recoja el job de R3 en su siguiente tick, y NEVER
  SHALL clasificarla en la misma petición. `title` sale de un catálogo cerrado de constantes y
  `description` es el mensaje del huésped literal.
- THE SYSTEM SHALL conceder cuatro permisos —`READ_INCIDENTS`, `MANAGE_INCIDENTS`,
  `EXECUTE_INCIDENTS`, `RESPOND_OWNER_APPROVALS`— repartidos así:

  | Rol | Puede |
  |---|---|
  | `TENANT_OWNER` | leer incidencias **y las fotos de sus incidencias**; responder aprobaciones |
  | `PROPERTY_MANAGER` | leer, clasificar, triar, asignar, cancelar **y** todo el ciclo del técnico, **fotos incluidas** |
  | `TECHNICIAN` | leer y ejecutar el ciclo (aceptar, empezar, esperar piezas, reanudar, resolver) y **subir y ver las fotos** de las suyas |
  | `CLEANER` | abrir una incidencia desde una tarea de limpieza suya, y nada más — y esa alta vive **bajo `cleaning`** ([`cleaner-incident-report.md`](cleaner-incident-report.md)), no en este módulo |
  | `SUPER_ADMIN` | nada de este módulo |

- THE SYSTEM SHALL conceder a `TECHNICIAN` exactamente lo que R5 y R6 necesitan y nada más: su
  conjunto completo es autoservicio (`READ_OWN_PROFILE`, `MANAGE_OWN_SESSION`,
  `READ_OWN_NOTIFICATIONS`) más `READ_INCIDENTS` y `EXECUTE_INCIDENTS`. NEVER SHALL poder clasificar,
  triar, asignar, cancelar ni responder aprobaciones. Las fotos de la incidencia viajan **sobre esos
  dos mismos permisos** y no ampliaron el conjunto: subir es `EXECUTE_INCIDENTS`, listar es
  `READ_INCIDENTS`.
- WHERE el solicitante es `TECHNICIAN`, THE SYSTEM SHALL devolver **sólo** las incidencias que tiene
  asignadas, derivando la restricción del **rol del token** y NEVER SHALL aceptarla ni ensancharla
  desde la petición: no existe parámetro `assigned_technician_id` en la ruta, y el filtro se
  sobrescribe en lugar de rellenarse por defecto.
- THE SYSTEM SHALL responder el **mismo `404` con el mismo cuerpo** para una incidencia inexistente,
  una de otro tenant y una asignada a otro técnico, de modo que la ruta no sirva de sonda de
  existencia.
- THE SYSTEM SHALL tomar el `tenant_id` únicamente del token verificado, SHALL pasarlo explícito a
  cada método de repositorio, y NEVER SHALL aceptarlo en ningún esquema de petición.
- THE SYSTEM NEVER SHALL exponer **las quince rutas de `/api/v1/incidents`** al rol `CLEANER` ni al
  portador de un token de huésped: leer, listar, clasificar, triar, asignar, cancelar, el ciclo
  del técnico y sus fotos siguen cerrados a los dos. Lo único que una `CLEANER` puede hacer con una incidencia
  es abrirla desde su propia tarea de limpieza, y esa ruta pertenece a otro módulo
  ([`cleaner-incident-report.md`](cleaner-incident-report.md)).
- THE SYSTEM SHALL paginar el listado con `?page&per_page` (por defecto 1 y 20, máximos 100.000 y
  100) y devolver `items`, `total`, `page` y `per_page`, y SHALL admitir los filtros `property_id`,
  `status` y `severity`, combinados con `AND`.
- THE SYSTEM SHALL responder los errores con el envoltorio `{error:{code,message,details}}` de PRD
  §23, mapeando: `404 NOT_FOUND` para incidencia o aprobación no encontradas; `409 CONFLICT` para
  transición inválida, incidencia cerrada, incidencia bloqueada por aprobación y aprobación ya
  respondida; `422 VALIDATION_ERROR` para invariantes de dominio y técnico inválido; `403 FORBIDDEN`
  para rol sin permiso; y `500 INTERNAL_ERROR` con mensaje constante para cualquier error del módulo
  sin mapear.
- THE SYSTEM SHALL rechazar campos desconocidos en todos los cuerpos de petición.
- THE SYSTEM NEVER SHALL incluir en la respuesta de incidencia `reported_by_guest_token`,
  `reported_by_user_id` ni `ai_classification`.
- THE SYSTEM SHALL regenerar y commitear `backend/openapi.json` y
  `frontend/lib/api/generated/openapi.d.ts` en el mismo PR
  ([`api-contract.md`](api-contract.md), `steering/documentation.md`).

### R9 — Auditoría y timeline

- WHEN cambia el estado de una incidencia o se responde una aprobación, THE SYSTEM SHALL escribir su
  `AuditLog` y su `TimelineEvent` **en la misma transacción** que el cambio.
- THE SYSTEM SHALL auditar sobre `INCIDENT` exactamente trece campos: `source`, `status`,
  `reservation_id`, `cleaning_task_id`, `category`, `severity`, `assigned_technician_id`,
  `owner_approval_required`, `estimated_cost`, `approved_cost` y `final_cost`, más `resolved_at` y
  `eta_at`. `eta_at` entra por el mismo criterio que `resolved_at`: es una marca de tiempo, no texto
  libre, así que la excepción 2 de la regla 11 no se toca.
  `cleaning_task_id` entró con [`cleaner-incident-report`](cleaner-incident-report.md): la fila de
  auditoría registra contra qué está anclada la incidencia —para eso está `reservation_id`— y
  «durante qué limpieza» es el ancla equivalente. Es un identificador y no texto, así que la
  excepción 2 de la regla 11 no se toca.
- THE SYSTEM NEVER SHALL auditar `title`, `description`, `ai_summary`, `ai_classification`,
  `assignment_note` ni `materials`, y esa exclusión SHALL ser **estructural**: nombrar cualquiera de
  los seis en un `ChangeSet` levanta `AuditContractError`, en las dos formas —`diff()` y
  `redacted()`—, por no ser campo declarado de la entidad. Los dos primeros son texto libre de origen externo sobre una tabla
  append-only; los dos siguientes son los sumideros que R2 acota; el último es la nota de la
  asignación, que además SHALL quedar **fuera de `REDACTED_FIELDS`** de forma deliberada —denylistar
  obligaría a añadirla al allowlist, que es estrictamente más superficie— y cuyo texto NEVER SHALL
  viajar al `metadata` del `TimelineEvent` de la asignación, que lleva solo `incident_id` y
  `technician_id`. `materials` lleva ese mismo contrato calcado: fuera de los campos auditables,
  fuera de `REDACTED_FIELDS`, y su texto NEVER SHALL viajar al `metadata` del `TimelineEvent` de la
  resolución.
- THE SYSTEM SHALL auditar sobre `OWNER_APPROVAL` exactamente cinco campos: `status`, `amount`,
  `related_type`, `responded_by` y `responded_at`, y NEVER SHALL auditar `reason` ni
  `response_notes`.
- THE SYSTEM SHALL auditar sobre `INCIDENT_PHOTO` exactamente tres campos —`stage`, `incident_id` y
  `uploaded_by`—, contra la **propia foto** como entidad y no contra la incidencia, y NEVER SHALL
  auditar `storage_key`. Es la **tercera** entidad auditable de este módulo, y su detalle vive en
  [`incident-photos`](incident-photos.md); lo que le toca a R9 es que la subida **no** escribe
  `TimelineEvent`, por el mismo motivo por el que no lo escribe esperar piezas: el vocabulario de
  PRD §10 no tiene un tipo para ella.
- THE SYSTEM SHALL nombrar como actor al usuario que ejecuta la transición, y NEVER SHALL escribir
  una fila que reclame a la vez un usuario y un portador de token.
- WHERE la clasificación la dispara el job **o el comando de seed**, THE SYSTEM SHALL escribir la
  fila **sin actor** (`actor_user_id` y `actor_ip` a `NULL`) y con actor `AI` en el timeline: la
  categoría y la severidad las pone el clasificador sobre un texto que ya estaba escrito, así que
  no hay decisión humana que registrar. `INCIDENT_CLASSIFIED` SHALL ser la **única** acción de este
  módulo que admite actor ausente; cualquier otra sin actor SHALL fallar, incluida el alta genérica.
  Lo que concede la excepción es la ausencia de **decisión**, no la de petición: una clasificación
  manual por `POST /incidents/{id}/classify` lleva su actor aunque la lance un operador, y ningún
  otro comando queda eximido por ser un comando.
- WHEN se crea una incidencia por el alta genérica, THE SYSTEM SHALL escribir su `AuditLog`
  `INCIDENT_CREATED` con un `ChangeSet` que sólo difiere `source` y `status`, y su `TimelineEvent`
  `INCIDENT_CREATED` con actor `USER`, título constante y metadatos sólo con identificadores.
- THE SYSTEM SHALL escribir en el timeline `INCIDENT_CLASSIFIED`, `OWNER_APPROVAL_REQUIRED`,
  `OWNER_APPROVED_EXPENSE`, `OWNER_REJECTED_EXPENSE`, `TECHNICIAN_ASSIGNED`, `TECHNICIAN_ACCEPTED`,
  `TECHNICIAN_REJECTED`, `TECHNICIAN_EN_ROUTE`, `TECHNICIAN_STARTED`, `INCIDENT_RESOLVED` e
  `INCIDENT_CANCELLED`, con **título constante** y `metadata` sólo con identificadores.
  `TECHNICIAN_REJECTED` lo añadió este ciclo al vocabulario de `TimelineEventType`, con el precedente
  de `GUEST_CHECKIN_COMPLETED`, que [`guest-portal-api`](guest-portal-api.md) ya había añadido fuera
  de la lista de PRD §7.8.
- WHEN se rechaza una incidencia o se escribe un `eta_at`, THE SYSTEM SHALL escribir su `AuditLog` y
  su `TimelineEvent` en la misma transacción que el cambio, nombrando como actor al usuario que
  ejecuta la operación.
- THE SYSTEM NEVER SHALL escribir evento de timeline al esperar piezas: el vocabulario de PRD §10 no
  tiene un tipo para ello y el hito ya lo cuenta el `status` de la incidencia. Es una decisión, no
  un olvido; el coste asumido es que el timeline no explica por sí solo por qué una incidencia lleva
  días abierta.

## Estado

- **Sin `AuditLog` para la transición de estado de la propiedad.** Las transiciones que dispara este
  módulo llevan actor `USER` y no escriben esa fila, mientras la regla 9 de `steering/security.md`
  sólo exime las de actor `SYSTEM`. No se cerró aquí porque el hueco es compartido: `properties`
  decidió lo contrario para *todos* los actores y lo dejó escrito en un test
  (`test_the_operational_state_is_not_an_auditable_property_field`), y `cleaning` tiene el mismo
  hueco. Cerrarlo sólo aquí dejaría un rastro incoherente. Candidato con nombre propuesto:
  `property-transition-audit`.
- **El aislamiento por tenant está implementado y verificado ruta por ruta, pero demostrado en dos
  de sus tres puertas.** El detalle, el contexto operativo y las nueve transiciones comparten hoy una
  única función —`_load_incident_in_scope`, una corrutina de módulo que
  [`tech-incident-context`](tech-incident-context.md) extrajo cuando la regla estaba escrita dos
  veces y añadir una tercera copia era la alternativa—; la tercera puerta
  —`RespondOwnerApprovalUseCase`— sigue resolviendo por su propio par de consultas y ningún test
  falla si alguien enhebra mal su `tenant_id`. Lo que falta es estructural: un test que **enumere**
  los sitios donde un caso de uso pide al repositorio, o pasar el tenant por un contexto tipado.
  Candidato: `tenant-scoping-enumeration-guard`.
- **Sin comprobador estático en CI.** No hay `mypy` ni `pyright` en el backend, así que ninguna
  afirmación de la forma «lo garantiza el tipo» es sostenible: un `Protocol` no impone su anotación
  de retorno en ejecución. Vale para todo el backend, no sólo para este módulo. Candidato:
  `backend-static-typecheck`.
- **`OwnerApprovalStatus.EXPIRED` existe en el enum y ningún camino lo escribe.** La expiración
  automática quedó fuera a propósito: `OwnerApproval` es la única tabla editable del esquema sin
  `updated_at`, y expirar sin dejar rastro temporal es una decisión de columna que le toca a quien
  traiga la expiración.
- **`OwnerApprovalRelatedType.OTHER` no reanuda ninguna incidencia**: responder una aprobación de ese
  tipo levanta `MaintenanceValidationError`. No hay hoy quien cree aprobaciones `OTHER`.
- **`incidents.assignment_note` no pasa por `storable_text`.** Es el único sumidero de texto libre
  vivo del módulo declarado como `str` con `max_length` a secas: `materials` entró con
  `MultiLineText` desde el primer día, así que un `U+0000` en la nota de asignación llega a asyncpg
  y sale hoy como un `500` sin declarar, mientras el mismo carácter en los materiales se rechaza
  como `422`. No se cerró en este ciclo porque el cuerpo de `assign` no es suyo —lo sirve
  [`tech-incident-context`](tech-incident-context.md)— y cambiar la validación de una ruta ajena de
  paso habría ensanchado el change. Candidato: `assignment-note-storable-text`.
- **No hay ruta de lectura de aprobaciones** ni permiso `READ_OWNER_APPROVALS`: la propietaria las
  descubre por su notificación y las responde por id. Ensancharlo es de quien traiga su bandeja.
- **El clasificador es de desarrollo.** El puerto se entrega con adaptador determinista, como manda
  el principio 3 de `steering/product.md`. El día que se enchufe un proveedor real, una incidencia
  cuya clasificación **falla** conserva `ai_classification` a `NULL` y vuelve a entrar en cada tick,
  para siempre si el fallo es permanente; el trabajo por tick está acotado por lote y por tenant,
  pero una avalancha que el proveedor no sepa clasificar se convierte en carga saliente permanente y
  acotada. Se ve en el contador `failed`.

## Key files

- `backend/app/maintenance/domain/entities.py` — `Incident`, `OwnerApproval`, `IncidentPhoto` y la
  tabla de transiciones (más `ensure_accepts_photo()`, que no está en ella a propósito).
- `backend/app/maintenance/domain/read_models.py` — `IncidentContext`, la proyección de
  [`tech-incident-context`](tech-incident-context.md).
- `backend/app/maintenance/domain/ports.py` — `IncidentClassifier` y `LiveCleaningTaskQuery`.
- `backend/app/maintenance/domain/value_objects.py` — `IncidentClassification` y sus invariantes.
- `backend/app/maintenance/domain/notifications.py` — plazos de SLA y las dos notificaciones.
- `backend/app/maintenance/domain/exceptions.py` — la jerarquía plana del módulo.
- `backend/app/maintenance/infrastructure/classifier.py` — `RuleBasedIncidentClassifier`.
- `backend/app/maintenance/application/use_cases.py` — los casos de uso y los mixins compartidos.
- `backend/app/maintenance/api/` — routers, dependencias, esquemas y el mapa de errores.
- `backend/app/auth/domain/policy.py` — los cuatro permisos y el grant de `TECHNICIAN`.
- `backend/app/audit/domain/value_objects.py` — `AUDITABLE_FIELDS` de `INCIDENT`,
  `OWNER_APPROVAL` e `INCIDENT_PHOTO`.
- `backend/app/maintenance/api/photos_router.py` — la ruta anónima de servido firmado, la única del
  módulo sin permiso ([`incident-photos`](incident-photos.md)).
- `backend/app/scheduler/tasks.py`, `backend/app/scheduler/schedule.py` — el job `classify_incidents`.
- `docs/maintenance.md` — cómo se opera.
