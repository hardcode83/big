# Design: platform-admin-api

## Context

`SUPER_ADMIN` is now a real identity (`super-admin-identity`, archivado hoy mismo): la fila
tiene `tenant_id = NULL`, se autentica de punta a punta y su sesión llega al request sin
marcar (regla 1 de `steering/security.md`, excepción nombrada). Lo que **falta** es la
**superficie HTTP** que justifique que ese rol exista — crear tenants y dar de alta personal
operativo en un tenant nombrado por el llamante, que es justo lo que el requisito de producto
pide.

Hoy la única vía es de mantenimiento:

- `POST /api/v1/tenants` no existe como ruta; la única materialización del alta de un tenant es
  `app/cli/bootstrap.py:140` (`apply_plan`), que arma un `TenantModel` a mano y le añade su
  `TenantConfigModel`. La fábrica de dominio correspondiente no existe: `Tenant`
  (`backend/app/tenants/domain/entities.py:37`) tiene `update` para patch y nunca un
  `create`/classmethod.
- `POST /api/v1/users` existe, en `backend/app/auth/api/users_router.py:92`, y deriva el
  `tenant_id` del token. Una llamada de `SUPER_ADMIN` sin `tenant_id` lo deja sin tenant, así
  que el caso de uso no aplica aunque se concediera `MANAGE_USERS`.
- `app/audit/domain/actions.py` ya conoce `TENANT_UPDATED` y `TENANT_CONFIG_UPDATED`, no
  `TENANT_CREATED`: la creación aún no es un verbo del vocabulario cerrado.
- `Permission.MANAGE_PLATFORM` no existe en `app/auth/domain/policy.py`, y `ROLE_PERMISSIONS`
  mapea a cinco roles sin un cajón específico para capacidad de plataforma.
- La sesión de `SUPER_ADMIN` es **sin marcar** (`auth/api/dependencies.py:424` solo llama a
  `bind_session_to_tenant` si `tenant_id is not None`), y cualquier endpoint nuevo depende de
  eso: pasar el tenant por la ruta es lo único que mantiene viva la regla 1 en su redacción
  actual (ya documentada por `super-admin-identity`).

El router de `tenants` (`backend/app/tenants/api/router.py`) y el de `users`
(`backend/app/auth/api/users_router.py`) sirven sus propios tenants y no son los sitios donde
montar las dos rutas nuevas: el guard `MANAGE_PLATFORM` propagaría permisos operativos
(R6.2) y haría explícito en el `openapi.json` que el conjunto de plataforma vive dentro de un
router de negocio.

## Decisions

### D1 — Nace un módulo `backend/app/platform/` con su propio router, dominio y casos de uso

**Chosen:** un módulo hexagonal completo bajo `backend/app/platform/`, con
`domain/` (una entidad ligera que da nombre al router y un vocabulario de excepciones), un
caso de uso de creación de tenant y uno de creación de usuario en tenant nombrado, y un
`api/router.py` montado bajo `/api/v1/platform`. Los esquemas Pydantic van en
`platform/api/schemas.py`; las dependencias de FastAPI, en `platform/api/dependencies.py`.

**Why:** R6.1 y R6.2 piden lo mismo, y separar la superficie en un router dedicado hace el
`MANAGE_PLATFORM` visible en `openapi.json` y en el código (D5 del proposal), sin contaminar
los `Require(Permission.MANAGE_TENANT_SETTINGS)` / `Require(Permission.MANAGE_USERS)` de los
routers de tenants y users. `users_router` queda **inalterado** y `tenants_router` también:
su servicio a `GET /tenants/{id}` y `PATCH /tenants/{id}` para el caso de uso propio del
tenant sigue siendo exactamente el mismo.

Rejected: añadir las dos rutas dentro de `tenants/api/router.py` con un guard propio — el
`MANAGE_PLATFORM` aparece como un permiso más en un router cuyo nombre sigue siendo
"tenants", y un humano leyendo `openapi.json` tardaría más en entender que ese grupo incluye
operaciones cross-tenant. La misma objeción aplica a `auth/api/users_router.py`.

### D2 — `Tenant.create(...)` se añade como classmethod a la entidad, y `TenantRepository` gana un `add(...)`

**Chosen:** `backend/app/tenants/domain/entities.py` gana `Tenant.create(...)` con los
mismos `_require_text` / `_require_email` / `normalise_country` / `normalise_timezone` /
`normalise_language` que ya usa `Tenant.update`. `backend/app/tenants/domain/repositories.py`
gana un método `add(tenant: Tenant, config: TenantConfig) -> None` que persiste los dos con
`session.add`, y `backend/app/tenants/infrastructure/repositories.py` lo implementa
insertando ambos modelos y haciendo un único `flush`. La unicidad de nombre se delega a un
`UniqueConstraint('name', name='uq_tenants_name')` que **esta entrada añade** mediante una
migración nueva (`tenants_name_unique`, encadenada a `c22b8ae01096`): la baseline
`4a5faad7796b_baseline_domain_foundation_core.py` crea `tenants.name` como `String(200)`
sin restricción, y `bootstrap.py:176` documenta expresamente la ausencia. La migración
también pone `unique=True` en `TenantModel.name`. El `IntegrityError` que el índice levanta
se traduce a `TenantAlreadyExistsError` y de ahí a 409 por el caso de uso, igual que
`user-management` traduce la violación de `uq_users_lower_email`.

**Why:** el bootstrap ya hace esto a mano y vale como prueba de que la operación existe; lo
que falta es darle la forma de dominio (validación centralizada en la entidad, no en
`app/cli/bootstrap.py` ni en el caso de uso nuevo) y un puerto para llamarla. Sin `add` en el
puerto el caso de uso de plataforma se vería obligado a importar el ORM, rompiendo la regla de
dependencia de `steering/backend-architecture.md`.

Rejected: factoría `TenantFactory` separada de la entidad — la regla de la sección "DDD:
bloques de construcción" dice que las invariantes que la entidad protege viven en la
entidad, no en una fábrica paralela; cederlas a `app/cli/bootstrap.py` con dos llamantes
pinta el caso simétrico de `User.create` que `user-management` rechazó.

### D3 — `CreateUserUseCase` se reusa tal cual con el `tenant_id` del path

**Chosen:** el endpoint `POST /api/v1/platform/tenants/{tenant_id}/users` monta su propio
caso de uso — un wrapper `CreateUserInTenantUseCase` que **no** duplica `CreateUserUseCase`,
sino que lo compone: resuelve el tenant por id (D4), lo confirma ACTIVO, y delega en
`CreateUserUseCase.execute(tenant_id=<path>, …)`. La auditoría sale con `tenant_id = <path>`,
no `None`, porque `CreateUserUseCase._audit.record` ya usa `tenant_id` del parámetro y no
del token (R4.3 del proposal).

**Why:** R4.3 promete "reusar el caso de uso de alta de `user-management`" — el motor de
creación (password generation, hashing, `must_change_password`, `AuditLog` con `password`
como `{"changed": true}`, traducción de `uq_users_lower_email` a 409) es exactamente el
mismo. Envolver en un caso de uso nuevo en `platform/` mantiene el router thin sin obligar
al router a importar `auth/application/user_admin`.

Rejected: copiar el cuerpo de `CreateUserUseCase` en un caso de uso propio del módulo
`platform/` — dos copias del mismo código de creación son dos sitios donde cambiar la
política de contraseña temporal cuando `auth-account-recovery` la mueva. La misma objeción
aplica a "exponer `CreateUserUseCase` como dependencia FastAPI en otro router": resuelve el
DRY a costa de meter un caso de uso de `auth` en el router de `platform`, lo que además
rompe la frontera por dominio de `steering/backend-architecture.md`.

### D4 — La existencia y el `status=ACTIVE` del tenant se comprueban con `TenantRepository.get`, montado en sesión sin marcar

**Chosen:** `platform/application/get_tenant_for_platform_use_case.py` (uno pequeño, o
reusar `GetTenantSettingsUseCase` con el truco de pasar el `tenant_id` del path en lugar del
del token) llama a `SqlAlchemyTenantRepository.get(tenant_id)`. La sesión sigue sin marcar
porque `SUPER_ADMIN` la deja así (`auth/api/dependencies.py:424`); la tabla `tenants` no
tiene `tenant_id` propio, así que el filtro global no la ve y este `get` por id es el camino
legítimo — `find_by_id` desde sesión sin marcar es exactamente la forma en que `get_active_by_id`
de `auth/infrastructure/repositories.py` ya hace la resolución cross-tenant en
`get_authenticated_request` para el bootstrap.

**Why:** R3.3 pide que "el tenant de la ruta no existe o no está ACTIVO" responda 404, y
`Tenant.get` ya devuelve `Tenant | None` con `status` en el dataclass. Sin leer el `status`
un `SUSPENDED` o un `INACTIVE` llegaría como 200 con un usuario creado en un tenant que no
puede iniciar sesión. La reutilización es directa: el caso de uso existente ya hace
`_require_own_tenant(...)` (compara el del path con el del token) y por eso R3.3 lo
**reescribe** — el path ya no valida "es tu tenant", eso es del router de tenants propio; el
caso de uso de plataforma valida "existe y está ACTIVE".

Rejected: añadir un filtro SQL `WHERE status = 'ACTIVE'` en una nueva query — duplica la
semántica de `auth-tenancy` y omite que `status` ya está en la entidad devuelta por `get`,
sin coste adicional.

### D5 — El `tenant_id` del `audit_logs` lo fija el caso de uso, no la sesión

**Chosen:** los dos casos de uso nuevos pasan `tenant_id` explícito a
`AuditLogFactory.build` — `tenant_id=tenant.id` para el alta de tenant, `tenant_id=<path>`
para el alta de usuario en tenant nombrado. La sesión sigue sin marcar (R1.3 del proposal:
la regla 1 de `steering/security.md` se relaja solo para el actor). El escritor usa el
mismo `_AuditWriter` que `user_management/application/user_admin.py:58` y `properties`:
`tenant_id` viene por parámetro, no de la sesión.

**Why:** D4 del proposal ya recoge esto como decisión vinculante. Lo que añade este diseño
es que el escritor ya existente lo cumple sin tocarse — basta con que el caso de uso le
pase el tenant. La invariante ("`audit_logs.tenant_id` no es nunca NULL") la sostiene la
propia fábrica `AuditLogFactory.build` (`backend/app/audit/domain/services.py:43`), que
recibe `tenant_id` como `uuid.UUID` requerido.

Rejected: convertir `audit_logs.tenant_id` en nullable y rellenarlo con `None` para el
actor — la regla 9 ("estados de propiedad ... AuditLog para: Reservation, estados de
propiedad, ...") presupone un `tenant_id` rellenable por entidad. La relajación rompería
`ix_audit_logs_tenant_id_entity_type_entity_id`, que es el camino que "qué pasó en este
tenant" usa.

### D6 — El permiso `MANAGE_PLATFORM` se concede exclusivamente a `SUPER_ADMIN`

**Chosen:** `app/auth/domain/policy.py` añade `MANAGE_PLATFORM = "MANAGE_PLATFORM"` a la
`Permission` (string, sin herencia, igual que los demás) y `ROLE_PERMISSIONS[SUPER_ADMIN]`
pasa a `_SELF_SERVICE | {MANAGE_PLATFORM}`. Los demás roles no se tocan: `TENANT_OWNER`,
`PROPERTY_MANAGER`, `CLEANER` y `TECHNICIAN` siguen con lo que ya tienen (R5.2), y
`GRANTABLE_ROLES` (`backend/app/auth/domain/entities.py:14`) sigue excluyendo
`SUPER_ADMIN`, así que `POST /api/v1/platform/tenants/{tenant_id}/users` rechaza
`role = SUPER_ADMIN` por el camino que ya rechaza ese rol en la ruta de users (R3.5).

**Why:** R5.1-R5.3 lo piden así. La pertenencia del permiso a `SUPER_ADMIN` y solo a
`SUPER_ADMIN` se demuestra por construcción: ni `_TENANT_SETTINGS_MANAGE`, ni `_USER_*`, ni
ninguna de las otras `_SOMETHING_*` lo arrastra; las pruebas de R5.3 son tests cerrados
sobre los cinco roles con `SUPER_ADMIN` incluido.

Rejected: meter `MANAGE_PLATFORM` dentro de un `_PLATFORM_*` bundle que también pudieran
usar otros roles — granularizar antes de tener más de un consumidor es el clásico permiso
que se queda sin usar (D3 del proposal). Una partición aquí no la pide nadie y obliga a
pensar quién paga cada mitad.

### D7 — `TENANT_CREATED` se añade al vocabulario cerrado de `actions.py`

**Chosen:** `app/audit/domain/actions.py` gana `TENANT_CREATED = "TENANT_CREATED"`, se
añade al `frozenset ACTIONS`, y `EntityTenant` (ya existe como `ENTITY_TENANT`) se queda
igual — solo crece la lista de acciones. El `ChangeSet` del diff lleva los cinco campos que
la entidad rellena en alta (`name`, `billing_email`, `country`, `timezone`,
`default_language`), todos como `diff("field", None, value)`.

**Why:** D1 del proposal lo exige por la regla 11 de `steering/security.md`: una sola
grafía por acción en `audit_logs.action`. Usar `TENANT_UPDATED` mintiendo que es creación
es la forma de "una fila de auditoría mal etiquetada es peor que una columna sin censar".

Rejected: reusar `TENANT_UPDATED` aunque la fila no exista antes — la query
"filas con `action = TENANT_CREATED`" deja de responder. Misma objeción a inventar `CREATE`
en vez de `_CREATED`: `_UPDATED` ya cubre lo siguiente y la grafía solo mantiene
consistencia con el resto del archivo (`USER_CREATED`, `PROPERTY_CREATED`,
`CLEANING_TASK_CREATED`, `INCIDENT_CREATED`).

## Changes by area

| Area | Files | Change |
|---|---|---|
| Audit vocabulary | `backend/app/audit/domain/actions.py` | Añadir `TENANT_CREATED` al `ACTIONS` frozenset; el `ENTITY_TENANT` ya existe. |
| Permission catalogue | `backend/app/auth/domain/policy.py` | Añadir `Permission.MANAGE_PLATFORM`; extender `ROLE_PERMISSIONS[SUPER_ADMIN]` con `_PLATFORM = {Permission.MANAGE_PLATFORM}`. |
| Tenants domain | `backend/app/tenants/domain/entities.py` | Añadir `Tenant.create(...)` reutilizando `_require_text`, `_require_email`, `normalise_country`, `normalise_timezone`, `normalise_language`. |
| Tenants ports | `backend/app/tenants/domain/repositories.py` | Añadir `TenantRepository.add(tenant: Tenant, config: TenantConfig) -> None` con docstring que explique que es la única vía de alta por dominio. |
| Tenants infra | `backend/app/tenants/infrastructure/repositories.py` | Implementar `add(...)` con `session.add` sobre `TenantModel` y `TenantConfigModel` y un `flush` para que `IntegrityError` (nombre duplicado) surja aquí y se traduzca a 409 en el caso de uso. |
| Platform module | `backend/app/platform/api/router.py` (nuevo), `schemas.py`, `dependencies.py` | Router `prefix="/platform"` con las dos rutas; `tags=["platform"]` y `summary`/`description` que digan literalmente "Requires `SUPER_ADMIN`". |
| Platform module | `backend/app/platform/application/use_cases.py` (nuevo) | `CreateTenantUseCase` (orquesta `Tenant.create`, `tenant_config.with_defaults`, `TenantRepository.add`, `audit`, `uow.commit` con traducción de `IntegrityError` a `DomainError` mapeada a 409). `CreateUserInTenantUseCase` (envuelve `CreateUserUseCase` con validación previa del tenant). |
| Platform module | `backend/app/platform/domain/exceptions.py` (nuevo) | `TenantAlreadyExistsError` (mapeada a 409), `TenantNotActiveError` (mapeada a 404, indistinguible de inexistente). |
| Mounting | `backend/app/main.py` | `from app.platform.api.router import router as platform_router` + `app.include_router(platform_router, prefix=API_V1_PREFIX)`. |
| Error mapping | `backend/app/platform/api/errors.py` (nuevo) | `register_platform_error_handlers(app)` mapeando las dos excepciones de arriba a los códigos 409/404 del envelope de PRD §23. |
| Audit factory call | (en el caso de uso nuevo) | `ChangeSet(actions.ENTITY_TENANT).diff("name", None, t.name).diff(...).diff(...)`. Para el alta de usuario, reusa el `_AuditWriter.record` de `user_admin.py`. |

## Data & interfaces

### API

Dos rutas nuevas en `backend/app/platform/api/router.py`, montadas en `app/main.py` bajo
`API_V1_PREFIX`:

- **`POST /api/v1/platform/tenants`** — body: `{name, billing_email, country, timezone,
  default_language}`. Decisión D6 obliga a `MANAGE_PLATFORM`. Respuestas: 201 con el recurso
  nuevo (incluye `id`, `status`, `tenant_configs` con sus defaults), 409 con `{error:
  {code: "TENANT_ALREADY_EXISTS", message, details}}` cuando el `name` esté en uso por un
  tenant `ACTIVE`, 422 con la lista de campos fallidos (validación Pydantic), 403 con un
  único motivo (no eres `SUPER_ADMIN`).
- **`POST /api/v1/platform/tenants/{tenant_id}/users`** — path: `tenant_id` UUID. Body:
  `{email, full_name, phone?, role}` con `role ∈ {TENANT_OWNER, PROPERTY_MANAGER, CLEANER,
  TECHNICIAN}`. Headers: `Authorization: Bearer <access_token>` de un `SUPER_ADMIN`. Decisión
  D6 obliga a `MANAGE_PLATFORM`. Respuestas: 201 con `{user, temporary_password}` (el
  password, **una sola vez**, con `Cache-Control: no-store` — el mismo `NO_STORE` de
  `auth/api/users_router.py:60`), 404 cuando el `tenant_id` no existe o no está `ACTIVE`,
  409 cuando el email ya existe bajo cualquier tenant (mismo trato que
  `user-management` R1.4), 422 para `role = SUPER_ADMIN` o body inválido, 403 con un único
  motivo.

### Schema

Ninguna migración nueva. El escritor usa las tablas que ya están: `tenants` (cinco campos
que ya existen en `tenants`/`tenant_configs`), `users` (las cinco columnas que ya tiene el
esquema), `audit_logs` (la fila existente con `tenant_id` rellenado por la entidad
afectada, no por la sesión).

### Config

Cero variables de entorno nuevas. La credencial de `SUPER_ADMIN` la sigue creando
`bootstrap.py` con las `BOOTSTRAP_SUPER_ADMIN_*` que ya están en `Settings` y
`.env.example`. No se abren nuevas rutas de credencial.

## Risks & mitigations

- **R-1 — `audit_logs.tenant_id` queda `NULL` si alguien futuro llama `_AuditWriter.record`
  con el tenant del token en vez del path.** El caso de uso nuevo cierra esto
  estructuralmente porque el parámetro `tenant_id` ya es el del path, no el del token — el
  token del `SUPER_ADMIN` lleva `tenant_id=None`. La invariante "nunca `NULL` en
  `audit_logs.tenant_id`" la sostiene la fábrica (`backend/app/audit/domain/services.py`):
  `tenant_id: uuid.UUID` (no `Optional`). El test que afirma esto es uno de R5: para los
  cinco roles que **no** tienen `MANAGE_PLATFORM`, el 403 corta antes de tocar auditoría, y
  para `SUPER_ADMIN` la única ruta autenticada que llega a la fábrica lleva `tenant_id`
  resuelto por el caso de uso, nunca por la sesión.
- **R-2 — Dos `POST` concurrentes con el mismo `name` eluden el check y
  crean duplicados.** El check se delega al índice `uq_tenants_name` (D2 lo nombra — la
  migración `tenants_name_unique` lo crea, porque la baseline no lo traía) y se traduce vía
  `IntegrityError` en el caso de uso. El camino paralelo
  (`get or create` antes de `add`) sería la fuente del bug, y por eso `TenantRepository.add`
  hace solo `session.add` + `flush`. Un test de concurrencia (dos altas simultáneas con el
  mismo nombre terminan una en 201 y otra en 409) cierra el flanco.
- **R-3 — La nueva ruta de creación de usuario hereda el `IntegrityError` a `uq_users_lower_email`
  y el wrapper olvida mapearlo a 409 con un mensaje accionable.** El
  `CreateUserInTenantUseCase` reusa `CreateUserUseCase.execute`, que ya traduce la
  violación del índice al código de `user-management`; el wrapper solo añade la
  comprobación previa del tenant. Test de R3.4 cubre el caso.
- **R-4 — `MANAGE_PLATFORM` se filtra a un rol futuro por descuido.** El permiso se concede
  explícitamente solo a `SUPER_ADMIN` (D6) — `_PLATFORM` no es un bundle que nadie arrastre,
  y el test R5.3 cierra el camino: para cada uno de los cinco roles, ambos endpoints
  devuelven 403.
- **R-5 — La consola de frontend (`super-admin-console`) intenta consumir estas rutas antes
  de que aterrice `super-admin-identity` archivado.** Eso es fuera de alcance de este
  change, pero la superficie OpenAPI está pensada para que el generador del frontend la
  pueda leer desde el día uno: `tags=["platform"]`, `summary` y `description` que digan
  literalmente "Requires `SUPER_ADMIN`". Una nota en `sdd/specs/auth-tenancy.md` sobre
  "permisos concedidos a `SUPER_ADMIN`" se añadirá al archivar (no antes), siguiendo el
  patrón que dejó `super-admin-identity` para la identificación del rol.
- **R-6 — El guard `MANAGE_PLATFORM` se monta por error en otro router en un cambio futuro.**
  La dependencia `require(Permission.MANAGE_PLATFORM)` vive solo en
  `backend/app/platform/api/dependencies.py`; un test estructural (`tests/test_route_authorization.py`-style)
  falla si una ruta con ese `require` aparece fuera del prefijo `/api/v1/platform`. Esto
  es un test nuevo específico de este change, no la suite genérica, y su intención es
  documentada en la nota de diseño.

## Open questions

1. **¿Dónde se monta `require(Permission.MANAGE_PLATFORM)` exactamente?** La propuesta
   dice "vive en un router propio bajo `/platform`" (R6.1), pero deja sin decir si el
   factory de la dependencia vive en `platform/api/dependencies.py` (módulo local) o
   directo en el router como un módulo más de `auth/api/dependencies.py`. La primera es
   más coherente con los otros routers; la segunda evita abrir un fichero nuevo. Mi
   recomendación: `backend/app/platform/api/dependencies.py`, siguiendo el patrón que ya
   usan `tenants/api/dependencies.py` y `auth/api/user_dependencies.py`. Si quieres
   otra cosa, dímelo antes de `/sdd:tasks`.
2. **¿Se conserva `app/cli/bootstrap.py` como única creadora de `tenant_configs`
   explícita o se le quita y se deja todo a `CreateTenantUseCase`?** Mover el alta del
   `tenant_configs` del bootstrap al caso de uso nuevo dejaría el CLI llamando al caso de
   uso (con `apply_plan` reescrito) y un único camino de creación. Conservarlo como
   ahora es más conservador: dos rutas que escriben el mismo par de filas pero no se
   pisan (el bootstrap solo se ejecuta una vez en el despliegue, la API es por entorno).
   Mi recomendación: conservador — el bootstrap conserva su camino, R7.1-R7.3 lo dice,
   y esta entrada no reorganiza el CLI.
3. **¿`CreateTenantUseCase` debe crear también el `TenantConfig` con `storage_type = LOCAL`
   explícito, o basta con `TenantConfig.with_defaults(...)` (que ya pone `LOCAL`)?
   `with_defaults` deja todo a los defaults del dataclass, incluido `storage_type = LOCAL`
   (consistente con `bootstrap.py:155`). Mi recomendación: `with_defaults`, sin tocar
   `storage_type` en el caso de uso. Si el operador quiere `S3` lo pide por otra vía
   (cambio de `storage_type` por `PATCH /tenants/{id}`, ya rechazado por R5.4 del
   `user-management`).

## Out of scope (recordatorio, ya en el proposal)

Cero UI, cero list/borrado/suspensión de tenants, cero impersonation, cero
edición/reset de usuarios desde plataforma, cero ampliación de `GRANTABLE_ROLES`, cero
nuevo `SUPER_ADMIN` por API. Todo esto queda para `saas-cross-tenant` u otra entrada
posterior.
