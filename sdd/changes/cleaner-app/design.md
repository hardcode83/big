# Design: cleaner-app

## Context

Las dos rutas del segmento `(field)/cleaner` existen como `RoutePlaceholder` desde
`frontend-foundation`:

- `frontend/app/(field)/cleaner/page.tsx` renderiza `<RoutePlaceholder routeId="cleaner" />`
  con `routeMetadata("cleaner")`.
- `frontend/app/(field)/cleaner/tasks/[id]/page.tsx` análoga con `routeId="cleaner-task"`.

El registro de rutas (`frontend/features/shell/navigation/route-registry.ts:309-328`) ya
declara los dos descriptores con `profile: "cleaner"` y la misma jerarquía de migas que
`tech` y `tech-incident`. La `CleanerShell` (`features/shell/components/cleaner-shell.tsx`)
y el `AuthGuard allow={["CLEANER"]}` están montados desde el change original.

El lado de datos existe entero: las once rutas que esta pantalla necesita están servidas y
contratadas, y `frontend/lib/api/generated/openapi.d.ts` ya las enumera con sus DTOs. El
transporte también: `frontend/lib/api/client.ts` aceptó el campo `formData?: FormData` con el
cambio `tech-app` (design D2, archivado 2026-08-30) — sin cabecera `Content-Type` propia,
con `FormData` reenviable tras un `401` recuperado y con `parseApiError` aplicado al cuerpo
no-OK—. **Esto corrige la premisa del primer párrafo de R5.2 del proposal**, escrito antes
de ese archivado: ya no hace falta habilitar nada en `client.ts`; la pantalla sólo lo
consume.

El espejo de permisos ya existe en `frontend/lib/auth/permissions.ts:37-58` con
`CLEANER: []`. Ningún botón de esta pantalla se oculta por permiso: la pantalla entera se
ofrece al rol, y el `AuthGuard` del layout es el único escudo de UX (R8.5). El backend
sigue siendo la autoridad.

El patrón a copiar está a la vista: `tech-app` (archivado 2026-08-30) hace casi lo mismo
para el técnico sobre `maintenance` — lista con contexto por fila, detalle con ciclo de
vida, subida `multipart`, mutaciones que invalidan, cierre con confirmación reversible,
`409` re-interpretado por el estado refrescado—. Las diferencias con esta pantalla son
puntuales y se citan en cada decisión: **no** hay notas de acceso en el contexto de
limpieza (regla 11 de `steering/security.md` no se toca), **no** hay `cancel` (el permiso
no es del rol), **sí** hay reporte de incidencia desde la tarea (que `tech-app` no tiene).

## Decisions

### D1 — Feature nueva `frontend/features/cleaner/`; las dos pantallas viven en la app del técnico del mismo modo

**Chosen:** módulo propio `features/cleaner/` con el layering de `features/tech/`
(`data/`, `hooks/`, `lib/`, `components/`, `index.ts`), importando `@/features/cleaning`
sólo por el nombre del namespace i18n y por `task-status.ts` — la fuente de datos de la
pantalla del manager **no** se reutiliza. No se añade nada a `features/cleaning/`: su
`CleaningDataSource` (`data/cleaning-source.ts`) habla con `GET /cleaning-tasks` filtrando
por `property_id` y `status`, pero no acepta `restrict_to_cleaner_id` ni emite `accept` /
`reject` / `start` / `complete`. Reusarla por la barra obligaría a dos clientes de la
misma API con dos `Http*Source` distintos y un mapeador común: el mismo problema que
`tech-app` D1 cerró al añadir las nueve llamadas a `HttpIncidentsSource` en vez de abrir
una `HttpTechSource`.

Rejected: meter las pantallas en `features/cleaning/components/cleaner/` — `cleaning` es
hoy la app del manager y compartirle una carpeta por nombre del rol difumina qué
superficie es cuál; el patrón establecido es una feature por familia de pantallas con su
propio shell.
Rejected: una `HttpCleanerSource` autónoma que comparta mapeadores con `HttpCleaningSource`
por re-importación — duplicaría `CleaningTask → CleaningTaskListItem` y obligaría a que
las dos fábricas de claves acordaran la del contexto, que es exactamente lo que R1.3 del
proposal prohíbe dejar al azar.

### D2 — `HttpCleanerSource` con trece métodos, sobre el transporte compartido tal cual

**Chosen:** `features/cleaner/data/http/http-cleaner-source.ts` añade trece métodos sobre
la `ApiClient` que ya inyecta `lib/api/createAuthenticatedClients`:

- LECTURAS (seis): `listTasks(tenantId, filters, page)`, `getTask(tenantId, id)`,
  `getTaskContext(tenantId, id)`, `getTaskChecklist(tenantId, id)`,
  `getTaskPhotoRequirements(tenantId, id)`, `getTaskPhotos(tenantId, id)`.
- ESCRITURAS (siete): `acceptTask`, `rejectTask`, `startTask`, `completeTask`,
  `completeChecklistItem`, `uploadPhoto`, `reportIncident`.

`uploadPhoto` envía `multipart/form-data` por el campo `formData?: FormData` que
`tech-app` D2 dejó en `RequestOptions` (`client.ts:81-106`). El proposal R5.2 lo daba por
ausente porque se escribió antes del archivado de `tech-app`: la primera línea de R5.2
queda desfasada. **No se modifica `client.ts`.** El comportamiento del transporte es
idéntico para los consumidores que ya lo usan; los tests `client.test.ts` que `tech-app`
añadió fijan las dos ramas (FormData sin `Content-Type` propio; JSON.stringify no se
aplica; el reintento tras `401` reenvía el mismo `FormData`).

Rejected: importar `features/cleaning/data/cleaning-source.ts` — sus métodos `listTasks`
y `assignTask` no satisfacen la pantalla del limpiadora: el primero no admite los
parámetros del filtro de R1.5/1.6, el segundo ni existe en el contrato del técnico.
Rejected: un `fetch` ad-hoc en la pantalla — repite el contrato y rompe la frontera que
`frontend/features/dashboard/data/boundary.test.ts` ya prueba.

### D3 — Once claves de consulta, todas bajo `tenantScopedKey`

**Chosen:** `features/cleaner/hooks/query-keys.ts` exporta `cleanerKeys` con:

```ts
list(tenantId, filters, page)
detail(tenantId, taskId)
context(tenantId, taskId)
checklist(tenantId, taskId)
photoRequirements(tenantId, taskId)
photos(tenantId, taskId)
listPrefix(tenantId)   // prefijo del list() para invalidación
```

Todos bajo `['tenant', tenantId, ...]` (`lib/query/query-keys.ts`). El filtro del R1.5
viaja en el objeto `filters` con orden de claves estable — `status` antes de `page`, sin
claves a `undefined` — para que dos renders equivalentes produzcan la misma clave. El
mismo `Object.hasOwn` que `tech-app` D6 usa para detectar un estado desconocido se aplica
aquí a la enumeración de chips.

Rejected: claves por recurso en plural (`cleanerTasks`, `cleanerTaskContexts`) — diverge
del patrón `incidentsKeys` / `cleaningKeys` sin motivo.
Rejected: un solo objeto `cleanerKeys.all(tenantId)` para todo el módulo — destruye el
aprovechamiento de caché entre lista y detalle.

### D4 — Contexto por fila con `useQueries`, bajo la clave del detalle

**Chosen:** la lista emite `GET /cleaning-tasks` con `useCleanerTaskPages(filters,
pageCount, perPage)` (gemelo del `useIncidentsPages` de `tech-app` D4) y, sobre las filas
que devuelve, monta `useCleanerTaskContexts(taskIds)`, que es un `useQueries` (TanStack
v5) con una entrada por fila cuya `queryKey` es
`cleanerKeys.context(tenantId, row.id)` — **la misma** que `useCleanerTaskContext` en el
detalle. Abrir una fila no vuelve a pedir su contexto (R1.3). Un contexto que falle
degrada la fila a `—` (R1.4) sin tumbar la lista: el fallo del **contexto** no es el
fallo del **listado**, y el `ErrorState` de pantalla completa lo decide la rama de
listado, no la de proyección.

Coste asumido: hasta `per_page` peticiones extra por página renderizada. Mitigado por la
deduplicación de TanStack por clave, por el reaprovechamiento del detalle y por la
degradación por fila.

**Diferencia con `tech-app` D4 que conviene decir aquí, no en un apéndice**: el
`CleaningTaskContextResponse` (`sdd/specs/cleaner-task-context.md`) **no** lleva
`access_notes`. El coste asumido arriba es, por tanto, estrictamente nombres y
direcciones —lo que `cleaner-task-context` enuncia—, no instrucciones de acceso. La
excepción 6 del censo de la regla 11 de `steering/security.md` no entra en esta
pantalla, y eso es lo que la diferencia del `IncidentContextResponse` que `tech-app`
heredó.

Rejected: pedir el contexto dentro del `queryFn` de la lista — quedaría bajo la clave de
la lista y el detalle lo volvería a pedir, rompiendo R1.3.

### D5 — Los chips son los siete estados visibles, no los nueve del enum

**Chosen:** el objeto `filters` lleva `status` como **un único valor** (el contrato no
admite varios, igual que `IncidentFilters`); el chip activo pulsado otra vez vuelve a
`{}`. Los siete chips son los del R1.5 del proposal: `ASSIGNED`, `ACCEPTED`,
`IN_PROGRESS`, `PENDING_REVIEW`, `COMPLETED`, `REJECTED`, `CANCELLED`.

`CREATED` y `FAILED` quedan **fuera** del chip pero **dentro** del mapa de color: el
primero porque `CleaningActor.restrict_to_cleaner_id` lo vacía por construcción para
`CLEANER` (R1.5); el segundo porque sólo lo escribe el manager con `POST /validate` y no
es un estado que la limpiadora necesite filtrar —sí puede verlo si una fila llega con
él, y `statusColorGroup` lo pinta rojo por `features/cleaning/lib/task-status.ts`. Esa
es la postura de `cleaning-manager-view` D12, que **define** el `Record` exhaustivo en
tiempo de compilación sobre los nueve del enum: añadir un décimo estado en el backend
rompe la compilación, no el chip.

Sin filtro, la lista se pide en el orden que sirve el backend (`created_at` descendente)
y **no** se reordena en cliente (R1.6). Los tres estados sin acciones (R3.1) reciben
copia traducida: «a la espera de validación», «cerrada», «cancelada».

Rejected: ocho chips con `FAILED` — propone filtrar por un estado sobre el que la
limpiadora no tiene acción; el coste de presentarlo es cero, pero su presencia como
atajo no aporta.
Rejected: siete chips pero `status === "FAILED"` filtrado de la respuesta — mentiría
sobre lo que la limpiadora ve en su lista.

### D6 — Una tabla estado→acciones exhaustiva en tiempo de compilación

**Chosen:** `features/cleaner/lib/cleaner-actions.ts` declara
`CLEANER_ACTIONS: Record<CleaningTaskStatus, readonly CleanerAction[]>` con la tabla
exacta del R3.1, leída de la matriz de transiciones vigente en `sdd/specs/cleaning.md`
§Ciclo de vida de la tarea y acotada a las siete acciones que `EXECUTE_CLEANING_TASKS`
alcanza:

| Estado | Acciones ofrecidas |
|---|---|
| `ASSIGNED` | Aceptar (`accept`), Rechazar (`reject`) |
| `ACCEPTED` | Iniciar (`start`) |
| `IN_PROGRESS` | Cerrar (`complete`), Reportar incidencia (`reportIncident`); los ítems y las fotos son controles sobre la misma pantalla, no acciones del header |
| `PENDING_REVIEW` | ninguna — «a la espera de validación» |
| `COMPLETED` | ninguna — «cerrada» |
| `REJECTED` | ninguna — «rechazada» |
| `CANCELLED` | ninguna — «cancelada» |
| `CREATED` | ninguna (no alcanzable para `CLEANER`) |
| `FAILED` | ninguna — la validación la emite el manager |

Al ser un `Record` sobre la unión generada, añadir un décimo estado rompe la
compilación en vez de dejar un botón fantasma. Un estado desconocido llegado por
deriva de despliegue cae en «ninguna acción» y nunca en un `undefined` que reviente el
render (mismo comentario que `task-status.ts:8-13` para el color).

Rejected: derivar los botones de los permisos del rol — R6.5 del proposal lo prohíbe y
además el rol no es lo que decide, el estado sí.

### D7 — El `409` del cierre se explica por las tres cláusulas, en el orden que las decide el dominio

**Chosen:** `features/cleaner/lib/conflict-reason.ts` traduce un `409` de `POST
/cleaning-tasks/{id}/complete` a una de tres razones —`missing-required-items`,
`missing-required-photos`, `critical-incident`— en el orden en que
`CompletionEvidenceGatherer` decide cada cláusula (`sdd/specs/cleaning.md` §Cierre y
validación). Cada razón:

- `missing-required-items`: la pantalla resalta los ítems del checklist con `pending: true`
  que sean `required: true`. El `409` del backend enumera los `item_id` en orden
  estable — `specs/cleaning.md` §Cierre y validación fija la enumeración de los
  pendientes como una diferencia de conjuntos ordenada—, así que no se reinventa el
  vocabulario.
- `missing-required-photos`: la pantalla resalta las entradas de `/photo-requirements`
  con `uploaded: false` que sean `required: true`, con su `label`.
- `critical-incident`: la pantalla muestra una copia traducida que **no** nombra
  identificador, título ni descripción de la incidencia. `CLEANER` no tiene
  `READ_INCIDENTS` y un cuerpo que los incluyera sería la lectura que se le niega
  (`sdd/specs/cleaner-incident-report.md` §La incidencia que le bloquea su propio
  cierre).

La razón se releyendo el estado refrescado **después** del `invalidateQueries` que la
mutación ya hace, no del sobre del error: los tres `409` del cierre comparten
`code: "CONFLICT"` y se diferencian sólo por un `message` técnico en inglés que R7.3
prohíbe renderizar.

`mapCleanerError` (D12) decide la **rama de pantalla completa** y el **texto del
mensaje** para los códigos que sí se localizan: `409` con la razón; `404` con
«tarea no disponible»; `422` con el mensaje del backend si lo trae (`MAX_INCIDENT_TITLE`
/ `MAX_INCIDENT_DESCRIPTION` violado en R6); `502` con «almacenamiento no disponible».

Rejected: leer `error.message` del envelope — inglés, no localizable, R6.2 del
precedent lo prohíbe y R7.3 del proposal hereda esa prohibición.
Rejected: un único mensaje genérico de `409` — incumple R7.3 literalmente.

### D8 — Mutar es invalidar, nunca parchear; `reject` además desmonta; `complete` además ofrece volver

**Chosen:** las siete mutaciones usan `useMutation` con `retry: false` y
`onSettled` invalidando las claves adecuadas — en éxito **y en fallo**, porque tras un
`409` la fila está, por definición, en un estado que este cliente ya no cree. Tabla:

- `acceptTask`, `startTask`, `completeChecklistItem`, `uploadPhoto`, `reportIncident`:
  invalidan `cleanerKeys.detail(t, id)` y `cleanerKeys.listPrefix(t)`. `uploadPhoto` añade
  `cleanerKeys.photoRequirements(t, id)` y `cleanerKeys.photos(t, id)`; las dos últimas
  se invalidan también en `completeChecklistItem` con su clave propia. `reportIncident`
  no toca fotos ni requisitos.
- `completeTask`: mismo patrón, y en éxito se renderiza la tarea cerrada con un panel
  inline de «Cerrada — Volver a mis tareas» que invoca `router.replace("/cleaner")`. Es
  la acción reversible de R7.2 del proposal: el equivalente del toast que `tech-app`
  pinta para su cierre, pero como botón y no como notificación efímera. La navegación
  sigue siendo del hook llamante — `useCleanerTaskCycleAction` expone `onCompleted` y
  la vista decide qué pintar —, no del hook.
- `rejectTask`: tras el `200`, `removeQueries` para `cleanerKeys.detail(t, id)` y
  `cleanerKeys.context(t, id)` (el detalle de una tarea rechazada seguirá respondiendo
  `404` para quien rechazó, igual que en `tech-app` D8 para el rechazo del técnico);
  invalida `cleanerKeys.listPrefix(t)`; el hook expone `onRejected` y la vista hace
  `router.replace("/cleaner")` (R3.3 del proposal). La navegación **no** la hace el
  hook, por el mismo motivo que `tech-app` D8: la mutación vive en `features/cleaner/`
  que es la capa de datos y no debería importar `next/navigation`.

Rejected: actualización optimista con rollback — habría un instante mostrando una
transición que el backend no confirmó; es justo el caso que el `409` de R7.3 hace
visible.
Rejected: parcheo en caché del detalle con la respuesta del servidor — el `removeQueries`
del rechazo lo hace inviable y la invalidación del prefijo de la lista cubre el resto.

### D9 — La subida `multipart` consume el `formData` del transporte sin más

**Chosen:** `useCleanerUploadPhoto` arma el `FormData` con dos campos —
`photo_type` (derivado del `photo_type` de la entrada de `/photo-requirements` que la
usuaria tocó, no de un campo libre) y `file` (los `bytes` del `File` seleccionado)— y
lo pasa a `request(..., { formData })`. Sin cabecera `Content-Type` propia: el navegador
la escribe con su `boundary`. El `Content-Type: application/json` no se aplica porque
la rama `formData` lo esquiva en `client.ts:194-197`; el `JSON.stringify` tampoco, por
la misma rama.

El `<input type="file" accept="image/jpeg,image/png,image/webp" capture="environment">`
es un **ayuda** del selector, no validación: `sdd/specs/cleaning.md` §Fotos de la
limpieza fija que el formato lo deciden los bytes del fichero y nunca el
`Content-Type` declarado. El `422` puede llegar igual (HEIC de iPhone); R5.5 del
proposal exige un mensaje **distinto** que nombre los formatos admitidos, y
`uploadPhoto.errors.format` lo dice. No hay pre-validación de tamaño: el tope vive en
`PHOTO_UPLOAD_MAX_BYTES`, una variable del backend que el contrato no publica, y
copiarla aquí sería inventar un número que puede diferir del real (mismo razonamiento
que `tech-app` D11).

Estados que ofrecen subir: `IN_PROGRESS`, y ningún otro (R5.1). No se ofrece borrar (la
API no lo expone, R5.7) ni se presenta la foto como requisito del cierre: la pantalla
pinta lo que hay y lo que falta, y el veredicto vive en el backend
(`cleaner-photo-requirements.md` §La cobertura ya subida, como hecho y no como veredicto).

Cuatro mensajes de error por código (R5.5): `409` con la razón de `conflictReason`
(D7), `413` con «demasiado grande», `422` nombrando JPEG/PNG/WebP, `502` con
«almacenamiento no disponible». Sin reintento en ninguno; cada uno requiere una acción
que el botón «Subir otra» no puede representar.

Rejected: una función `uploadFile` propia — duplica `parseApiError`, la cabecera `getHeaders`
y el reintento de `401` que `tech-app` D2 ya consolidó en el transporte. La condición
de R5.4 del proposal (cabezal de sesión, reintento único, mapeo de errores) la cumple
el cliente tal cual está hoy.

### D10 — La galería con `<img src>` verbatim y recuperación por re-listado

**Chosen:** `<img src={photo.url}>` tal cual, con el `eslint-disable-next-line
@next/next/no-img-element` que ya usa `features/tech/components/detail/photo-gallery.tsx`
y `features/dashboard/components/detail/property-detail-sections.tsx`. Funciona en los
dos backends de almacenamiento sin que la pantalla sepa cuál hay: la URL `LOCAL` es
**relativa** (`/api/v1/cleaning-photos/{id}?exp=…&sig=…`,
`backend/app/integrations/infrastructure/storage/local.py:108-115`) y la del `S3` es
absoluta y presignada.

Nada se persiste, reescribe ni reconstruye (R2.5). No hay `storage_key` en ningún
cuerpo. La recuperación ante una firma caducada es **volver a listar**: el `onError`
de la imagen invalida `cleanerKeys.photos(t, id)` **como mucho una vez por id de foto
montado** (un `useRef<Set<string>>` guarda los ya reintentados, mismo patrón que
`tech-app` D10), para que una foto realmente ilegible no entre en bucle de refetch.

Sin `staleTime` propio: hereda los **60 s** del shell en `lib/query/query-client.ts`.
Al montar se revalida lo que pase de 60 s, muy por debajo de los 3600 s de la firma;
para la pantalla que se queda abierta, no hay revalidación por tiempo
(`refetchOnWindowFocus` está en `false`) y ése es justo el caso que cubre el `onError`
de arriba.

Rejected: `next/image` — exigiría declarar `remotePatterns` para un host de S3 que
depende del tenant, y no hay loader para URLs firmadas externas.

### D11 — Reporte de incidencia: formulario inline de dos campos, sobre el detalle

**Chosen:** panel colapsable bajo la barra de acciones, con `title`
(`<input maxLength={300}>`) y `description` (`<textarea maxLength={5000}>`) nativos,
sin primitiva de formulario en `components/ui/` (mismo razonamiento que `tech-app`
D12). Validación local sólo impide emitir (R6.2): `title` sin caracteres de control y
recortado en bordes (`str_strip_whitespace=True` lo revalida el backend, igual que en
`specs/cleaner-incident-report.md`); `description` con tabulador y saltos admitidos
(`MultiLineText`). `SingleLineText` y `MultiLineText` viven en
`backend/app/core/storable_text.py` y se revalidan en el `422` sin que el cliente
decida el carácter.

El botón «Reportar incidencia» se ofrece en `ASSIGNED`, `ACCEPTED` e `IN_PROGRESS`
(`INCIDENT_REPORTABLE_STATUSES`, R6.1); en estados terminales y en `PENDING_REVIEW` no
se pinta. La respuesta es el acuse de tres campos (`id`, `status`, `created_at`) y el
panel se cierra; no se vuelve a pintar el `title` ni la `description` (R6.3 del
proposal). La pantalla **no** lista, lee, clasifica ni resuelve incidencias: las
quince rutas de `/api/v1/incidents` siguen cerradas al rol (R6.4).

Rejected: una pantalla `/cleaner/tasks/[id]/incidents/new` — la limpiadora no navega
dos pantallas para reportar; el flujo es del piso, en el piso.
Rejected: modal fuera del flujo — la propuesta dice «abre un formulario»; inline bajo
la barra de acciones es la lectura literal y la que mejor cumple R8.3 a 360 px.

### D12 — Estados compartidos, `mapCleanerError` como tabla de ramas

**Chosen:** `LoadingState` (`role="status"` + `aria-busy`), `EmptyState` y `ErrorState`
(`role="alert"`) de `@/components/states`, que ya traen la semántica que R8.2 pide.
`mapCleanerError` (D7) elige la rama de pantalla completa y el texto del mensaje:
`401` se queda en `loading` (lo lleva el flujo de expiración de sesión); `404` es
`not-found` con vuelta a `/cleaner`; el resto cae en `error` con texto por código. Sin
reintento en `4xx`. Sin detalle crudo de error renderizado.

La rama en línea del contexto de fila (`—` con el resto de la fila intacta) la decide
la propia query de D4, no `mapCleanerError`: no es un estado de pantalla completa, es
una proyección accesoria. El `ErrorState` en línea de «ha fallado una página posterior»
lo decide `hasPageError` del resultado de `useCleanerTaskPages`, mismo patrón que
`tech-app` D14.

### D13 — Namespace `cleaner` nuevo; los rótulos de enum se reutilizan de `cleaning`

**Chosen:** `frontend/locales/{es,en}/cleaner.json`, registrados en `NAMESPACES` y
`resources` de `lib/i18n/resources.ts`. Las pantallas usan
`useTranslation(["cleaner", "cleaning", "states"])` y toman de `cleaning` los rótulos
de `status.*` (mismo patrón que `tech-app` D13 con `incidents`): **no** se crea una
segunda tabla de rótulos de enum por el mismo motivo que R8.4 prohíbe una segunda tabla
de colores.

`lib/i18n/catalog-parity.test.ts` ya obliga a que los dos catálogos tengan las mismas
claves, así que R8.1 queda cubierto por un test que existe.

### D14 — `formData` ya existe; el cliente no se toca

**Chosen:** ningún cambio en `frontend/lib/api/client.ts`. El campo `formData?: FormData`
que `tech-app` D2 dejó el 2026-08-30 cubre los tres requisitos literales del primer
párrafo de R5.2 del proposal —cabecera de sesión inyectada por `getHeaders`, reintento
único tras `401` por `onUnauthorized`, y `parseApiError` aplicado al cuerpo no-OK—.
**La primera frase de R5.2 queda desfasada** porque el proposal se escribió antes del
archivado de `tech-app`, y esta decisión lo dice aquí para que la prosa del proposal
no se lea como una instrucción pendiente.

Rejected: añadir un `uploadFile(path, formData)` específico en `lib/api/` — sería un
envoltorio sin valor sobre `request(path, { formData })`: el cliente ya pasa la
cabecera de sesión, ya reintenta una vez ante `401` reenviando el mismo `FormData`, y
ya mapea el envelope §23 con `parseApiError`.

### D15 — Mobile-first: una columna, tarjetas, acción reversible de salida

**Chosen:** ambas pantallas en una sola columna (`mx-auto w-full max-w-md`), sin
desplazamiento horizontal a 360 px. La lista es un `<ul>` de tarjetas pulsables, **no**
una `<table>`: una tabla de seis columnas no cabe en 360 px sin scroll lateral
(medido en `tech-app` D15). Las acciones del detalle van en una barra al final del
flujo con objetivos táctiles ≥ 44×44 px, sobre el `Button` de `components/ui/`. Badges
de estado con `TONE_BADGE_CLASS[statusColorGroup(status)]` desde
`features/cleaning/lib/task-status.ts` (R8.4) — un solo mapa de clases en todo el árbol.

Nulos en línea dentro de una fila poblada: em-dash `—` (U+2014) sin concatenar unidad y
sin `?? ""` (R2.4), como hace `fmtDateTime` en `features/tech/components/detail/*`.

La barra de acciones del detalle es el último elemento del flujo vertical y se queda
visible al hacer scroll: no se pega al borde inferior del viewport (no hay
`position: fixed`), porque la pantalla se opera con la mano que sostiene el móvil y
el panel inferior del navegador del sistema ocupa esa zona.

### D16 — Sin diagrama nuevo

**Chosen:** no se genera ninguno. El único que este change podría mover es
`docs/diagrams/2026-07-13_autohost-secuencia-limpieza.png`, y la regla de
`steering/architecture.md` es que se regenera cuando cambia **un paso** de la secuencia
—su nombre, sus orígenes, su destino, su ruta o el evento de timeline—, no cuando
cambia quién o qué la dispara. Aquí no cambia ningún paso: es la misma máquina de
limpieza, operada desde otra pantalla. La tabla de D6 dice lo que un diagrama diría, y
con los nombres exactos de las rutas.

### D17 — Formateador de fecha local, y la extracción anotada como candidato de roadmap

**Chosen:** `features/cleaner/lib/format.ts` con su propio `formatDateTime(iso, locale)`
sobre `Intl.DateTimeFormat`, tomando el locale activo como parámetro y no el
`undefined` del runtime — la enmienda que `pricing-web` escribió a su D14 y cuyo motivo
se repite aquí: un usuario con navegador en inglés que elige español leería el formato
equivocado en una pantalla española.

Sería la **sexta** copia del mismo formateador en el árbol (`features/dashboard/
lib/format.ts`, `features/conversations/components/list/conversations-view.tsx`,
`features/cleaning/components/cleaning-task-row.tsx`, `features/pricing/lib/format.ts`,
`features/tech/lib/format.ts`); la regla que el proyecto se escribió a sí mismo
—extraer al tercer consumidor, D22 de `pricing-web`, que es como nació
`lib/ui/status-tone.ts`— pidió extraerlo ya. Resuelto en el gate de `/sdd:design`
(OQ1, a resolver) a favor de **no** extraerlo aquí: la extracción tocaría cuatro
features que el proposal declara fuera de alcance, con `blocked-transitions-web` en
vuelo sobre el mismo árbol. Se anota como candidato de roadmap al archivar
(`shared-datetime-formatter`), con la cuenta de consumidores en el momento de
escribirlo.

Rejected: extraer ahora a `lib/format/` — el alcance, no la técnica, igual que
`tech-app` D17.
Rejected: crear `lib/format/` y migrar sólo esta feature — dejaría cinco copias con
una etiquetada «la buena», que es lo peor de las dos opciones.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Ruta | `frontend/app/(field)/cleaner/page.tsx` | Sustituye `RoutePlaceholder` por `<CleanerTaskListView />`; `generateMetadata` con `routeMetadata("cleaner")` se conserva |
| Ruta | `frontend/app/(field)/cleaner/tasks/[id]/page.tsx` | Sustituye `RoutePlaceholder` por `<CleanerTaskDetailView />`; `generateMetadata` con `routeMetadata("cleaner-task")` se conserva |
| Feature — data | `frontend/features/cleaner/data/dto.ts` *(nuevo)* | `CleaningTask`, `CleaningTaskListItem`, `CleaningTaskContext`, `CleaningChecklist`, `CleaningChecklistItem`, `PhotoRequirementState`, `PhotoRequirementsResponse`, `CleaningPhoto`, `CleaningFilters`, `CleaningIncidentReportInput`, `CleaningIncidentReportAck`, todos alias de `components["schemas"]` |
| | `frontend/features/cleaner/data/http-cleaner-source.ts` *(nuevo)* | Implementación sobre `ApiClient` con los once métodos (D2) |
| | `frontend/features/cleaner/data/index.ts` *(nuevo)* | Punto de composición (`createAuthenticatedClients` + `getCleanerDataSource`) |
| Feature — hooks | `frontend/features/cleaner/hooks/query-keys.ts` *(nuevo)* | Las siete claves de D3 sobre `tenantScopedKey` |
| | `frontend/features/cleaner/hooks/use-cleaner-tasks.ts` *(nuevo)* | `useCleanerTaskPages`, `useCleanerTaskContexts`, `useCleanerTask`, `useCleanerTaskContext`, `useCleanerTaskChecklist`, `useCleanerTaskPhotoRequirements`, `useCleanerTaskPhotos` |
| | `frontend/features/cleaner/hooks/use-cleaner-cycle.ts` *(nuevo)* | `useCleanerTaskCycleAction` (cubre `accept` / `start` / `completeChecklistItem` / `reportIncident`), `useRejectCleaningTask`, `useCompleteCleaningTask`, `useUploadCleaningPhoto` |
| Feature — lib | `frontend/features/cleaner/lib/cleaner-actions.ts` *(nuevo)* | `Record<CleaningTaskStatus, readonly CleanerAction[]>` exhaustivo (D6) |
| | `frontend/features/cleaner/lib/conflict-reason.ts` *(nuevo)* | Las tres razones del `409` del cierre (D7) |
| | `frontend/features/cleaner/lib/error-mapping.ts` *(nuevo)* | `ApiError.status → clave i18n` (D12) |
| | `frontend/features/cleaner/lib/format.ts` *(nuevo)* | `formatDateTime(iso, locale)` (D17) |
| Feature — components | `frontend/features/cleaner/components/list/cleaner-task-list-view.tsx` *(nuevo)* | Lista con chips, paginación, contextos por fila, EmptyState / ErrorState (D4, D5) |
| | `frontend/features/cleaner/components/list/cleaner-task-list-row.tsx` *(nuevo)* | Tarjeta: piso + ventana + estado + `—` si contexto degradado (D4, R2.6) |
| | `frontend/features/cleaner/components/list/cleaner-task-status-chips.tsx` *(nuevo)* | Siete chips excluyentes (D5) |
| | `frontend/features/cleaner/components/list/cleaner-task-pagination.tsx` *(nuevo)* | prev/next + «página X de Y» (mismo patrón que `cleaning-pagination.tsx`) |
| | `frontend/features/cleaner/components/detail/cleaner-task-detail-view.tsx` *(nuevo)* | Cinco peticiones en paralelo, composición, barra de acciones al final del flujo (R2.1) |
| | `frontend/features/cleaner/components/detail/cleaner-task-context-block.tsx` *(nuevo)* | Bloque de piso + dirección + ventana con `timezone` y los dos instantes formateados (R2.2) |
| | `frontend/features/cleaner/components/detail/cleaner-task-checklist.tsx` *(nuevo)* | Lista de ítems, marcar como completado vía `completeChecklistItem` (R4) |
| | `frontend/features/cleaner/components/detail/cleaner-task-photo-requirements.tsx` *(nuevo)* | Lista de categorías, una entrada por botón de subida, marca «cubierta» cuando `uploaded: true` (R5.1) |
| | `frontend/features/cleaner/components/detail/cleaner-task-photo-gallery.tsx` *(nuevo)* | `<img>` con `onError` que invalida `cleanerKeys.photos` una vez por id (D10) |
| | `frontend/features/cleaner/components/detail/cleaner-task-photo-upload-button.tsx` *(nuevo)* | `<input type="file">` con `accept`/`capture`, arma `FormData`, dispara `useUploadCleaningPhoto` (D9) |
| | `frontend/features/cleaner/components/detail/cleaner-task-action-bar.tsx` *(nuevo)* | Lee `CLEANER_ACTIONS[status]` y renderiza los botones de D6; en `IN_PROGRESS` muestra también «Reportar incidencia» (R6.1) y «Cerrar limpieza» (R7.1) |
| | `frontend/features/cleaner/components/detail/cleaner-incident-report-panel.tsx` *(nuevo)* | Formulario inline de dos campos con validación local y submit vía `useCleanerTaskCycleAction('reportIncident')` (D11) |
| | `frontend/features/cleaner/components/detail/cleaner-completion-panel.tsx` *(nuevo)* | Panel reversible de salida post-cierre con botón «Volver a mis tareas» (D8, R7.2) |
| Feature — barrel | `frontend/features/cleaner/index.ts` *(nuevo)* | Exporta `CleanerTaskListView`, `CleanerTaskDetailView` |
| i18n | `frontend/locales/es/cleaner.json` *(nuevo)* | Toda la copia de la app de la limpiadora |
| | `frontend/locales/en/cleaner.json` *(nuevo)* | Espejo; `lib/i18n/catalog-parity.test.ts` cubre la paridad |
| | `frontend/lib/i18n/resources.ts` | Registra el namespace `cleaner` (import, `NAMESPACES`, `resources.es.cleaner`, `resources.en.cleaner`) |
| Tests | `frontend/app/route-coverage.test.ts` | `REAL_PAGE_ROUTE_IDS` gana `"(field)/cleaner/page.tsx": "cleaner"` y `"(field)/cleaner/tasks/[id]/page.tsx": "cleaner-task"`. Sin esto el test falla: la página deja de llevar `routeId=`. |
| | `frontend/app/route-wiring.test.tsx` | Casos: `/cleaner` monta `CleanerTaskListView`; `/cleaner/tasks/{id}` monta `CleanerTaskDetailView` |
| | `frontend/features/cleaner/**/*.test.ts(x)` | Cobertura por requisito: ver *Verification* abajo |

**Lo que NO cambia, dicho para el panel de review:** ni `backend/`, ni
`backend/openapi.json`, ni `frontend/lib/api/generated/openapi.d.ts`, ni
`frontend/lib/api/client.ts`. Este change no toca el contrato y el transporte ya
admite `formData` por el archivado de `tech-app`, así que no corre `make openapi` ni
`npm run api:generate` — las dos mitades del puente de `steering/documentation.md` no
se disparan. Tampoco hay variable de entorno nueva, así que `.env.example` no se
toca.

## Data & interfaces

Sin esquema, sin migración, sin variable de entorno, sin endpoints nuevos. Solo se
**consumen** tipos ya generados y métodos ya expuestos por el transporte.

Interfaz de la feature (firmas, no implementación):

```ts
export interface CleanerDataSource {
  // Lecturas
  listTasks(tenantId: string, filters: CleanerFilters, page: number):
    Promise<PaginatedResponse<CleaningTaskListItem>>;
  getTask(tenantId: string, taskId: string): Promise<CleaningTask>;
  getTaskContext(tenantId: string, taskId: string): Promise<CleaningTaskContext>;
  getTaskChecklist(tenantId: string, taskId: string): Promise<CleaningChecklist>;
  getTaskPhotoRequirements(tenantId: string, taskId: string):
    Promise<PhotoRequirementsResponse>;
  getTaskPhotos(tenantId: string, taskId: string): Promise<CleaningPhoto[]>;
  // Mutaciones
  acceptTask(tenantId: string, taskId: string): Promise<CleaningTask>;
  rejectTask(tenantId: string, taskId: string): Promise<CleaningTask>;
  startTask(tenantId: string, taskId: string): Promise<CleaningTask>;
  completeTask(tenantId: string, taskId: string): Promise<CleaningTask>;
  completeChecklistItem(tenantId: string, taskId: string, itemId: string):
    Promise<CleaningChecklistItem>;
  uploadPhoto(tenantId: string, taskId: string, photoType: string, file: File):
    Promise<CleaningPhoto>;
  reportIncident(tenantId: string, taskId: string,
    input: CleaningIncidentReportInput): Promise<CleaningIncidentReportAck>;
}

export interface CleanerFilters {
  status?: CleaningTaskStatus;     // un único valor (D5)
}

export interface CleaningIncidentReportInput {
  title: string;
  description: string;
}

export type CleanerAction =
  | "accept" | "reject" | "start"
  | "complete"
  | "completeChecklistItem"        // acción por ítem, no de la barra
  | "uploadPhoto"                  // acción por entrada, no de la barra
  | "reportIncident";
export const CLEANER_ACTIONS: Record<CleaningTaskStatus, readonly CleanerAction[]>;

export type ConflictReason =
  | "missing-required-items"
  | "missing-required-photos"
  | "critical-incident";
export function conflictReason(task: CleaningTask): ConflictReason;
```

Claves de consulta (todas bajo `['tenant', tenantId, ...]`,
`lib/query/query-keys.ts`):

- `cleanerKeys.list(t, {status}, page)` →
  `['tenant', t, 'cleaner-tasks', {status}, page]`
- `cleanerKeys.listPrefix(t)` → `['tenant', t, 'cleaner-tasks']`
- `cleanerKeys.detail(t, id)` → `['tenant', t, 'cleaner-task', id]`
- `cleanerKeys.context(t, id)` → `['tenant', t, 'cleaner-task-context', id]`
- `cleanerKeys.checklist(t, id)` → `['tenant', t, 'cleaner-task-checklist', id]`
- `cleanerKeys.photoRequirements(t, id)` →
  `['tenant', t, 'cleaner-task-photo-requirements', id]`
- `cleanerKeys.photos(t, id)` → `['tenant', t, 'cleaner-task-photos', id]`

## Requisitos sin implicación de diseño

- **R2.6** (no llamar a `/api/v1/properties/…` ni construir URLs de almacenamiento) y
  **R5.7** (ni borrado de fotos ni presentar la foto como requisito del cierre) son
  prohibiciones: se cumplen por ausencia. Lo que las hace verificables es que la única
  fuente de datos que estas pantallas alcanzan es `HttpCleanerSource`, que no conoce
  ninguna ruta de propiedades ni de reservas ni ningún borrado.
- **R8.5** (la autorización la decide el backend) tampoco añade código: el
  `AuthGuard` ya está montado en el layout desde `frontend-foundation` y ninguna
  decisión de D6 sale del rol (no hay entrada nueva en `ROLE_UI_PERMISSIONS` para
  `CLEANER`; la fila hoy dice `CLEANER: []` y sigue diciendo `CLEANER: []`).
- **R5.3** (los `404` se tratan como «tarea no disponible» sin distinguir) se cubre
  por la rama `not-found` de `mapCleanerError` (D12) y por el «Volver a `/cleaner`»
  del panel de detalle, sin enumerar las tres causas que el backend colapsa.
- **R6.4** (la pantalla no lista, lee, clasifica ni resuelve incidencias) se cumple
  por construcción: el botón «Reportar incidencia» es el único consumidor de
  `reportIncident` desde esta feature y no hay imports cruzados hacia `features/
  incidents/`.

## Risks & mitigations

- **N+1 de contextos en la lista (D4).** Hasta `per_page` peticiones extra por página
  renderizada. Mitigado por la deduplicación de TanStack, el reaprovechamiento del
  detalle y la degradación por fila. No se mitiga del todo y no puede mitigarse
  desde aquí: la salida real es que `GET /api/v1/cleaning-tasks` proyecte
  `property_name` y `property_internal_code` en cada fila — `cleaning-assign-
  preconditions` ya añadió `assignment_blocked_by` al item del listado, así que la
  forma está—. Eso es una entrada `[BE]` propia. **A diferencia de `tech-app`** el
  contexto de limpieza **no** lleva notas de acceso (D4), así que la caché del
  dispositivo no recibe instrucciones de acceso por la puerta de atrás. Anotado
  como candidato de roadmap al archivar (`cleaner-list-property-projection`).
- **Firma caducada en una pantalla abierta mucho rato.** Mitigado por el `onError`
  de D10, acotado a un reintento por foto. Residual aceptado: una foto que falle por
  otro motivo se ve rota tras ese único reintento, que es preferible a un bucle de
  listados.
- **`shell-topbar-overflow-360` y `blocked-transitions-web` comparten árbol.** El
  primero está en vuelo en otro worktree y deja un `scrollWidth` residual sobre el
  `Topbar` (medido el 2026-08-29 en `tech-app`); R8.3 lo declara satisfecho para lo
  que estas dos pantallas gobiernan, no para el shell. El segundo es `[FE]` sobre
  `features/incidents/` y **no** toca `features/cleaner/`, así que la única
  superposición posible sería `lib/i18n/resources.ts` o los catálogos `locales/`,
  que se resuelven con un merge en `/sdd:ship` (merge de la base, no rebase).
- **Deriva de despliegue en los enums.** Un estado o un `photo_type` que el frontend
  compilado no conozca. Mitigado por construcción: `statusColorGroup` degrada a gris
  y `CLEANER_ACTIONS` se consulta con `Object.hasOwn`, devolviendo «ninguna acción»
  en lugar de reventar. Un `photo_type` desconocido en `/photo-requirements` cae
  fuera del `Record` de `CLEANING_ACTIONS['uploadPhoto']` por entrada y no pinta
  botón — el frontend no rompe, pero la limpiadora no puede cubrir un tipo que
  existe en backend sin regenerar el contrato.
- **El primer párrafo de R5.2 del proposal queda desfasado.** El transporte ya
  admite `formData` desde `tech-app` D2 (archivado 2026-08-30). La corrección se
  hace aquí, en D14, que es el lugar que la revisión lee, y **no** en el proposal,
  cuya prosa no se modifica post-aprobación.
- **El espejo de permisos se desincroniza del backend.** Esta pantalla **no** añade
  entradas al espejo (`CLEANER: []` cubre exactamente lo que la pantalla pinta y
  nada más); el riesgo del espejo es el mismo que `cleaning-manager-view` D7
  describió y `messaging-ai` D17 amplió. Sin delta aquí.

## Open questions

- **OQ1 — ¿Se extrae `formatDateTime` a `lib/format/`?** Resuelta a favor de **no**,
  por el mismo razonamiento que `tech-app` D17: el alcance tocaría cuatro features
  fuera del proposal. Anotado como candidato al archivar. Recogido en D17.
- **OQ2 — ¿Chips de estado con 7 o con 9 entradas?** Resuelta a favor de **7**
  (los del R1.5 del proposal). `FAILED` se pinta en la fila pero no se ofrece como
  filtro. Recogido en D5.
- **OQ3 — El primer párrafo de R5.2 dice que `createApiClient` no admite
  `multipart`.** Resuelta: ya lo admite por `tech-app` D2 (archivado 2026-08-30). La
  corrección va aquí en D14 y en la prosa del design, no en el proposal.
- **OQ4 — Reporte de incidencia como modal o como panel inline.** Resuelta a favor
  de **panel inline** bajo la barra de acciones: R8.3 (mobile-first a 360 px) y
  R6.1 (la limpiadora reporta desde la tarea que está haciendo). Recogido en D11.

### Encargos explícitos a `/sdd:archive`

1. **`cleaner-list-property-projection`** — entrada `[BE]` para que
   `GET /api/v1/cleaning-tasks` proyecte `property_name` y `property_internal_code`
   en cada fila, mitigando el N+1 de D4 en el origen y no en el cliente. La forma
   ya está: `cleaning-assign-preconditions` añadió `assignment_blocked_by` al item
   del listado con el mismo principio. `needs: cleaner-app`. S.
2. **`shared-datetime-formatter`** — candidato de roadmap de D17, sexta copia del
   mismo formateador; la regla del proyecto pide extraer al tercer consumidor y
   `pricing-web` D22 la cumplió extrayendo el tono. Aquí la extracción no se hace
   por alcance, no por técnica; queda dicho para el siguiente consumidor.
3. **Corregir dos frases de spec viva** que el proposal lista bajo «Trabajo
   pendiente para `/sdd:archive`» (sección de Affected specs): la frase de
   `sdd/specs/cleaner-task-context.md:159, 167-168` sobre `access_records.notes` que
   sigue siendo de `cleaner-app` (ya no lo es, porque el disparador no se cumple) y
   la frase de `sdd/specs/access-notifications.md:131-134` que cita esa misma
   atribución. La regla 1 de SDD tiene ambas en spec viva y solo archive las puede
   tocar.
