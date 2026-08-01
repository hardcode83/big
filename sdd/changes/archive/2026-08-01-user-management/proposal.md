# Proposal: user-management

## Why

`auth-tenancy` dejó fuera a propósito el alta y la administración de usuarios: hoy los
usuarios entran **solo** por `python -m app.cli.bootstrap`, que crea el tenant inicial, su
`TenantConfig` y dos cuentas (`TENANT_OWNER` y `PROPERTY_MANAGER`). Dar de alta una
limpiadora o un técnico exige, literalmente, entrar en la VM y ejecutar un comando — y las
capacidades que vienen detrás (`cleaning` asigna tareas a un `CLEANER`, `maintenance`
tickets a un `TECHNICIAN`) no tienen a quién asignárselas sin eso.

Los endpoints de tenant (`GET`/`PATCH /api/v1/tenants/{id}`) están en PRD §23 y **no los
cubre ninguna otra entrada del roadmap**: `hardening-release` solo tiene el frontend de
settings, que los consume. Sin ellos, el umbral de aprobación del propietario (principio 4
de `steering/product.md`), los SLAs y las ventanas de check-in/checkout solo se cambian por
SQL, y `celery-jobs` los va a leer cada minuto.

Esta capacidad es además el **primer escritor real de `audit_logs`**, cuya entidad llegó con
`domain-foundation-financial`, así que le toca instanciar el contrato de la regla 11 de
`steering/security.md` para `audit_logs.changes` y la regla 9 para los cambios de rol.

Fuentes: PRD §23 (endpoints), §6 (roles), §22 (seguridad), `specs/auth-tenancy.md`
(alcance declarado), `specs/reservations.md` (patrón de API de negocio ya establecido),
ADR 0005 (unicidad global del email).

## What changes

Después de este change existe la administración del tenant por API: los cinco endpoints de
usuarios de PRD §23 (`GET`/`POST /api/v1/users`, `GET`/`PATCH`/`DELETE
/api/v1/users/{id}`), un reset de contraseña asistido por administrador
(`POST /api/v1/users/{id}/reset-password`, adición deliberada a §23), y
`GET`/`PATCH /api/v1/tenants/{id}` cubriendo el `Tenant` y su `TenantConfig` como un solo
recurso. Toda mutación deja un `AuditLog` en la misma transacción, con `changes` en forma
estructurada. La contraseña de un usuario nuevo la **genera el sistema** y se devuelve una
sola vez; nadie más la vuelve a ver.

Se cierran de paso dos deudas ajenas cuya condición cumple este change: la consolidación de
`app/auth/infrastructure/unit_of_work.py` con `app/core/unit_of_work.py` (ocho líneas
duplicadas, asignada en `specs/reservations.md` al "próximo change que toque `auth`"), y los
dos criterios bloqueantes que `auth-tenancy` no pudo verificar sobre endpoints
autorreferenciales (R7 aquí abajo).

**Decisiones de alcance ya tomadas** (respuestas del dueño del change, 2026-07-31):
contraseña temporal generada y devuelta una vez —no invitación por email, que dependería del
`NotificationAdapter` de `access-notifications`—; `TENANT_OWNER` administra y
`PROPERTY_MANAGER` solo lee; el reset asistido entra.

**Pendiente de `/sdd:design`**: si la administración de usuarios vive en `app/auth/` (donde
están hoy `UserModel`, `User` y `UserRepository`) o en un módulo `app/users/` propio.

## Requirements

### R1 — Alta de usuario con contraseña temporal

**As a** `TENANT_OWNER`, **I want** crear cuentas para mi personal desde la API, **so that**
pueda incorporar una limpiadora o un técnico sin entrar en la VM a ejecutar un comando.

Acceptance criteria:

1. WHEN se solicita `POST /api/v1/users` con datos válidos, THE SYSTEM SHALL crear el
   usuario en el tenant del token con estado `ACTIVE` y responder `201` con el recurso
   creado y la contraseña temporal generada.
2. THE SYSTEM SHALL generar la contraseña temporal con un generador criptográficamente
   seguro y devolverla **exactamente una vez**, en el cuerpo del `201`, y no SHALL
   persistirla en claro, escribirla en el log de la aplicación, en `audit_logs.changes` ni
   en ningún `TimelineEvent`.
3. THE SYSTEM SHALL derivar el `tenant_id` del token y no SHALL aceptarlo en el cuerpo, la
   query ni la ruta.
4. IF el email normalizado ya existe bajo **cualquier** tenant, THEN THE SYSTEM SHALL
   responder `409` con un mensaje accionable, y no SHALL nombrar el tenant al que pertenece
   la dirección existente.
5. THE SYSTEM SHALL apoyar esa unicidad en el índice `uq_users_lower_email` traduciendo su
   violación, y no en una comprobación previa: dos altas simultáneas con la misma dirección
   pasarían las dos la comprobación y una acabaría en `500` sobre el índice.
6. IF el rol solicitado es `SUPER_ADMIN`, THEN THE SYSTEM SHALL responder `422`: sus
   capacidades en PRD §6 son globales, no operativas de un tenant, y su visibilidad
   cross-tenant está diferida a `saas-cross-tenant` — crear uno desde dentro de un tenant
   sería concederse un rol cuyo alcance esta capacidad no puede acotar.
7. THE SYSTEM SHALL normalizar el email (recortado y en minúsculas) al escribir, igual que
   `auth-tenancy`, y validar que `preferred_language` es `es` o `en`.

### R2 — Listado y consulta de usuarios

**As a** `PROPERTY_MANAGER`, **I want** ver quién trabaja en el tenant y con qué rol, **so
that** pueda asignar limpiezas e incidencias a la persona correcta.

Acceptance criteria:

1. WHEN se solicita `GET /api/v1/users`, THE SYSTEM SHALL devolver únicamente los usuarios
   del tenant del token, paginados con `page`/`per_page` y el envelope
   `{data, total, page, per_page, total_pages}` de PRD §23.
2. THE SYSTEM SHALL acotar `per_page` a 100 y `page` a 100.000 respondiendo `422` fuera de
   esos rangos, igual que `reservations`: `page` se traduce en un `OFFSET` de SQL y un valor
   sin cota desborda y produce un error de driver en vez de una respuesta del envelope.
3. THE SYSTEM SHALL ordenar el listado por un criterio estable con el `id` como segundo
   criterio, de modo que paginar no muestre una fila dos veces ni omita otra.
4. WHEN el listado recibe un filtro por rol o por estado, THE SYSTEM SHALL aplicarlo (los
   índices `ix_users_tenant_id_role` e `ix_users_tenant_id_status` ya existen).
5. THE SYSTEM SHALL NOT exponer `password_hash` en ninguna respuesta de esta capacidad.
6. WHEN se solicita `GET /api/v1/users/{id}` de un usuario del tenant, THE SYSTEM SHALL
   devolverlo.

### R3 — Edición, cambio de rol y baja

**As a** `TENANT_OWNER`, **I want** corregir los datos de una cuenta, cambiar su rol y darla
de baja, **so that** el acceso al sistema refleje quién trabaja hoy conmigo y en qué.

Acceptance criteria:

1. WHEN se solicita `PATCH /api/v1/users/{id}`, THE SYSTEM SHALL aplicar solo los campos
   presentes en el cuerpo, sobre `name`, `phone`, `preferred_language`, `email`, `role` y
   `status`.
2. THE SYSTEM SHALL rechazar en `PATCH` los campos que no le pertenecen (`tenant_id`,
   `password_hash`, `last_login_at`, `id`, los de auditoría) con `422`.
3. WHEN un `PATCH` cambia el email, THE SYSTEM SHALL normalizarlo y aplicar la misma
   traducción a `409` de R1.4: la dirección **es** la identidad de login (ADR 0005), y sin
   esta vía un typo en el email del único propietario solo se corrige por SQL.
4. WHEN un `PATCH` cambia el rol, THE SYSTEM SHALL registrar un `AuditLog` con el rol
   anterior y el nuevo (regla 9 de `steering/security.md`).
5. IF un usuario intenta cambiar su **propio** rol o su propio estado, THEN THE SYSTEM SHALL
   rechazarlo: una autodegradación deja al tenant sin quien administre y no existe endpoint
   de vuelta.
6. IF la operación dejaría al tenant sin ningún `TENANT_OWNER` en estado `ACTIVE`, THEN THE
   SYSTEM SHALL rechazarla por el mismo motivo, sea por cambio de rol o por baja.
7. WHEN un usuario pasa a `INACTIVE` o `SUSPENDED`, THE SYSTEM SHALL revocar su familia de
   tokens de refresh. La revalidación por petición de `auth-tenancy` ya le devuelve `401`
   con el token de acceso, pero `POST /auth/refresh` no la atraviesa, así que sin esto una
   cuenta desactivada sigue emitiendo pares nuevos indefinidamente.
8. WHEN se solicita `DELETE /api/v1/users/{id}`, THE SYSTEM SHALL pasar el usuario a
   `INACTIVE` conservando la fila y responder `204`. Borrarla rompería el rastro que la
   regla 9 obliga a conservar: `audit_logs.actor_user_id` y `timeline_events.actor_user_id`
   apuntan al usuario. Mismo criterio que el `DELETE` de `reservations`.
9. IF el usuario ya está `INACTIVE`, THEN THE SYSTEM SHALL responder `204` sin registrar un
   segundo `AuditLog` de baja.

### R4 — Reset de contraseña asistido

**As a** `TENANT_OWNER`, **I want** regenerar la contraseña de un usuario que la ha perdido,
**so that** una limpiadora bloqueada pueda volver a trabajar sin esperar a una capacidad
marcada como opcional en el PRD.

Acceptance criteria:

1. WHEN se solicita `POST /api/v1/users/{id}/reset-password` sobre un usuario del tenant,
   THE SYSTEM SHALL generar una contraseña temporal nueva con las mismas garantías de R1.2,
   reemplazar el hash almacenado y responder con la temporal una sola vez.
2. WHEN se completa un reset, THE SYSTEM SHALL revocar la familia de tokens de refresh del
   usuario afectado: un reset que deja vivas las sesiones anteriores no recupera la cuenta,
   solo añade una credencial más.
3. THE SYSTEM SHALL registrar el reset en `AuditLog` sin la contraseña, sin el hash y sin
   ninguna forma reversible de ellos.
4. Este endpoint **no** está en la lista de PRD §23; THE SYSTEM SHALL documentarlo como
   adición deliberada, con su motivo: `auth-account-recovery` es opcional en PRD §24 y
   depende del `NotificationAdapter` de `access-notifications`, así que sin esto el MVP no
   tiene ninguna vía de recuperación.

### R5 — Configuración del tenant

**As a** `TENANT_OWNER`, **I want** consultar y ajustar la configuración de mi tenant, **so
that** el umbral de aprobación de gastos y los SLAs sean los míos y no los del `server_default`.

Acceptance criteria:

1. WHEN se solicita `GET /api/v1/tenants/{id}` con el `id` del tenant del token, THE SYSTEM
   SHALL devolver los datos del tenant junto a su `TenantConfig` como un solo recurso (PRD
   §23 no define endpoint propio para la config, y la relación es 1:1 por el índice único de
   `tenant_configs.tenant_id`).
2. WHEN se solicita `PATCH /api/v1/tenants/{id}`, THE SYSTEM SHALL aplicar solo los campos
   presentes, sobre `name`, `billing_email`, `country`, `timezone`, `default_language` del
   tenant y los umbrales, SLAs, ventanas y conmutadores de notificación de `TenantConfig`.
3. THE SYSTEM SHALL rechazar el campo `status` del tenant con `422`: `auth-tenancy`
   revalida en cada petición que el tenant siga `ACTIVE`, así que suspenderse a sí mismo
   deja a **todos** sus usuarios en `401` sin vía de vuelta por la API. Cambiar el estado de
   un tenant es una operación de plataforma.
4. THE SYSTEM SHALL rechazar `storage_type` con `422`: cambiarlo apunta las fotos ya subidas
   a un backend que no las tiene, y elegir `S3` sin credenciales rompe los uploads. Pertenece
   a `cleaning`, con su migración de datos.
5. THE SYSTEM SHALL validar los rangos de lo que acepta —umbral de aprobación no negativo,
   umbral de confianza de IA dentro de `[0, 1]` y representable en `Numeric(3,2)`, SLAs
   positivos, ventanas no negativas, `country` como ISO-3166-1 alpha-2, `default_language`
   en `es`/`en`— y responder `422` fuera de ellos.
6. THE SYSTEM SHALL validar que `timezone` es una zona IANA real: `celery-jobs` calcula las
   ventanas de check-in y checkout con ella, y una cadena inválida convierte un error de
   configuración en un fallo del scheduler.
7. IF el tenant no tiene fila en `tenant_configs`, THEN THE SYSTEM SHALL crearla con los
   valores por defecto antes de aplicar el parche, de modo que la API no dependa de que el
   bootstrap la haya creado.
8. WHEN se modifica el tenant o su configuración, THE SYSTEM SHALL registrar un `AuditLog`.
   La regla 9 no lo lista, pero `owner_approval_threshold_eur` **es** el control del
   principio 4 de `steering/product.md`: cambiarlo sin rastro cambia en silencio qué gastos
   necesitan aprobación del propietario.

### R6 — AuditLog: el primer escritor de la tabla

**As a** propietaria, **I want** que todo cambio administrativo deje rastro consultable,
**so that** pueda saber quién concedió un rol o movió un umbral, y cuándo.

Acceptance criteria:

1. THE SYSTEM SHALL escribir `audit_logs.changes` **siempre en forma estructurada** (regla
   11 de `steering/security.md`): ningún valor de la regla 3 sobrevive en esa columna, ni
   siquiera enmascarado — se registra `{"changed": true}` o se elimina la clave.
2. WHEN se registra un alta o un reset, THE SYSTEM SHALL representar la contraseña como
   `{"changed": true}` y no SHALL incluir la temporal ni su hash.
3. THE SYSTEM SHALL registrar `actor_user_id` del token y `actor_ip` resuelta con el mismo
   `get_client_ip` de `auth-tenancy`, heredando su limitación documentada sobre el peer de
   confianza (que cierra `api-ingress-routing`).
4. WHILE se escribe una mutación, THE SYSTEM SHALL persistir el cambio y su `AuditLog` en
   **una única transacción** a través del `UnitOfWork`, de modo que un fallo al escribir el
   rastro deje el cambio sin aplicar. Mismo criterio con el que `reservations` escribe su
   `TimelineEvent`.
5. THE SYSTEM SHALL fijar el vocabulario de `action` y `entity_type` en constantes de
   dominio —PRD §7.25 los tipa como `VARCHAR` libre— para que el índice
   `(tenant_id, entity_type, entity_id)` sirva para listar el historial de una entidad.
6. THE SYSTEM SHALL NOT exponer ninguna vía de la API que edite o borre filas de
   `audit_logs`.

### R7 — Aislamiento por tenant y matriz de autorización

**As a** responsable del producto, **I want** que estos endpoints demuestren el aislamiento
por tenant rol a rol, **so that** la regla 1 de `steering/security.md` quede verificada
también sobre la superficie que administra cuentas.

Acceptance criteria:

1. WHEN un usuario referencia por `id` un usuario o un tenant que **existe** pero pertenece
   a otro tenant, THE SYSTEM SHALL responder `404` y no `403`, sin revelar que el recurso
   existe. *(R4.3 heredado de `auth-tenancy`, bloqueante.)*
2. THE SYSTEM SHALL incluir una matriz de tests de autorización **por endpoint y por rol**,
   con los cinco roles, demostrando que un usuario del tenant A no obtiene ni modifica datos
   del tenant B por ninguno de estos endpoints. *(R4.4 heredado de `auth-tenancy`,
   bloqueante.)*
3. THE SYSTEM SHALL decidir la autorización **antes** de consultar el recurso, de modo que
   un rol sin permiso reciba la misma respuesta para un `id` real y para uno inventado.
4. WHERE el rol es `TENANT_OWNER`, THE SYSTEM SHALL permitir todos los endpoints de esta
   capacidad.
5. WHERE el rol es `PROPERTY_MANAGER`, THE SYSTEM SHALL permitir `GET /api/v1/users`,
   `GET /api/v1/users/{id}` y `GET /api/v1/tenants/{id}` —necesita el personal para asignar
   tareas y los umbrales y SLAs para operar— y SHALL denegar con `403` toda mutación. Quien
   asigna roles puede escalar privilegios, así que la asignación se queda en el propietario.
6. WHERE el rol es `CLEANER` o `TECHNICIAN`, THE SYSTEM SHALL denegar con `403` todos los
   endpoints de esta capacidad: su autoservicio es `GET /api/v1/auth/me`. El listado expone
   el email y el rol de todo el personal del tenant.
7. WHERE el rol es `SUPER_ADMIN`, THE SYSTEM SHALL denegar con `403` todos los endpoints,
   por el mismo razonamiento con el que lo hace `reservations`: sus capacidades de PRD §6 son
   globales, no operativas de un tenant, y lo cross-tenant está diferido a
   `saas-cross-tenant`.
8. THE SYSTEM SHALL filtrar `tenant_id` explícitamente en cada consulta y comprobarlo en
   cada escritura, porque el filtro global de sesión no cubre los `INSERT`.
9. THE SYSTEM SHALL cubrir con su propio test que `GET`/`PATCH /api/v1/tenants/{id}` compara
   el `id` de la ruta contra el tenant del token: la tabla `tenants` **no tiene columna
   `tenant_id`** y `tenant_scoped_classes()` selecciona por columna, así que el filtro global
   de `auth-tenancy` no la cubre y esa comparación explícita es la única protección.
   `tenant_configs` sí la lleva y sí queda cubierta.

## Out of scope

- **Frontend** de usuarios y de settings — `dashboard-web` y `hardening-release`.
- **Forzar el cambio de la contraseña temporal en el primer login** y **el cambio de
  contraseña por el propio usuario** — `auth-account-recovery`. Exigen una columna nueva
  (`must_change_password`) y un endpoint de autoservicio. Consecuencia aceptada y que hay
  que documentar: la temporal sobrevive hasta que un administrador la rote.
- **`/forgot-password` sin intervención de un administrador** — `auth-account-recovery`
  (opcional en PRD §24, depende de `access-notifications`).
- **Invitación por email con token** — depende del `NotificationAdapter` de
  `access-notifications`.
- **Alta y baja de tenants** (`POST`/`DELETE /api/v1/tenants`) — no están en PRD §23 y el
  MVP tiene un único tenant creado por el bootstrap. El `status` del tenant queda fuera por
  R5.3.
- **Visibilidad cross-tenant e impersonation de `SUPER_ADMIN`** — `saas-cross-tenant`.
- **Identidad global con memberships multi-tenant** — `saas-cross-tenant`, según ADR 0005.
- **La comprobación de que el peer es un proxy de confianza** para resolver `actor_ip` —
  `api-ingress-routing`, que es donde el proxy existe de verdad.
- **El `AuditLog` retroactivo de las seis mutaciones de `reservations`/`integrations`** —
  deuda anotada en `specs/reservations.md` con dueño propio. Este change monta el escritor y
  deja la deuda accionable, pero no vuelve a esos casos de uso.
- **Salida de la API a internet**: estos endpoints se verifican con tests y, en dev, por
  túnel SSH (`RUNBOOK.md` §7.4). Lo cambia `api-ingress-routing`.

## Affected specs

- `sdd/specs/user-management.md` — *(no existe aún — se creará al archivar)*: usuarios,
  reset asistido, configuración del tenant y `AuditLog`.
- `sdd/specs/auth-tenancy.md` — a modificar: el catálogo de `Permission` crece con los
  permisos que declaren estos endpoints; se cierra su **alcance declarado** sobre R4.3/R4.4;
  la revocación de familia por desactivación añade un valor a `SessionRevokedReason` (enum
  nativo → migración de Alembic); consolidación de `app/auth/infrastructure/unit_of_work.py`
  con `app/core/unit_of_work.py`.
- `sdd/specs/reservations.md` — a modificar (solo su sección de deuda): la consolidación del
  `UnitOfWork` deja de estar pendiente, y el escritor de `AuditLog` pasa a existir.
- `sdd/specs/domain-foundation-financial.md` — a modificar si procede: `audit_logs` deja de
  no tener escritor.
