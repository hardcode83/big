# Capacidad operativa de `SUPER_ADMIN`

## Purpose

`SUPER_ADMIN` es la identidad sin tenant (`super-admin-identity`) cuya superficie HTTP está
aquí: dos rutas que materializan lo que de otro modo requiere editar la base de datos a
mano o llamar a la API desde un rol que no existe todavía. Crea tenants nuevos con su
configuración por defecto y da de alta personal operativo (`TENANT_OWNER`, `PROPERTY_MANAGER`,
`CLEANER`, `TECHNICIAN`) en un tenant que el propio llamante nombra en la ruta. Es el
puente entre "el rol existe y se autentica" (`super-admin-identity`) y "la consola de
operador aterriza" (`super-admin-console`), y no se solapa con la superficie de tenants o
de users existente porque vive en su propio router bajo `/api/v1/platform`.

El *cómo se opera* (reglas duras, diagnósticos, advertencias) vive en
[`docs/super-admin-console.md`](../../docs/super-admin-console.md) cuando aterrice la
consola; aquí documenta el *qué hace* el backend que esa consola consume.

## Requirements

### Crear un tenant

- WHEN se solicita `POST /api/v1/platform/tenants` con un cuerpo válido, THE SYSTEM SHALL
  crear el tenant con estado `ACTIVE`, su fila `tenant_configs` por defecto (`storage_type
  = LOCAL`, `country/timezone` del cuerpo o los defaults `ES`/`Europe/Madrid`), y responder
  `201` con el recurso recién creado (incluye `id`, `status` y `tenant_configs` anidada).
- WHEN se solicita con un `name` que ya pertenece a un tenant `ACTIVE`, THE SYSTEM SHALL
  responder `409` con `{error: {code: "TENANT_ALREADY_EXISTS", ...}}` y SHALL NOT crear
  un segundo tenant con el mismo nombre. La unicidad la sostiene el índice
  `uq_tenants_name` (`backend/alembic/versions/936fef5a01b1_tenants_name_unique.py`), y la
  traducción del `IntegrityError` se hace por nombre de constraint, no por una comprobación
  previa: dos altas concurrentes con el mismo nombre pasarían la comprobación y una
  acabaría en `500`.
- WHEN el cuerpo es inválido (campo requerido ausente, `name` vacío, `country` que no
  encaje en el patrón, etc.), THE SYSTEM SHALL responder `422` con la lista de campos que
  fallan y SHALL NOT filtrar metadatos de infraestructura.
- THE SYSTEM SHALL mantener `app/cli/bootstrap.py` operativo para crear los tenants
  seed; esta ruta NO los replica, y la unicidad del `name` se respeta venga de donde
  venga la petición (un test pina que crear un tenant por API con el nombre de un seed
  termina en `409`, no en `201`).
- THE SYSTEM SHALL añadir `TENANT_CREATED` al vocabulario cerrado de
  `audit_logs.action` (`backend/app/audit/domain/actions.py`): una sola grafía por
  operación, siguiendo el patrón de `USER_CREATED` y `PROPERTY_CREATED`. NO SHALL reusar
  `TENANT_UPDATED` mintiendo que es creación — la query "filas con `action =
  TENANT_CREATED`" dejaría de responder.

### Crear un usuario en un tenant nombrado

- WHEN se solicita `POST /api/v1/platform/tenants/{tenant_id}/users` con un cuerpo válido,
  THE SYSTEM SHALL crear el usuario en el tenant del path con estado `ACTIVE`,
  `must_change_password = true`, y responder `201` con el recurso y la contraseña
  temporal **una sola vez**, con la cabecera `Cache-Control: no-store`.
- THE SYSTEM SHALL derivar el `tenant_id` del segmento de la ruta y NO SHALL aceptarlo
  del cuerpo, la query string ni las cabeceras — la regla 1 de `steering/security.md`
  sigue valiendo, solo que el origen del tenant pasa del token a la ruta en estas dos
  rutas.
- WHEN el `tenant_id` de la ruta no existe o no está `ACTIVE`, THE SYSTEM SHALL responder
  `404`, indistinguible de un tenant que jamás fue creado. La respuesta nunca debe
  servir de sonda de existencia.
- IF el email normalizado ya existe bajo cualquier tenant, THEN THE SYSTEM SHALL
  responder `409` con un mensaje accionable, sin nombrar el tenant al que pertenece.
- THE SYSTEM SHALL rechazar con `422` `role = SUPER_ADMIN`: el rol está fuera del
  vocabulario de creación por API (`GRANTABLE_ROLES` lo sigue excluyendo). Un campo
  `role=SUPER_ADMIN` cae por el `field_validator` del esquema
  (`backend/app/platform/api/schemas.py`), no por la entidad — la entrada de la API de
  plataforma es la primera línea de defensa.
- WHEN el cuerpo es inválido, THE SYSTEM SHALL responder `422` con la lista de campos
  que fallan.
- THE SYSTEM SHALL reusar el caso de uso de alta de `user-management` con la salvedad de
  que el `tenant_id` viene del path, no del token: mismas validaciones de email, mismo
  mecanismo de contraseña temporal (sin caracteres ambiguos, 16 caracteres, garantía de
  clases), mismo `must_change_password = true`, mismo formato de respuesta. La contraseña
  temporal nunca se serializa en `audit_logs.changes` (`{"changed": true}`), y nunca se
  persiste en claro ni se escribe en log de aplicación.

### Autorización: `MANAGE_PLATFORM` solo lo tiene `SUPER_ADMIN`

- THE SYSTEM SHALL añadir el permiso `MANAGE_PLATFORM = "MANAGE_PLATFORM"` al enum
  `Permission` de `backend/app/auth/domain/policy.py`, con la misma forma que los demás
  (string, sin herencia explícita).
- THE SYSTEM SHALL conceder `MANAGE_PLATFORM` exclusivamente a
  `UserRole.SUPER_ADMIN` en `ROLE_PERMISSIONS`; `TENANT_OWNER`, `PROPERTY_MANAGER`,
  `CLEANER` y `TECHNICIAN` SHALL NOT obtenerlo. Ninguna regla de default de un
  `_SELF_SERVICE` lo arrastra: se nombra explícitamente para `SUPER_ADMIN`.
- WHEN el llamante no es `SUPER_ADMIN` (sin importar qué permiso o rol tenga), THE
  SYSTEM SHALL responder `403`, sin distinguir entre "no eres `SUPER_ADMIN`" y "no
  tienes `MANAGE_PLATFORM`" — un único motivo, un único código.
- THE SYSTEM SHALL declarar el permiso exigido en cada ruta mediante la dependencia
  `require(Permission.MANAGE_PLATFORM)`, y SHALL vivir solo bajo el prefijo
  `/api/v1/platform`. Una guarda estructural
  (`tests/test_route_authorization.py::test_manage_platform_only_lives_under_platform_prefix`)
  pina que ningún `Require(Permission.MANAGE_PLATFORM)` aparezca fuera de ese prefijo, y
  la guarda `test_authorization.py::test_post_platform_returns_403_for_other_roles`
  pina el `403` para los cinco roles restantes.
- THE SYSTEM SHALL declarar las dos rutas en la OpenAPI con `tags=["platform"]`,
  `summary` y `description` que digan literalmente "Requires `SUPER_ADMIN`", para que
  un humano que lea `openapi.json` no tenga que adivinarlo.

### Auditoría con `tenant_id` de la entidad afectada

- WHEN un `POST /api/v1/platform/tenants` termina en `201`, THE SYSTEM SHALL escribir
  una fila de `audit_logs` con `entity_type = "TENANT"`, `action = "TENANT_CREATED"`,
  `tenant_id` el del tenant recién creado, `actor_user_id` el del `SUPER_ADMIN`
  autenticado, `actor_ip` la de la petición, y `changes` describiendo los cinco campos
  del cuerpo (`name`, `billing_email`, `country`, `timezone`, `default_language`).
- WHEN un `POST /api/v1/platform/tenants/{tenant_id}/users` termina en `201`, THE
  SYSTEM SHALL escribir una fila de `audit_logs` con `entity_type = "USER"`, `action =
  "USER_CREATED"`, `tenant_id` el del path, `actor_user_id` el del `SUPER_ADMIN`
  autenticado, `actor_ip` la de la petición, y `changes` describiendo los campos del
  cuerpo. La contraseña temporal NO SHALL aparecer en `changes`.
- IF la escritura de `audit_logs` falla por cualquier motivo, THEN THE SYSTEM SHALL
  revertir la creación (tenant o usuario) en la misma transacción, de modo que la
  auditoría nunca quede desfasada del estado real.
- THE SYSTEM SHALL usar el `tenant_id` del registro `audit_logs` igual al `tenant_id`
  de la entidad afectada, no al del actor. La relajación de la regla 1 de
  `steering/security.md` cubre la sesión del actor (`SUPER_ADMIN` con sesión sin
  marcar), no el `tenant_id` del registro: `audit_logs.tenant_id` sigue siendo
  `NOT NULL`, y la columna sostiene `ix_audit_logs_tenant_id_entity_type_entity_id`.

### Aislamiento: la superficie vive en su propio router

- THE SYSTEM SHALL añadir `backend/app/platform/api/router.py` con las dos rutas
  declaradas, montadas en `app/main.py` bajo el prefijo `/api/v1/platform`. Ninguna de
  las dos rutas entra en `backend/app/tenants/api/router.py` ni en
  `backend/app/auth/api/users_router.py`: las dependencias de esos routers
  (`require(Permission.MANAGE_TENANT_SETTINGS)` y `require(Permission.MANAGE_USERS)`)
  siguen sirviendo al resto de rutas de cada router, sin cambio.
- THE SYSTEM SHALL declarar la dependencia `PlatformDep` en
  `backend/app/platform/api/dependencies.py` con la misma forma que las dependencias
  `Require(Permission.MANAGE_TENANT_SETTINGS)` y `Require(Permission.MANAGE_USERS)` que
  los otros routers usan, para que la separación entre la superficie de plataforma y la
  de tenants o users sea visible en el código (D5 del diseño).
- THE SYSTEM SHALL registrar los manejadores de error de plataforma en
  `backend/app/platform/api/errors.py`, mapeando `TenantAlreadyExistsError` a `409` y
  `TenantNotActiveError` a `404` indistinguible de tenant inexistente.

## Out of scope

- La consola de frontend (pantallas, aterrizaje por rol, formularios en React) — eso es
  `super-admin-console` (corte c de la partición de `super-admin-console`), que depende
  de esta entrada y de `super-admin-identity`.
- Visibilidad cross-tenant e impersonation de `SUPER_ADMIN` — eso es `saas-cross-tenant`,
  post-MVP y condicional. Esta entrada **no** concede a `SUPER_ADMIN` leer datos
  operativos de un tenant; solo crea el tenant y le da cuentas.
- Abrir `GRANTABLE_ROLES` para crear o promover a `SUPER_ADMIN` por API — la decisión
  sigue siendo no, heredada de `super-admin-identity` R4.2.
- Listar, suspender, reactivar o borrar tenants — el router de `tenants` actual mantiene
  `GET` y `PATCH` para el caso de uso propio del tenant; las acciones cross-tenant
  sobre el ciclo de vida del tenant requieren alcance separado.
- Editar o resetear cuentas de un tenant desde la plataforma — el flujo propio del
  tenant (`PATCH /users/{id}`, `POST /users/{id}/reset-password`) cubre esos casos.

## Key files

- `backend/app/platform/api/router.py` — los dos endpoints (`POST /platform/tenants`,
  `POST /platform/tenants/{tenant_id}/users`).
- `backend/app/platform/api/schemas.py` — DTOs (`CreateTenantRequest`,
  `CreatePlatformUserRequest`, `CreatedPlatformUserResponse`, `PlatformUserResponse`).
- `backend/app/platform/api/dependencies.py` — `PlatformDep` con
  `Require(Permission.MANAGE_PLATFORM)`.
- `backend/app/platform/api/errors.py` — mapeo de `TenantAlreadyExistsError` a `409` y
  `TenantNotActiveError` a `404`.
- `backend/app/platform/api/use_case_dependencies.py` — wiring FastAPI de los casos de
  uso.
- `backend/app/platform/application/use_cases.py` — `CreateTenantUseCase` (orquesta
  `Tenant.create`, `tenant_config.with_defaults`, `TenantRepository.add`, auditoría,
  `uow.commit` con traducción de `IntegrityError`) y `CreateUserInTenantUseCase`
  (envuelve `CreateUserUseCase` con validación previa del tenant).
- `backend/app/platform/domain/exceptions.py` — `TenantAlreadyExistsError` (409) y
  `TenantNotActiveError` (404).
- `backend/app/main.py` — montaje del router bajo `API_V1_PREFIX`.
- `backend/app/auth/domain/policy.py` — `Permission.MANAGE_PLATFORM` y entrada
  `_PLATFORM` aplicada solo a `ROLE_PERMISSIONS[SUPER_ADMIN]`.
- `backend/app/audit/domain/actions.py` — `TENANT_CREATED` añadida al vocabulario
  cerrado y al `frozenset ACTIONS`.
- `backend/app/tenants/domain/entities.py` — `Tenant.create(...)` con los mismos
  normalizadores que `Tenant.update`.
- `backend/app/tenants/domain/repositories.py` — `TenantRepository.add(...)`.
- `backend/app/tenants/infrastructure/repositories.py` — implementación de `add(...)`
  con dos `session.add` y un `flush` para que `uq_tenants_name` aflore como
  `IntegrityError`.
- `backend/alembic/versions/936fef5a01b1_tenants_name_unique.py` — `uq_tenants_name`.
- `backend/alembic/versions/936fef59b1d4_merge_platform_admin_api_pre_revision.py`,
  `backend/alembic/versions/4ba1f499f7c2_merge_platform_admin_api_staff_messaging.py` —
  merge revisions vacías para reunificar la cadena de migraciones.
- `backend/tests/platform/test_api.py`,
  `backend/tests/platform/test_authorization.py`,
  `backend/tests/platform/test_isolation.py`,
  `backend/tests/platform/test_use_cases.py` — la suite del módulo.
- `backend/tests/test_route_authorization.py` — guarda estructural
  `test_manage_platform_only_lives_under_platform_prefix`.
- `backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts` — artefactos
  regenerados con `make openapi` y `npm run api:generate`; los dos se commitean en el
  mismo PR (regla de `sdd/steering/documentation.md`).