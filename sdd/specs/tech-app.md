# App del técnico (`/tech`)

## Purpose

Las dos superficies web sobre las que un `TECHNICIAN` **opera** el backend de mantenimiento
(PRD §12, §24): `/tech` lista sus incidencias asignadas con la vivienda de cada fila, y
`/tech/incidents/[id]` reúne la avería, el contexto de acceso a la propiedad, la galería de fotos,
los botones del ciclo del técnico y el cierre con coste y materiales, con la puerta de aprobación
de la propietaria mostrada tal como el backend la resuelve. Es una capa de presentación pura sobre
los contratos que ya describen [`maintenance.md`](maintenance.md),
[`tech-incident-context.md`](tech-incident-context.md) e
[`incident-photos.md`](incident-photos.md) — **no añade ni relaja ninguna regla de negocio ni de
acceso**: el backend sigue siendo la única autoridad sobre las transiciones, el acotamiento por
técnico y el umbral de aprobación. Es mobile-first porque su usuario trabaja de pie, en el portal
de un edificio y con una mano.

El rol alcanza exactamente lo que la pantalla usa. `TECHNICIAN` es
`_SELF_SERVICE | _INCIDENT_EXECUTE` en `backend/app/auth/domain/policy.py`, es decir
`READ_INCIDENTS` + `EXECUTE_INCIDENTS` sobre `app/maintenance/api/incidents_router.py`:
`GET /incidents`, `GET /incidents/{id}`, `GET /incidents/{id}/context`,
`GET /incidents/{id}/photos`, los `POST` de `accept`, `reject`, `en-route`, `wait-parts`,
`resume`, `resolve` y `photos`, y la ruta anónima a propósito
`GET /api/v1/incident-photos/{photo_id}`. **No** alcanza `classify`, `PATCH /incidents/{id}`,
`assign` ni `cancel` (`ManageDep`), ni ninguna ruta de `/api/v1/properties/…` (`READ_PROPERTIES`).

## Requirements

### R1 — Mis incidencias en `/tech`

- WHEN un usuario autenticado con rol `TECHNICIAN` abre `/tech`, THE SYSTEM SHALL renderizar la
  lista servida por `GET /api/v1/incidents` en lugar del `RoutePlaceholder`, y SHALL NOT enviar
  ningún parámetro que identifique al técnico: el acotamiento por fila lo deriva el backend del
  token (`IncidentActor.restrict_to_technician_id`) y no existe parámetro de consulta para él.
- WHEN la lista se renderiza, THE SYSTEM SHALL mostrar por fila el título, la severidad, el estado,
  la categoría y la fecha de creación de `IncidentResponse`, más el `property_name` y el
  `property_internal_code` obtenidos de `GET /api/v1/incidents/{id}/context` para esa fila.
- THE SYSTEM SHALL emitir la consulta de contexto de cada fila bajo la **misma clave de query
  tenant-scoped** que consume el detalle (`incidentsKeys.context(tenantId, incidentId)`), de modo
  que abrir una fila no vuelva a pedir su contexto.
- WHERE no hay ningún filtro seleccionado, THE SYSTEM SHALL pedir la página sin `status` y
  presentarla en el orden que sirve el backend (`created_at` descendente) SIN reordenar en cliente,
  y SHALL indicar en la propia pantalla que la lista incluye incidencias ya cerradas.
- WHEN el usuario selecciona uno de los chips de estado, THE SYSTEM SHALL re-consultar con un
  **único** valor `status` —el contrato no admite varios— y reflejar esa selección en la clave de
  query; un segundo clic sobre el chip activo SHALL volver al estado sin filtro.
- THE SYSTEM SHALL ofrecer los seis estados que un técnico puede ver en sus propias filas
  (`ASSIGNED`, `ACCEPTED`, `IN_PROGRESS`, `WAITING_EXTERNAL_PARTS`, `AWAITING_OWNER_APPROVAL`,
  `RESOLVED`) y SHALL NOT ofrecer `OPEN`, `CLASSIFIED` ni `CANCELLED`: en ninguno de los tres la
  incidencia está asignada a nadie, así que el filtro devolvería siempre vacío.
- WHEN hay más páginas disponibles, THE SYSTEM SHALL ofrecer un control «cargar más» que acumula
  páginas sobre la lista ya presentada, sin paginación numerada.
- IF la respuesta está vacía, THEN THE SYSTEM SHALL renderizar el `EmptyState` compartido; IF la
  petición falla, THEN THE SYSTEM SHALL renderizar el `ErrorState` compartido sin exponer el
  detalle del error, reutilizando `retryPolicy` (sin reintento en 4xx).

### R2 — Detalle: a qué vivienda voy, cómo entro y qué me dijeron

- WHEN un técnico abre `/tech/incidents/[id]`, THE SYSTEM SHALL sustituir el `RoutePlaceholder` y
  componer la pantalla con `GET /api/v1/incidents/{id}` y `GET /api/v1/incidents/{id}/context`.
- THE SYSTEM SHALL mostrar de `IncidentResponse`: título, descripción, severidad, categoría,
  estado, fuente, `eta_at`, `estimated_cost`, `approved_cost`, `final_cost`, `materials`,
  `owner_approval_required`, `resolved_at` y `created_at`.
- THE SYSTEM SHALL mostrar de `IncidentContextResponse`: `property_name`,
  `property_internal_code`, la dirección completa (`address_line1`, `address_line2`, `city`,
  `province`, `postal_code`, `country`), `access_notes` como instrucciones de acceso y
  `assignment_note` como la nota del manager —que es lo que PRD §12 llama «notas del
  propietario/manager»: `Incident` no tiene columna propia para ellas.
- THE SYSTEM SHALL renderizar `access_notes` **verbatim**, sin enmascarar ni reestructurar: el
  técnico asignado es uno de los tres lectores declarados de la excepción 6 del censo de la regla 11
  de `sdd/steering/security.md`.
- WHEN un campo nulo de esos DTOs se renderiza en línea dentro de una fila poblada, THE SYSTEM SHALL
  mostrar el em-dash `—` (U+2014) como marca tipográfica, conforme a la convención de
  [`frontend-foundation.md`](frontend-foundation.md), y SHALL NOT concatenarlo con su unidad ni
  usar `?? ""`.
- THE SYSTEM SHALL NOT llamar a ninguna ruta de `/api/v1/properties/…` ni construir URLs de
  almacenamiento en el cliente: el rol no tiene `READ_PROPERTIES` y la proyección de contexto existe
  precisamente para eso.
- IF cualquiera de las dos peticiones responde `404`, THEN THE SYSTEM SHALL tratarlo como
  «incidencia no disponible» sin distinguir si no existe, es de otro tenant o es de otro técnico
  —el backend los hace deliberadamente indistinguibles— y ofrecer la vuelta a `/tech`.

### R3 — El ciclo del técnico: aceptar, rechazar, en ruta, piezas, reanudar

- THE SYSTEM SHALL ofrecer exactamente las acciones que el estado admite, según la tabla
  `TECH_ACTIONS` de `frontend/features/tech/lib/tech-actions.ts`, que es la lectura de
  `_TRANSITIONS` (`backend/app/maintenance/domain/entities.py`) acotada a las seis operaciones que
  alcanza `EXECUTE_INCIDENTS`: `ASSIGNED` → «Aceptar» (`POST accept`) y «Rechazar» (`POST reject`);
  `ACCEPTED` → «En ruta» (`POST en-route`) y «Rechazar»; `IN_PROGRESS` → «Esperando piezas»
  (`POST wait-parts`) y el cierre de R4; `WAITING_EXTERNAL_PARTS` → «Reanudar» (`POST resume`).
- THE SYSTEM SHALL declarar esa tabla como un `Record` sobre `IncidentStatus` —el enum que viene del
  contrato generado— de modo que un estado nuevo en el backend rompa la compilación en lugar de
  dejar un botón fantasma, y SHALL consultarla con `Object.hasOwn`, devolviendo «ninguna acción»
  ante un estado que el frontend compilado no conozca en lugar de fallar en el render.
- WHERE el estado no ofrece ninguna acción de ciclo, THE SYSTEM SHALL explicar por qué distinguiendo
  tres motivos: `AWAITING_OWNER_APPROVAL` es «a la espera de la propietaria», `RESOLVED` y
  `CANCELLED` son «cerrada», y `OPEN` y `CLASSIFIED` son «no accionable» — SHALL NOT presentar estos
  dos últimos como cerrados.
- WHEN el técnico ejecuta «Aceptar» o «En ruta», THE SYSTEM SHALL permitir adjuntar una ETA opcional
  en el cuerpo `IncidentEtaRequest`, enviada como instante **con offset de zona**, y SHALL omitir el
  cuerpo por completo cuando no se informa ninguna.
- IF la API rechaza la ETA con `422` («must carry a timezone», «cannot be in the past»), THEN THE
  SYSTEM SHALL mostrarlo junto al campo sin perder lo que el técnico había escrito, y SHALL NOT
  replicar esa validación como si fuera suya —la frontera es `now` del servidor.
- WHEN `POST reject` responde `200`, THE SYSTEM SHALL devolver al técnico a `/tech` e invalidar la
  lista, porque el rechazo borra los tres campos de la asignación (asignatario, ETA y nota) y a
  partir de ese momento `GET /incidents/{id}` le responde `404` a quien rechazó.
- WHEN cualquiera de estas mutaciones responde `200`, THE SYSTEM SHALL refrescar la incidencia y la
  lista desde la respuesta o invalidando su clave, sin recomponer el estado en el cliente.
- IF una mutación responde `409`, THEN THE SYSTEM SHALL mostrar el mensaje que corresponde a cada
  uno de sus tres casos (transición inválida, incidencia cerrada, esperando a la propietaria),
  refrescar la incidencia y SHALL NOT reintentar automáticamente.

### R4 — Cerrar con coste y materiales, y la puerta de la propietaria

- WHERE el estado es `IN_PROGRESS`, THE SYSTEM SHALL ofrecer un formulario de cierre con
  `final_cost` **obligatorio** (número ≥ 0, ≤ 99 999 999,99, como mucho dos decimales) y `materials`
  opcional (entre 1 y 2000 caracteres), y SHALL enviarlo a `POST /incidents/{id}/resolve`.
- WHEN la respuesta llega con `status = RESOLVED`, THE SYSTEM SHALL presentar la incidencia como
  cerrada mostrando `final_cost`, `materials` y `resolved_at`.
- WHEN la respuesta llega con `status = AWAITING_OWNER_APPROVAL`, THE SYSTEM SHALL comunicar
  explícitamente que **el cierre no se ha aceptado** y queda a la espera de la propietaria,
  conservando visible el `final_cost` que devuelve la respuesta y SHALL NOT inventar un
  `resolved_at` que la respuesta trae a `null`.
- THE SYSTEM SHALL NOT calcular, mostrar ni anticipar el umbral `owner_approval_threshold_eur`: el
  rol no puede leer la configuración del tenant y la puerta la resuelve el backend al recibir el
  cierre. La app lo muestra; no lo predice ni lo evita.
- IF la validación local del formulario falla, THEN THE SYSTEM SHALL no emitir la petición; IF la
  API responde `422`, THEN THE SYSTEM SHALL mostrarlo sin vaciar el formulario.

### R5 — Fotos del incidente: galería y subida antes/después

- WHEN el detalle carga, THE SYSTEM SHALL listar `GET /api/v1/incidents/{id}/photos` y renderizar
  cada `IncidentPhotoResponse.url` **tal cual** en el `src` de la imagen, agrupadas por `stage` y de
  la más antigua a la más reciente, que es el orden que sirve el backend.
- THE SYSTEM SHALL NOT persistir, reescribir ni reconstruir esa `url` —es una URL firmada acuñada
  para esa respuesta y con caducidad acotada—; cuando deje de servir, la recuperación SHALL ser
  volver a listar, acotada a **un** reintento por foto, y SHALL NOT existir ninguna `storage_key` en
  el cliente.
- WHERE el estado es `IN_PROGRESS` o `WAITING_EXTERNAL_PARTS`, THE SYSTEM SHALL ofrecer subir una
  foto con `stage` ∈ {`BEFORE`, `AFTER`} —enum cerrado de dos valores, sin campo de texto libre—
  mediante `POST /api/v1/incidents/{id}/photos` en `multipart/form-data`. En cualquier otro estado
  la subida SHALL NOT ofrecerse.
- THE SYSTEM SHALL emitir esa subida por el campo `formData` de `createApiClient`, mutuamente
  excluyente con `body`, que envía el `FormData` tal cual y **no** fija `Content-Type` —lo escribe
  el navegador para que lleve el `boundary`— conservando la cabecera de sesión, el reintento único
  ante `401` y el mapeo de errores del cliente compartido. THE SYSTEM SHALL mantener idéntico el
  comportamiento de las llamadas que no pasan ese campo.
- WHEN la subida responde `201`, THE SYSTEM SHALL invalidar la lista de fotos de esa incidencia.
- IF la subida responde `409` (estado que no admite fotos), `413` (tamaño), `422` (los bytes no son
  JPEG, PNG ni WebP) o `502` (fallo del almacenamiento), THEN THE SYSTEM SHALL mostrar un mensaje
  distinto para cada uno y SHALL NOT reintentar automáticamente. El mensaje del `422` SHALL nombrar
  los formatos admitidos, porque la causa frecuente en un móvil es un HEIC de iPhone y la acción que
  lo resuelve es cambiar el formato, no reintentar.
- THE SYSTEM SHALL NOT presentar la foto de cierre como requisito del cierre —no hay puerta de
  evidencia en `resolve`— ni ofrecer borrar una foto: la API no expone ningún borrado.

### R6 — Postura mobile-first, estados e i18n

- THE SYSTEM SHALL pasar toda cadena visible por `frontend/locales/es/tech.json` y
  `frontend/locales/en/tech.json`, sin ninguna literal en los componentes. El em-dash de R2 es la
  excepción declarada: es un signo tipográfico idéntico en los dos idiomas, va inline en el JSX y
  SHALL NOT tener clave de catálogo.
- THE SYSTEM SHALL construir los estados de carga, vacío y error sobre los primitivos compartidos
  (`StatePanel`, `LoadingState`, `EmptyState`, `ErrorState`), con `aria-busy` en la carga y
  `role="alert"` en el error, y SHALL NOT renderizar el detalle crudo de ningún error.
- THE SYSTEM SHALL disponer ambas pantallas en una sola columna con objetivos táctiles cómodos y sin
  desplazamiento horizontal a 360 px de ancho en el contenido que estas dos pantallas gobiernan.
- THE SYSTEM SHALL reutilizar `features/incidents/lib/severity-tone.ts` sobre `lib/ui/status-tone.ts`
  para la severidad y SHALL NOT introducir una segunda tabla de colores. El estado se pinta como un
  chip neutro (`text-muted-foreground`) porque no existe ninguna tabla
  estado-de-incidencia→`Tone` en el árbol; crearla es la entrada de roadmap `incident-status-tone`.
- THE SYSTEM SHALL formatear fechas con `formatDateTime(iso, locale)`, que recibe el `locale` de
  i18next como **parámetro** —nunca `undefined`, que resolvería al del navegador— y degrada al valor
  crudo ante una fecha inparseable en lugar de lanzar `RangeError`.
- THE SYSTEM SHALL confiar la autorización al backend: el `AuthGuard allow={["TECHNICIAN"]}` que
  monta el layout es un escudo de UX, y ninguna decisión de negocio SHALL derivarse del rol en el
  cliente.

## Known limitations

- **N+1 de contextos en la lista.** Cada fila pide su propio
  `GET /api/v1/incidents/{id}/context`, hasta `per_page` peticiones extra por página. Está mitigado
  —TanStack deduplica por clave, el detalle reaprovecha lo que la lista trajo y un fallo por fila
  degrada a `—` sin tumbar la pantalla— pero no resuelto: la salida es que `GET /api/v1/incidents`
  proyecte el nombre y el código de la vivienda en cada fila, que es la entrada de roadmap
  `incident-list-property-projection`.
- **Consecuencia sobre la excepción 6 del censo de la regla 11 de `steering/security.md`.** Esa
  proyección es *coarse*: un `/tech` abierto mantiene hasta `per_page` bloques de `access_notes` en
  la caché del cliente. Cada llamada está autorizada y acotada por `restrict_to_technician_id`, así
  que no se cruza ninguna frontera de confianza; lo que se gasta es la forma del remedio que el
  steering eligió.
- **Sin filtro multi-estado.** `GET /api/v1/incidents` admite un solo valor de `status`, y por eso la
  pantalla ofrece chips en lugar de una vista «activas».

## Key files

- `frontend/app/(field)/tech/page.tsx` y `frontend/app/(field)/tech/incidents/[id]/page.tsx` — las
  dos rutas, ya no `RoutePlaceholder`, bajo el `TechnicianShell` y el `AuthGuard allow={["TECHNICIAN"]}`
  que monta el layout del grupo `(field)`.
- `frontend/features/tech/components/list/` — `tech-incidents-view.tsx` (lista + «cargar más» +
  estados), `tech-incident-row.tsx` (la fila con su vivienda), `tech-status-chips.tsx` (los seis
  chips de valor único).
- `frontend/features/tech/components/detail/` — `tech-incident-detail-view.tsx` (composición),
  `tech-incident-fields.tsx`, `tech-context-block.tsx` (dirección, acceso y nota del manager),
  `tech-cycle-actions.tsx`, `tech-eta-field.tsx`, `tech-photo-gallery.tsx`, `tech-photo-upload.tsx`,
  `tech-resolve-form.tsx`.
- `frontend/features/tech/lib/tech-actions.ts` — `TECH_ACTIONS`, `techActions`,
  `techNoActionReason` y `techAcceptsPhotoUpload`: las tres tablas `Record<IncidentStatus, …>` que
  deciden qué ofrece cada estado.
- `frontend/features/tech/lib/format.ts` — `formatDateTime(iso, locale)`.
- `frontend/features/incidents/hooks/` — `use-incidents.ts` (lista, detalle, contexto, fotos),
  `use-incident-cycle.ts` (las cinco mutaciones del ciclo y la subida), `query-keys.ts`
  (`incidentsKeys`, con `context` compartida entre lista y detalle).
- `frontend/features/incidents/data/http/http-incidents-source.ts` y `data/dto.ts` — el transporte y
  los DTO, ensanchados con `etaAt` y `materials`.
- `frontend/features/incidents/lib/conflict-reason.ts` — los tres casos del `409`.
- `frontend/lib/api/client.ts` — el campo `formData` de `RequestOptions`, primera petición multipart
  del frontend.
- `frontend/locales/{es,en}/tech.json` — el catálogo, registrado en `frontend/lib/i18n/resources.ts`.
