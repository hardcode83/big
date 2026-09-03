# Proposal: staff-messaging

## Why

Hoy la comunicación con el personal de campo es estrictamente unidireccional: el sistema le
escribe filas de `NotificationLog` a la limpiadora y al técnico (asignación, recordatorio de
SLA…), y no existe ninguna vía de respuesta. `MessageSenderType` tiene cinco miembros —`GUEST`,
`OWNER`, `MANAGER`, `AI`, `SYSTEM`— y ninguno de campo; `ROLE_PERMISSIONS` da a `CLEANER`
exactamente `_SELF_SERVICE | _CLEANING_EXECUTE` y a `TECHNICIAN`
`_SELF_SERVICE | _INCIDENT_EXECUTE`, así que las siete rutas de `/conversations` les contestan
`403` (verificado en `backend/app/auth/domain/policy.py`); y `policy.py` lo argumenta por
escrito: *"`CLEANER` and `TECHNICIAN` get neither — a guest's conversation is not part of doing a
cleaning or a repair"*. Cuando una limpiadora necesita aclarar algo de una tarea, o un técnico
algo de una incidencia, hoy no tiene ningún canal dentro del producto para contestar al manager.

Entrada de roadmap `staff-messaging` (añadida el 2026-08-28, análisis largo en
`sdd/roadmap/staff-messaging.md`); depende de `cleaning`, `maintenance` y `access-notifications`,
las tres archivadas.

## What changes

Un hilo de mensajes **acotado a la tarea de limpieza o a la incidencia**, no a `Conversation`
(que sigue siendo del huésped por contrato — ver más abajo por qué no se ensancha). La limpiadora
puede escribir y leer mensajes sobre su propia tarea asignada; el técnico, sobre su propia
incidencia asignada; el manager puede escribir y leer en cualquier hilo de su tenant. Cada mensaje
nuevo notifica al otro extremo por la bandeja in-app que ya sirve `access-notifications`
(`NotificationLog`, con `recipient_user_id` y `related_type`/`related_id` apuntando a la tarea o
la incidencia).

**Decisiones de diseño, resueltas en `design.md`**: la persistencia son dos entidades nuevas
gemelas, `CleaningTaskMessage`/`IncidentMessage` (D1 — no una tabla polimórfica), y el mensaje
**no** genera `TimelineEvent` (D6, decidido con el usuario el 2026-09-02) — el timeline queda
para estados operacionales de la propiedad, no para un log de chat.

## Requirements

### R1 — Hilo limpiadora↔manager sobre una tarea de limpieza

**As a** limpiadora, **I want** escribir y leer mensajes ligados a mi tarea de limpieza asignada,
**so that** pueda resolver dudas con el manager sin salir del flujo de la tarea.

Acceptance criteria:

1. WHEN `CLEANER` envía un mensaje sobre una tarea de limpieza cuyo `assigned_cleaner_id` es el
   suyo, THE SYSTEM SHALL persistirlo y devolver `201` con el mensaje creado (autor, contenido,
   timestamp).
2. WHEN `CLEANER` solicita los mensajes de una tarea cuyo `assigned_cleaner_id` es el suyo,
   THE SYSTEM SHALL devolver `200` con los mensajes de esa tarea en orden cronológico.
3. IF `CLEANER` intenta leer o escribir en una tarea cuyo `assigned_cleaner_id` no es el suyo (o
   que no existe en su tenant), THEN THE SYSTEM SHALL responder como si la tarea no existiera —
   mismo código y mismo cuerpo que el resto de rutas de `cleaning` acotadas por
   `restrict_to_cleaner_id` (`CleaningTaskNotFoundError`, nunca `403`, para no convertir el
   endpoint en una sonda de qué tareas existen).
4. WHEN `PROPERTY_MANAGER` envía o solicita mensajes sobre cualquier tarea de limpieza de su
   tenant, THE SYSTEM SHALL permitirlo sin la restricción de R1.1/R1.2 — el manager opera el
   tenant entero, igual que ya hace en el resto de `cleaning`.
5. El scoping SHALL derivarse del rol persistido del llamante (`CleaningActor`), nunca de un
   campo de la petición — mismo patrón que `restrict_to_cleaner_id` (design D7 de `cleaning`).

### R2 — Hilo técnico↔manager sobre una incidencia

**As a** técnico, **I want** escribir y leer mensajes ligados a mi incidencia asignada,
**so that** pueda coordinarme con el manager sin salir del flujo de la incidencia.

Acceptance criteria (espejo de R1 sobre `maintenance`):

1. WHEN `TECHNICIAN` envía un mensaje sobre una incidencia cuyo `assigned_technician_id` es el
   suyo, THE SYSTEM SHALL persistirlo y devolver `201`.
2. WHEN `TECHNICIAN` solicita los mensajes de una incidencia cuyo `assigned_technician_id` es el
   suyo, THE SYSTEM SHALL devolver `200` con los mensajes en orden cronológico.
3. IF `TECHNICIAN` intenta leer o escribir en una incidencia que no es la suya, THEN THE SYSTEM
   SHALL responder como si no existiera (`IncidentNotFoundError`, nunca `403` — mismo patrón que
   `GetIncidentUseCase`, D3 de `tech-incident-context`).
4. WHEN `PROPERTY_MANAGER` envía o solicita mensajes sobre cualquier incidencia de su tenant,
   THE SYSTEM SHALL permitirlo sin la restricción de R2.1/R2.2.
5. El scoping SHALL derivarse del rol persistido del llamante (`IncidentActor`), nunca de un
   campo de la petición — mismo patrón que `restrict_to_technician_id` (D13 de `maintenance`).

### R3 — Permisos nuevos y aislamiento de tenant

**As a** sistema, **I want** que estas rutas exijan un permiso propio y verificable, **so that**
ningún rol obtenga acceso implícito a mensajería de personal por tener otro permiso operativo.

Acceptance criteria:

1. THE SYSTEM SHALL gatear lectura y escritura de estos mensajes con permisos existentes de cada
   dominio — `READ_CLEANING_TASKS` y (`EXECUTE_CLEANING_TASKS` o `MANAGE_CLEANING_TASKS`) para el
   hilo de limpieza; `READ_INCIDENTS` y `EXECUTE_INCIDENTS` para el hilo de incidencia — de modo
   que `CLEANER` (acotado a lo suyo por R1.5), `TECHNICIAN` (acotado a lo suyo por R2.5) y
   `PROPERTY_MANAGER` (tenant completo) queden cubiertos sin declarar ningún permiso nuevo en
   `Permission`/`ROLE_PERMISSIONS`. *(Amienda la redacción original de este criterio — pedía "al
   menos un permiso nuevo" — con la decisión D3 de `design.md`, verificada contra
   `backend/app/auth/domain/policy.py`: los cuatro roles ya tienen, hoy, el permiso equivalente
   sobre la entidad padre.)*
2. THE SYSTEM SHALL mantener toda query acotada por `tenant_id` (regla 1 de `steering/security.md`)
   y llevar un test automático que demuestre que un tenant no accede a los mensajes de otro —
   obligatorio para todo módulo nuevo.
3. `MessageSenderType` (`app/messaging/domain/enums.py`) es del dominio `messaging` y de la
   `Conversation` del huésped; THE SYSTEM SHALL NOT reutilizarlo para el remitente de estos
   mensajes ni ensanchar `Conversation`/`READ_CONVERSATIONS`/`MANAGE_CONVERSATIONS` para dar
   cabida a `CLEANER`/`TECHNICIAN` — ver «What changes» sobre por qué el hilo va acotado a la
   tarea/incidencia y no a `Conversation`.

### R4 — Notificación al otro extremo

**As a** destinatario (manager, limpiadora o técnico), **I want** enterarme de un mensaje nuevo en
mi hilo sin tener que refrescar la pantalla activamente, **so that** la conversación sea útil en
la práctica y no solo un histórico que hay que ir a mirar.

Acceptance criteria:

1. WHEN se crea un mensaje de personal (R1.1, R1.4, R2.1, R2.4), THE SYSTEM SHALL encolar una
   `NotificationLog` dirigida al destinatario que no lo escribió, con `related_type`/`related_id`
   apuntando a la tarea o la incidencia — mismo mecanismo que ya usa `access-notifications` para
   la bandeja in-app.
2. IF quien escribe es `CLEANER` o `TECHNICIAN`, THEN THE SYSTEM SHALL notificar a **todos** los
   `PROPERTY_MANAGER` del tenant (una fila de `NotificationLog` por cada uno) — decisión D9 de
   `design.md`, tomada con el usuario el 2026-09-02: hoy no existe el concepto de manager
   asignado a una tarea o incidencia (solo `assigned_cleaner_id`/`assigned_technician_id`), y
   introducirlo queda fuera de alcance de este change.
3. IF quien escribe es `PROPERTY_MANAGER`, THEN THE SYSTEM SHALL notificar a la limpiadora o el
   técnico asignado a la tarea/incidencia.

### R5 — Contenido gobernado por la regla 11

**As a** sistema, **I want** que el contenido del mensaje pase por el mismo guardián que el resto
de sumideros de texto libre, **so that** no se abra un nuevo hueco frente a la regla 11 de
`steering/security.md`.

Acceptance criteria:

1. THE SYSTEM SHALL acotar el contenido del mensaje a un máximo de caracteres (mismo límite que
   `messages.content`, 4000, salvo que `/sdd:design` justifique otro) y SHALL rechazar el exceso
   antes de persistir.
2. THE SYSTEM SHALL pasar el contenido por el guardián de `app/core/storable_text.py` antes de
   escribirlo.
3. El nuevo sumidero de texto libre SHALL tener su fila propia en el censo de la regla 11 de
   `steering/security.md` (la tabla que hoy documenta `messages.content` y los sumideros de
   `maintenance`) antes de que este change se archive.

## Out of scope

- **Huésped↔limpiadora y huésped↔técnico**: nadie lo ha pedido, PRD §11 y §12 no lo contemplan, y
  abriría la identidad del personal a un portador anónimo de token.
- **IA, escalación e intents** sobre estos hilos: no tocan `messaging` ni `Conversation`; la IA no
  interviene en la comunicación de personal.
- **Ensanchar `Conversation`** o dar a `CLEANER`/`TECHNICIAN` `READ_CONVERSATIONS` —ver R3.3—.
- ~~**Visibilidad de `TENANT_OWNER`** sobre estos hilos~~ — **amendado por `design.md` D3**:
  reutilizar `READ_CLEANING_TASKS`/`READ_INCIDENTS` para la lectura (decisión ya tomada por D3
  para evitar un permiso dedicado) concede a `TENANT_OWNER` lectura tenant-wide de ambos hilos
  como efecto colateral, porque ya tiene esos dos permisos vía `_CLEANING_READ`/`_INCIDENT_READ`.
  Ningún requisito la pedía explícitamente, pero excluirla exigiría reintroducir la fuente de
  verdad duplicada (un permiso o una restricción de rol dedicados) que D3 decidió evitar. Se
  acepta: `TENANT_OWNER` puede leer ambos hilos desde esta entrega.
- **Escribir en una tarea/incidencia en estado terminal**: no se restringe explícitamente en este
  proposal (el scoping por asignación de R1/R2 no filtra por estado, igual que
  `restrict_to_cleaner_id`/`restrict_to_technician_id` hoy no lo hacen para lectura), pero si
  `/sdd:design` decide cerrarlo, es una restricción adicional sobre R1/R2, no un cambio de
  alcance.
- **Manager "de guardia"/asignado a una tarea o incidencia**: no se introduce (D9 de
  `design.md`); R4.2 notifica a todos los `PROPERTY_MANAGER` del tenant.
- **`TimelineEvent`** por cada mensaje: no se genera (D6 de `design.md`) — el timeline queda para
  estados operacionales de la propiedad, no para un log de chat.

## Affected specs

- `sdd/specs/cleaning.md` — se amplía con el hilo de mensajes de la tarea.
- `sdd/specs/maintenance.md` — se amplía con el hilo de mensajes de la incidencia.
- `sdd/specs/access-notifications.md` — nuevo `notification_type`/`related_type` para estos
  mensajes.
- `sdd/steering/security.md` — nueva fila en el censo de la regla 11 para el contenido del
  mensaje de personal (R5.3).
- `sdd/specs/staff-messaging.md` *(no existe aún — se creará al archivar)*.
