# Proposal: photo-storage-manager-view

## Why

El backend ya expone `GET /api/v1/incidents/{incident_id}/photos`
([`incident-photos`](../../specs/incident-photos.md)) y
`GET /api/v1/cleaning-tasks/{id}/photos` (sección «Fotos de la limpieza» de
[`cleaning`](../../specs/cleaning.md)) para `PROPERTY_MANAGER` y `TENANT_OWNER`
(`READ_INCIDENTS`/`READ_CLEANING_TASKS`, sin permiso nuevo), y el frontend ya
tiene el hook `useIncidentPhotos()` — consumido hoy solo por
`TechPhotoGallery` en `/tech/incidents/[id]`. Ninguna pantalla del workspace
del manager/propietaria pinta esas fotos: ni `/incidents/[id]`
(`incident-triage-web`) ni `/cleaning/[id]` (recién entregada por
`cleaning-manager-task-detail`, que nombra explícitamente esta entrada como su
sitio de montaje). Es un hueco excluido explícitamente tres veces seguidas
(`cleaning-manager-view`, `incident-triage-web`, `staff-messaging-web`) sin
que nadie abriera la entrada prometida — verificado contra el código, no solo
contra la prosa del roadmap: ambas vistas de detalle del manager (
`frontend/features/incidents/components/detail/incident-detail-view.tsx`,
`frontend/features/cleaning/components/detail/cleaning-task-detail-view.tsx`)
no mencionan fotos hoy.

Además, `bootstrap_storage_type` (`backend/app/core/config.py`, default
`LOCAL`) solo se fuerza a `S3` pasándolo en línea a mano
(`docker compose exec -e BOOTSTRAP_STORAGE_TYPE=S3 …`,
`infra/environments/dev/RUNBOOK.md`); ningún gate impide que un tenant nuevo
nazca en `LOCAL` en `dev`/`staging`/`production` si alguien olvida el flag,
pese a que `settings.environment` ya distingue `local` del resto. El único
flujo automatizado que bootstrapea contra `dev` hoy
(`.github/workflows/demo-reset.yml`) ya pasa el flag explícito, así que el
gate no le cambia nada — cierra el olvido humano, no un caso ya cubierto.

## What changes

Las dos vistas de detalle del workspace (`/incidents/[id]` y `/cleaning/[id]`)
ganan una sección de galería de fotos de solo lectura, reutilizando el
almacenamiento compartido y sus URLs firmadas exactamente como las sirve la
API — sin subida ni borrado desde estas pantallas. Por separado, el comando de
bootstrap (`app/cli/bootstrap.py` / `build_plan()`) rechaza crear o converger
un tenant con almacenamiento `LOCAL` fuera del entorno `local`, exigiendo que
`BOOTSTRAP_STORAGE_TYPE` se pase explícito en `dev`/`staging`/`production`.

## Requirements

### R1 — Galería de fotos en el detalle de incidencia del manager

**As a** manager o propietaria revisando una incidencia, **I want** ver las
fotos de antes/después que subió el técnico en `/incidents/[id]`, **so that**
pueda verificar la reparación sin salir de la app.

Acceptance criteria:

1. WHEN un usuario con `READ_INCIDENTS` abre `/incidents/[id]`, THE SYSTEM
   SHALL listar las fotos de `GET /api/v1/incidents/{incident_id}/photos`
   agrupadas por etapa (`BEFORE`/`AFTER`), reutilizando `useIncidentPhotos()`
   ya existente.
2. WHILE la petición de fotos está en curso, THE SYSTEM SHALL mostrar un
   estado de carga; IF falla, THEN THE SYSTEM SHALL mostrar un estado de
   error con reintento — los mismos primitivos compartidos
   (`LoadingState`/`ErrorState`/`EmptyState`) que ya usa `TechPhotoGallery`.
3. WHEN la incidencia no tiene fotos, THE SYSTEM SHALL mostrar un estado
   vacío en vez de una galería en blanco.
4. THE SYSTEM SHALL pintar cada `url` devuelta **tal cual**, sin
   transformarla ni concatenarla a un origen propio, para que funcione igual
   en `LOCAL` (relativa) y `S3` (absoluta).
5. THE SYSTEM NEVER SHALL ofrecer control de subida ni de borrado en esta
   pantalla: subir sigue siendo solo del técnico (`EXECUTE_INCIDENTS`, que
   este rol no tiene) y no existe borrado por API.
6. IF la URL firmada de una foto caduca (el `<img>` dispara `onError`), THEN
   THE SYSTEM SHALL re-listar las fotos como máximo una vez por foto
   montada, el mismo mecanismo de recuperación que `TechPhotoGallery`.
7. THE SYSTEM SHALL declarar toda cadena nueva (título de sección, estados de
   carga/vacío/error) en `locales/es/` y `locales/en/`, nada hardcodeado
   (`steering/frontend.md`).

### R2 — Galería de fotos en el detalle de tarea de limpieza del manager

**As a** manager o propietaria revisando una tarea de limpieza, **I want**
ver las fotos que subió la limpiadora en `/cleaning/[id]`, **so that** pueda
verificar el trabajo sin salir de la app.

Acceptance criteria:

1. WHEN un usuario con `READ_CLEANING_TASKS` abre `/cleaning/[id]`, THE
   SYSTEM SHALL listar las fotos de `GET /api/v1/cleaning-tasks/{id}/photos`
   agrupadas por `photo_type` (el conjunto lo define la plantilla de la
   tarea, no un enum cerrado — a diferencia de R1), a través de un hook nuevo
   en `frontend/features/cleaning/hooks/` (la tarea existe en la API desde
   `cleaning`, pero no tiene consumidor de manager en el frontend).
2. WHILE la petición de fotos está en curso, THE SYSTEM SHALL mostrar un
   estado de carga; IF falla, THEN THE SYSTEM SHALL mostrar un estado de
   error con reintento; WHEN la tarea no tiene fotos, THE SYSTEM SHALL
   mostrar un estado vacío — mismos primitivos compartidos que R1.
3. THE SYSTEM SHALL pintar cada `url` devuelta tal cual, igual que R1.4.
4. THE SYSTEM NEVER SHALL ofrecer control de subida ni de borrado: subir
   sigue siendo solo de la limpiadora (`EXECUTE_CLEANING_TASKS`, que este rol
   no tiene) y no existe borrado por API.
5. IF la URL firmada de una foto caduca, THEN THE SYSTEM SHALL re-listar las
   fotos como máximo una vez por foto montada, igual que R1.6.
6. THE SYSTEM SHALL declarar toda cadena nueva en `locales/es/` y
   `locales/en/`, nada hardcodeado.

### R3 — El bootstrap rechaza nacer `LOCAL` fuera de `local`

**As an** operador desplegando un tenant nuevo, **I want** que el comando de
bootstrap rechace almacenamiento `LOCAL` fuera del entorno `local`, **so
that** ningún tenant de `dev`/`staging`/`production` quede con fotos que
nadie puede recuperar por olvidar un flag.

Acceptance criteria:

1. WHEN `settings.environment` no es `local` Y el `bootstrap_storage_type`
   resuelto es `LOCAL`, THE SYSTEM SHALL rechazar el bootstrap **antes** de
   abrir transacción, con un `BootstrapConfigurationError` que nombre
   `BOOTSTRAP_STORAGE_TYPE` como la variable a fijar explícitamente —mismo
   patrón que `build_plan()` ya usa para las once `BOOTSTRAP_*` requeridas.
2. THE SYSTEM SHALL dejar el entorno `local` sin cambios: `LOCAL` sigue
   siendo el default y no exige ningún flag ahí.
3. THE SYSTEM SHALL NOT tocar el enum `StorageType`, la columna
   `TenantConfig.storage_type`, su default, ni ninguna ruta de la API: es un
   rechazo en tiempo de bootstrap, no un cambio de esquema ni de contrato.
4. THE SYSTEM SHALL dejar inerte todo despliegue ya bien configurado:
   `.github/workflows/demo-reset.yml` ya pasa `BOOTSTRAP_STORAGE_TYPE=S3` en
   línea, así que el rechazo no le cambia nada.

## Out of scope

- Subir o borrar fotos desde estas dos pantallas — sigue siendo del técnico y
  de la limpiadora respectivamente; no hay superficie de borrado en la API
  (decisión de [`file-storage`](../../specs/file-storage.md) §Estado).
- Validación por IA de las fotos — sin puerto que la soporte
  ([`incident-photos`](../../specs/incident-photos.md), [`cleaning`](../../specs/cleaning.md)).
- Elegir proveedor de almacenamiento para `staging`/`production` — sigue sin
  decidir, es una decisión propia de cada entorno
  ([`file-storage`](../../specs/file-storage.md) §Estado).
- Cambiar `storage_type` de un tenant ya existente vía API o UI — el `PATCH`
  de `TenantConfig` sigue sin admitirlo (`auth-tenancy` R5.4 de
  `user-management`), y mover un tenant con fotos ya subidas apuntaría a un
  almacén donde no están.
- Cualquier acción de mutación de incidencia o de tarea de limpieza
  (clasificar, triage, asignar, cancelar, checklist, mensajería) — no
  cambian, no forman parte de esta entrada.
- Regenerar el contrato OpenAPI — las dos rutas y sus esquemas
  (`IncidentPhotoListResponse`, `CleaningPhotoListResponse`) ya están
  publicados y presentes en `frontend/lib/api/generated/openapi.d.ts`; esta
  entrada solo añade consumidores.
- La galería de fotos del propio técnico (`/tech/incidents/[id]`) y de la
  propia limpiadora (`/cleaner/tasks/[id]`) — ya entregadas, no se tocan.

## Affected specs

- `sdd/specs/incident-photos.md` — corrige la afirmación de §Estado «Sin
  pantalla. Las tres rutas existen y nadie las llama todavía [salvo
  `tech-app`]»: deja de ser cierto con esta entrada.
- `sdd/specs/cleaning.md` — documenta el nuevo consumidor de manager de
  «Fotos de la limpieza» (§Fotos de la limpieza), junto a la limpiadora que
  sube y el técnico/manager que ya listaban por API.
- `sdd/specs/auth-tenancy.md` — sección «Bootstrap del acceso inicial»,
  documenta el nuevo rechazo `BootstrapConfigurationError` cuando
  `environment != local` y `bootstrap_storage_type == LOCAL`.
- `sdd/specs/frontend-foundation.md` — la prosa de `/incidents/[id]` y
  `/cleaning/[id]` en el censo de rutas gana una mención de la sección de
  fotos (no añade ruta nueva, ambas ya son superficies funcionales).
- `sdd/specs/photo-storage-manager-view.md` *(no existe aún — se creará al
  archivar)* — spec propia de las dos galerías del manager, igual que
  `incident-photos.md` es spec propia de su capability aunque reutilice el
  almacén compartido.
