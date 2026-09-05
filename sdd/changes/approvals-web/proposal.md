# Proposal: approvals-web

## Why

Hay un **callejón sin salida alcanzable en uso normal**. Cuando el técnico cierra una incidencia
con un coste que cruza `owner_approval_threshold_eur` (default `Decimal("100.00")`,
`backend/app/tenants/domain/entities.py:151`), la incidencia aparca en `AWAITING_OWNER_APPROVAL`
(`maintenance/application/use_cases.py:2173`, y su gemela de presupuesto en `:1566`). A partir de
ahí:

- El técnico no puede seguir: `frontend/features/tech/lib/tech-actions.ts:31` ofrece —
  correctamente — **cero acciones** para ese estado.
- El manager no puede intervenir: `RESPOND_OWNER_APPROVALS` es del `TENANT_OWNER` y de nadie más
  (`backend/app/auth/domain/policy.py:367`).
- Y la propietaria **no tiene dónde responder**: `frontend/app/(workspace)/approvals/page.tsx` es
  un `RoutePlaceholder`. La ruta de respuesta existe
  (`backend/app/maintenance/api/approvals_router.py:39`) pero **la de lista no existe a propósito**
  (docstring de `approvals_router.py:3-8` y `sdd/specs/maintenance.md:588`: *«Ensancharlo es de
  quien traiga su bandeja»*). Esta entrada es esa bandeja.

Hoy la única pista de que hay una aprobación pendiente es el bloque de `detail.approvals` del
detalle de la propiedad (`frontend/features/dashboard/components/detail/property-detail-sections.tsx:129-146`),
que pinta etiqueta e importe **sin botón**.

Fuente: `sdd/roadmap/approvals-web.md` (hito «MVP operable» 1), PRD §12 «Regla de aprobación»,
PRD §23 R2, DoD §28.12, y el principio 4 de `sdd/steering/product.md` («Gastos > umbral requieren
aprobación del propietario»).

## What changes

Existirá una ruta de **lista** de aprobaciones del tenant y la pantalla `/approvals` que la
consume: cola de pendientes con la información suficiente para decidir sin abrir tres pantallas,
botones de aprobar/rechazar con motivo para la propietaria, lectura para el manager, e histórico
corto de las ya respondidas. Y el bucle se cierra por los dos extremos: la campana de la
propietaria lleva a donde puede actuar, y **el técnico se entera** de que su incidencia volvió a
su cola — hoy `RespondOwnerApprovalUseCase` (`use_cases.py:1608`) no escribe ninguna
notificación, y la fila `technician` de `frontend/features/notifications/lib/notification-destinations.ts`
está vacía aunque `frontend/app/(field)/tech/incidents/[id]` **ya existe** (medido: el comentario
que dice «Empty until `tech-app` delivers `/tech/incidents/[id]`» está obsoleto).

## Requirements

### R1 — La ruta de lista de aprobaciones

**Como** propietaria o manager, **quiero** consultar las aprobaciones de mi tenant por API,
**para que** exista un consumidor de la cola y no haya que descubrirlas propiedad a propiedad.

Criterios de aceptación:

1. WHEN un usuario autenticado con permiso de lectura de aprobaciones pide la lista, THE SYSTEM
   SHALL devolver las aprobaciones **de su `tenant_id`** — el del token, nunca un parámetro — con
   paginación, y las pendientes **primero la más antigua**, la misma disciplina que
   `OwnerApprovalReader.list_pending_for_property` (`maintenance/domain/repositories.py:234-247`)
   declara para el dashboard: esto es una lista de tareas pendientes.
2. WHEN no se indica estado, THE SYSTEM SHALL devolver **sólo las `PENDING`**; y SHALL aceptar un
   filtro por estado que permita pedir las ya respondidas.
3. WHEN devuelve una fila, THE SYSTEM SHALL incluir lo que hace falta para decidir sin navegar:
   identificador de la aprobación, `related_type`, importe y moneda, `requested_at`, la incidencia
   que la origina (id, título, categoría, severidad) y la vivienda **en forma legible** — nombre o
   código interno, no sólo el UUID.
4. THE SYSTEM SHALL exponer la lista bajo un permiso que alcancen `TENANT_OWNER` y
   `PROPERTY_MANAGER` y **no** `TECHNICIAN` ni `CLEANER`. *(Nota medida para el design: reutilizar
   `READ_INCIDENTS` incumple este criterio — `_INCIDENT_EXECUTE` lo incluye y `UserRole.TECHNICIAN`
   lo tiene, `policy.py:252` y `:425`, así que el técnico vería la cola de gastos del tenant.)*
5. IF quien pide la lista no tiene ese permiso, THEN THE SYSTEM SHALL responder `403` sin revelar
   si existen aprobaciones.
6. WHEN esta ruta entre en servicio, THE SYSTEM SHALL reescribir la declaración de ausencia
   deliberada que hoy sostienen `approvals_router.py:3-8`, `policy.py:66-67` y
   `sdd/specs/maintenance.md:588` — no ignorarla.

### R2 — La cola en `/approvals`

**Como** propietaria, **quiero** ver en una pantalla las aprobaciones que esperan mi respuesta,
**para que** dejar de ser el eslabón que bloquea al técnico no dependa de que alguien me pase un id.

Criterios de aceptación:

1. WHEN una propietaria o un manager abre `/approvals`, THE SYSTEM SHALL sustituir el
   `RoutePlaceholder` por la cola real de pendientes, con importe, vivienda legible, incidencia y
   cuánto lleva esperando.
2. WHEN no hay ninguna pendiente, THE SYSTEM SHALL mostrar un estado vacío explícito, no una tabla
   en blanco.
3. THE SYSTEM SHALL ofrecer, además de la cola, un **histórico corto** de las últimas respondidas
   con su resultado (`APPROVED`/`REJECTED`) y su fecha.
4. WHILE la lista carga o falla, THE SYSTEM SHALL usar los estados de carga y error del sistema de
   diseño ya vigente en las demás pantallas de la workspace, sin inventar formas nuevas.
5. THE SYSTEM SHALL escribir **toda** cadena nueva en `locales/es` y `locales/en`, sin literales en
   el componente.
6. WHEN se renderiza una fila, THE SYSTEM SHALL **no** pintar UUID crudos al usuario — misma norma
   que `notificationHref` aplica en `notification-destinations.ts`.

### R3 — La decisión, desde la cola

**Como** propietaria, **quiero** aprobar o rechazar con un motivo desde la propia cola, **para que**
la incidencia vuelva a moverse.

Criterios de aceptación:

1. WHERE el usuario es `TENANT_OWNER`, THE SYSTEM SHALL ofrecer en cada fila pendiente aprobar y
   rechazar, con un campo de motivo opcional que viaja como `response_notes`.
2. WHERE el usuario es `PROPERTY_MANAGER`, THE SYSTEM SHALL mostrar la cola **sin** esos botones —
   gateado por permiso en el cliente, como hace `conversation-thread-view.tsx`, sabiendo que la
   autorización real la impone el backend.
3. WHEN la propietaria confirma una decisión, THE SYSTEM SHALL invocar
   `POST /api/v1/owner-approvals/{id}/respond` y refrescar la cola con el resultado.
4. IF la aprobación ya había sido respondida (`OwnerApprovalAlreadyAnsweredError`), THEN THE SYSTEM
   SHALL mostrar el error traducido y recargar la cola, en vez de dejar en pantalla una fila que ya
   no existe.
5. WHEN la decisión es rechazar, THE SYSTEM SHALL advertir en la propia interfaz que eso **cancela
   la incidencia** — es lo que hace `respond` hoy (`use_cases.py:1665`), y no es reversible desde
   esta pantalla.
6. THE SYSTEM SHALL enviar `response_notes` tal cual lo teclea la persona, sin estructurarlo:
   `owner_approvals.response_notes` está censada bajo la **excepción 3** de la regla 11
   (`sdd/steering/security.md:196`, `:248`) y fuera de `AUDITABLE_FIELDS`. Esta pantalla es el
   primer escritor de esa columna desde la UI y **no** añade fila al censo ni columna nueva.

### R4 — El técnico se entera de que puede seguir

**Como** técnico, **quiero** enterarme de que la aprobación se resolvió, **para que** no tenga que
volver a abrir la incidencia por si acaso.

Criterios de aceptación:

1. WHEN una aprobación se responde y la incidencia tiene una persona asignada, THE SYSTEM SHALL
   escribir una notificación dirigida a esa persona diciendo si el gasto se aprobó o se rechazó.
2. THE SYSTEM SHALL usar para ello un `NotificationType` propio — hoy **ninguno de sus veinte
   miembros sirve** (`backend/app/notifications/domain/enums.py`), y hay precedente declarado para
   añadir uno fuera del catálogo de PRD §14 (`REVIEW_RESPONSE_APPROVED`, `PASSWORD_RESET_REQUESTED`).
3. IF la incidencia no tiene persona asignada, THEN THE SYSTEM SHALL no escribir notificación
   alguna y no fallar.
4. THE SYSTEM SHALL mantener el cuerpo de esa notificación en **forma cerrada** —constante más
   identificadores—, como el resto de `maintenance/domain/notifications.py`: no transporta ni
   `reason` ni `response_notes`.
5. THE SYSTEM SHALL escribirla dentro de la misma unidad de trabajo que ya cierra
   `RespondOwnerApprovalUseCase`, de modo que no exista una respuesta registrada sin su aviso.

### R5 — La campana lleva a donde se actúa

**Como** propietaria y como técnico, **quiero** que la notificación me deje en la pantalla donde
puedo hacer algo, **para que** el aviso no sea un callejón más.

Criterios de aceptación:

1. WHEN una notificación `OWNER_APPROVAL_REQUIRED` se muestra en la shell `workspace`, THE SYSTEM
   SHALL enlazar a `/approvals`. *(Hoy enlaza a la incidencia: la notificación se escribe con
   `related_type=RELATED_TYPE_INCIDENT` y `related_id=incident_id`,
   `maintenance/domain/notifications.py:194-196`, y la propietaria sólo tiene lectura sobre
   `/incidents/[id]`.)*
2. WHEN una notificación sobre una incidencia se muestra en la shell `technician`, THE SYSTEM SHALL
   enlazar a `/tech/incidents/{id}`, rellenando la fila `technician` de
   `NOTIFICATION_DESTINATIONS`, que está vacía y cuyo comentario justificativo —«until `tech-app`
   delivers `/tech/incidents/[id]`»— es falso: esa ruta existe.
3. THE SYSTEM SHALL conservar la invariante de `notificationHref`: un tipo sin destino, o una fila
   con `related_type`/`related_id` a medias, no produce enlace **y nunca imprime el UUID**.
4. THE SYSTEM SHALL dejar la fila `cleaner` como está — su cambio pertenece a quien entregue esa
   superficie.

## Out of scope

- **Cambiar `owner_approval_threshold_eur`** desde la web: es de `tenant-settings-web`, que ya lo
  declara. Esta pantalla lee el efecto del umbral, no lo edita.
- **Aprobaciones que no nacen de una incidencia.** `related_type` admite otros valores y
  `revenue-statements` tiene su propia vía; el job `reconcile_owner_approvals_for_expenses`
  (`scheduler/schedule.py`) ya la cose. R1 no impide que aparezcan en la lista, pero esta entrada
  no construye nada específico para ellas.
- **`EXPIRED` y la caducidad automática** de una aprobación: sigue fuera de alcance, como la dejó
  `maintenance`.
- **Notificar a la propietaria por WhatsApp o email** más allá de lo que
  `notification-channel-routing` decida: aquí sólo `IN_APP`.
- **Las mutaciones del manager sobre la incidencia** (asignar, triar, cancelar): son de
  `incident-triage-web`, en vuelo en paralelo.
- **Rehacer el bloque de aprobaciones del detalle de propiedad.** Puede enlazar a `/approvals`,
  pero su contrato (`OwnerApprovalSummary`, sin `reason` ni `response_notes`) no se toca.
- **Deshacer un rechazo.** `answer()` es de una sola vez por diseño (`entities.py:719`) y esta
  pantalla no lo reabre.

## ASSUMPTION / notas de verificación

- `ASSUMPTION`: la verificación manual que esta entrada debe dejar hecha —incidencia resuelta con
  coste final 150 € → aparece en `/approvals` → aprobar → el técnico la ve desbloqueada en `/tech`
  y la campana le lleva a ella— necesita una incidencia **asignada**, y hoy `assign` sólo tiene
  como llamante `cli/seed_demo.py` fuera de los tests (eso es lo que arregla `incident-triage-web`).
  Se asume que la pasada manual parte de `make bootstrap`/`seed_demo` o de la CLI, no de la UI.
- La segunda compuerta (coste final, `use_cases.py:2173`) **sí es alcanzable hoy desde el
  navegador** por el ciclo del técnico, así que el callejón sin salida se reproduce sin depender de
  ningún change en vuelo.

## Affected specs

- `sdd/specs/maintenance.md` — reescribe la limitación declarada de `:588` («no hay ruta de lectura
  de aprobaciones ni permiso `READ_OWNER_APPROVALS`») y añade la ruta de lista y la notificación de
  R4.
- `sdd/specs/auth-tenancy.md` — el permiso nuevo y su reparto por rol.
- `sdd/specs/api-contract.md` — la ruta nueva en el contrato publicado y su regeneración en el
  cliente tipado.
- `sdd/specs/access-notifications.md` — el `NotificationType` nuevo de R4 y su escritor.
- `sdd/specs/notifications-inbox-web.md` — los destinos de R5 (`workspace` → `/approvals`,
  `technician` → `/tech/incidents/[id]`).
- `sdd/specs/approvals-web.md` — *(no existe aún — se creará al archivar)*: la pantalla y su
  contrato.
