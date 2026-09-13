# Configuración del tenant (`/settings`)

## Purpose

`/settings` es la pantalla de la workspace donde el `TENANT_OWNER` administra el personal de su
tenant (alta, listado, edición, cambio de rol, baja, reactivación y reset de contraseña) y la
configuración operativa del tenant (umbral de aprobación, SLAs, ventanas de check-in/checkout y
conmutadores de notificación), sin depender de `curl` contra el backend de `user-management`.
Sustituye el `RoutePlaceholder` que tenía antes. El `PROPERTY_MANAGER` ve las mismas dos secciones
en solo lectura; `CLEANER`, `TECHNICIAN` y `SUPER_ADMIN` no llegan a la ruta.
`/settings/integrations` queda fuera de esta capacidad — sigue siendo el mismo `RoutePlaceholder`
de antes (decisión de diseño D6, ver `Estado y deuda conocida`).

## Requirements

### R1 — Directorio de usuarios del tenant

- WHEN un `TENANT_OWNER` o `PROPERTY_MANAGER` abre `/settings`, THE SYSTEM SHALL renderizar un
  listado paginado respaldado por `GET /api/v1/users` (nombre, email, rol, estado), consumiendo el
  envelope `{data, total, page, per_page, total_pages}`.
- WHEN el listado recibe un filtro por rol o por estado, THE SYSTEM SHALL aplicarlo vía los
  parámetros de consulta de `GET /api/v1/users`.
- WHEN se selecciona una fila, THE SYSTEM SHALL mostrar el detalle del usuario vía
  `GET /api/v1/users/{id}`, incluidos los usuarios `INACTIVE`/`SUSPENDED`.
- WHERE el rol de la sesión es `CLEANER`, `TECHNICIAN` o `SUPER_ADMIN`, THE SYSTEM SHALL NOT
  renderizar `/settings`: el `<AuthGuard allow={["TENANT_OWNER", "PROPERTY_MANAGER"]}>` que ya
  envuelve todo `(workspace)/layout.tsx` redirige antes de montar la vista — sin gating adicional a
  nivel de página (design D3) —, y `route-registry.ts` no ofrece la entrada de `/settings` en el
  grupo "Administración" a esos tres roles.

### R2 — Alta de personal

- WHEN un `TENANT_OWNER` envía el formulario de alta con datos válidos, THE SYSTEM SHALL invocar
  `POST /api/v1/users` y revelar la contraseña temporal devuelta **exactamente una vez**, con
  `TemporaryPasswordReveal` (reexportado desde `features/platform` — design D1), sin persistirla
  en cliente más allá de esa revelación.
- IF el backend responde `409` (email ya existente), THEN THE SYSTEM SHALL mostrar el mensaje
  accionable del backend sin inferir ni mostrar a qué tenant pertenece la dirección.
- WHERE el actor autenticado no tiene el permiso `MANAGE_USERS` (solo `TENANT_OWNER` lo tiene en
  `ROLE_UI_PERMISSIONS`, design D2), THE SYSTEM SHALL NOT renderizar el control de alta —
  ocultarlo, no deshabilitarlo (design D5): un `PROPERTY_MANAGER` nunca ve el botón de alta, no un
  botón inactivo.

### R3 — Edición, cambio de rol, baja y reactivación

- WHEN un `TENANT_OWNER` envía una edición, THE SYSTEM SHALL enviar a `PATCH /api/v1/users/{id}`
  solo los campos que cambiaron.
- IF la acción dejaría al tenant sin ningún `TENANT_OWNER` activo o es una autodegradación/autobaja,
  THEN THE SYSTEM SHALL mostrar el `422` del backend con su motivo (el texto del propio backend vía
  `mapFieldErrors`/`ApiError.message`, nunca un mensaje genérico ni un reintento silencioso).
- WHEN la acción objetivo es la propia fila del actor autenticado, THE SYSTEM SHALL deshabilitar en
  el cliente los controles de cambio de rol y de estado sobre esa fila (defensa en profundidad; el
  backend ya lo rechaza con `422`).
- THE SYSTEM SHALL llamar `DELETE /api/v1/users/{id}` para desactivar (un hook dedicado,
  `use-deactivate-user.ts`, no el mismo que la edición de perfil — design D7) y
  `PATCH /api/v1/users/{id} {status: "ACTIVE"}` para reactivar una fila `INACTIVE`/`SUSPENDED` (el
  mismo hook que la edición de perfil, `use-update-user.ts` — no hay verbo de backend distinto para
  reactivar).
- IF la baja objetivo es la única limpiadora `ACTIVE` del tenant, THEN THE SYSTEM SHALL mostrar una
  advertencia no bloqueante sobre la autoasignación de checkout antes de confirmar, sin deshabilitar
  ni retirar el botón de confirmar. THE SYSTEM SHALL determinar «única limpiadora activa» con una
  consulta dedicada, disparada solo mientras el diálogo de confirmación está abierto y solo cuando
  la fila objetivo es `role: "CLEANER"` y `status: "ACTIVE"` —
  `GET /api/v1/users?role=CLEANER&status=ACTIVE&per_page=1`, leyendo `total === 1` del envelope
  (design D8) — y no de un recuento en cliente sobre la página ya cargada, que puede estar filtrada,
  ordenada o paginada de forma distinta a la población real.
- WHERE el actor autenticado no tiene el permiso `MANAGE_USERS`, THE SYSTEM SHALL NOT renderizar
  ningún control de mutación (editar, cambiar rol, desactivar, reactivar, reset de contraseña)
  sobre filas de usuario.

### R4 — Reset de contraseña asistido

- WHEN un `TENANT_OWNER` solicita un reset desde el detalle de un usuario, THE SYSTEM SHALL invocar
  `POST /api/v1/users/{id}/reset-password` y revelar la temporal devuelta exactamente una vez, con
  el mismo componente de revelación que R2.

### R5 — Configuración del tenant

- WHEN un `TENANT_OWNER` o `PROPERTY_MANAGER` abre la sección de tenant, THE SYSTEM SHALL
  renderizarla vía `GET /api/v1/tenants/{id}` (tenant + `TenantConfig` anidada): nombre, email de
  facturación, país, huso horario, idioma por defecto, umbral de aprobación, umbral de confianza de
  IA, los cuatro SLAs, ventanas de check-in/checkout, `auto_create_cleaning_task`, requisito de foto
  de limpieza, tipo de almacenamiento y los conmutadores de notificación.
- WHERE el rol de la sesión es `PROPERTY_MANAGER` (sin el permiso `MANAGE_TENANT_SETTINGS`), THE
  SYSTEM SHALL renderizar la sección en solo lectura, sin control de envío — la misma pantalla de
  detalle que usa el `TENANT_OWNER`, sin los campos editables ni el botón de guardar (design D5:
  ocultar, no deshabilitar).
- WHEN un `TENANT_OWNER` envía un cambio, THE SYSTEM SHALL enviar a `PATCH /api/v1/tenants/{id}`
  solo los campos que cambiaron, validados en cliente a los mismos rangos del backend (umbral no
  negativo, SLAs positivos, confianza en `[0,1]`, huso horario IANA) para no enviar una petición
  condenada a `422`.
- WHEN se cambia el idioma por defecto, THE SYSTEM SHALL mostrar copy inline indicando que no
  afecta al `preferred_language` de los usuarios existentes.
- WHEN se cambia el umbral de aprobación, THE SYSTEM SHALL mostrar copy inline indicando que no
  reevalúa aprobaciones ya generadas.
- THE SYSTEM SHALL enviar `owner_approval_threshold_eur` y `ai_confidence_threshold` como cadena
  con la precisión decimal exacta que espera el backend, nunca como `number` de JS: son campos
  `Numeric` serializados como string en el contrato generado, y el primero de esta forma en el
  frontend en atravesar ese patrón.

### R6 — Navegación gateada por rol

- WHEN `route-registry.ts` resuelve la navegación para `CLEANER`, `TECHNICIAN` o `SUPER_ADMIN`, THE
  SYSTEM SHALL NOT mostrar la entrada de `/settings` en el grupo "Administración".
- IF un `CLEANER` o `TECHNICIAN` navega directamente a `/settings`, THEN THE SYSTEM SHALL
  redirigirlo por el `AuthGuard` existente, con el mismo criterio que el resto de rutas gateadas
  por rol — una prueba de regresión pin ese comportamiento sin añadir un segundo mecanismo de
  gating (design D3).

## Estado y deuda conocida

- **`/settings/integrations` no forma parte de esta capacidad**: sigue siendo el mismo
  `RoutePlaceholder` de antes de este change, decisión asumida (D6) porque el roadmap no fuerza
  ninguna dirección y una futura provisión de webhook-endpoints es un ocupante plausible de esa
  ruta. Retirarla o completarla es una decisión futura, no tomada aquí.
- **Sin permiso "solo lectura" nuevo en el backend**: el `PROPERTY_MANAGER` ya tenía
  `READ_USERS`/`READ_TENANT_SETTINGS` en `policy.py`; esta capacidad es la primera consumidora de
  frontend de esos permisos de lectura. El mirror del cliente (`ROLE_UI_PERMISSIONS`) es
  deliberadamente parcial (solo declara lo que oculta), así que un `403` real del backend sigue
  siendo la autoridad, nunca el mirror.

## Key files

- `frontend/app/(workspace)/settings/page.tsx` — la ruta; monta `TenantSettingsView` en vez del
  `RoutePlaceholder` anterior.
- `frontend/features/tenant-settings/components/tenant-settings-view.tsx` — composición de las dos
  secciones (Usuarios, Tenant) apiladas verticalmente, sin primitiva de Tabs (design D4).
- `frontend/features/tenant-settings/components/list/user-list.tsx`,
  `user-row-actions.tsx` — R1, R3.
- `frontend/features/tenant-settings/components/detail/create-user-form.tsx`,
  `edit-user-form.tsx`, `deactivate-user-confirm.tsx`, `reset-password-confirm.tsx`,
  `user-detail-view.tsx` — R2, R3, R4.
- `frontend/features/tenant-settings/components/tenant-config-form.tsx` — R5, con
  `lib/validate-tenant-config.ts` para la validación de rangos en cliente.
- `frontend/features/tenant-settings/hooks/` — `use-users.ts`, `use-user.ts`,
  `use-create-user.ts`, `use-update-user.ts`, `use-deactivate-user.ts`, `use-reset-password.ts`,
  `use-active-cleaner-count.ts` (R3.4/D8), `use-tenant.ts`, `use-update-tenant.ts`,
  `query-keys.ts` (`tenantSettingsKeys` sobre `tenantScopedKey`).
- `frontend/features/tenant-settings/data/http/http-tenant-settings-source.ts`,
  `data/index.ts`, `dto.ts` — el cliente HTTP y los DTOs de los ocho endpoints de
  [`user-management.md`](user-management.md).
- `frontend/features/platform/index.ts` — exporta `TemporaryPasswordReveal`, reusada aquí (design
  D1); `mapFieldErrors` también se reusa desde ahí.
- `frontend/lib/auth/permissions.ts` — `MANAGE_USERS`, `MANAGE_TENANT_SETTINGS`, concedidos solo a
  `TENANT_OWNER` (design D2), espejo parcial de `policy.py`'s `_USER_MANAGE`/`_TENANT_MANAGE`.
- `frontend/features/shell/navigation/route-registry.ts` — entradas `settings` y
  `settings-integrations`; `(workspace)/layout.tsx` — el `AuthGuard` que gatea la ruta (R1.4, R6).
- `frontend/locales/{es,en}/tenant-settings.json` — el namespace `tenant-settings` completo en los
  dos idiomas.
- Backend: [`user-management.md`](user-management.md) — los ocho endpoints y reglas de
  autorización/aislamiento que esta pantalla consume tal cual, sin cambios de contrato.
