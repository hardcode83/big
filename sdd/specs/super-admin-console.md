# Consola de plataforma (`SUPER_ADMIN`)

## Purpose

`SUPER_ADMIN` aterriza, tras el login, en una consola de plataforma propia — no en
`/dashboard` ni en el `WorkspaceShell` con aislamiento por tenant, porque el rol no
pertenece a ningún tenant. Desde ahí puede **ver los tenants que existen** (lista de solo
lectura), **crear un tenant nuevo** y **darle su primer personal** (`TENANT_OWNER`,
`PROPERTY_MANAGER`, `CLEANER` o `TECHNICIAN`), reusando las rutas de backend que
`super-admin-identity` documenta. Es el *cómo se opera* esa superficie — pantallas,
formularios, manejo de la contraseña de un solo uso —; el *qué hace* el backend que esta
consola consume vive en `sdd/specs/super-admin-identity.md`. No lee datos operativos de
ningún tenant ni permite entrar en él — eso sigue siendo `saas-cross-tenant`, post-MVP y
condicional.

## Requirements

### Aterrizaje y aislamiento de la ruta

- THE SYSTEM SHALL añadir una fila `SUPER_ADMIN: "/platform"` a `ROLE_HOME`
  (`frontend/features/auth/lib/role-home.ts`).
- WHEN un `SUPER_ADMIN` inicia sesión sin `?returnTo=`, THE SYSTEM SHALL enviarlo a
  `/platform` — `LoginForm` ya resuelve cualquier rol distinto de `CLEANER`/`TECHNICIAN`
  directamente vía `roleHome(role)`, sin cambio adicional en ese componente.
- THE SYSTEM SHALL montar `/platform` en su propio grupo de rutas
  `app/(platform)/layout.tsx`: `AuthGuard allow={["SUPER_ADMIN"]}` alrededor de un
  `ShellFrame` desnudo (solo topbar: `Brand` + `UserMenu`; sin sidebar, sin navegación
  inferior, sin footer — la misma composición que `(authenticated)/layout.tsx` usa para
  `/welcome`).
- THE SYSTEM SHALL NOT montar `WorkspaceShell` (selector de tenant, navegación con
  alcance de tenant) para `SUPER_ADMIN` — el rol no pertenece a ningún tenant y ese chrome
  no aplica.
- WHEN un rol distinto de `SUPER_ADMIN` solicita `/platform`, THE SYSTEM SHALL denegarla
  con el mismo criterio de rebote (`AuthGuard`, `/login?denied=role`) que el resto de
  grupos de ruta protegidos.
- THE SYSTEM SHALL registrar `/platform` en `route-registry.ts` con un `ShellProfile`
  propio (`"platform"`), `pattern: "/platform"`, `match: "exact"` y sin `navigationGroup`
  — nada más enlaza a ella, el mismo tratamiento que recibe `welcome` — y en
  `REAL_PAGE_ROUTE_IDS` (`app/route-coverage.test.ts`) como
  `"(platform)/platform/page.tsx": "platform"`.

### Lista de tenants existentes

- THE SYSTEM SHALL renderizar en `/platform` la lista de tenants devuelta por
  `GET /api/v1/platform/tenants` (`sdd/specs/super-admin-identity.md`), mostrando al
  menos nombre, estado y fecha de creación de cada uno.
- THE SYSTEM SHALL paginar la lista cuando `total` exceda una página, con un componente
  `PlatformPagination` propio (`features/platform/components/platform-pagination.tsx`) —
  un tercer near-copy de `CleaningPagination`/`PricingPagination`, sin generalizar los
  tres en un componente compartido (decisión explícita del change, disponible como
  limpieza futura separada).
- IF no existe ningún tenant, THEN THE SYSTEM SHALL mostrar un estado vacío localizado en
  vez de una tabla en blanco.
- IF la carga de la lista falla, THEN THE SYSTEM SHALL mostrar un estado de error
  localizado con posibilidad de reintentar, sin propagar el error crudo del backend.
- THE SYSTEM SHALL identificar cada fila con una acción "add staff" que abre el
  formulario de alta de personal (siguiente sección) pre-acotado al `id` de esa fila —
  alcanzable para cualquier tenant existente, no solo el recién creado.

### Crear un tenant desde la consola

- THE SYSTEM SHALL presentar, en un `Sheet` (no una ruta ni un `Dialog` de
  confirmar/cancelar), un formulario con exactamente los campos que acepta
  `CreateTenantRequest` (`name`, `billing_email`, `country`, `timezone`,
  `default_language`), llamando a `POST /api/v1/platform/tenants`.
- WHEN la API responde `201`, THE SYSTEM SHALL mostrar el tenant creado y ofrecer, en el
  mismo `Sheet` y sin recargar ni volver a pedir la lista de tenants, continuar
  directamente al alta de su primer personal usando el `id` que la propia respuesta
  devuelve. La mutación de creación de tenant NO SHALL invalidar ni re-consultar la
  query key de la lista (`platformKeys.tenantsList(...)`) — la lista solo refleja el
  tenant nuevo en su próximo refetch natural (revisita, refoco, o reapertura manual de
  `/platform`), una ventana de staleness aceptada por el requisito.
- IF la API rechaza la petición (`422`/`409`), THEN THE SYSTEM SHALL mostrar el error por
  campo que la API devuelve, sin inventar un mensaje genérico — `422` lee
  `error.details.errors` y clava el mensaje al último segmento de `loc`; `409`
  (`TenantAlreadyExistsError`) no trae `loc`, así que el campo se infiere por punto de
  llamada (`name`, en el formulario de tenant). Cualquier otro estado (`403`, `5xx`, red)
  cae al patrón de error genérico localizado, no a un error de campo.
- THE SYSTEM SHALL NOT ofrecer un campo de `status` en el formulario — un tenant nace
  `ACTIVE` siempre.

### Dar de alta personal en un tenant nombrado

- THE SYSTEM SHALL presentar un formulario con exactamente los campos que acepta
  `CreatePlatformUserRequest`, acotado a un tenant elegido (de la lista o del recién
  creado), llamando a `POST /api/v1/platform/tenants/{tenant_id}/users`.
- THE SYSTEM SHALL restringir el selector de rol a `TENANT_OWNER`, `PROPERTY_MANAGER`,
  `CLEANER` y `TECHNICIAN` exclusivamente, y SHALL NOT ofrecer `SUPER_ADMIN` como opción
  — `GRANTABLE_ROLES` lo sigue excluyendo y esta consola no reabre esa decisión.
- WHEN la API responde `201`, THE SYSTEM SHALL mostrar la contraseña temporal de un solo
  uso de forma prominente (`TemporaryPasswordReveal`), con un control de copiar al
  portapapeles (`navigator.clipboard.writeText`, sin fallback) y una advertencia visible
  y persistente de que no volverá a mostrarse.
- THE SYSTEM SHALL NOT persistir esa contraseña en ningún almacenamiento del cliente más
  allá de la vista en memoria de la propia pantalla — nada en `localStorage`, en la query
  string ni en el historial de navegación. La mutación de alta de personal
  (`useCreatePlatformUser`) SHALL declarar `gcTime: 0` para que el `MutationCache` de
  TanStack Query no retenga la contraseña en claro más allá del tiempo de vida del
  `Sheet` — sin ese ajuste, el `gcTime` por defecto (5 minutos) la mantendría alcanzable
  en esa caché tras cerrarse la pantalla.
- IF la API rechaza la petición, THEN THE SYSTEM SHALL mostrar el error por campo que
  devuelve (mismo mapeo que la creación de tenant; `409` de `EmailAlreadyExistsError` se
  atribuye al campo `email`).
- THE SYSTEM SHALL cerrar el `Sheet` sin ofrecer ningún camino para volver a ver la
  contraseña ya mostrada — coherente con el contrato "exactamente una vez" del backend.

### i18n y línea base responsive

- THE SYSTEM SHALL pasar toda string visible de la consola por
  `locales/{es,en}/platform.json` (namespace `platform`, registrado en
  `lib/i18n/resources.ts`), sin nada hardcodeado — encabezados de columna, ambos
  formularios, el texto de la contraseña revelada, el estado vacío y el de error.
- **Excepción deliberada, acotada a los mensajes de campo:** los mensajes de error de
  campo que `mapFieldErrors` extrae de la respuesta del backend (`msg`/`message`) se
  muestran verbatim, en inglés, sin pasar por `locales/` — son el propio texto del
  backend (`steering/backend.md`: mensajes técnicos en inglés), y traducirlos sería
  fabricar el "mensaje genérico inventado" que el requisito rechaza explícitamente.
  Ningún otro texto de la consola está exento de i18n.
- THE SYSTEM SHALL usar un layout responsive con las convenciones shadcn/Tailwind ya
  existentes — uso principal esperado de escritorio, pero operable desde el móvil.

## Out of scope

- Leer datos operativos de cualquier tenant, o impersonar a un usuario dentro de él —
  `saas-cross-tenant`, post-MVP y condicional.
- Suspender, reactivar, archivar o borrar tenants, y editar o resetear cuentas desde la
  consola — decisión heredada sin cambios de `super-admin-identity`.
- Crear o promover a otro `SUPER_ADMIN` por la consola — `GRANTABLE_ROLES` sigue sin
  abrirse.
- Filtrar o buscar en la lista de tenants más allá de la paginación simple.
- Una pantalla de auditoría agregada — `AuditLog` ya registra cada alta; leerla de forma
  agregada es reporting fuera de alcance.

## Key files

- `frontend/app/(platform)/layout.tsx`, `frontend/app/(platform)/platform/page.tsx` — el
  grupo de rutas y la pantalla única de la consola.
- `frontend/features/auth/lib/role-home.ts` — fila `SUPER_ADMIN: "/platform"`.
- `frontend/features/shell/navigation/route-registry.ts` — `ShellProfile` `"platform"` y
  descriptor de `/platform`.
- `frontend/features/platform/components/platform-console.tsx` — orquesta qué formulario
  vive en el `Sheet` compartido (`create-tenant` | `create-user`), sin navegación.
- `frontend/features/platform/components/tenant-list.tsx`,
  `platform-pagination.tsx` — lista y paginación de tenants.
- `frontend/features/platform/components/create-tenant-form.tsx`,
  `create-user-form.tsx`, `temporary-password-reveal.tsx` — los dos formularios y el
  componente de revelado de contraseña de un solo uso.
- `frontend/features/platform/hooks/use-tenants.ts`,
  `use-create-tenant.ts`, `use-create-platform-user.ts`, `query-keys.ts` — hooks
  TanStack Query; `platformKeys.tenantsList(page, per_page)` es una convención propia,
  deliberadamente no construida sobre `tenantScopedKey` (que exige un `tenantId` no
  vacío — `SUPER_ADMIN` no tiene ninguno).
- `frontend/features/platform/lib/field-errors.ts` — `mapFieldErrors`, el único mapeo de
  error de campo del frontend que lee el cuerpo `422`/`409` del backend.
- `frontend/features/platform/data/http/http-platform-source.ts`,
  `data/index.ts`, `dto.ts`, `index.ts` — fuente HTTP, composición y DTOs de la feature,
  siguiendo el mismo patrón hexagonal que `features/conversations`/`features/properties`.
- `frontend/locales/{es,en}/platform.json` — namespace i18n de la consola.
- `frontend/app/route-coverage.test.ts` — fila `REAL_PAGE_ROUTE_IDS` para
  `(platform)/platform/page.tsx`.
