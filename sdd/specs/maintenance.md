# Mantenimiento de incidencias

## Purpose

El módulo `maintenance` opera el ciclo de vida completo de una incidencia sobre una propiedad,
desde el `OPEN` que deja cualquier fuente hasta `RESOLVED` o `CANCELLED`: clasificación automática
por un puerto propio, aprobación de la propietaria cuando el gasto supera el umbral del tenant,
asignación a un técnico con su plazo de SLA, el ciclo de transiciones que conduce el técnico, y la
recomposición del estado operacional de la propiedad. Es el único escritor de mutaciones sobre
`incidents` y `owner_approvals`; la **creación** llega desde fuera, hoy por dos vías: la anónima
del portal del huésped ([`guest-portal-api.md`](guest-portal-api.md)) y, desde el 2026-08-16, una
conversación cuyo intent es `MAINTENANCE_ISSUE` o `ACCESS_PROBLEM`
([`messaging-ai.md`](messaging-ai.md)).

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
  | `start` | `ACCEPTED` | `IN_PROGRESS` |
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
  minutos**, y NEVER SHALL clasificar dentro de la petición que crea la incidencia: el único
  escritor de incidencias en `OPEN` es una ruta **anónima desde internet**, y colgar de ella la
  llamada al clasificador es lo que prohíbe la regla 12(d) de `steering/security.md`.
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
- THE SYSTEM NEVER SHALL aceptar como asignatario un usuario que no sea `TECHNICIAN` **y** esté
  `ACTIVE` en el tenant del solicitante; el rechazo SHALL ser `InvalidTechnicianError`.
- THE SYSTEM SHALL derivar el plazo de la severidad —`sla_critical_minutes`, `sla_high_minutes`,
  `sla_medium_minutes`, `sla_low_minutes` de `TenantConfig`— y SHALL registrarlo como
  `sla_deadline_at` **sobre la maquinaria de SLA que ya existe** en `notifications`
  (`list_sla_breach_candidates`, `mark_breached`, `cancel_sla_deadline`), sin construir una segunda.
- WHEN el técnico acepta, THE SYSTEM SHALL cancelar el plazo pendiente.
- WHEN se reasigna una incidencia que ya tenía asignatario, THE SYSTEM SHALL cancelar el plazo del
  anterior antes de abrir el del nuevo.
- THE SYSTEM SHALL apuntar `related_id` de estas notificaciones a la **incidencia**, no a la
  aprobación, con `related_type = "incident"`.
- THE SYSTEM SHALL dejar la notificación de aprobación **sin** `sla_deadline_at`: no hay plazo que
  reclamarle a una propietaria, y en consecuencia `OWNER_APPROVAL_REQUIRED` no tiene política de
  escalado.

### R6 — El ciclo del técnico

- THE SYSTEM SHALL permitir al técnico asignado las transiciones `ASSIGNED → ACCEPTED`,
  `ACCEPTED → IN_PROGRESS`, `IN_PROGRESS → WAITING_EXTERNAL_PARTS`,
  `WAITING_EXTERNAL_PARTS → IN_PROGRESS` e `IN_PROGRESS → RESOLVED`.
- WHEN el técnico resuelve, THE SYSTEM SHALL exigir `final_cost`, y —salvo que se abra la segunda
  puerta de aprobación— fijar `resolved_at` y pasar a `RESOLVED`.
- THE SYSTEM SHALL rechazar todo coste negativo con `MaintenanceValidationError`.
- THE SYSTEM SHALL permitir también a `PROPERTY_MANAGER` conducir estas transiciones, para
  desatascar; es la única diferencia con limpieza, donde ejecutar es sólo de la limpiadora.
- THE SYSTEM NEVER SHALL permitir conducirlas a un técnico que no sea el asignado, y esa negativa
  SHALL ser indistinguible de «no existe» (ver R8).

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

- THE SYSTEM SHALL exponer doce rutas, todas autenticadas y todas con permiso declarado: once bajo
  `/api/v1/incidents` (`GET` de listado, `GET` de detalle, `PATCH` de triaje y los `POST` de
  `classify`, `assign`, `accept`, `start`, `wait-parts`, `resume`, `resolve` y `cancel`) y
  `POST /api/v1/owner-approvals/{approval_id}/respond`.
- THE SYSTEM NEVER SHALL exponer una ruta de **creación** de incidencias en este módulo. Las dos
  superficies que las crean son la anónima del portal del huésped y el pipeline de mensajería.
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
  | `TENANT_OWNER` | leer incidencias; responder aprobaciones |
  | `PROPERTY_MANAGER` | leer, clasificar, triar, asignar, cancelar **y** todo el ciclo del técnico |
  | `TECHNICIAN` | leer y ejecutar el ciclo (aceptar, empezar, esperar piezas, reanudar, resolver) |
  | `CLEANER`, `SUPER_ADMIN` | nada de este módulo |

- THE SYSTEM SHALL conceder a `TECHNICIAN` exactamente lo que R5 y R6 necesitan y nada más: su
  conjunto completo es autoservicio (`READ_OWN_PROFILE`, `MANAGE_OWN_SESSION`,
  `READ_OWN_NOTIFICATIONS`) más `READ_INCIDENTS` y `EXECUTE_INCIDENTS`. NEVER SHALL poder clasificar,
  triar, asignar, cancelar ni responder aprobaciones.
- WHERE el solicitante es `TECHNICIAN`, THE SYSTEM SHALL devolver **sólo** las incidencias que tiene
  asignadas, derivando la restricción del **rol del token** y NEVER SHALL aceptarla ni ensancharla
  desde la petición: no existe parámetro `assigned_technician_id` en la ruta, y el filtro se
  sobrescribe en lugar de rellenarse por defecto.
- THE SYSTEM SHALL responder el **mismo `404` con el mismo cuerpo** para una incidencia inexistente,
  una de otro tenant y una asignada a otro técnico, de modo que la ruta no sirva de sonda de
  existencia.
- THE SYSTEM SHALL tomar el `tenant_id` únicamente del token verificado, SHALL pasarlo explícito a
  cada método de repositorio, y NEVER SHALL aceptarlo en ningún esquema de petición.
- THE SYSTEM NEVER SHALL exponer estas rutas al rol `CLEANER` ni al portador de un token de huésped.
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
- THE SYSTEM SHALL auditar sobre `INCIDENT` exactamente once campos: `source`, `status`,
  `reservation_id`, `category`, `severity`, `assigned_technician_id`, `owner_approval_required`,
  `estimated_cost`, `approved_cost` y `final_cost`, más `resolved_at`.
- THE SYSTEM NEVER SHALL auditar `title`, `description`, `ai_summary` ni `ai_classification`, y esa
  exclusión SHALL ser **estructural**: nombrar cualquiera de los cuatro en un `ChangeSet` levanta
  `AuditContractError`. Los dos primeros son texto libre de origen externo sobre una tabla
  append-only; los otros dos son los sumideros que R2 acota.
- THE SYSTEM SHALL auditar sobre `OWNER_APPROVAL` exactamente cinco campos: `status`, `amount`,
  `related_type`, `responded_by` y `responded_at`, y NEVER SHALL auditar `reason` ni
  `response_notes`.
- THE SYSTEM SHALL nombrar como actor al usuario que ejecuta la transición, y NEVER SHALL escribir
  una fila que reclame a la vez un usuario y un portador de token.
- WHERE la clasificación la dispara el job, THE SYSTEM SHALL escribir la fila **sin actor**
  (`actor_user_id` y `actor_ip` a `NULL`) y con actor `AI` en el timeline: la dispara el reloj, no
  una persona. `INCIDENT_CLASSIFIED` SHALL ser la **única** acción de este módulo que admite actor
  ausente; cualquier otra sin actor SHALL fallar.
- THE SYSTEM SHALL escribir en el timeline `INCIDENT_CLASSIFIED`, `OWNER_APPROVAL_REQUIRED`,
  `OWNER_APPROVED_EXPENSE`, `OWNER_REJECTED_EXPENSE`, `TECHNICIAN_ASSIGNED`, `TECHNICIAN_ACCEPTED`,
  `TECHNICIAN_STARTED`, `INCIDENT_RESOLVED` e `INCIDENT_CANCELLED`, con **título constante** y
  `metadata` sólo con identificadores.
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
  de sus tres puertas.** El detalle y las ocho transiciones comparten una única función; la tercera
  —`RespondOwnerApprovalUseCase`— resuelve por su propio par de consultas y ningún test falla si
  alguien enhebra mal su `tenant_id`. Lo que falta es estructural: un test que **enumere** los sitios
  donde un caso de uso pide al repositorio, o pasar el tenant por un contexto tipado. Candidato:
  `tenant-scoping-enumeration-guard`.
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
- **`TimelineEventType.TECHNICIAN_EN_ROUTE` existe y nadie lo escribe**: no hay transición «en ruta»
  en el ciclo entregado.
- **No hay ruta de lectura de aprobaciones** ni permiso `READ_OWNER_APPROVALS`: la propietaria las
  descubre por su notificación y las responde por id. Ensancharlo es de quien traiga su bandeja.
- **El clasificador es de desarrollo.** El puerto se entrega con adaptador determinista, como manda
  el principio 3 de `steering/product.md`. El día que se enchufe un proveedor real, una incidencia
  cuya clasificación **falla** conserva `ai_classification` a `NULL` y vuelve a entrar en cada tick,
  para siempre si el fallo es permanente; el trabajo por tick está acotado por lote y por tenant,
  pero una avalancha que el proveedor no sepa clasificar se convierte en carga saliente permanente y
  acotada. Se ve en el contador `failed`.

## Key files

- `backend/app/maintenance/domain/entities.py` — `Incident`, `OwnerApproval` y la tabla de
  transiciones.
- `backend/app/maintenance/domain/ports.py` — `IncidentClassifier` y `LiveCleaningTaskQuery`.
- `backend/app/maintenance/domain/value_objects.py` — `IncidentClassification` y sus invariantes.
- `backend/app/maintenance/domain/notifications.py` — plazos de SLA y las dos notificaciones.
- `backend/app/maintenance/domain/exceptions.py` — la jerarquía plana del módulo.
- `backend/app/maintenance/infrastructure/classifier.py` — `RuleBasedIncidentClassifier`.
- `backend/app/maintenance/application/use_cases.py` — los casos de uso y los mixins compartidos.
- `backend/app/maintenance/api/` — routers, dependencias, esquemas y el mapa de errores.
- `backend/app/auth/domain/policy.py` — los cuatro permisos y el grant de `TECHNICIAN`.
- `backend/app/audit/domain/value_objects.py` — `AUDITABLE_FIELDS` de `INCIDENT` y `OWNER_APPROVAL`.
- `backend/app/scheduler/tasks.py`, `backend/app/scheduler/schedule.py` — el job `classify_incidents`.
- `docs/maintenance.md` — cómo se opera.
