# Proposal: super-admin-identity

## Why

Jose declaró el 2026-08-29, en el gate de `/sdd:design` de `notifications-inbox-web`, que
`SUPER_ADMIN` debe ser un superusuario **con visibilidad sobre todos los tenants y no
perteneciente a ninguno**, y que su menú de plataforma tiene que reemplazar lo que hoy se hace
a mano contra la base de datos o la API. El `/sdd:new` de `super-admin-console` (2026-08-31)
midió que esa entrada no era implementable de una pieza y la partió en tres; ésta es el
**corte (a)**: el modelo de identidad. `platform-admin-api` (corte b, `needs: super-admin-identity`)
y `super-admin-console` (corte c, `needs` ambas) dependen de que esta exista primero. Censo
completo y frontera con `saas-cross-tenant` (post-MVP, condicional) en
`sdd/roadmap/super-admin-console.md`.

Hoy el rol simplemente **no cabe en el esquema**: `UserModel.tenant_id`
(`app/auth/infrastructure/models.py`) es `NOT NULL` desde la migración baseline
(`4a5faad7796b`), `User.tenant_id` (`app/auth/domain/entities.py`) es un campo obligatorio del
dataclass, y todo el ciclo de autenticación lo asume presente: `AccessTokenClaims.tenant_id` no
es opcional, `get_active_by_id(tenant_id, user_id)` (`app/auth/infrastructure/repositories.py`)
hace un `JOIN` contra `TenantModel` que exige un tenant `ACTIVE`, `RequestContext.tenant_id`
(`app/auth/domain/context.py`) rechaza en `__post_init__` cualquier valor que no sea un `UUID`, y
`bind_session_to_tenant` (`app/core/db.py`) **lanza** si se le pasa `None` — es la mitad del
mecanismo de aislamiento por tenant (`_scope_statement_to_tenant`, rule 1 de
`steering/security.md`), que hoy asume que toda sesión marcada lo está con un tenant real.

**Corrección al censo de `sdd/roadmap/super-admin-console.md`**: dice que «solo existe el
[`SUPER_ADMIN`] que siembra el bootstrap». Medido hoy contra `app/cli/bootstrap.py`,
`apply_plan.plan.users` solo contiene un `SeedUser` `TENANT_OWNER` y uno `PROPERTY_MANAGER`
(`sdd/specs/auth-tenancy.md`: «El bootstrap crea **dos** cuentas y nada más»). **No existe ningún
`SUPER_ADMIN` en el sistema hoy**, ni sembrado ni creable por API (`GRANTABLE_ROLES` lo excluye,
`app/auth/domain/entities.py:14`). Esta capacidad no solo tiene que dejar sitio para la
identidad en el esquema: tiene que dar una forma de crearla, o el modelo queda sin verificar de
punta a punta.

## What changes

`SUPER_ADMIN` pasa a poder existir sin `tenant_id`, se autentica de punta a punta (login,
refresh, logout, `me`) sin que ningún paso del ciclo asuma un tenant, y su sesión de base de
datos se queda **sin marcar** — la excepción a la regla 1 de `steering/security.md` que el
requisito pide, documentada por su nombre y su alcance en vez de dejarla implícita. El bootstrap
gana una tercera cuenta seed para que la identidad sea verificable, no solo declarable en el
esquema. No cambia ningún permiso operativo, ninguna ruta de plataforma y ninguna pantalla — eso
es `platform-admin-api` y `super-admin-console`, que dependen de esto.

## Requirements

### R1 — El esquema admite un `SUPER_ADMIN` sin tenant

**As a** persona que despliega la plataforma, **I want** que una cuenta `SUPER_ADMIN` pueda
existir sin pertenecer a ningún tenant, **so that** el rol represente lo que el producto necesita
—una identidad de plataforma, no la de un tenant más— en vez de forzar un tenant de mentira para
que el esquema la acepte.

Acceptance criteria:

1. WHEN se crea una cuenta con `role = SUPER_ADMIN`, THE SYSTEM SHALL permitir que su
   `tenant_id` sea nulo.
2. THE SYSTEM SHALL seguir exigiendo `tenant_id` no nulo para `TENANT_OWNER`,
   `PROPERTY_MANAGER`, `CLEANER` y `TECHNICIAN` — la relajación no alcanza a ningún otro rol.
3. THE SYSTEM SHALL enviar la migración de Alembic que relaja `users.tenant_id` a nullable sin
   exigir backfill: cada fila existente ya tiene un `tenant_id` concreto.
4. IF la migración se revierte con alguna fila `users.tenant_id IS NULL` en la base, THEN THE
   SYSTEM SHALL rechazar el downgrade en vez de reintroducir el `NOT NULL` sobre datos que ya lo
   violan.

### R2 — La autenticación funciona de punta a punta sin tenant

**As a** `SUPER_ADMIN`, **I want** poder hacer login, refrescar mi sesión, cerrarla y leer mi
propio perfil igual que cualquier otro rol, **so that** la identidad sin tenant no sea solo una
fila que el esquema acepta sino una cuenta que realmente funciona.

Acceptance criteria:

1. WHEN un `SUPER_ADMIN` hace `POST /api/v1/auth/login` con credenciales válidas, THE SYSTEM
   SHALL responder `200` con un par de tokens cuyos claims no requieren un `tenant_id`.
2. WHEN se verifica el access token de un `SUPER_ADMIN` (`get_authenticated_request`), THE
   SYSTEM SHALL reconstruir el `RequestContext` sin unir contra ningún tenant, revalidando
   solo que el usuario sigue `ACTIVE`.
3. WHEN se presenta a `POST /api/v1/auth/refresh` un refresh token válido de un `SUPER_ADMIN`,
   THE SYSTEM SHALL rotarlo exactamente igual que para cualquier otro rol (mismo mecanismo de
   family/rotación de `auth-tenancy`).
4. WHEN un `SUPER_ADMIN` llama `GET /api/v1/auth/me` o `POST /api/v1/auth/logout`, THE SYSTEM
   SHALL responder correctamente — ningún `500` por código que asuma que toda petición
   autenticada trae un tenant.

### R3 — La sesión de un `SUPER_ADMIN` queda sin marcar, y la excepción está documentada

**As a** responsable de seguridad del proyecto, **I want** que la excepción a la regla 1 de
`steering/security.md` que un `SUPER_ADMIN` sin tenant necesita esté nombrada, acotada y escrita,
**so that** no sea un agujero implícito que alguien descubra leyendo el código.

Acceptance criteria:

1. WHEN una petición se autentica como `SUPER_ADMIN`, THE SYSTEM SHALL NOT vincular la sesión
   de base de datos a ningún tenant — el filtro global de `_scope_statement_to_tenant`
   (`app/core/db.py`) se queda inactivo para esa petición, igual que ya ocurre hoy con el
   bootstrap, el login anónimo o `POST /auth/refresh`.
2. THE SYSTEM SHALL documentar esta excepción por su nombre en `steering/security.md` regla 1:
   qué peticiones cubre, por qué (`SUPER_ADMIN` no pertenece a ningún tenant por requisito de
   producto) y qué seguridad la delimita (el rol no tiene ningún permiso operativo salvo
   autoservicio — R4).

### R4 — Esta capacidad no amplía lo que un `SUPER_ADMIN` puede hacer

**As a** revisor de seguridad, **I want** que dar identidad al `SUPER_ADMIN` no le conceda de
paso ningún permiso operativo, **so that** la excepción a la regla 1 quede acotada a "existir y
autenticarse" y no se cuele una escalada de privilegios por el camino.

Acceptance criteria:

1. THE SYSTEM SHALL mantener `ROLE_PERMISSIONS[UserRole.SUPER_ADMIN]` igual a `_SELF_SERVICE`
   (`READ_OWN_PROFILE`, `MANAGE_OWN_SESSION`, `READ_OWN_NOTIFICATIONS`) y nada más — ningún
   permiso de lectura o gestión de ningún módulo de negocio.
2. THE SYSTEM SHALL mantener `GRANTABLE_ROLES` sin cambios (`SUPER_ADMIN` excluido,
   `app/auth/domain/entities.py:14`): no se puede crear ni promover a `SUPER_ADMIN` por API. La
   única vía sigue siendo la CLI de R5 — abrir esa puerta es una decisión propia que
   `platform-admin-api` o una entrada futura pueden tomar, no ésta.

### R5 — La cuenta se puede crear de verdad

**As a** persona que despliega un entorno nuevo, **I want** una forma de crear la primera cuenta
`SUPER_ADMIN`, **so that** el modelo de identidad sea verificable de punta a punta y no quede
como un esquema que nadie puede poblar.

Acceptance criteria:

1. THE SYSTEM SHALL extender `app/cli/bootstrap.py` (o un comando equivalente) para crear una
   tercera cuenta seed, `SUPER_ADMIN`, sin `tenant_id`, con sus propias variables
   `BOOTSTRAP_SUPER_ADMIN_*` siguiendo el patrón ya validado de las ocho `BOOTSTRAP_*`
   existentes (nombre, email, contraseña — validadas antes de abrir transacción, como las
   demás).
2. THE SYSTEM SHALL mantener el comando convergente (R7.2/D10 de `auth-tenancy`): una
   re-ejecución no duplica la cuenta ni falla si ya existe.
3. IF la dirección de la cuenta `SUPER_ADMIN` ya existe bajo un tenant, THEN THE SYSTEM SHALL
   abortar con el mismo `BootstrapConflictError` que ya protege a las otras dos cuentas.

## Out of scope

- Cualquier ruta nueva de administración de plataforma (`POST /api/v1/tenants`, alta de
  managers/cleaners/technicians en un tenant nombrado, su auditoría) — eso es
  `platform-admin-api`, que depende de esta entrada.
- Cualquier superficie de frontend (aterrizaje por rol, pantallas) — eso es
  `super-admin-console`, que depende de ésta y de `platform-admin-api`.
- Visibilidad cross-tenant e impersonation — eso es `saas-cross-tenant`, post-MVP y condicional;
  esta entrada no la precomprometeni la bloquea.
- Abrir `GRANTABLE_ROLES` para crear o promover a `SUPER_ADMIN` por API (R4.2): se queda cerrado.
- Cómo escribe `AuditLog` una acción iniciada por un `SUPER_ADMIN`: `audit_logs` también lleva
  `TenantScopedMixin`, y ninguna ruta de esta entrada (login/refresh/logout/me) escribe una
  entidad auditada. La primera que lo necesite es `platform-admin-api`, y esa decisión es suya.

## Affected specs

- `sdd/specs/auth-tenancy.md` (existe) — secciones «Tokens» (claim `tenant_id`), «Aislamiento
  por tenant» (censo de sesiones sin marcar) y «Bootstrap del acceso inicial» (dos cuentas → tres).
