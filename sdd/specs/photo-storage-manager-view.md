# Photo storage manager view

## Purpose

Da al manager y a la propietaria una **vista de solo lectura** de las fotos que ya suben el
técnico y la limpiadora, en los dos detalles del workspace que carecían de ella:
`/incidents/[id]` (antes/después de una incidencia) y `/cleaning/[id]` (evidencia de una tarea de
limpieza). No añade almacenamiento, permiso ni ruta de API — reutiliza
`GET /api/v1/incidents/{incident_id}/photos` de [`incident-photos`](incident-photos.md) y
`GET /api/v1/cleaning-tasks/{id}/photos` de [`cleaning`](cleaning.md) §Fotos de la limpieza,
ambas ya autorizadas para `READ_INCIDENTS`/`READ_CLEANING_TASKS`. Cierra un hueco que quedó
prometido y sin abrir tres entradas seguidas (`cleaning-manager-view`, `incident-triage-web`,
`staff-messaging-web`). Junto con la galería, endurece el bootstrap: un tenant nuevo ya no puede
nacer con almacenamiento `LOCAL` fuera del entorno `local` por un flag olvidado.

## Requirements

### Galería de fotos en el detalle de incidencia del manager

- WHEN un usuario con `READ_INCIDENTS` abre `/incidents/[id]`, THE SYSTEM SHALL listar las fotos
  de `GET /api/v1/incidents/{incident_id}/photos` agrupadas por etapa (`BEFORE`/`AFTER`),
  reutilizando el hook `useIncidentPhotos()` ya existente para `tech-app` — sin hook, DTO ni
  query key nuevos en el lado de incidencias.
- WHILE la petición de fotos está en curso, THE SYSTEM SHALL mostrar un estado de carga; IF
  falla, THEN THE SYSTEM SHALL mostrar un estado de error con reintento; WHEN la incidencia no
  tiene fotos, THE SYSTEM SHALL mostrar un estado vacío — los mismos primitivos compartidos
  (`LoadingState`/`ErrorState`/`EmptyState`) que ya usa `TechPhotoGallery`.
- THE SYSTEM SHALL pintar cada `url` devuelta **tal cual**, sin transformarla ni concatenarla a
  un origen propio, para que funcione igual en `LOCAL` (relativa) y `S3` (absoluta).
- THE SYSTEM NEVER SHALL ofrecer control de subida ni de borrado en esta pantalla: subir sigue
  siendo solo del técnico asignado (`EXECUTE_INCIDENTS`, permiso que este rol no tiene) y no
  existe borrado por ninguna vía de la API.
- IF la URL firmada de una foto caduca (el `<img>` dispara `onError`), THEN THE SYSTEM SHALL
  re-listar las fotos como máximo una vez por foto montada — el mismo mecanismo de recuperación
  que `TechPhotoGallery`.
- THE SYSTEM SHALL declarar toda cadena nueva (título de sección, estados de carga/vacío/error)
  en `locales/es/incidents.json` y `locales/en/incidents.json`.

### Galería de fotos en el detalle de tarea de limpieza del manager

- WHEN un usuario con `READ_CLEANING_TASKS` abre `/cleaning/[id]`, THE SYSTEM SHALL listar las
  fotos de `GET /api/v1/cleaning-tasks/{id}/photos` agrupadas por `photo_type` — el conjunto lo
  define la plantilla de la tarea, no un enum cerrado, a diferencia de la galería de incidencia —
  a través de un hook nuevo (`useCleaningTaskPhotos`) porque el lado de limpieza no tenía
  consumidor de manager para esta ruta.
- WHILE la petición de fotos está en curso, THE SYSTEM SHALL mostrar un estado de carga; IF
  falla, THEN THE SYSTEM SHALL mostrar un estado de error con reintento; WHEN la tarea no tiene
  fotos, THE SYSTEM SHALL mostrar un estado vacío — mismos primitivos compartidos que la galería
  de incidencia.
- THE SYSTEM SHALL pintar cada `url` devuelta tal cual, igual que la galería de incidencia.
- THE SYSTEM NEVER SHALL ofrecer control de subida ni de borrado: subir sigue siendo solo de la
  limpiadora asignada (`EXECUTE_CLEANING_TASKS`, permiso que este rol no tiene) y no existe
  borrado por ninguna vía de la API.
- IF la URL firmada de una foto caduca, THEN THE SYSTEM SHALL re-listar las fotos como máximo
  una vez por foto montada, igual que la galería de incidencia.
- THE SYSTEM SHALL declarar toda cadena nueva en `locales/es/cleaning.json` y
  `locales/en/cleaning.json`.

### El bootstrap rechaza nacer `LOCAL` fuera de `local`

- WHEN `settings.environment` no es `local` Y el `bootstrap_storage_type` resuelto es `LOCAL`,
  THE SYSTEM SHALL rechazar el bootstrap **antes** de abrir transacción, con un
  `BootstrapConfigurationError` que nombre `BOOTSTRAP_STORAGE_TYPE` como la variable a fijar
  explícitamente — mismo patrón que `build_plan()` ya usa para las once `BOOTSTRAP_*`
  requeridas. `app/cli/demo_reset.py` aplica el mismo rechazo en su propio `build_plan()`.
- THE SYSTEM SHALL dejar el entorno `local` sin cambios: `LOCAL` sigue siendo el default y no
  exige ningún flag ahí.
- THE SYSTEM SHALL NOT tocar el enum `StorageType`, la columna `TenantConfig.storage_type`, su
  default, ni ninguna ruta de la API: es un rechazo en tiempo de bootstrap, no un cambio de
  esquema ni de contrato.
- THE SYSTEM SHALL dejar inerte todo despliegue ya bien configurado:
  `.github/workflows/demo-reset.yml` ya pasa `BOOTSTRAP_STORAGE_TYPE=S3` en línea, así que el
  rechazo no le cambia nada.

## Lo que esta capacidad no hace

- Subir o borrar fotos desde estas dos pantallas — sigue siendo del técnico y de la limpiadora
  respectivamente; no hay superficie de borrado en la API
  ([`file-storage`](file-storage.md) §Estado).
- Validación por IA de las fotos — sin puerto que la soporte
  ([`incident-photos`](incident-photos.md), [`cleaning`](cleaning.md)).
- Elegir proveedor de almacenamiento para `staging`/`production` — sigue sin decidir, es una
  decisión propia de cada entorno ([`file-storage`](file-storage.md) §Estado).
- Cambiar `storage_type` de un tenant ya existente vía API o UI — el `PATCH` de `TenantConfig`
  sigue sin admitirlo ([`auth-tenancy`](auth-tenancy.md)), y mover un tenant con fotos ya
  subidas apuntaría a un almacén donde no están.
- Cualquier acción de mutación de incidencia o de tarea de limpieza (clasificar, triage, asignar,
  cancelar, checklist, mensajería) — no cambian, no forman parte de esta entrada.
- La galería de fotos del propio técnico (`/tech/incidents/[id]`) y de la propia limpiadora
  (`/cleaner/tasks/[id]`) — ya entregadas, no se tocan.

## Estado

- **Entregada el 2026-09-18.** Verificada manualmente contra el stack levantado: subida de una
  foto `BEFORE` como `TECHNICIAN`, subida de foto de limpieza como `CLEANER`, y confirmación de
  que ambas galerías renderizan para `PROPERTY_MANAGER` y `TENANT_OWNER` sin ningún control de
  subida ni de borrado visible, con el estado vacío correcto en una incidencia sin fotos.
- 330/332 archivos, 3691/3692 tests backend en verde; los 2 fallos son la limitación
  pre-existente de bind-mount ENOENT del worktree (`sdd/project.md` §Worktree bootstrap), no
  relacionada. Lint y typecheck de frontend limpios. i18n simétrico en ambos locales para
  `incidents` y `cleaning`.

## Key files

- `frontend/features/incidents/components/detail/incident-photos-block.tsx` — galería de
  incidencia, montada en `incident-detail-view.tsx`; reutiliza `useIncidentPhotos()`.
- `frontend/features/cleaning/components/detail/detail-photos-block.tsx` — galería de limpieza,
  montada en `cleaning-task-detail-view.tsx`.
- `frontend/features/cleaning/hooks/use-cleaning-photos.ts` — `useCleaningTaskPhotos(taskId)`,
  nuevo hook, nueva query key `cleaningKeys.photos(tenantId, taskId)`.
- `frontend/features/cleaning/data/dto.ts`, `data/cleaning-source.ts`,
  `data/http/http-cleaning-source.ts` — `CleaningPhotoDto` y `listPhotos` en la interfaz de
  fuente de datos y su implementación HTTP.
- `backend/app/cli/bootstrap.py`, `backend/app/cli/demo_reset.py` — `build_plan()` de cada uno
  rechaza `LOCAL` fuera de `local` con `BootstrapConfigurationError`.
