# Proposal: maintenance

## Why

El módulo de mantenimiento (PRD §12, orden de desarrollo §26.11) es la única capacidad del MVP
cuyo dominio está **completamente modelado y completamente muerto**: `Incident` y `OwnerApproval`
existen como entidades, modelos y tablas desde `domain-foundation-ops` y
`domain-foundation-financial`, pero nada las opera. Hoy el único escritor de `incidents` es la vía
anónima del portal del huésped, que a propósito **no** fija categoría, severidad, clasificación ni
asignación (R5.4 de `guest-portal-api`), y `cleaning` solo las lee para bloquear un cierre
(`BlockingIncidentQuery.has_unresolved_critical`).

La consecuencia se ha ido acumulando en los changes vecinos, por escrito:

- `backend/app/properties/domain/state_machine.py` declara **27 transiciones** disparadas por
  `INCIDENT_HIGH` / `INCIDENT_CRITICAL` / `INCIDENT_RESOLVED` que **nadie dispara**, así que
  `MAINTENANCE_REQUIRED` y `CRITICAL_INCIDENT` son estados inalcanzables.
- `specs/dashboard-api.md` marca la próxima acción de esos dos estados como *«— (hasta
  `maintenance`)»* y avisa de que `incidents` y `owner_approvals` *«llegan vacíos»*.
- `specs/domain-foundation-ops.md:15` deja escrito que las mutaciones —clasificar, asignar,
  resolver— *«llegan con `maintenance`»*.
- `sdd/roadmap/seed-data-demo-extension.md` declara `needs: maintenance` porque sembrar las tres
  incidencias de PRD §27 antes duplicaría invariantes que este change define.
- `UserRole.TECHNICIAN` tiene hoy solo `_SELF_SERVICE` (`auth/domain/policy.py:223`): el rol
  existe y no puede hacer nada.

Es además una de las dos entradas que quedan para desbloquear la ola 2 del roadmap (`field-apps`
necesita `maintenance` y `messaging-ai`; `seed-data-demo-extension` solo esta).

Fuente funcional: PRD §12 (flujo, regla de aprobación, SLA de técnicos) y §26.11.

## What changes

Después de este change existe el **flujo operativo completo de una incidencia**, del `OPEN` que
deja cualquier fuente hasta `RESOLVED`: clasificación automática por un puerto propio con
adaptador mock, aprobación del propietario cuando el coste estimado supera el umbral del tenant,
asignación a un técnico con su plazo de SLA, el ciclo de transiciones que el técnico conduce desde
su móvil, y el recálculo del estado de la propiedad a través de `PropertyStateMachine`. El módulo
`maintenance` gana el `api/` que nunca tuvo, el rol `TECHNICIAN` gana permisos, y las 27
transiciones de incidencia de la máquina de estados dejan de ser código inalcanzable.

**El clasificador es un puerto propio de `maintenance`, no el `MockAIAdapter` de `messaging-ai`**
(decisión del usuario en el gate de `/sdd:new`, 2026-08-15). El repo ya asignó por escrito ese
adaptador a `messaging-ai` (`cleaning/api/tasks_router.py:323`), y colgar de él una capability
nuclear serializaría dos entradas que la frontera del roadmap declara paralelas. Un puerto de un
solo método por rol es la disciplina que `steering/backend-architecture.md` prescribe y la que
`guest-portal-api` ya aplicó a `IncidentRepository.add`.

## Requirements

### R1 — Clasificación automática de la incidencia

**Como** manager, **quiero** que cada incidencia nueva llegue ya categorizada y con severidad,
**para** no tener que triar a mano lo que la IA puede triar.

Criterios de aceptación:

1. THE SYSTEM SHALL declarar en `maintenance` un puerto de clasificación propio con **un solo
   método**, que recibe el texto de la incidencia y devuelve categoría, severidad, resumen y una
   confianza, y SHALL entregar al menos un adaptador determinista de desarrollo que lo implemente.
2. WHEN una incidencia está en `OPEN`, THE SYSTEM SHALL invocar ese puerto y, con el resultado,
   fijar `category`, `severity`, `ai_summary` y `ai_classification`, pasando la incidencia a
   `CLASSIFIED`.
3. IF la confianza devuelta es menor que `TenantConfig.ai_confidence_threshold`, THEN THE SYSTEM
   SHALL dejar la incidencia en `OPEN` con `category` y `severity` en sus valores por defecto, de
   modo que quede pendiente de clasificación humana y sea distinguible de una ya clasificada.
4. THE SYSTEM SHALL permitir a `TENANT_OWNER` y `PROPERTY_MANAGER` fijar o corregir `category` y
   `severity` a mano mientras la incidencia no esté en un estado terminal.
5. THE SYSTEM NEVER SHALL dejar que el clasificador escriba `title` ni `description`: son texto
   libre de origen externo y su contenido no se reescribe.
6. IF el adaptador de clasificación falla o no responde, THEN THE SYSTEM SHALL dejar la incidencia
   en `OPEN` y NEVER SHALL perderla ni dejarla en un estado intermedio.

### R2 — Aprobación del propietario por encima del umbral

**Como** propietaria, **quiero** aprobar o rechazar cualquier gasto que supere mi umbral **antes**
de que se ejecute, **para** que nadie gaste en mis viviendas sin mi visto bueno.

Criterios de aceptación:

1. WHEN una incidencia recibe un `estimated_cost` mayor que
   `TenantConfig.owner_approval_threshold_eur`, THE SYSTEM SHALL crear un `OwnerApproval` en
   `PENDING` con `related_type = INCIDENT` y `related_id` la incidencia, marcar
   `owner_approval_required` y pasar la incidencia a `AWAITING_OWNER_APPROVAL`.
2. IF el `estimated_cost` es menor o igual que el umbral, o no hay coste estimado, THEN THE SYSTEM
   SHALL continuar el flujo sin crear ninguna aprobación.
3. WHEN se crea un `OwnerApproval`, THE SYSTEM SHALL notificar al propietario a través del
   `NotificationAdapter` existente, dejando su `NotificationLog`.
4. WHEN el propietario responde, THE SYSTEM SHALL registrar `status`, `responded_at`,
   `responded_by` y `response_notes`; IF la respuesta es `APPROVED`, THEN SHALL fijar
   `approved_cost` y devolver la incidencia al flujo de asignación.
5. IF la respuesta es `REJECTED`, THEN THE SYSTEM SHALL pasar la incidencia a `CANCELLED`
   (`ASSUMPTION`: PRD §12 describe la espera y no dice qué pasa al rechazar).
6. THE SYSTEM NEVER SHALL permitir responder una aprobación a un rol distinto de `TENANT_OWNER`,
   ni responder dos veces la misma, ni responder una de otro tenant.

### R3 — Asignación a técnico y plazo de SLA

**Como** manager, **quiero** asignar la incidencia a un técnico y que el sistema le reclame el
plazo que corresponde a su severidad, **para** que una crítica no duerma como una menor.

Criterios de aceptación:

1. WHEN un manager asigna la incidencia, THE SYSTEM SHALL fijar `assigned_technician_id`, pasar a
   `ASSIGNED` y notificar al técnico por el `NotificationAdapter`.
2. THE SYSTEM SHALL derivar el plazo de la severidad usando `TenantConfig.sla_critical_minutes`,
   `sla_high_minutes`, `sla_medium_minutes` y `sla_low_minutes`, y SHALL registrarlo sobre la
   maquinaria de SLA que ya existe en `notifications`
   (`list_sla_breach_candidates` / `mark_breached` / `cancel_sla_deadline`), sin construir una
   segunda.
3. WHEN el técnico acepta la incidencia, THE SYSTEM SHALL cancelar el plazo pendiente.
4. THE SYSTEM NEVER SHALL aceptar como asignatario un usuario cuyo rol no sea `TECHNICIAN`, ni un
   usuario de otro tenant.
5. THE SYSTEM SHALL permitir reasignar una incidencia no terminal, cancelando el plazo del
   asignatario anterior y abriendo el del nuevo.

### R4 — Ciclo del técnico hasta la resolución

**Como** técnico, **quiero** aceptar, marcar en ruta, reportar espera de piezas y cerrar con el
coste final, **para** que el estado de la incidencia refleje lo que estoy haciendo.

Criterios de aceptación:

1. THE SYSTEM SHALL permitir al técnico asignado las transiciones `ASSIGNED → ACCEPTED`,
   `ACCEPTED → IN_PROGRESS`, `IN_PROGRESS → WAITING_EXTERNAL_PARTS`,
   `WAITING_EXTERNAL_PARTS → IN_PROGRESS` e `IN_PROGRESS → RESOLVED`.
2. WHEN el técnico resuelve la incidencia, THE SYSTEM SHALL exigir `final_cost`, fijar
   `resolved_at` y pasar a `RESOLVED`.
3. IF el `final_cost` supera el umbral del tenant y no existe un `OwnerApproval` aprobado que lo
   cubra, THEN THE SYSTEM SHALL crear una nueva aprobación y NEVER SHALL resolver la incidencia
   hasta que se responda (`ASSUMPTION`: PRD §12 fija el umbral sobre el coste estimado y no dice
   qué pasa si el real lo desborda; sin esta cláusula, estimar 90 EUR y gastar 500 evita la regla
   de aprobación entera).
4. THE SYSTEM SHALL rechazar cualquier transición fuera del orden declarado, con el formato de
   error de PRD §23, sin modificar nada.
5. THE SYSTEM NEVER SHALL permitir conducir estas transiciones a un técnico que no sea el
   asignado; un `PROPERTY_MANAGER` sí puede, para desatascar.
6. WHEN la incidencia queda `CLASSIFIED` con severidad `HIGH` o `CRITICAL`, y WHEN queda
   `RESOLVED`, THE SYSTEM SHALL recalcular el estado operacional de la propiedad **a través de
   `PropertyStateMachine`** con los disparadores `INCIDENT_HIGH`, `INCIDENT_CRITICAL` e
   `INCIDENT_RESOLVED` que ya existen, sin escribir el estado directamente.

### R5 — API del módulo y permisos del técnico

**Como** manager y como técnico, **quiero** rutas propias de incidencias, **para** operarlas sin
pasar por el portal del huésped, que es la única superficie que existe hoy.

Criterios de aceptación:

1. THE SYSTEM SHALL dar a `maintenance` su capa `api/`, que hoy no tiene, con listado paginado y
   detalle según las convenciones de PRD §23 (`?page&per_page`, errores
   `{error:{code,message,details}}`, fechas ISO 8601 UTC).
2. THE SYSTEM SHALL conceder a `TECHNICIAN` los permisos que necesitan R3 y R4, del mismo modo que
   `CLEANER` tiene `_CLEANING_EXECUTE`, y NEVER SHALL concederle nada más.
3. WHERE el solicitante es `TECHNICIAN`, THE SYSTEM SHALL devolver **solo** las incidencias que
   tiene asignadas.
4. THE SYSTEM NEVER SHALL exponer estas rutas al rol `CLEANER` ni al portador de un token de
   huésped, y NEVER SHALL devolver una incidencia de otro tenant.
5. THE SYSTEM SHALL regenerar y commitear `backend/openapi.json` y
   `frontend/lib/api/generated/openapi.d.ts` en el mismo PR, según `steering/documentation.md`.

### R6 — Auditoría y timeline de cada transición

**Como** propietaria, **quiero** que toda la vida de una incidencia quede auditada y en el
timeline, **para** poder reconstruir qué pasó y quién lo decidió.

Criterios de aceptación:

1. WHEN cambia el estado de una incidencia o se responde una aprobación, THE SYSTEM SHALL escribir
   su `AuditLog` y su `TimelineEvent` **en la misma transacción** que el cambio.
2. THE SYSTEM SHALL ensanchar el allowlist de campos auditables de `INCIDENT` —hoy `source`,
   `status` y `reservation_id`— con los campos que este flujo muta, y NEVER SHALL incluir `title`
   ni `description`, que son texto libre de origen externo sobre una tabla append-only.
3. THE SYSTEM SHALL usar los `TimelineEventType` que ya existen (`INCIDENT_CLASSIFIED`,
   `INCIDENT_RESOLVED`, `INCIDENT_CANCELLED`) y SHALL mantener la disciplina de
   `ReportGuestIncidentUseCase`: título constante y `metadata` solo con identificadores.
4. THE SYSTEM SHALL nombrar como actor al usuario que ejecuta la transición, y NEVER SHALL escribir
   una fila que reclame a la vez un usuario y un portador de token.

## Out of scope

- **Fotos de incidencia** (PRD §12, UI del técnico). Es el patrón exacto que en limpieza fue
  `cleaning-photos-storage`, un change entero con su propio panel. Entrada propia; el puerto de
  ficheros ya existe y su camino `LOCAL` funciona.
- **`Expense` al resolver** (PRD §12, «TimelineEvent + Expense creado»). El módulo `statements` y
  la entidad `Expense` tienen dueño declarado en `revenue` (`specs/domain-foundation-financial.md`).
  Escribirlos aquí duplicaría invariantes que esa entrada va a definir — la misma disciplina que
  mantuvo al seed fuera de `properties` sin `properties-crud`.
- **Expiración automática de `OwnerApproval`** (`OwnerApprovalStatus.EXPIRED`). El docstring de la
  entidad advierte que es *«la única tabla editable del esquema sin `updated_at`»* y que una
  expiración automática no deja rastro temporal. Este change **no** la implementa y por tanto **no**
  añade `updated_at`: `responded_at` cubre todas las respuestas que sí implementa. Queda para quien
  traiga la expiración, con la decisión de columna incluida.
- **UI del técnico y bandeja móvil** (PRD §12 «UI del técnico», §24). Es `field-apps` [FE], que
  declara `needs: maintenance`.
- **Detección del intent `MAINTENANCE_ISSUE` desde la mensajería** (PRD §12, fuente de creación
  vía IA conversacional). Es de `messaging-ai`; este change deja la incidencia clasificable venga
  de donde venga.
- **Alerta de cerradura como fuente** (`IncidentSource.LOCK_ALERT`). El PRD la describe como
  importación manual desde GrinPass; sin superficie de importación no hay nada que construir.
- **Clasificación con un proveedor de IA real.** El puerto se entrega con adaptador de desarrollo,
  como manda el principio 3 de `steering/product.md` (adapters mock donde falten credenciales).

- **El `AuditLog` de una transición de estado de propiedad con actor `USER`** — candidato a change
  propio, levantado por el panel de seguridad de la sección 6 durante `/sdd:run` (2026-08-15).
  La regla 9 de `steering/security.md` exime esa fila **sólo con actor `SYSTEM`** y dice de los
  demás que «NO está exenta», con su motivo: `audit_logs` aporta `actor_ip` y el índice
  `ix_audit_logs_tenant_id_actor_user_id_created_at`, que es el que responde «todo lo que hizo
  esta persona» a través de entidades. Todas las transiciones que dispara este change con actor
  son `USER`, y no escriben esa fila.
  **No se cierra aquí porque el hueco no es de este change y cerrarlo sólo aquí lo empeora**:
  `properties` decidió lo contrario para *todos* los actores y lo dejó escrito en un test que lo
  dice por su nombre (`test_the_operational_state_is_not_an_auditable_property_field`), con
  `current_operational_state` fuera de `AUDITABLE_FIELDS["PROPERTY"]`; y `cleaning` tiene el mismo
  hueco en su `_TaskTransitionMixin`. Una propiedad con fila de auditoría cuando la mueve una
  incidencia y sin ella cuando la bloquea su propietaria es un rastro incoherente **y** incompleto.
  Lo que hay que decidir —cuál cede, la regla 9 o la postura de `properties`— toca los tres
  escritores de `current_operational_state` y el allowlist compartido. Nombre sugerido:
  `property-transition-audit`.

- **La demostración del aislamiento por enumeración, en vez de un test por puerta** —
  candidato a change propio, levantado por el panel de tenancy en la re-revisión del
  2026-08-15. El aislamiento de este módulo está bien implementado y verificado ruta por ruta,
  pero **demostrado** sólo en dos de sus tres puertas: el detalle (`GetIncidentUseCase`) y las
  ocho transiciones (`_load_incident`, que es una única función compartida). La tercera
  —`RespondOwnerApprovalUseCase`, detrás de `POST /owner-approvals/{id}/respond`— resuelve por
  su propio par `approvals.get` + `incidents.get` y ningún test puede fallar si alguien
  enhebra mal su `tenant_id`: el de RBAC sólo mira el 403, y el de «aprobación desconocida»
  usa un `uuid4()` sobre dobles, no una fila real de otro tenant.
  **No se cierra aquí porque un tercer espía deja el cuarto abierto**: cada ronda de este
  review cubrió un call site y la siguiente encontró otro. Lo que hace falta es estructural y
  es una decisión de diseño: o un test que **enumere** los sitios donde un caso de uso pide al
  repositorio y exija que cada uno reciba el `tenant_id` del llamante —la disciplina sin
  allowlist que `backend-response-hardening` ya usó para `nosniff`, donde una ruta nueva entra
  sola—, o pasar el tenant por un contexto tipado en lugar de por un argumento posicional
  repetido en cada firma. Nombre sugerido: `tenant-scoping-enumeration-guard`.

- **Un comprobador estático en CI** — candidato a change propio, levantado por el panel de
  seguridad en la re-revisión del 2026-08-15. El repositorio **no tiene ninguno**: ni `mypy`
  ni `pyright` en `backend/pyproject.toml`, ni en el `Makefile`, ni paso de tipos en
  `.github/workflows/`. Los LSP que declara `sdd/project.md` son otra cosa — ayudan al editor,
  no bloquean un merge. La consecuencia la encontró este change al tercer intento de redactar
  su fila del censo: **ninguna afirmación de la forma «lo garantiza el tipo» es sostenible
  aquí**, porque un `Protocol` no impone su anotación de retorno en ejecución y nada comprueba
  estáticamente que se respete. La fila quedó acotada a «todo adaptador que devuelva el tipo
  declarado», que es cierto; cerrar la clase entera es lo que haría un comprobador en CI, y
  vale para todo el backend, no para esta columna. Nombre sugerido: `backend-static-typecheck`.

## Affected specs

- `sdd/specs/maintenance.md` *(no existe aún — se creará al archivar)*
- `sdd/specs/domain-foundation-ops.md` — su §12 y §15 declaran que el `application/` de `Incident`
  quedó a medias y que las mutaciones «llegan con `maintenance`»; hay que cerrarlo.
- `sdd/specs/dashboard-api.md` — retirar los *«— (hasta `maintenance`)»* de `MAINTENANCE_REQUIRED`
  y `CRITICAL_INCIDENT` y la nota de que `incidents` y `owner_approvals` llegan vacíos.
- `sdd/specs/guest-portal-api.md` — su R5.4 afirma que una incidencia del portal es
  «indistinguible para el flujo de clasificación»; ahora ese flujo existe y hay que decir cuál es.
- `sdd/specs/auth-tenancy.md` — los permisos nuevos de `TECHNICIAN`.
- `sdd/specs/timeline-state-machine.md` — los disparadores de incidencia dejan de ser inalcanzables.
- `sdd/specs/api-contract.md` — las rutas nuevas del módulo.
