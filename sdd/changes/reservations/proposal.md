# Proposal: reservations

## Why

La app tiene infra, CD, HTTPS, auth/RBAC/tenencia y un dominio modelado, pero
**ni un endpoint de negocio**: `main.py` monta un solo router, el de auth. La
reserva es el dato del que cuelga todo lo demás — la máquina de estados de
propiedad resuelve su precedencia a partir de "reserva activa" y "próxima
reserva" (`specs/timeline-state-machine.md`), y limpieza, acceso, mensajería y
statements se disparan desde el ciclo de una reserva. Sin reservas persistidas y
gestionables, `celery-jobs`, `cleaning` y el dashboard no tienen sobre qué
operar.

Esta entrada es el paso 9 del orden de desarrollo del PRD (§26.9) y cubre
PRD §16 (integración PMS) y §7.7 (entidad `Reservation`, ya modelada y migrada en
`domain-foundation-core`).

Además es el **primer módulo que persiste `TimelineEvent`**:
`timeline-state-machine` se archivó como dominio puro que "no persiste ni muta la
propiedad", así que hoy existe la fábrica de eventos validada y no existe ninguna
escritura. El timeline auditable es el principio 1 de `steering/product.md`, y
esta capability es la primera que lo materializa en base de datos.

## What changes

Aparece el módulo `reservations` completo de backend siguiendo la arquitectura
hexagonal por dominios que ya usa `auth` (`domain/` → `application/use_cases` →
`infrastructure/repositories` → `api/router`): los cinco endpoints de
`/api/v1/reservations` de PRD §23 con RBAC y aislamiento por tenant, la
persistencia de los `TimelineEvent` que cada mutación genera —en la misma
transacción que la mutación—, el puerto `PMSAdapter` con su `MockPMSAdapter` y
una sincronización idempotente por `external_pms_id`, y la importación manual por
CSV de PRD §16 (`POST /api/v1/integrations/pms/import-csv`) con informe por
filas. Las reservas quedan vinculadas a `Guest` cuando el origen aporta datos de
huésped.

**Lo que esta entrada del roadmap NO puede cerrar**: el `webhook handling`
(cuarto ítem de la entrada) depende de dos entradas anteriores del roadmap que
siguen sin empezar — la entidad `WebhookEvent` (PRD §7.26) pertenece a
`domain-foundation-financial`, y PRD §16 exige que el evento se guarde con
`processed=FALSE` y lo procese el job Celery `process_webhook_events`, que
pertenece a `celery-jobs`. No se implementa aquí a medias ni se le roba la
entidad a la entrada que la posee; ver *Out of scope* y la nota de cierre.

## Requirements

### R1 — CRUD de reservas

**As a** PROPERTY_MANAGER, **I want** crear, consultar, editar y cancelar
reservas por API, **so that** la operación diaria deje de depender de datos
sembrados a mano en la base de datos.

Acceptance criteria:

1. WHEN se solicita `GET /api/v1/reservations`, THE SYSTEM SHALL devolver
   únicamente las reservas del tenant del token, paginadas, admitiendo filtros
   por `property_id`, `status` y rango de fechas de estancia.
2. WHEN se solicita `POST /api/v1/reservations` con datos válidos, THE SYSTEM
   SHALL crear la reserva con `channel` `MANUAL` o `DIRECT`, derivar `nights`
   como la diferencia entre `check_out_date` y `check_in_date` y `total_guests`
   como `adults + children`, y responder `201` con el recurso creado.
3. IF `check_out_date` no es posterior a `check_in_date`, o `adults` es menor que
   1, o `children` es negativo, THEN THE SYSTEM SHALL rechazar la petición con
   `422` en el envelope de error de PRD §23 sin escribir nada.
4. IF la `property_id` indicada no existe en el tenant del token, THEN THE SYSTEM
   SHALL responder `404`.
5. WHEN se solicita `PATCH /api/v1/reservations/{id}`, THE SYSTEM SHALL aplicar
   solo los campos presentes en el cuerpo, revalidar las invariantes de fechas y
   ocupación sobre el resultado, y recalcular `nights` y `total_guests` cuando sus
   campos de origen cambien.
6. WHEN se solicita `DELETE /api/v1/reservations/{id}`, THE SYSTEM SHALL pasar la
   reserva a `status` `CANCELLED` conservando la fila —cancelación, no borrado
   físico— y responder `204`.
7. IF la reserva referida ya está en `CANCELLED` y se solicita `DELETE`, THEN THE
   SYSTEM SHALL responder `204` sin generar un segundo evento de cancelación.
8. WHEN se solicita `GET /api/v1/reservations/{id}` de una reserva del tenant,
   THE SYSTEM SHALL devolver la reserva con su huésped vinculado si existe, sin
   exponer ningún dato de documento del huésped.

### R2 — Timeline persistido en la misma transacción

**As a** propietaria, **I want** que toda alta, edición, cancelación e
importación de reserva deje su evento en el timeline, **so that** el historial de
la vivienda sea auditable de verdad y no una reconstrucción a posteriori.

Acceptance criteria:

1. WHEN una reserva se crea por API, THE SYSTEM SHALL persistir un
   `TimelineEvent` `RESERVATION_CREATED_MANUAL` con `actor_type` `USER` y el
   `actor_user_id` del token, referido a la propiedad y a la reserva.
2. WHEN una reserva se modifica por API, THE SYSTEM SHALL persistir un
   `RESERVATION_UPDATED` cuyo `metadata` registre los campos cambiados.
3. WHEN una reserva se cancela, THE SYSTEM SHALL persistir un
   `RESERVATION_CANCELLED`.
4. WHEN una reserva se crea por sincronización con el PMS, THE SYSTEM SHALL
   persistir un `RESERVATION_IMPORTED` con `actor_type` `SYSTEM` y sin
   `actor_user_id`.
5. WHEN una reserva se crea por importación CSV, THE SYSTEM SHALL persistir un
   `RESERVATION_IMPORTED` con `actor_type` `USER` y el `actor_user_id` de quien
   subió el fichero — la importación manual la ejecuta una persona identificada,
   no el sistema.
6. WHILE se escribe una mutación de reserva, THE SYSTEM SHALL persistir la
   reserva y su evento de timeline en una única transacción, de modo que un fallo
   al escribir el evento deje la reserva sin cambiar.
7. WHEN se construye cualquiera de esos eventos, THE SYSTEM SHALL hacerlo a
   través de la fábrica de dominio ya existente, sin duplicar sus validaciones en
   la capa de aplicación.

### R3 — Puerto `PMSAdapter` y sincronización idempotente

**As a** manager, **I want** traer reservas del PMS externo por un adapter
sustituible, **so that** el día que haya credenciales de Octorate/Smoobu solo
haya que cambiar la implementación.

Acceptance criteria:

1. WHEN el módulo declara su dependencia del PMS, THE SYSTEM SHALL hacerlo como
   un puerto `PMSAdapter` en la capa de dominio, con `MockPMSAdapter` como única
   implementación de este change y marcada `EXTERNAL_DEPENDENCY`.
2. WHEN se sincroniza una reserva cuyo `external_pms_id` ya existe en el tenant,
   THE SYSTEM SHALL actualizar la reserva existente en lugar de crear una
   segunda, y no SHALL emitir `RESERVATION_IMPORTED` por una reserva ya conocida.
3. WHEN se sincroniza dos veces el mismo conjunto de reservas sin cambios
   externos, THE SYSTEM SHALL dejar el mismo número de reservas y no añadir
   eventos de timeline en la segunda pasada.
4. IF una reserva del PMS referencia una propiedad que no existe en el tenant,
   THEN THE SYSTEM SHALL omitir esa reserva e informarla como error de la
   sincronización, sin abortar las restantes.
5. WHEN una reserva del PMS aporta datos de huésped, THE SYSTEM SHALL vincularla
   a un `Guest` del tenant reutilizando el que coincida por email normalizado y
   creándolo si no existe.

### R4 — Importación manual por CSV

**As a** manager, **I want** subir un CSV de reservas, **so that** poder cargar
la operación real sin esperar a la integración con el PMS.

Acceptance criteria:

1. WHEN se solicita `POST /api/v1/integrations/pms/import-csv` con un fichero
   válido, THE SYSTEM SHALL importar las filas válidas y responder un informe con
   el número de reservas creadas, actualizadas y omitidas.
2. IF una fila es inválida, THEN THE SYSTEM SHALL omitir esa fila, continuar con
   el resto e incluir en el informe su número de línea y el motivo.
3. WHEN el fichero supera el límite configurado de tamaño o de número de filas,
   THE SYSTEM SHALL rechazarlo con `413` sin importar ninguna fila.
4. IF el fichero no es un CSV con las columnas requeridas, THEN THE SYSTEM SHALL
   responder `422` describiendo las columnas que faltan.
5. WHEN una fila trae un `external_pms_id` ya presente en el tenant, THE SYSTEM
   SHALL aplicar la misma regla de idempotencia que la sincronización (R3.2).

### R5 — Aislamiento por tenant y autorización por rol

**As a** propietaria, **I want** que ningún usuario vea ni toque reservas de otro
tenant y que cada rol pueda hacer exactamente lo que le corresponde, **so that**
la regla 1 de `steering/security.md` siga siendo verificable cuando el sistema
deja de ser autorreferencial.

Acceptance criteria:

1. WHEN un usuario autenticado referencia por `id` una reserva que existe pero
   pertenece a otro tenant, THE SYSTEM SHALL responder `404` y no `403`, sin
   revelar que el recurso existe.
2. WHEN un usuario autenticado lista reservas, THE SYSTEM SHALL derivar el
   `tenant_id` del token y no SHALL aceptarlo como parámetro de la petición.
3. WHEN se registra cualquier endpoint nuevo de este módulo, THE SYSTEM SHALL
   declarar su permiso explícito, de modo que el recorrido de rutas existente
   siga fallando si alguno no lo declara.
4. WHERE el rol es `PROPERTY_MANAGER`, THE SYSTEM SHALL permitir crear, editar,
   cancelar, listar, consultar, sincronizar e importar.
5. WHERE el rol es `TENANT_OWNER`, THE SYSTEM SHALL permitir listar y consultar,
   y SHALL denegar con `403` crear, editar, cancelar, sincronizar e importar.
6. WHERE el rol es `CLEANER`, `TECHNICIAN` o `SUPER_ADMIN`, THE SYSTEM SHALL
   denegar con `403` todos los endpoints de este módulo.
7. WHEN se ejecuta la suite, THE SYSTEM SHALL demostrar con tests la matriz
   completa endpoint × rol de los cinco roles, y que un usuario del tenant A no
   obtiene ni modifica reservas del tenant B.

## Out of scope

- **`webhook handling` (PRD §16, endpoint `POST /api/v1/webhooks/{provider}`)** —
  requiere la entidad `WebhookEvent` (PRD §7.26), que la entrada
  `domain-foundation-financial` posee y que aún no existe en el esquema, y el job
  `process_webhook_events`, que pertenece a `celery-jobs`. Se retoma cuando
  ambas hayan pasado; no se le roba la entidad a su entrada ni se implementa una
  recepción que no persista lo que el PRD exige persistir.
- **Transiciones de estado operacional disparadas por reservas**
  (`AWAITING_CHECKIN`, `OCCUPIED_ESTIMATED`, `CHECKOUT_*`) — son dependientes del
  reloj y pertenecen a `celery-jobs` (PRD §26.8). Este change persiste reservas y
  eventos de timeline; no invoca la máquina de estados.
- **El resto del protocolo `PMSAdapter`** (`update_price`, `block_dates`,
  `get_availability`, `list_properties`, `get_messages`, `send_message`) — llegan
  con `revenue` y `messaging-ai`. Aquí solo `list_reservations` y
  `get_reservation`.
- **Frontend de reservas** (`/reservations`, PRD §24) — pertenece a
  `dashboard-web`.
- **Captura de documento y flujo SES.Hospedajes** (PRD §17) — el campo
  `legal_registration_status` existe en la entidad y se deja en su default;
  el flujo es de `access-notifications` y `guest-portal`.
- **Exponer la API a internet** — sigue siendo `api-ingress-routing`; estos
  endpoints se verifican con tests y, en dev, por túnel SSH (RUNBOOK §7.4).
- **`AuditLog` de las mutaciones** — la entidad pertenece a
  `domain-foundation-financial`. El rastro de este change es el `TimelineEvent`,
  que sí existe.

## Affected specs

- `sdd/specs/reservations.md` *(no existe aún — se creará al archivar)*
- `sdd/specs/auth-tenancy.md` — el catálogo de `Permission` y la matriz de roles
  crecen con los permisos de este módulo.
- `sdd/specs/timeline-state-machine.md` — sigue siendo dominio puro, pero deja de
  ser cierto que nadie persiste sus eventos: la spec debe apuntar dónde vive esa
  persistencia.

## Nota de cierre de la entrada del roadmap

Esta entrada del roadmap queda **parcialmente entregada**: tres de sus cuatro
ítems (CRUD, `MockPMSAdapter`, import CSV) se cierran aquí; el cuarto
(`webhook handling`) queda pendiente de `domain-foundation-financial` y
`celery-jobs` por la razón documentada arriba. Al archivar hay que decidir
explícitamente si la entrada se marca `[x]` con una entrada nueva de seguimiento
para los webhooks, o si se deja abierta hasta que el cuarto ítem exista.
