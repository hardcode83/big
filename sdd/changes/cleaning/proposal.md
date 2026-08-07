# Proposal: cleaning

## Why

`AWAITING_CLEANING` es hoy un **estado terminal en la práctica**. `celery-jobs` entregó
`process_checkouts` transicionando la propiedad, pero no creando la `CleaningTask`, y lo dejó
escrito en su propio código y en su spec: `backend/app/scheduler/tasks.py:104-109` y
`sdd/specs/celery-jobs.md:126-127`. La consecuencia se propaga hacia arriba: sin filas en
`cleaning_tasks`, la precedencia contextual de `ContextualStateResolver` ve **siempre** «sin
limpieza pendiente» (`backend/app/properties/domain/state_resolution.py:143-147`), así que las
ramas `CLEANING_IN_PROGRESS` y `CREATED`/`ASSIGNED`/`ACCEPTED` de PRD §8.2 nunca se ejercitan
con datos reales.

No es solo la máquina de estados. Hay tres piezas más ya construidas que **nadie ha ejecutado
nunca** porque les falta el escritor:

- Los cinco disparadores de limpieza de `PropertyStateTrigger` — `CLEANER_ASSIGNED`,
  `CLEANER_REJECTED`, `CLEANING_ASSIGNMENT_EXPIRED`, `CLEANING_STARTED`, `CLEANING_COMPLETED`
  (`properties/domain/transition_enums.py:9-13`), más `after_cleaning_completion` y la
  precondición de `CLEANING_SCHEDULED` (`state_resolution.py:126-178`).
- La política de escalado por SLA de `CLEANING_TASK_ASSIGNED` → `SLA_BREACH` al
  `PROPERTY_MANAGER` (`notifications/domain/escalation.py:53-57`), que `celery-jobs` escribió
  a partir de PRD §14 y que no puede dispararse porque **nada escribe una fila de ese tipo**.
- Las cuatro tablas de `domain-foundation-ops` (`cleaning_tasks`,
  `cleaning_checklist_templates`, `cleaning_checklist_completions`, `cleaning_photos`), sin un
  solo escritor: `backend/app/cleaning/` tiene `domain/` e `infrastructure/` y **ninguna capa
  de aplicación ni API**.

Es además la **prioridad 3 de PRD §30** (estado operacional → timeline → limpieza) y el paso
26.10 del orden de desarrollo. Reemplaza la coordinación de limpiezas que hacía MAGNO
(PRD §11), que es literalmente el trabajo que el producto existe para sustituir.

## What changes

Nace la capa de aplicación y API del módulo `cleaning`: resolución de la plantilla de
checklist, **alta automática de la `CleaningTask` al cerrar el checkout** honrando
`TenantConfig.auto_create_cleaning_task` y `Reservation.cleaning_required`, el ciclo de vida
completo de la tarea (asignación, aceptación, rechazo, inicio, cierre) cableado a los cinco
disparadores de la máquina de estados, el checklist ítem a ítem, la regla de validación de
PRD §11 y la notificación de asignación con `sla_deadline_at`, que convierte a este change en
el **primer escritor real** de la política de escalado que `celery-jobs` dejó preparada.

Los endpoints son los de PRD §23 salvo los dos de fotos, que se separan (ver *Out of scope*).

## Requirements

### R1 — Plantilla de checklist resoluble

**As a** manager, **I want** que cada propiedad tenga una plantilla de checklist activa,
**so that** una tarea de limpieza pueda crearse con contenido y no como un cascarón.

`CleaningTask.checklist_template_id` es **NOT NULL**
(`cleaning/infrastructure/models.py:21-23`), pero PRD §23 no declara ningún endpoint de
plantillas y PRD §27 no siembra ninguna. Sin resolver esto, R2 es imposible.
**ASSUMPTION**: se añaden endpoints de plantilla que PRD §23 no lista; es un hueco del PRD,
no una función nueva. La desviación se registra siguiendo la convención de ADR 0005.

Acceptance criteria:

1. WHEN un `PROPERTY_MANAGER` o `TENANT_OWNER` solicite `POST /api/v1/cleaning-checklist-templates`,
   THE SYSTEM SHALL crear una plantilla del tenant del token con `items` y `required_photos`, y
   responder `201`.
2. THE SYSTEM SHALL validar la estructura de `items` y `required_photos` en el alta —cada
   elemento con `id` no vacío y único dentro de la plantilla y un `required` booleano— y
   responder `422` en el envelope de PRD §23 sin escribir nada cuando no la cumpla.
   `domain-foundation-ops` persiste esas columnas `JSONB` **sin validar su estructura**
   (`specs/domain-foundation-ops.md`, §Esquema DB); a partir de aquí el `item_id` es la clave
   con la que se completa el checklist, así que deja de poder ser texto libre.
3. WHEN se necesite la plantilla de una propiedad, THE SYSTEM SHALL resolver la plantilla
   activa de esa `property_id` y, si no existe, la activa del tenant con `property_id IS NULL`.
4. IF hay más de una plantilla activa candidata en el mismo nivel de resolución, THEN THE
   SYSTEM SHALL rechazar la resolución en vez de elegir una: dos plantillas activas para la
   misma propiedad es una ambigüedad del tenant, y escoger por `id` ancla el contenido del
   checklist a un desempate arbitrario.
5. WHEN un `PROPERTY_MANAGER` o `TENANT_OWNER` solicite `GET /api/v1/cleaning-checklist-templates`,
   THE SYSTEM SHALL devolver únicamente las plantillas de su tenant con el envelope paginado
   de PRD §23.

### R2 — Alta automática de la tarea al cerrar el checkout

**As a** manager, **I want** que la tarea de limpieza aparezca sola cuando el huésped se va,
**so that** `AWAITING_CLEANING` deje de ser un estado sin continuación.

Acceptance criteria:

1. WHEN `process_checkouts` transicione una propiedad a `AWAITING_CLEANING`, THE SYSTEM SHALL
   crear una `CleaningTask` en estado `CREATED` asociada a esa propiedad y a la reserva que
   originó la transición.
2. IF `TenantConfig.auto_create_cleaning_task` es `false` O la reserva tiene
   `cleaning_required = false`, THEN THE SYSTEM SHALL transicionar igualmente y **no** crear
   la tarea.
3. THE SYSTEM SHALL escribir la transición, su `TimelineEvent` y la `CleaningTask` **en la
   misma transacción**: una propiedad en `AWAITING_CLEANING` sin tarea es exactamente el
   estado terminal que este change existe para eliminar.
4. IF no hay plantilla resoluble para la propiedad (R1.3/R1.4), THEN THE SYSTEM SHALL
   transicionar sin crear la tarea, contabilizarlo en el informe del job y emitir un registro
   con `tenant_id` y `property_id`, en lugar de fallar el job para el resto del tenant.
5. THE SYSTEM SHALL ser idempotente por propiedad y reserva: una segunda ejecución del job
   sobre la misma reserva no crea una segunda tarea.
6. WHEN la tarea se cree, THE SYSTEM SHALL derivar `scheduled_start` del instante de checkout
   efectivo y `scheduled_end` del `check_in` de la siguiente reserva confirmada cuando exista.

### R3 — Ciclo de asignación cableado a la máquina de estados

**As a** limpiadora, **I want** recibir, aceptar o rechazar la tarea, **so that** el estado de
la propiedad refleje quién tiene la próxima acción.

Acceptance criteria:

1. WHEN la tarea se cree y el tenant tenga **exactamente una** persona con rol `CLEANER` en
   estado `ACTIVE`, THE SYSTEM SHALL asignársela automáticamente, pasarla a `ASSIGNED` y
   disparar `CLEANER_ASSIGNED` (PRD §11: «automática si hay una activa, si no queda
   pendiente»).
2. IF no hay ninguna `CLEANER` activa, O hay más de una, THEN THE SYSTEM SHALL dejar la tarea
   en `CREATED` sin asignar y notificar al manager (R6.3).
3. WHEN un `PROPERTY_MANAGER` solicite `PATCH /api/v1/cleaning-tasks/{id}` asignando una
   `assigned_cleaner_id`, THE SYSTEM SHALL exigir que esa persona tenga rol `CLEANER` en el
   tenant del token y responder `422` en caso contrario.
4. WHEN la limpiadora asignada solicite `POST /api/v1/cleaning-tasks/{id}/accept`, THE SYSTEM
   SHALL pasar la tarea a `ACCEPTED` y registrar `accepted_at`.
5. WHEN la limpiadora asignada solicite `POST /api/v1/cleaning-tasks/{id}/reject`, THE SYSTEM
   SHALL pasar la tarea a `REJECTED` y disparar `CLEANER_REJECTED`, devolviendo la propiedad
   a `AWAITING_CLEANING`, y SHALL dejar la propiedad con una tarea viva sin asignar.
   **Corregido durante `/sdd:run` (sección 1)**: la redacción anterior decía «liberar
   `assigned_cleaner_id`», escrita antes de la decisión D3 del design. Borrar esa columna en
   la fila rechazada elimina el registro de **quién** rechazó, que es la mitad del valor de
   un rechazo y la justificación explícita de D3. La liberación del hueco la aporta la tarea
   de reemplazo, que nace en `CREATED` y sin asignar.
6. WHEN la limpiadora asignada solicite `POST /api/v1/cleaning-tasks/{id}/start`, THE SYSTEM
   SHALL pasar la tarea a `IN_PROGRESS`, registrar `started_at` y disparar `CLEANING_STARTED`.
7. IF una transición de tarea se solicita desde un estado que no la admite, THEN THE SYSTEM
   SHALL responder `409` sin tocar la tarea ni el estado de la propiedad.
8. THE SYSTEM SHALL delegar **toda** transición de estado de propiedad en
   `PropertyStateMachine`, nunca escribiendo `current_operational_state` por su cuenta
   (PRD §8, `steering/architecture.md`), y persistir su fila de `property_state_transitions`
   en la misma transacción (`steering/security.md` regla 9).

### R4 — Checklist ítem a ítem

**As a** limpiadora, **I want** ir marcando el checklist, **so that** el progreso quede
registrado y el cierre pueda verificarse.

Acceptance criteria:

1. WHEN se solicite `GET /api/v1/cleaning-tasks/{id}/checklist`, THE SYSTEM SHALL devolver los
   ítems de la plantilla de la tarea con su estado de completado.
2. WHEN la limpiadora asignada solicite
   `POST /api/v1/cleaning-tasks/{id}/checklist/{item_id}/complete`, THE SYSTEM SHALL registrar
   la `CleaningChecklistCompletion` con `completed_by` y `completed_at`.
3. IF `item_id` no pertenece a la plantilla de la tarea, THEN THE SYSTEM SHALL responder `404`
   sin escribir nada.
4. WHEN el mismo `item_id` se complete dos veces, THE SYSTEM SHALL ser idempotente y no
   violar `uq_cleaning_checklist_completions_cleaning_task_id_item_id`.
5. IF la tarea no está en `IN_PROGRESS`, THEN THE SYSTEM SHALL rechazar la escritura del
   checklist con `409`.

### R5 — Cierre y regla de validación de PRD §11

**As a** manager, **I want** que una limpieza no pueda darse por buena a medias, **so that**
el siguiente huésped no entre a una vivienda sin verificar.

Acceptance criteria:

1. WHEN la limpiadora asignada solicite `POST /api/v1/cleaning-tasks/{id}/complete`, THE
   SYSTEM SHALL verificar que **todos** los ítems `required: true` de la plantilla están
   completados y responder `409` enumerando los que faltan cuando no sea así.
2. IF existe alguna incidencia `CRITICAL` sin resolver sobre la propiedad, THEN THE SYSTEM
   SHALL rechazar el cierre con `409`. **Nota de alcance**: `maintenance` aún no tiene capa de
   aplicación, así que hoy nada crea incidencias; el criterio se implementa contra la tabla
   `incidents` y se prueba insertando filas directamente, igual que la máquina de estados ya
   hace con su contexto.
3. WHEN el cierre supere la validación, THE SYSTEM SHALL pasar la tarea a `COMPLETED` con
   `completed_at`, poner `validation_status` en `PASSED` y disparar `CLEANING_COMPLETED`.
4. THE SYSTEM SHALL resolver el estado resultante de la propiedad con
   `after_cleaning_completion`, es decir `AWAITING_CHECKIN`, `READY_FOR_NEXT_GUEST` o
   `VACANT_READY` según haya reserva hoy, futura o ninguna (PRD §8.1).
5. WHEN un `PROPERTY_MANAGER` valide manualmente una tarea, THE SYSTEM SHALL registrar
   `validated_by_user_id` y `validated_at`.
   **ASSUMPTION**: se añade `POST /api/v1/cleaning-tasks/{id}/validate`, que PRD §23 no lista —
   su enumeración se detiene en `complete`. Es el mismo hueco del PRD que los endpoints de
   plantilla de R1 y se registra igual, con la convención de desviación de ADR 0005. Anotado al
   corregir el design en `/sdd:review`, donde el revisor de arquitectura vio que el endpoint
   existía en el código y en ningún artefacto.
6. THE SYSTEM SHALL dejar `ai_validation_result` sin escribir: la validación automática
   depende de `MockAIAdapter`, que llega con `messaging-ai` (PRD §26.12).

### R6 — Notificación de asignación con SLA

**As a** manager, **I want** enterarme cuando una limpiadora no responde, **so that** el SLA de
PRD §11 tenga efecto en vez de existir solo en la política.

Acceptance criteria:

1. WHEN una tarea pase a `ASSIGNED`, THE SYSTEM SHALL escribir una fila de `NotificationLog`
   con `notification_type = CLEANING_TASK_ASSIGNED`, `related_type`/`related_id` apuntando a
   la tarea y `sla_deadline_at = now + TenantConfig.sla_medium_minutes` (default 240,
   PRD §11).
2. THE SYSTEM SHALL escribir `subject` y `body` conforme al contrato que `celery-jobs` ya fijó
   para esas columnas (`steering/security.md` regla 11): se cumple el contrato vigente, no se
   deriva uno nuevo.
3. IF no hay ninguna `CLEANER` activa a la que asignar (R3.2), THEN THE SYSTEM SHALL notificar
   al manager de inmediato, sin plazo de SLA (PRD §11: «Si no hay limpiadora disponible:
   alertar a manager inmediatamente»).
4. WHEN la limpiadora acepte o rechace la tarea, THE SYSTEM SHALL **no** escribir una segunda
   notificación de asignación.
   **Recortado durante `/sdd:review` (panel de QA)**, y la redacción anterior queda aquí porque
   el recorte importa: pedía «cerrar el SLA pendiente de esa asignación para que
   `check_sla_breaches` no escale una asignación ya respondida», y eso **no se puede construir
   en este change**. Un candidato a incumplimiento exige `status = SENT`
   (`notifications/infrastructure/repositories.py:37`) y **nada marca `SENT`**: el emisor es de
   `access-notifications`. Es decir, lo que habría que cancelar no puede existir todavía, y el
   puerto no expone ninguna vía para hacerlo —`mark_breached` es deliberadamente estrecho y su
   docstring dice por qué—. La cancelación viaja con quien tenga el emisor y el derecho a tocar
   `status`; queda escrita en la entrada de roadmap `access-notifications` y en `BLOCKED.md`
   (OQ1). Lo que este change garantiza es lo de arriba, ni más ni menos.
5. THE SYSTEM SHALL demostrar con un test de extremo a extremo que una asignación sin
   respuesta pasado el plazo produce el escalado `SLA_BREACH` al `PROPERTY_MANAGER` que
   `notifications/domain/escalation.py:53-57` ya define y que hoy nunca se ejecuta.
6. THE SYSTEM SHALL limitarse a **persistir** la notificación: el envío real es de
   `access-notifications`, que trae el `NotificationAdapter`.

### R7 — API, aislamiento y autorización

**As a** propietaria, **I want** que las tareas de limpieza de mi tenant sean inaccesibles para
cualquier otro, **so that** la regla 1 de seguridad siga siendo absoluta y verificable.

Acceptance criteria:

1. WHEN se solicite `GET /api/v1/cleaning-tasks`, THE SYSTEM SHALL devolver únicamente las
   tareas del tenant del token, con el envelope paginado `{data, total, page, per_page,
   total_pages}` de PRD §23 y las mismas cotas de `page`/`per_page` que `reservations`.
2. WHILE el solicitante tenga rol `CLEANER`, THE SYSTEM SHALL devolver y admitir acción
   **solo** sobre las tareas cuya `assigned_cleaner_id` sea la suya — restricción a nivel de
   fila, adicional al scoping por tenant. `auth/domain/policy.py:53-54` ya declara que
   «`CLEANER` y `TECHNICIAN` ven solo sus propias tareas»; este change es el primero que tiene
   tareas sobre las que hacerlo cumplir.
3. IF se referencia una tarea, plantilla o propiedad que existe pero pertenece a otro tenant,
   THEN THE SYSTEM SHALL responder `404` y no `403`, sin revelar su existencia.
4. THE SYSTEM SHALL declarar permisos propios en `Permission`/`ROLE_PERMISSIONS` para cada
   endpoint nuevo y demostrar la **matriz completa de autorización por endpoint y por rol**
   para los cinco roles de PRD §6, tal como hicieron `reservations` y `user-management`.
5. THE SYSTEM SHALL demostrar con tests de aislamiento propios que
   `cleaning_checklist_completions` no es alcanzable desde otro tenant.
   Es obligación explícita y no rutina: no tiene columna `tenant_id` —scoping transitivo por
   FK, decidido en `domain-foundation-ops`—, y `tenant_scoped_classes()` selecciona **por
   columna** (`core/db.py:62`), así que el filtro global de defensa en profundidad **no la
   cubre** y todo el aislamiento recae en el `JOIN` con el padre.
   **Recortado durante `/sdd:review` (panel de QA)**: la redacción anterior decía
   «`cleaning_checklist_completions` **y `cleaning_photos`**», y la segunda mitad no cabe aquí.
   `cleaning_photos` no tiene en este change repositorio, ni adaptador, ni un solo escritor, así
   que un test de aislamiento sobre ella no demostraría nada — no existe camino que pudiera
   filtrar. Es el mismo recorte que §Out of scope ya hace con la subida de fotos y la validación
   por IA, y que a esta cláusula se le pasó. La obligación viaja íntegra en la entrada de
   roadmap `cleaning-photos-storage`, que la nombra con su razón.
6. THE SYSTEM SHALL regenerar `openapi.json` con los endpoints nuevos y mantener verde el
   check de deriva de `api-contract-export`.

## Out of scope

- **Fotos y `StorageAdapter`** — `POST`/`GET /api/v1/cleaning-tasks/{id}/photos`, el puerto de
  almacenamiento, su implementación `LOCAL`/`S3` (`TenantConfig.storage_type` ya existe), las
  signed URL con expiry 3600 s de la regla 5 de `steering/security.md` y la validación de MIME
  y tamaño de la regla 6. Va a la entrada nueva **`cleaning-photos-storage`**. El motivo es que
  es una pieza de infraestructura con diseño propio y `steering/backend-architecture.md` nombra
  precisamente al «`StorageAdapter` gigante con 15 métodos» como su ejemplo de fallo de
  segregación de interfaces (citado en `integrations/domain/ports.py:11`), así que dimensionar
  el puerto es una decisión, no un detalle.
  **Coste asumido y nombrado**: hasta que aterrice esa entrada, la regla de validación de
  PRD §11 se cumple **sin su cláusula de fotos** — una tarea puede cerrarse sin haber subido
  las fotos requeridas. Es el mismo tipo de hueco que este change viene a cerrar, así que
  queda anotado en la spec, no solo aquí.
- **Validación automática con IA** de las fotos (`ai_validation_result`): depende de
  `MockAIAdapter`, que llega con `messaging-ai` (PRD §26.12).
- **Creación de incidencias** desde la limpieza (el botón «reportar incidencia» de PRD §11):
  pertenece a `maintenance` (PRD §26.11). Este change solo **lee** incidencias para la
  precondición de cierre (R5.2).
- **Envío real** de notificaciones: `NotificationAdapter` es de `access-notifications`
  (PRD §26.14).
- **Todo el frontend**: la vista de manager y la app mobile-first de limpiadora son PRD §26.18
  y §26.19, entrada `field-apps`.
- **Reasignación automática tras rechazo o expiración**: `CLEANING_ASSIGNMENT_EXPIRED` existe
  como disparador, pero un job de reasignación es política operativa nueva. Este change deja
  la tarea en un estado desde el que el manager reasigna, y el escalado por SLA se lo dice.

## Affected specs

- `sdd/specs/cleaning.md` *(no existe aún — se creará al archivar)*
- `sdd/specs/celery-jobs.md` — sus líneas 126-127 declaran la deuda y la consecuencia
  («`AWAITING_CLEANING` es terminal en la práctica»); dejan de ser ciertas.
- `sdd/specs/domain-foundation-ops.md` — el scoping transitivo de
  `cleaning_checklist_completions`/`cleaning_photos` pasa de decisión de esquema a invariante
  con enforcement y test propio.
- `sdd/specs/user-management.md` — el catálogo de `Permission`/`ROLE_PERMISSIONS` crece con
  los permisos de limpieza y `CLEANER` deja de tener solo `_SELF_SERVICE`.
- `sdd/specs/api-contract.md` — `openapi.json` incorpora los endpoints nuevos.
- `sdd/specs/timeline-state-machine.md` — sin cambios de contrato; se anota que sus ramas de
  limpieza pasan a ejercitarse con datos reales.
