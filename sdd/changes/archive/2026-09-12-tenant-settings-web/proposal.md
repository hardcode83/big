# Proposal: tenant-settings-web

## Why

`/settings` y `/settings/integrations` son hoy `RoutePlaceholder` (`frontend/app/(workspace)/settings/page.tsx:11`, `settings/integrations/page.tsx:11`); ningún fichero de `frontend/features` llama a `/api/v1/tenants/*` ni a `/api/v1/users`, y `route-registry.ts` no expone ninguna pantalla de usuarios. El backend está completo (`user-management`): seis rutas de personal (`auth/api/users_router.py:73-220`) y `GET`/`PATCH /tenants/{id}` con `TenantConfig` (`tenants/api/router.py:47,60`). Consecuencia real: **un `TENANT_OWNER` no puede dar de alta a su propia limpiadora** — solo el `SUPER_ADMIN` puede, desde `/platform` — y las tres decisiones de operación que PRD §7.2 pone en sus manos (umbral de aprobación, SLAs, canales de notificación) solo se tocan con `curl`. Esta entrada salió de `hardening-release` el 2026-09-04 (`sdd/roadmap.md:295`, nota completa en `sdd/roadmap/tenant-settings-web.md`) porque el autoservicio del tenant no debe esperar al endurecimiento de release.

## What changes

`/settings` deja de ser un placeholder: gana una sección de **Usuarios** (listar, dar de alta, editar, cambiar rol, desactivar, reset de contraseña con revelación única de la temporal — reutilizando `create-user-form.tsx` y `temporary-password-reveal.tsx` de `features/platform`) y una sección de **Tenant** (formulario sobre `GET`/`PATCH /tenants/{id}` con los campos de `TenantConfig`). Ambas secciones se gatean por permiso en el cliente reflejando la autorización real del backend: el `TENANT_OWNER` opera las dos; el `PROPERTY_MANAGER` las ve en solo lectura (`policy.py:384-421`); `CLEANER`, `TECHNICIAN` y `SUPER_ADMIN` no ven la ruta. `/settings/integrations` queda fuera de esta entrega (ver Out of scope); si la ruta del sidebar se retira o se deja como placeholder declarado lo decide `/sdd:design`.

## Requirements

### R1 — Directorio de usuarios del tenant

**As a** `TENANT_OWNER` o `PROPERTY_MANAGER`, **I want** ver el personal del tenant en `/settings`, **so that** pueda saber quién tiene acceso sin consultar la API a mano.

Acceptance criteria:

1. WHEN un `TENANT_OWNER` o `PROPERTY_MANAGER` abre `/settings`, THE SYSTEM SHALL renderizar un listado paginado respaldado por `GET /api/v1/users` (nombre, email, rol, estado), consumiendo el envelope `{data, total, page, per_page, total_pages}`.
2. WHEN el listado recibe un filtro por rol o por estado, THE SYSTEM SHALL aplicarlo vía los parámetros de consulta de `GET /api/v1/users`.
3. WHEN se selecciona una fila, THE SYSTEM SHALL mostrar el detalle del usuario vía `GET /api/v1/users/{id}`, incluidos los usuarios `INACTIVE`/`SUSPENDED`.
4. WHERE el rol de la sesión es `CLEANER`, `TECHNICIAN` o `SUPER_ADMIN`, THE SYSTEM SHALL NOT renderizar `/settings` — se redirige por el `AuthGuard` existente, igual que otras rutas gateadas por rol.

### R2 — Alta de personal

**As a** `TENANT_OWNER`, **I want** dar de alta una cuenta de personal (manager, limpiadora, técnico) con un rol de `GRANTABLE_ROLES`, **so that** mis propiedades tengan personal sin depender de un ingeniero.

Acceptance criteria:

1. WHEN un `TENANT_OWNER` envía el formulario de alta con datos válidos, THE SYSTEM SHALL invocar `POST /api/v1/users` y revelar la contraseña temporal devuelta **exactamente una vez**, reutilizando `temporary-password-reveal.tsx`, sin persistirla en cliente más allá de esa revelación.
2. IF el backend responde `409` (email ya existente), THEN THE SYSTEM SHALL mostrar el mensaje accionable del backend sin inferir ni mostrar a qué tenant pertenece la dirección.
3. WHERE el actor autenticado no es `TENANT_OWNER`, THE SYSTEM SHALL NOT renderizar el control de alta.

### R3 — Edición, cambio de rol y baja

**As a** `TENANT_OWNER`, **I want** editar el perfil de un usuario, cambiar su rol entre los concedibles, desactivarlo y reactivarlo, **so that** pueda mantener al día quién trabaja en el tenant y con qué acceso.

Acceptance criteria:

1. WHEN un `TENANT_OWNER` envía una edición, THE SYSTEM SHALL enviar a `PATCH /api/v1/users/{id}` solo los campos que cambiaron.
2. IF la acción dejaría al tenant sin ningún `TENANT_OWNER` activo o es una autodegradación/autobaja, THEN THE SYSTEM SHALL mostrar el `422` del backend con su motivo, sin reintento silencioso ni mensaje genérico.
3. WHEN la acción objetivo es la propia fila del actor autenticado, THE SYSTEM SHALL deshabilitar en el cliente los controles de cambio de rol y de estado sobre esa fila (defensa en profundidad; el backend ya lo rechaza con `422`).
4. IF la baja objetivo es la única limpiadora `ACTIVE` del tenant, THEN THE SYSTEM SHALL mostrar una advertencia no bloqueante sobre la autoasignación de checkout antes de confirmar — decisión #4 de `sdd/roadmap/tenant-settings-web.md`, sin bloquear la acción.
5. WHERE el actor autenticado no es `TENANT_OWNER`, THE SYSTEM SHALL NOT renderizar ningún control de mutación sobre filas de usuario.

### R4 — Reset de contraseña asistido

**As a** `TENANT_OWNER`, **I want** forzar un reset de contraseña para un miembro del personal y ver la nueva temporal una sola vez, **so that** pueda recuperar una cuenta sin depender del autoservicio anónimo.

Acceptance criteria:

1. WHEN un `TENANT_OWNER` solicita un reset desde el detalle de un usuario, THE SYSTEM SHALL invocar `POST /api/v1/users/{id}/reset-password` y revelar la temporal devuelta exactamente una vez, con el mismo componente de revelación que R2.

### R5 — Configuración del tenant

**As a** `TENANT_OWNER`, **I want** ver y editar la configuración operativa del tenant (umbral de aprobación, SLAs, `auto_create_cleaning_task`, conmutadores de notificación, idioma por defecto), **so that** pueda ajustar cómo opera AutoHostAI sin usar `curl`.

Acceptance criteria:

1. WHEN un `TENANT_OWNER` o `PROPERTY_MANAGER` abre la sección de tenant, THE SYSTEM SHALL renderizarla vía `GET /api/v1/tenants/{id}` (tenant + `TenantConfig` anidada).
2. WHERE el rol de la sesión es `PROPERTY_MANAGER`, THE SYSTEM SHALL renderizar la sección en solo lectura, sin control de envío.
3. WHEN un `TENANT_OWNER` envía un cambio, THE SYSTEM SHALL enviar a `PATCH /api/v1/tenants/{id}` solo los campos que cambiaron, validados en cliente a los mismos rangos del backend (umbral no negativo, SLAs positivos, confianza en `[0,1]`, huso horario IANA) para no enviar una petición condenada a `422`.
4. WHEN se cambia el idioma por defecto, THE SYSTEM SHALL mostrar copy inline indicando que no afecta al `preferred_language` de los usuarios existentes.
5. WHEN se cambia el umbral de aprobación, THE SYSTEM SHALL mostrar copy inline indicando que no reevalúa aprobaciones ya generadas.

### R6 — Navegación gateada por rol

**As a** usuario del workspace, **I want** que `/settings` aparezca y se comporte según mi rol, **so that** el personal sin permiso nunca vea una pantalla de administración que no puede usar.

Acceptance criteria:

1. WHEN `route-registry.ts` resuelve la navegación para `CLEANER`, `TECHNICIAN` o `SUPER_ADMIN`, THE SYSTEM SHALL NOT mostrar la entrada de `/settings` en el grupo "Administración".
2. IF un `CLEANER` o `TECHNICIAN` navega directamente a `/settings`, THEN THE SYSTEM SHALL redirigirlo por el `AuthGuard` existente, con el mismo criterio que el resto de rutas gateadas por rol.

## Out of scope

- **`/settings/integrations` funcional** (conexión PMS por UI): las credenciales de proveedor son CLI-only por la regla 3(a) de `steering/security.md` y `pms_provider` es create-only; queda fuera del MVP. Si la ruta del sidebar se retira o se deja como placeholder declarado lo decide `/sdd:design` (nota en `sdd/roadmap/tenant-settings-web.md`, punto 1). Lo único potencialmente futuro ahí — provisión de webhook-endpoints — no es parte de esta entrega.
- **Autoservicio de contraseña** (cambio por el propio usuario, recuperación anónima, gate de rotación de la temporal): ya entregado por `auth-account-recovery`.
- **Plantillas de checklist de limpieza**: candidata `cleaning-templates-web`.
- **Segundo `SUPER_ADMIN` / visibilidad cross-tenant**: fuera de alcance por `super-admin-identity` y `saas-cross-tenant`.
- **Cambiar `status` del tenant o `storage_type` de la config**: el backend ya los rechaza con `422` en las tres capas; esta UI no expone ningún control para ellos.
- **`AuditLog` retroactivo** de `reservations`/`integrations`: deuda conocida y explícita de `user-management`, no se toca aquí.
- **Backend nuevo**: las ocho rutas consumidas ya existen y están fuera de alcance de este change salvo que el testing en frontend descubra un defecto real.

## Affected specs

- `sdd/specs/tenant-settings-web.md` — *(no existe aún — se creará al archivar)*: la nueva capacidad de frontend (`/settings`, sus dos secciones y el gateo por rol).
- `sdd/specs/user-management.md` — se actualiza la línea "No incluye frontend… llega con `dashboard-web` y `hardening-release`" (líneas 18-19 y 287) para reflejar que `tenant-settings-web` es ahora el primer (y único) consumidor de frontend de estas ocho rutas, con el mismo criterio que ya documenta para `platform-admin-api`/`super-admin-console`.
