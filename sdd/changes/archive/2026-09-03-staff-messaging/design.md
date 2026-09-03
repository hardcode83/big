# Design: staff-messaging

## Context

`policy.py` (`backend/app/auth/domain/policy.py`) hoy da a `CLEANER` exactamente
`_SELF_SERVICE | _CLEANING_EXECUTE` y a `TECHNICIAN` `_SELF_SERVICE | _INCIDENT_EXECUTE`
(líneas 374/377); ninguno de los dos tiene `READ_CONVERSATIONS`. Los dos dominios que este
change extiende ya resolvieron dos veces el mismo problema de forma — una entidad hija ligada
a la tarea/incidencia padre, con su propio repositorio — para `cleaning_photos` e
`incident_photos` (`backend/app/cleaning/infrastructure/models.py`,
`backend/app/maintenance/infrastructure/models.py`): `id`, `tenant_id`, FK compuesta
`(tenant_id, <parent>_id)` con `ondelete="RESTRICT"`, un `Index` compuesto, un campo FK plano a
`users.id` para quién actuó (`uploaded_by`), y `created_at` escrito por el caso de uso (nunca
`server_default`, para que el orden de inserción sobreviva a un burst). El scoping por rol ya
existe y está probado: `CleaningActor.restrict_to_cleaner_id` /
`IncidentActor.restrict_to_technician_id` (`cleaning/application/use_cases.py:536`,
`maintenance/application/use_cases.py:437`) derivan del rol persistido, nunca de la petición, y
un acceso ajeno responde `CleaningTaskNotFoundError`/`IncidentNotFoundError` — nunca `403` — para
no convertir el endpoint en una sonda.

El censo de la regla 11 de `steering/security.md` ya tiene el contrato que este change necesita:
la **excepción 3** ("persona autenticada tecleando su propia nota, acotada, `storable_text`,
fuera de `AUDITABLE_FIELDS` y fuera del `metadata` del timeline") gobierna `assignment_note`,
`materials`, y el `title`/`description` que teclea la limpiadora. Es el mismo contrato que
`cleaning_task_messages.content`/`incident_messages.content` necesitan, no uno nuevo.

`cleaning/domain/notifications.py` y su gemelo de `maintenance` ya declaran la disciplina que R4
pide: "the body carries ids and a type, never the content of another row" — los constructores de
`NotificationLog` de ese módulo son la pieza a extender, no una nueva.

## Decisions

### D1 — Persistencia: dos tablas gemelas, no una polimórfica

**Chosen:** `cleaning_task_messages` (dominio `cleaning`) e `incident_messages` (dominio
`maintenance`), cada una con FK compuesta `(tenant_id, task_id)` / `(tenant_id, incident_id)`
`ON DELETE RESTRICT` hacia su padre — literalmente el mismo `__table_args__` que
`incident_photos` (`backend/app/maintenance/infrastructure/models.py:194-218`). Cada dominio es
dueño de su hilo: coherente con "un repositorio por agregado raíz" de
`steering/backend-architecture.md` y con que `cleaning`/`maintenance` ya son los dominios que el
proposal elige (R1/R2) en vez de ensanchar `messaging`.

Rejected: una tabla `staff_messages` con `related_type`/`related_id` polimórfico como
`NotificationLog` — ahí funciona porque el target de una notificación puede ser casi cualquier
entidad y no hay integridad referencial que declarar. Aquí el target es siempre una de dos
entidades conocidas, así que una FK compuesta real es posible y estrictamente más segura (un
`incident_id` que no exista, o que exista en otro tenant, falla en la base de datos y no en
tiempo de ejecución de la aplicación) — y es la elección que este mismo problema de forma ya
tomó dos veces.

### D2 — Autor: `author_id` + `author_role` congelado, sin reusar `MessageSenderType`

**Chosen:** cada mensaje guarda `author_id` (FK `users.id`, `ON DELETE RESTRICT`, sin
qualificación de tenant — mismo patrón que `uploaded_by`) y `author_role` (el `UserRole`
persistido del llamante **en el instante de escribir**, congelado en la fila).

Rejected: derivar el rol por `JOIN` a `users.role` en cada lectura — un cambio de rol futuro
reescribiría en silencio la autoría histórica (alguien que escribió como `CLEANER` y más tarde
pasa a `PROPERTY_MANAGER` no puede convertirse retroactivamente en la autora-manager de un
mensaje que envió de limpiadora). Rejected también: reusar `MessageSenderType` — R3.3 del
proposal lo prohíbe explícitamente, y sus cinco miembros no tienen ninguno de campo.

### D3 — Permisos: reutilizar los cuatro permisos que cada dominio ya tiene, no crear uno nuevo

**Chosen:** ningún permiso nuevo en `Permission`/`ROLE_PERMISSIONS`. Gatea así:

- **Lectura** de un hilo de limpieza: `READ_CLEANING_TASKS` — `CLEANER` la tiene vía
  `_CLEANING_EXECUTE`, `PROPERTY_MANAGER` vía `_CLEANING_MANAGE` (policy.py:188-194, 347).
- **Escritura** en un hilo de limpieza: `EXECUTE_CLEANING_TASKS` **o** `MANAGE_CLEANING_TASKS` —
  necesita el `or` porque, a diferencia de `maintenance`, el manager de `cleaning` **no** tiene
  `EXECUTE_CLEANING_TASKS` (policy.py:340-354 le da `_CLEANING_MANAGE`, nunca `_CLEANING_EXECUTE`).
- **Lectura y escritura** de un hilo de incidencia: `READ_INCIDENTS` y `EXECUTE_INCIDENTS` —
  `TECHNICIAN` la tiene vía `_INCIDENT_EXECUTE`, y `PROPERTY_MANAGER` **ya** tiene las dos
  (`_INCIDENT_MANAGE` y `_INCIDENT_EXECUTE` juntas, policy.py:360-363, comentario "para
  desatascar" de R4.5) — aquí no hace falta ni el `or`.

Esto **amiende R3.1 del proposal**, que pedía "declarar al menos un permiso nuevo": no hace
falta ninguno, y no tocar `ROLE_PERMISSIONS` es menos superficie que ampliarlo. Se amienda
`proposal.md` en la puerta de este documento, no en silencio (regla de amendments de OQ).

**Efecto colateral aceptado — lectura de `TENANT_OWNER`:** reutilizar `READ_CLEANING_TASKS`/
`READ_INCIDENTS` para la lectura también concede lectura tenant-wide de ambos hilos a
`TENANT_OWNER`, que ya tiene esos dos permisos vía `_CLEANING_READ`/`_INCIDENT_READ`
(policy.py). El proposal marcaba esta visibilidad como fuera de alcance ("si hace falta, es una
extensión de permisos posterior"), pero excluirla aquí exigiría un permiso dedicado o una
restricción de rol ad-hoc solo para este caso — exactamente la fuente de verdad duplicada que
el párrafo anterior de esta decisión ya rechaza. Se acepta el efecto colateral en lugar de esa
alternativa, y se amienda el out-of-scope del proposal en consecuencia: `TENANT_OWNER` puede
leer ambos hilos desde esta entrega.

Rejected: un permiso dedicado (`READ_TASK_MESSAGES` / `MANAGE_TASK_MESSAGES` o similar) — cada
rol que necesita acceder a un hilo ya tiene, hoy, el permiso equivalente sobre la entidad padre;
uno nuevo sería una segunda fuente de verdad para la misma decisión de acceso ("¿puedo operar
esta tarea/incidencia?"), y ampliar `ROLE_PERMISSIONS` es superficie de seguridad que se evita
cuando no hace falta.

### D4 — Scoping y forma del error: exactamente R1.5/R2.5, sin variación

**Chosen:** el caso de uso de escritura/lectura recibe `CleaningActor`/`IncidentActor` (sin
extenderlos: ya exponen `restrict_to_cleaner_id`/`restrict_to_technician_id`) y aplica el mismo
`_load_task`/`_load_incident_in_scope` que ya usa el resto del dominio — así que un `CLEANER`
sobre una tarea ajena, o un `TECHNICIAN` sobre una incidencia ajena, ve
`CleaningTaskNotFoundError`/`IncidentNotFoundError`, nunca `403`. El estado de la
tarea/incidencia **no** filtra el acceso al hilo — igual que hoy no filtra `_load_task` — así
que se puede escribir sobre una tarea/incidencia cerrada; es la misma no-restricción que el
proposal ya declaraba fuera de alcance forzar.

Rejected: bloquear la escritura en estado terminal — nadie lo pide, y sería la primera vez que
el scoping por asignación de estos dos dominios mira el estado en vez de solo la asignación;
si se necesita, es una restricción posterior y aislada, no parte de este change.

### D5 — Contenido: máximo 2000 caracteres, `storable_text`, excepción 3 del censo de la regla 11

**Chosen:** `content: Annotated[MultiLineText, Field(max_length=2000,
min_length=1)]` con recorte de espacios — la forma exacta de `incidents.materials`
(`security.md:178`; `MultiLineText` es `storable_text("\t\n\r")`, corregido aquí el 2026-09-02
tras el panel de la sección 3 — la redacción original decía `storable_text(" ")`, que no es lo
que su propio precedente usa). 2000, no 4000: alinea con `assignment_note`/`materials`/
`owner_approvals.response_notes`, que son el mismo contrato ("persona autenticada tecleando su
propia nota corta"), y no con `messages.content` (prosa de un tercero anónimo transcrita vía
WhatsApp/IA — un contrato PRD-facing distinto). Este contrato entra en el censo de la regla 11
como **dos filas nuevas bajo excepción 3** (una por columna), con el mismo texto que ya usan
`assignment_note`/`materials`: fuera de `AUDITABLE_FIELDS` (no aplica: ni `CleaningTaskMessage`
ni `IncidentMessage` están en la lista de entidades auditadas de la regla 9 — ver D7) y fuera del
`metadata` de cualquier `TimelineEvent` (no aplica: D6 decide no emitir ninguno).

Rejected: 4000 — ese número gobierna prosa de huésped, no una nota corta de coordinación interna;
copiarlo sin más repetiría el error que D2 evita con `author_role` (tratar dos contratos
distintos como si fueran el mismo porque comparten forma superficial).

### D6 — No genera `TimelineEvent`

**Decidido con el usuario (2026-09-02):** un mensaje de personal NO escribe fila en
`timeline_events`. El timeline es
append-only y responde "qué pasa y quién tiene la próxima acción" (principio 2 de
`steering/product.md`, `<10s`) sobre **estados operacionales de la propiedad** — no es un log de
chat. Una limpiadora y un manager intercambiando varios mensajes por tarea inundaría el timeline
de la propiedad con entradas no accionables, justo lo contrario de lo que el principio 2 pide.

Es una decisión de producto y no de ingeniería, así que se deja para la puerta de este documento
en vez de cerrarse aquí en silencio (ver «Open questions»).

### D7 — Sin `AuditLog`: `CleaningTaskMessage`/`IncidentMessage` no son entidades auditadas

**Chosen:** ningún escritor pasa por `ChangeSet`/`AuditLogFactory`. La regla 9 de
`steering/security.md` enumera las entidades auditadas —Reservation, estados de propiedad,
documentos de Guest, AccessRecord, PricingRule/PriceRecommendation, OwnerApproval, roles de
User, Incident— y un mensaje de personal no es ninguna de ellas ni una mutación de `Incident`
(es una entidad hija nueva, como `IncidentPhoto`, que tampoco se audita).

Rejected: extender `AUDITABLE_FIELDS["INCIDENT"]`/`["CLEANING_TASK"]` con algo relativo al
mensaje — no hay ninguna mutación de la tarea/incidencia que registrar; el mensaje vive en su
propia tabla.

### D8 — Notificación: `NotificationLog` con solo identificadores, nuevo tipo por dominio

**Chosen:** extender `cleaning/domain/notifications.py` y `maintenance/domain/notifications.py`
con un builder `staff_message_notification` cada uno, mismo shape que `assignment_notification`
— `body` lleva **solo** `message_id` y `task_id`/`incident_id` más un texto constante ("Tienes un
mensaje nuevo en la tarea/incidencia…"), **nunca** `content`. Dos `NotificationType` nuevos —
`CLEANING_TASK_MESSAGE`, `INCIDENT_MESSAGE` — como divergencia declarada del catálogo de PRD §14,
mismo precedente que `REVIEW_RESPONSE_APPROVED` (`notifications/domain/enums.py:34-40`). Sin
`sla_deadline_at` (no hay plazo de respuesta) y sin escalación — igual que aquel.

Rejected: interpolar un fragmento de `content` en `subject`/`body` — crearía un segundo sumidero
de texto libre paralelo dentro de `notification_logs`, duplicando exactamente lo que D5 ya
gobierna en `cleaning_task_messages.content`/`incident_messages.content`, y violaría la
disciplina que el propio módulo declara en su docstring.

### D9 — Reparto de la notificación cuando escribe personal de campo (R4.2)

Hoy no existe el concepto de "manager asignado a una tarea/incidencia" — solo
`assigned_cleaner_id`/`assigned_technician_id`.

**Decidido con el usuario (2026-09-02):** notificar a **todos** los `PROPERTY_MANAGER` del
tenant — una fila de `NotificationLog` por cada uno. Simple, sin estado nuevo.

Rejected: introducir un concepto de manager "de guardia"/asignado a la tarea o incidencia —
resolvería el ruido en un tenant con varios managers, pero es una entidad nueva que ningún
requisito pide hoy y que ninguno de los dos dominios tiene; queda fuera de alcance.

## Changes by area

| Area | Files | Change |
|---|---|---|
| `auth` | `backend/app/auth/domain/policy.py` | **Ninguno** (D3) — se documenta explícitamente para que quien lea el diff no busque un permiso que no llega |
| `cleaning` domain | `backend/app/cleaning/domain/entities.py` | + `CleaningTaskMessage` (dataclass simple: `id`, `tenant_id`, `task_id`, `author_id`, `author_role`, `content`, `created_at` — sin invariante propia, mismo caso que `IncidentPhoto`) |
| `cleaning` domain | `backend/app/cleaning/domain/repositories.py` | + `CleaningTaskMessageRepository` (Protocol: `add`, `list_for_task`) |
| `cleaning` domain | `backend/app/cleaning/domain/notifications.py` | + `staff_message_notification(...)` (D8) |
| `cleaning` application | `backend/app/cleaning/application/use_cases.py` | + `SendCleaningTaskMessageUseCase`, `ListCleaningTaskMessagesUseCase` — reusan `CleaningActor` existente |
| `cleaning` infrastructure | `backend/app/cleaning/infrastructure/models.py` | + `CleaningTaskMessageModel` (`__tablename__ = "cleaning_task_messages"`, FK compuesta a `cleaning_tasks`, mismo `__table_args__` que `incident_photos`) |
| `cleaning` infrastructure | `backend/app/cleaning/infrastructure/repositories.py` | + `SqlAlchemyCleaningTaskMessageRepository` |
| `cleaning` api | `backend/app/cleaning/api/messages_router.py` (nuevo, espejo de `photos_router.py`) | `POST`/`GET /api/v1/cleaning-tasks/{task_id}/messages` |
| `cleaning` api | `backend/app/cleaning/api/schemas.py` | + `SendCleaningTaskMessageRequest`, `CleaningTaskMessageResponse` |
| `maintenance` | espejo exacto de las siete filas de arriba, con `IncidentMessage`/`incident_messages`/`incident_id`/`IncidentActor` | `POST`/`GET /api/v1/incidents/{incident_id}/messages` |
| `notifications` domain | `backend/app/notifications/domain/enums.py` | + `CLEANING_TASK_MESSAGE`, `INCIDENT_MESSAGE` en `NotificationType` |
| `backend/app/main.py` | — | montar los dos routers nuevos |
| `backend/alembic/versions/` | nueva revisión | crea `cleaning_task_messages` e `incident_messages` (una sola revisión, un solo change) — ver Risks sobre el `down_revision` |
| specs | `sdd/specs/cleaning.md`, `sdd/specs/maintenance.md` | + sección del hilo de mensajes en cada uno |
| specs | `sdd/specs/access-notifications.md` | + los dos `notification_type`/`related_type` nuevos |
| specs | `sdd/specs/staff-messaging.md` (nuevo) | capacidad documentada aparte, mismo patrón que `cleaner-task-context.md`/`tech-incident-context.md` — vive en dos dominios de código, es una capacidad de producto |
| steering | `sdd/steering/security.md` | + 2 filas en la tabla de la regla 11 (excepción 3) |

## Data & interfaces

**Esquema** (los dos, gemelos salvo el nombre de la FK):

```
cleaning_task_messages
  id            uuid PK
  tenant_id     uuid
  task_id       uuid            -- FK compuesta (tenant_id, task_id) -> cleaning_tasks, RESTRICT
  author_id     uuid            -- FK users.id, RESTRICT
  author_role   varchar         -- UserRole congelado en el instante de escribir
  content       varchar(2000)
  created_at    timestamptz     -- escrito por el caso de uso, sin server_default

incident_messages   -- idéntica, con incident_id en vez de task_id
```

**Endpoints** (convención de paginación/errores de PRD §23, ya usada por el resto del módulo):

```
POST /api/v1/cleaning-tasks/{task_id}/messages   -> 201 CleaningTaskMessageResponse
GET  /api/v1/cleaning-tasks/{task_id}/messages    -> 200 paginado, orden cronológico
POST /api/v1/incidents/{incident_id}/messages     -> 201 IncidentMessageResponse
GET  /api/v1/incidents/{incident_id}/messages      -> 200 paginado, orden cronológico
```

`CleaningTaskMessageResponse`/`IncidentMessageResponse`: `id`, `author_id`, `author_role`,
`content`, `created_at` — sin equivalente a `storage_key`, así que no hay campo que excluir a
propósito como en `IncidentPhotoResponse`.

**Eventos**: ninguno nuevo más allá de la `NotificationLog` de D8 (sujeta a D9). Sin
`TimelineEvent` (D6, abierta). Sin `AuditLog` (D7).

## Risks & mitigations

- **Migración con varias cabezas en juego.** Medido de forma estática (sin stack levantado en
  este worktree — falta `.env`/`ENCRYPTION_KEY`) recorriendo `down_revision` de
  `backend/alembic/versions/`: hoy hay **tres** cabezas —`c22b8ae01096`
  (`super_admin_identity`), `2b28c6b3f82a` (`guest_portal_messaging`) y `r3v1ew5a03`
  (`revenue_reviews_timeline_events`)—, aunque el archivo de `guest-portal-messaging` (mergeado
  el 2026-09-02) ya declara que se re-encadenó sobre la revisión de merge existente, así que esta
  cifra puede haber bajado desde entonces. `/sdd:tasks`/`/sdd:run` deben correr
  `docker compose exec backend uv run alembic heads` (con el stack arriba) antes de escribir el
  `down_revision` de la migración nueva, y si sigue habiendo más de una cabeza, resolverla con
  `alembic merge` primero — mismo caso que motivó el preflight de `#153`.
- **Deriva entre los dos módulos casi idénticos.** `cleaning` y `maintenance` implementan el
  mismo shape dos veces (como ya hacen `cleaning_photos`/`incident_photos`). Mitigación: escribir
  primero uno completo con sus tests, luego el segundo como espejo literal — no en paralelo — y
  si los tests de ambos acaban siendo estructuralmente idénticos, extraer un helper de test
  compartido en vez de mantener dos copias.
- **Guardián de la regla 11.** `make check-rule11-ownership` debe pasar en verde tras añadir las
  dos filas nuevas del censo — correrlo localmente antes de dar la tarea por hecha, no solo
  esperar al CI (coste ya bajado: no necesita Docker ni stack levantado).

## Open questions

Ninguna pendiente: D6 y D9 se decidieron con el usuario el 2026-09-02 (ver ambas secciones).
