# Proposal: platform-admin-api

## Why

`/sdd:new super-admin-console` (2026-08-31) partió la consola de plataforma en tres cortes y
ésta es el **(b)**: las rutas HTTP que `SUPER_ADMIN` necesita para reemplazar lo que hoy se
hace escribiendo en la base de datos o llamando a la API a mano. Censo completo de la
partición y frontera con `saas-cross-tenant` (post-MVP, condicional) en
`sdd/roadmap/super-admin-console.md`.

El modelo de identidad sin tenant (corte a) se archivó hoy mismo como
`sdd/changes/archive/2026-09-02-super-admin-identity/`: `SUPER_ADMIN` ya existe en el
esquema, se autentica de punta a punta con sesión sin marcar, y la excepción a la regla 1 de
`steering/security.md` está nombrada y acotada en el propio steering. Esta entrada levanta
sobre eso lo que el requisito de producto pide: **crear tenants** y **dar de alta personal
operativo en un tenant nombrado por el llamante**.

Las dos rutas no existen. `POST /api/v1/tenants` solo se materializa hoy en
`app/cli/bootstrap.py:129` (CLI); el router de `backend/app/tenants/api/router.py` solo
tiene `GET /{tenant_id}` y `PATCH /{tenant_id}`. `POST /api/v1/users` existe pero **deriva
el `tenant_id` del token** (`sdd/specs/user-management.md` §45–46), así que un
`SUPER_ADMIN` sin tenant no puede usarla tal cual: aunque se le concediera `MANAGE_USERS`
operaría sobre un tenant que no existe. Ningún ajuste cosmético — son dos rutas nuevas, una
excepción nombrada al scoping de `users.tenant_id` en el caso de uso de creación, y un
nuevo permiso de plataforma. La auditoría es regla 9 de `steering/security.md` y ya está
implementada para `USER_CREATED` y `USER_UPDATED`; basta con escribir las filas correctas.

## What changes

`SUPER_ADMIN` obtiene dos rutas de backend que le permiten operar como administrador de
plataforma, no como usuario de un tenant:

- **`POST /api/v1/platform/tenants`** crea un tenant nuevo (con su `tenant_configs` por
  defecto, idempotente respecto a una fila preexistente del bootstrap) y devuelve `201` con
  el recurso. Auditoría con `entity_type = TENANT`, `action = TENANT_CREATED` (acción
  nueva, decisión D1 de esta entrada). El `tenant_id` de la fila de `audit_logs` es el del
  tenant recién creado — el registro es sobre la entidad afectada, no sobre el tenant del
  actor, y eso es lo que hace que el índice por `tenant_id` siga respondiendo a "qué pasó
  en este tenant".
- **`POST /api/v1/platform/tenants/{tenant_id}/users`** crea un `USER` con `role ∈
  {TENANT_OWNER, PROPERTY_MANAGER, CLEANER, TECHNICIAN}` en el tenant nombrado en la ruta
  (no del token). Devuelve `201` con el recurso y la contraseña temporal una sola vez,
  reusando el caso de uso de alta de `user-management` con la salvedad de que el
  `tenant_id` viene del path y no del token. Auditoría con `entity_type = USER`, `action =
  USER_CREATED`, `tenant_id` el del path. `SUPER_ADMIN` sigue **fuera** de
  `GRANTABLE_ROLES` (`super-admin-identity` R4.2): no se puede crear ni promover a otro
  `SUPER_ADMIN` por API; abrir esa puerta queda fuera de alcance.

El permiso nuevo `MANAGE_PLATFORM` se concede exclusivamente a `SUPER_ADMIN` (ningún otro
rol lo tiene, ni lo tendrá sin reabrir esta decisión). Ningún permiso operativo cambia para
`TENANT_OWNER`, `PROPERTY_MANAGER`, `CLEANER` ni `TECHNICIAN`. Ninguna ruta nueva entra en
los routers existentes: las dos rutas viven en un router propio bajo `/platform`, separado
del de tenants y del de users, para que la superficie auditada sea identificable y para que
los `Require(Permission.MANAGE_PLATFORM)` no contaminen los routers de negocio.

## Requirements

### R1 — `POST /api/v1/platform/tenants` crea un tenant nuevo y devuelve `201`

**As a** `SUPER_ADMIN`, **I want** crear un tenant desde la API, **so that** dejar de
escribir en la base de datos para dar de alta un operador nuevo.

Acceptance criteria:

1. WHEN se solicita `POST /api/v1/platform/tenants` con un cuerpo válido (`name`,
   `billing_email`, `country`, `timezone`, `default_language`), THE SYSTEM SHALL crear el
   tenant con estado `ACTIVE`, su fila `tenant_configs` por defecto si falta, y responder
   `201` con el recurso recién creado.
2. WHEN se solicita `POST /api/v1/platform/tenants` con `name` repetido respecto a un
   tenant `ACTIVE`, THE SYSTEM SHALL responder `409` con un mensaje accionable, y SHALL
   NOT crear un segundo tenant con el mismo nombre.
3. WHEN se solicita `POST /api/v1/platform/tenants` con un cuerpo inválido, THE SYSTEM
   SHALL responder `422` con la lista de campos que fallan, sin filtrar metadatos de
   infraestructura.
4. WHEN el llamante no es `SUPER_ADMIN` (sin importar qué permiso o rol tenga), THE SYSTEM
   SHALL responder `403`, sin distinguir entre "no eres `SUPER_ADMIN`" y "no tienes
   `MANAGE_PLATFORM`" — un único motivo, un único código.

### R2 — La creación del tenant queda auditada con `entity_type = TENANT`

**As a** auditor de seguridad, **I want** que toda creación de tenant quede en
`audit_logs` con el formato que la regla 9 espera, **so that** reconstruir quién dio de alta
qué tenant no dependa de leer logs de aplicación.

Acceptance criteria:

1. WHEN un `POST /api/v1/platform/tenants` termina en `201`, THE SYSTEM SHALL escribir una
   fila de `audit_logs` con `entity_type = "TENANT"`, `action = "TENANT_CREATED"`,
   `tenant_id` el del tenant recién creado, `actor_user_id` el del `SUPER_ADMIN`
   autenticado, `actor_ip` la de la petición, y `changes` describiendo los campos del
   cuerpo del request.
2. THE SYSTEM SHALL añadir la constante `TENANT_CREATED` al vocabulario cerrado de
   `backend/app/audit/domain/actions.py` y SHALL NOT inventar una grafía distinta en el
   escritor — un solo spelling por tabla (D4 de `access-notifications`).
3. IF la escritura de `audit_logs` falla por cualquier motivo, THEN THE SYSTEM SHALL
   revertir la creación del tenant en la misma transacción, de modo que la auditoría nunca
   quede desfasada del estado real.
4. WHEN el llamante es `SUPER_ADMIN` y la fila de `audit_logs` exige `tenant_id`, THE
   SYSTEM SHALL usar el del tenant recién creado y NO SHALL dejar `tenant_id = NULL` en
   `audit_logs`: la tabla sigue siendo `TenantScopedMixin`, y la relajación de la regla 1
   de `steering/security.md` cubre la sesión del actor, no el `tenant_id` del registro.

### R3 — `POST /api/v1/platform/tenants/{tenant_id}/users` da de alta personal en un tenant nombrado

**As a** `SUPER_ADMIN`, **I want** crear cuentas operativas (`TENANT_OWNER`,
`PROPERTY_MANAGER`, `CLEANER`, `TECHNICIAN`) en un tenant que yo nombre, **so that** abrir
un cliente nuevo no requiera editar la base de datos ni pedir a un `TENANT_OWNER` que cree
a su propio manager.

Acceptance criteria:

1. WHEN se solicita `POST /api/v1/platform/tenants/{tenant_id}/users` con un cuerpo válido
   (`email`, `full_name`, `phone` opcional, `role ∈ {TENANT_OWNER, PROPERTY_MANAGER,
   CLEANER, TECHNICIAN}`), THE SYSTEM SHALL crear el usuario en el tenant de la ruta con
   estado `ACTIVE`, `must_change_password = true`, y responder `201` con el recurso y la
   contraseña temporal una sola vez.
2. THE SYSTEM SHALL derivar el `tenant_id` del segmento de la ruta, no **should**
   aceptarlo del cuerpo, la query string ni las cabeceras — la regla 1 de
   `steering/security.md` sigue valiendo, solo que el origen del tenant pasa del token a
   la ruta en estas dos rutas.
3. WHEN el `tenant_id` de la ruta no existe o no está `ACTIVE`, THE SYSTEM SHALL responder
   `404`, indistinguible de un tenant que jamás fue creado.
4. IF el email normalizado ya existe bajo cualquier tenant, THEN THE SYSTEM SHALL
   responder `409` sin nombrar el tenant al que pertenece (mismo trato que
   `user-management` R1).
5. THE SYSTEM SHALL rechazar con `422` `role = SUPER_ADMIN`: el rol está fuera del
   vocabulario de creación por API (`GRANTABLE_ROLES` no se abre, decisión D2 de esta
   entrada — la misma que cerró `super-admin-identity` R4.2).
6. WHEN se solicita `POST /api/v1/platform/tenants/{tenant_id}/users` con un cuerpo
   inválido, THE SYSTEM SHALL responder `422` con la lista de campos que fallan.
7. WHEN el llamante no es `SUPER_ADMIN`, THE SYSTEM SHALL responder `403` con un único
   motivo, sin distinguir entre falta de rol y falta de permiso.

### R4 — El alta de personal queda auditada con `entity_type = USER`

**As a** auditor de seguridad, **I want** que todo alta de personal desde el panel de
plataforma quede en `audit_logs` con la misma forma que el alta desde el router de
usuarios, **so that** una sola consulta responda "qué usuarios creó esta persona" sin
importar la ruta usada.

Acceptance criteria:

1. WHEN un `POST /api/v1/platform/tenants/{tenant_id}/users` termina en `201`, THE SYSTEM
   SHALL escribir una fila de `audit_logs` con `entity_type = "USER"`, `action =
   "USER_CREATED"`, `tenant_id` el del path, `actor_user_id` el del `SUPER_ADMIN`
   autenticado, `actor_ip` la de la petición, y `changes` describiendo los campos del
   cuerpo (sin la contraseña temporal — es un secreto de regla 3 y nunca se serializa en
   una respuesta, tampoco en un `AuditLog`).
2. IF la escritura de `audit_logs` falla por cualquier motivo, THEN THE SYSTEM SHALL
   revertir la creación del usuario en la misma transacción, por el mismo motivo que R2.3.
3. THE SYSTEM SHALL reusar el caso de uso de alta de `user-management` (DRY con la ruta
   existente): mismas validaciones de email, mismo mecanismo de temporal, mismo
   `must_change_password = true`, mismo formato de respuesta. La diferencia con la ruta
   existente es solo de dónde sale el `tenant_id` y quién puede llamarla.

### R5 — El permiso `MANAGE_PLATFORM` solo lo tiene `SUPER_ADMIN`

**As a** revisor de seguridad, **I want** que el nuevo permiso esté concedido únicamente a
`SUPER_ADMIN` y a nadie más, **so that** "administrar la plataforma" sea una capacidad
nombrada, no un cajón donde otros roles acaben colándose.

Acceptance criteria:

1. THE SYSTEM SHALL añadir el permiso `MANAGE_PLATFORM` al `Permission` enum de
   `backend/app/auth/domain/policy.py`, con la misma forma que los demás (string, sin
   jerarquía explícita).
2. THE SYSTEM SHALL conceder `MANAGE_PLATFORM` exclusivamente a `UserRole.SUPER_ADMIN` en
   `ROLE_PERMISSIONS`; `TENANT_OWNER`, `PROPERTY_MANAGER`, `CLEANER` y `TECHNICIAN`
   SHALL NOT obtenerlo. Ninguna regla de default de un `_SELF_SERVICE` lo arrastra: se
   nombra explícitamente para `SUPER_ADMIN`.
3. THE SYSTEM SHALL demostrar con tests, para cada uno de los cinco roles, que `POST
   /api/v1/platform/tenants` y `POST /api/v1/platform/tenants/{tenant_id}/users`
   responden `403` cuando el llamante no es `SUPER_ADMIN` (incluido `TENANT_OWNER` de
   cualquier tenant, `PROPERTY_MANAGER`, `CLEANER`, `TECHNICIAN` y un `SUPER_ADMIN` con
   sesión marcada — que no existe, pero el test lo declara para que una regresión futura
   lo mantenga cerrado).

### R6 — La superficie está aislada del router de tenants y del router de users

**As a** revisor de seguridad, **I want** que las dos rutas vivan en un router propio bajo
`/platform`, **so that** la superficie de plataforma sea identificable de un vistazo y los
guards de `MANAGE_PLATFORM` no se cuelen en routers de negocio.

Acceptance criteria:

1. THE SYSTEM SHALL añadir `backend/app/platform/api/router.py` con las dos rutas
   declaradas, montadas en `app/main.py` bajo el prefijo `/api/v1/platform`.
2. THE SYSTEM SHALL NOT tocar `backend/app/tenants/api/router.py` ni
   `backend/app/users/api/router.py` para añadir estas dos rutas: las dependencias de esos
   routers (`require(Permission.MANAGE_TENANT_SETTINGS)` y `require(Permission.MANAGE_USERS)`)
   siguen sirviendo al resto de rutas de cada router, sin cambio.
3. THE SYSTEM SHALL declarar las dos rutas en la OpenAPI con `tags=["platform"]`, summary y
   description que digan explícitamente que requieren `SUPER_ADMIN`, para que un humano que
   lea `openapi.json` no tenga que adivinarlo.

### R7 — El bootstrap deja de ser el único creador de tenants

**As a** persona que despliega un entorno nuevo, **I want** que la CLI de bootstrap siga
funcionando como hasta ahora, **so that** los entornos nuevos sigan siendo inicializables
sin necesidad de llamar a la API.

Acceptance criteria:

1. THE SYSTEM SHALL mantener `app/cli/bootstrap.py` operativo para crear los dos tenants
   seed (`MAGNO_REDES11`, `MAGNO_PAJARITOS8`) y sus cuentas; las nuevas rutas de
   plataforma NO los replican.
2. THE SYSTEM SHALL demostrar con un test que llamar a `POST /api/v1/platform/tenants` con
   el mismo `name` que uno de los dos seed termina en `409`, no en `201`: la unicidad
   del nombre se respeta venga de donde venga la petición.
3. THE SYSTEM SHALL demostrar con un test que el orden de bootstrap no cambia: una
   re-ejecución del comando sigue siendo convergente (R7.2/D10 de `auth-tenancy`), y el
   alta de un tercer tenant por la API no afecta a una segunda ejecución.

## Out of scope

- **La consola de frontend** (pantallas, aterrizaje por rol, formularios en React) — eso es
  `super-admin-console` (corte c), que depende de esta entrada y de `super-admin-identity`.
- **Visibilidad cross-tenant e impersonation** de `SUPER_ADMIN` — eso es
  `saas-cross-tenant`, post-MVP y condicional. Esta entrada **no** concede a
  `SUPER_ADMIN` leer datos operativos de un tenant; solo crea el tenant y le da cuentas.
- **Abrir `GRANTABLE_ROLES` para crear o promover a `SUPER_ADMIN` por API** — la decisión
  sigue siendo no, heredada de `super-admin-identity` R4.2; abrirla es una entrada propia
  si algún día hace falta.
- **Listar, suspender, reactivar o borrar tenants** — el router de `tenants` actual
  mantiene `GET` y `PATCH` para el caso de uso propio del tenant; las acciones
  cross-tenant sobre el ciclo de vida del tenant (suspender, archivar, listar) requieren
  alcance separado y permisos cross-tenant, que es justamente lo que `saas-cross-tenant`
  cubre cuando se decida.
- **Editar o resetear cuentas de un tenant** desde la plataforma — el flujo propio del
  tenant (`PATCH /users/{id}`, `POST /users/{id}/reset-password`) cubre esos casos. Añadir
  aquí un duplicado cross-tenant de edición es lo que `saas-cross-tenant` debe decidir, no
  esta entrada.
- **Una pantalla de "todo lo que ha hecho `SUPER_ADMIN`"** — la auditoría existe (`AuditLog`
  con `actor_user_id` del `SUPER_ADMIN`); leerla de forma agregada es una capacidad de
  reporting que no se promete con esto.

## Affected specs

- `sdd/specs/auth-tenancy.md` (existe) — sección «Permisos» (alta de `MANAGE_PLATFORM`
  concedido solo a `SUPER_ADMIN`) y sección «Aislamiento por tenant» (censo de las dos
  rutas nuevas en el inventario de excepciones a la regla 1).
- `sdd/specs/user-management.md` (existe) — nota sobre el caso de uso compartido con la
  ruta de plataforma (R4.3 de esta entrada) y sobre la no-apertura de `GRANTABLE_ROLES`.
- `sdd/specs/super-admin-identity.md` *(no existe aún — se creará al archivar)* —
  capacidad operativa de `SUPER_ADMIN` (lo que puede hacer con su identidad sin tenant):
  `POST /platform/tenants`, `POST /platform/tenants/{id}/users`, con auditoría y permiso
  `MANAGE_PLATFORM`. Esta entrada lo deja plantado; la consolida `super-admin-identity` al
  archivarse aquí, no antes.
- `sdd/specs/audit.md` *(no existe aún — se creará al archivar si no se decide reusar el
  tratamiento disperso actual)* — vocabulario cerrado de `audit_logs.action` (entrada
  nueva: `TENANT_CREATED`) y la convención de que el `tenant_id` del registro es el de la
  entidad afectada, no el del actor, para que la relajación de la regla 1 del actor no se
  cuele como `tenant_id = NULL` en `audit_logs`.

## Decisions captured

- **D1 — `TENANT_CREATED` se añade al vocabulario cerrado de `actions`**. La acción no
  existe hoy (`backend/app/audit/domain/actions.py` lista `TENANT_UPDATED` y
  `TENANT_CONFIG_UPDATED`, no la creación). Se añade siguiendo el patrón de las demás
  entradas de la tabla (D4 de `access-notifications`).
- **D2 — `GRANTABLE_ROLES` no se abre**. `SUPER_ADMIN` sigue sin poder crearse ni
  promocionarse por API; abrir esa puerta es decisión propia de una entrada futura, igual que
  cerró `super-admin-identity` R4.2. Esta entrada es para operar la plataforma, no para
  extender quién puede operar la plataforma.
- **D3 — `MANAGE_PLATFORM` es un permiso de granularidad gruesa**. Se podría partir en
  `CREATE_TENANT` + `CREATE_USER_IN_TENANT`, pero hoy el único rol con cualquiera de las
  dos es `SUPER_ADMIN` y la superficie es de dos rutas: granularizar antes de tener más de
  un consumidor es el clásico permiso que se queda sin usar. Si `saas-cross-tenant` acaba
  creando otro rol con parte de estas capacidades, granularizar entonces es el momento.
- **D4 — El `tenant_id` del `audit_logs` es el de la entidad afectada, no el del actor**.
  La regla 1 de `steering/security.md` se relaja solo para la sesión del actor
  (`SUPER_ADMIN` con sesión sin marcar, ya cubierto por `super-admin-identity`); el
  `audit_logs.tenant_id` sigue siendo `NOT NULL` y se llena con el tenant de la entidad
  sobre la que se actuó. Esto evita tener que relajar la columna y mantiene
  `ix_audit_logs_tenant_id_entity_type_entity_id` útil: un `SUPER_ADMIN` que crea 50
  tenants deja 50 filas, una por tenant, encontrables por el índice.
- **D5 — Las dos rutas viven en un router nuevo bajo `/platform`, no en los existentes**.
  El router de `tenants` actual sigue sirviendo `GET` y `PATCH` para el caso de uso
  propio del tenant con `READ_TENANT_SETTINGS` y `MANAGE_TENANT_SETTINGS`; el de `users`
  igual. Mezclar `MANAGE_PLATFORM` ahí propagaría el permiso y haría el guard propenso a
  olvidar. Un router separado hace la superficie explícita en el `openapi.json` y en el
  código.