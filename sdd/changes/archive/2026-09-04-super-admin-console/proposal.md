# Proposal: super-admin-console

## Why

`SUPER_ADMIN` existe en el esquema y en el backend, y no alcanza ninguna pantalla: hoy
crear un tenant o dar de alta a su primer manager se hace escribiendo a mano contra la
base de datos o llamando a la API con un cliente HTTP. Requisito declarado por Jose el
2026-08-29 (gate de `/sdd:design` de `notifications-inbox-web`): un superusuario con
visibilidad de plataforma, no perteneciente a ningún tenant, cuyo menú en el frontend
haga lo que hoy se hace a mano.

Es el corte (c) — el último — de la partición que este mismo `/sdd:new` hizo el
2026-08-31 sobre la entrada original `[BE+FE]` (censo completo y razón del corte en
`sdd/roadmap/super-admin-console.md`). Los otros dos cortes ya están archivados y son la
base de este proposal:

- **`super-admin-identity`** (archivada 2026-09-02): `SUPER_ADMIN` puede existir sin
  `tenant_id`, se autentica de punta a punta con la sesión de base de datos sin marcar.
- **`platform-admin-api`** (archivada 2026-09-03): dos rutas bajo `/api/v1/platform`,
  gateadas por el permiso nuevo `MANAGE_PLATFORM` (solo `SUPER_ADMIN` lo tiene) —
  `POST /tenants` y `POST /tenants/{tenant_id}/users` — documentadas en
  `sdd/specs/super-admin-identity.md`, que dice literalmente que el "cómo se opera la
  superficie" lo escribe esta entrada.

**Un límite real que este `/sdd:new` decidió no heredar en silencio**: `platform-admin-api`
dejó "listar tenants" explícitamente fuera de alcance (su router de plataforma solo tiene
las dos rutas `POST`; el de `tenants` mantiene `GET`/`PATCH` **por id**, nunca una lista).
Sin una lista, la consola solo podría operar sobre un `tenant_id` que el propio
`SUPER_ADMIN` ya conociera de memoria o de una nota — típicamente el que él mismo acaba de
crear en la misma sesión de navegador — y quedaría inutilizable en cuanto quisiera volver a
un tenant de una sesión anterior. Decidido explícitamente en el gate de este `/sdd:new`
(2026-09-03): esta entrada reabre esa frontera de forma acotada y añade **una** ruta de
lectura nueva, `GET /api/v1/platform/tenants`, con el mismo permiso y el mismo patrón de
paginación que el resto de la aplicación — no las demás operaciones de ciclo de vida
(suspender/archivar/borrar) que `platform-admin-api` también excluyó y que siguen
correspondiendo a `saas-cross-tenant`.

## What changes

Después de este change, `SUPER_ADMIN` aterriza tras el login en una consola de plataforma
propia — no en `/dashboard` ni en el `WorkspaceShell` con aislamiento por tenant, porque el
rol no pertenece a ninguno — con dos capacidades: **ver los tenants que existen** (lista
nueva, de solo lectura) y, sobre uno de ellos, **crear el tenant** o **darle su primer
personal** (`TENANT_OWNER`, `PROPERTY_MANAGER`, `CLEANER` o `TECHNICIAN`), reusando las dos
rutas de `platform-admin-api` ya existentes. Nada de esto lee datos operativos de un
tenant ni permite entrar en él — eso sigue siendo `saas-cross-tenant`, post-MVP y
condicional.

## Requirements

### R1 — `SUPER_ADMIN` aterriza en su propia consola, no en `/dashboard`

**As a** `SUPER_ADMIN`, **I want** llegar a una pantalla que pueda usar en cuanto inicio
sesión, **so that** no me rebote un `AuthGuard` pensado para roles de tenant.

Acceptance criteria:

1. THE SYSTEM SHALL añadir una fila `SUPER_ADMIN` a `ROLE_HOME`
   (`frontend/features/auth/lib/role-home.ts`) que apunte a la ruta de la consola de
   plataforma.
2. WHEN un `SUPER_ADMIN` inicia sesión sin `?returnTo=`, THE SYSTEM SHALL enviarlo a esa
   ruta.
3. THE SYSTEM SHALL proteger la ruta de la consola con un `AuthGuard allow={["SUPER_ADMIN"]}`
   propio, siguiendo el mismo patrón que ya usan `(workspace)` y los grupos de rol de campo
   — nunca reusando el `AuthGuard allow={["TENANT_OWNER", "PROPERTY_MANAGER"]}` de
   `(workspace)/layout.tsx`.
4. THE SYSTEM SHALL NOT montar el `WorkspaceShell` (selector de tenant, navegación con
   alcance de tenant) para `SUPER_ADMIN` — el rol no pertenece a ningún tenant y ese chrome
   no aplica.
5. WHEN un rol distinto de `SUPER_ADMIN` solicita la ruta de la consola, THE SYSTEM SHALL
   denegarla con el mismo criterio de rebote que el resto de grupos de ruta protegidos.

### R2 — Lista de tenants existentes

**As a** `SUPER_ADMIN`, **I want** ver los tenants que ya existen, **so that** pueda elegir
uno para darle personal sin depender de recordar su id de una sesión anterior.

Acceptance criteria:

1. THE SYSTEM SHALL exponer `GET /api/v1/platform/tenants` en el router de plataforma
   (`app/platform/api/router.py`), gateada por `Permission.MANAGE_PLATFORM` —mismo permiso
   que las dos rutas existentes, mismo `PlatformDep`—, paginada con la forma ya usada por el
   resto de listados (`items`, `total`, `page`, `per_page`).
2. THE SYSTEM SHALL devolver los tenants ordenados por `created_at` descendente (el más
   reciente primero), sin parámetro de orden configurable.
3. IF no existe ningún tenant, THEN THE SYSTEM SHALL devolver `items: []` y `total: 0`,
   nunca un error.
4. THE SYSTEM SHALL reusar `TenantResponse` (`app/tenants/api/schemas.py`) como forma de
   cada elemento — el mismo mapeo que ya usa `POST /platform/tenants` — sin declarar un
   tipo paralelo.
5. THE SYSTEM SHALL NOT exponer esta ruta a ningún rol distinto de `SUPER_ADMIN`.
6. THE SYSTEM SHALL renderizar la lista en la consola mostrando al menos nombre, estado y
   fecha de creación de cada tenant, con paginación si `total` excede una página.

### R3 — Crear un tenant desde la consola

**As a** `SUPER_ADMIN`, **I want** crear un tenant nuevo desde el navegador, **so that** no
tenga que escribir contra la base de datos ni llamar a la API a mano.

Acceptance criteria:

1. THE SYSTEM SHALL presentar un formulario con exactamente los campos que acepta
   `CreateTenantRequest` (`name`, `billing_email`, `country`, `timezone`,
   `default_language`), llamando a `POST /api/v1/platform/tenants`.
2. WHEN la API responde `201`, THE SYSTEM SHALL mostrar el tenant creado y ofrecer, en la
   misma vista y sin recargar ni volver a pedir la lista de R2, continuar directamente al
   alta de su primer personal (R4) usando el `id` que la propia respuesta devuelve.
3. IF la API rechaza la petición (`422`/`409`), THEN THE SYSTEM SHALL mostrar el error por
   campo que la API devuelve, sin inventar un mensaje genérico.
4. THE SYSTEM SHALL NOT ofrecer un campo de `status` — un tenant nace `ACTIVE` siempre,
   igual que en el contrato de la API.

### R4 — Dar de alta personal en un tenant nombrado

**As a** `SUPER_ADMIN`, **I want** crear una cuenta de manager, propietaria, limpiadora o
técnico en un tenant concreto, **so that** ese tenant tenga al menos un login operativo sin
pasar por el bootstrap de CLI.

Acceptance criteria:

1. THE SYSTEM SHALL presentar un formulario con exactamente los campos que acepta
   `CreatePlatformUserRequest`, acotado a un tenant elegido (de la lista de R2 o del recién
   creado en R3), llamando a `POST /api/v1/platform/tenants/{tenant_id}/users`.
2. THE SYSTEM SHALL restringir el selector de rol a `TENANT_OWNER`, `PROPERTY_MANAGER`,
   `CLEANER` y `TECHNICIAN` exclusivamente, y NEVER SHALL ofrecer `SUPER_ADMIN` como opción
   — `GRANTABLE_ROLES` sigue excluyéndolo y este change no reabre esa decisión.
3. WHEN la API responde `201`, THE SYSTEM SHALL mostrar la contraseña temporal de un solo
   uso de forma prominente, con un control de copiar al portapapeles y una advertencia
   visible de que no volverá a mostrarse.
4. THE SYSTEM SHALL NOT persistir esa contraseña en ningún almacenamiento del cliente más
   allá de la vista en memoria de la propia pantalla — nada en `localStorage`, en la query
   string ni en el historial de navegación —, coherente con el `Cache-Control: no-store`
   que la propia respuesta de la API ya lleva.
5. IF la API rechaza la petición, THEN THE SYSTEM SHALL mostrar el error por campo que
   devuelve.

### R5 — i18n y línea base mobile-first

**As a** operador que puede no leer español o estar en el móvil, **I want** que la consola
siga las mismas convenciones de i18n y responsive del resto de la app, **so that** no sea
una superficie de segunda categoría.

Acceptance criteria:

1. THE SYSTEM SHALL pasar toda string visible por `locales/es/` y `locales/en/`
   (`steering/frontend.md`), sin nada hardcodeado.
2. THE SYSTEM SHALL usar un layout responsive con las convenciones shadcn/Tailwind ya
   existentes — el uso principal se espera de escritorio, pero un operador puede empezar
   desde el móvil.

## Out of scope

- **Leer datos operativos de cualquier tenant, o impersonar a un usuario dentro de él** —
  eso es `saas-cross-tenant`, post-MVP y condicional. Incluye la ampliación «entrar en un
  tenant a comprobar que todo va bien» que Jose declaró junto al requisito original: **no**
  es esta entrada.
- **Suspender, reactivar, archivar o borrar tenants**, y **editar o resetear cuentas** desde
  la superficie de plataforma — decisión heredada sin cambios de `platform-admin-api`
  (siguen correspondiendo a `saas-cross-tenant` cuando se decida).
- **Crear o promover a otro `SUPER_ADMIN`** por la consola — `GRANTABLE_ROLES` sigue sin
  abrirse; decisión no reabierta por este change.
- **Filtrar o buscar en la lista de tenants** (R2) más allá de la paginación simple — se
  añade si el número real de tenants lo justifica; hoy no.
- **Una pantalla de auditoría** ("todo lo que ha hecho `SUPER_ADMIN`") — `AuditLog` ya
  registra cada alta; leerla de forma agregada es una capacidad de reporting que
  `platform-admin-api` ya declaró que no promete y este change tampoco.

## Affected specs

- `sdd/specs/super-admin-identity.md` (existe) — añade la documentación de
  `GET /api/v1/platform/tenants` (R2) y la sección de "cómo se opera la superficie" que el
  propio spec dejó pendiente para esta entrada.
- `sdd/specs/frontend-auth-role-routing.md` (existe) — la fila `SUPER_ADMIN` en `ROLE_HOME`
  y el `AuthGuard` nuevo de la consola.
- `sdd/specs/user-management.md` (existe) — referencia cruzada al alta de personal desde la
  consola (R4), sin duplicar las reglas de `CreatePlatformUserRequest` que ya documenta
  `super-admin-identity.md`.
- `sdd/specs/super-admin-console.md` *(no existe aún — se creará al archivar)* — el
  comportamiento de la consola en sí: rutas de frontend, formularios, manejo de la
  contraseña de un solo uso.
