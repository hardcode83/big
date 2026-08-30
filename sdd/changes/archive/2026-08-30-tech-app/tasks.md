# Tasks: tech-app

> Referencias: `proposal.md` (R1–R6) y `design.md` (D1–D17).
> Comandos de verificación de `sdd/project.md`: `cd frontend && npm run typecheck`,
> `npm run lint`, `npm test` (dentro del contenedor: `docker compose exec -T frontend …`).
> **Change 100 % frontend**: no se toca `backend/`, ni `backend/openapi.json`, ni
> `frontend/lib/api/generated/openapi.d.ts`, ni `.env.example` (design *Changes by area*).

## 1. Transporte: `multipart` en el cliente compartido (D2)

- [x] 1.1 En `frontend/lib/api/client.ts`, añadir `formData?: FormData` a `RequestOptions`
  (JSDoc: excluyente con `body`; el navegador escribe el `Content-Type` con su `boundary`).
  En `request()`: cuando `formData` está presente, NO fijar `Content-Type` por defecto y enviar
  `body: formData` en lugar de `JSON.stringify(body)`. Todo lo demás intacto —`getHeaders`
  (cabecera `Authorization`), el reintento único ante `401` vía `onUnauthorized` y
  `parseApiError`—; el `FormData` se reutiliza tal cual al reentrar en el bucle del reintento. [R5.4]
- [x] 1.2 Ampliar `frontend/lib/api/client.test.ts` con tres casos: (a) con `formData`, el `fetch`
  recibe la instancia de `FormData` como cuerpo y **no** hay cabecera `Content-Type` propia;
  (b) con `formData`, `JSON.stringify` no se aplica y `Authorization` sí viaja; (c) tras un `401`
  recuperado por `onUnauthorized`, el segundo `fetch` reenvía **el mismo** `FormData`.
  Añadir además un caso de no-regresión: una petición JSON existente conserva
  `Content-Type: application/json` y el cuerpo serializado. [R5.4]

## 2. Capa de datos de lectura en `features/incidents` (D1, D4)

- [x] 2.1 En `frontend/features/incidents/data/dto.ts`: añadir `etaAt: string | null` y
  `materials: string | null` a `IncidentDetailDto` (pasa de 18 a 20 campos, los que
  `IncidentResponse` ya trae desde `tech-cycle-completion`); añadir
  `IncidentPhotoStage = components["schemas"]["IncidentPhotoStage"]`, `IncidentContextDto`,
  `IncidentPhotoDto` (con JSDoc: URL firmada, se pinta tal cual y no se persiste) y
  `ResolveIncidentInput { finalCost: string; materials?: string }`, con las formas exactas de
  *Data & interfaces* del design. [R2.2, R2.3, R5.1]
- [x] 2.2 En `frontend/features/incidents/data/http/http-incidents-source.ts`: extender
  `mapIncidentDetail` con `etaAt`/`materials`; añadir `mapIncidentContext` y `mapIncidentPhoto`
  (frontera snake_case→camelCase, `url` copiada verbatim y **sin** ninguna `storage_key`);
  añadir `getIncidentContext(tenantId, incidentId)` sobre
  `GET /api/v1/incidents/{incident_id}/context` y `listPhotos(tenantId, incidentId)` sobre
  `GET /api/v1/incidents/{incident_id}/photos`. Ninguna ruta de `/api/v1/properties/…` entra
  aquí. [R1.2, R2.3, R2.5, R5.1, R5.2]
- [x] 2.3 En `frontend/features/incidents/hooks/query-keys.ts`: añadir
  `context(tenantId, incidentId)` → `['tenant', t, 'incidents-context', id]`,
  `photos(tenantId, incidentId)` → `['tenant', t, 'incidents-photos', id]` y
  `listPrefix(tenantId)` → `['tenant', t, 'incidents-list']`, sobre `tenantScopedKey`. JSDoc en
  `context`: es **la misma** clave que consumen la lista y el detalle, y esa identidad es lo que
  hace que abrir una fila no vuelva a pedir su contexto. [R1.3]
- [x] 2.4 En `frontend/features/incidents/hooks/use-incidents.ts`: añadir `useIncidentContext`
  y `useIncidentPhotos`, ambos con `retry: retryPolicy` y sobre las claves de 2.3. [R1.3, R2.1, R5.1]
- [x] 2.5 Tests de la capa de lectura: ampliar
  `frontend/features/incidents/data/http/http-incidents-source.test.ts` (las dos rutas nuevas
  golpean la URL correcta, mapean los campos y no emiten ningún parámetro que identifique al
  técnico) y `frontend/features/incidents/hooks/use-incidents.test.tsx` (los dos hooks nuevos
  usan la clave tenant-scoped esperada). Añadir un test que fije que `HttpIncidentsSource` **no**
  declara ninguna ruta `/api/v1/properties/` ni ningún método de borrado de fotos —la prohibición
  de R2.5/R5.7 se verifica sobre la única fuente que estas pantallas alcanzan. [R1.1, R2.5, R5.7]

## 3. Mutaciones del ciclo, cierre y subida (D2, D7, D8)

- [x] 3.1 Crear `frontend/features/incidents/lib/conflict-reason.ts`:
  `ConflictReason = "closed" | "awaiting-owner" | "out-of-order"` y
  `conflictReason(status: IncidentStatus): ConflictReason`, en el orden en que lo decide
  `_refuse_if_closed_or_awaiting_owner` (cerrada → a la espera de la propietaria → fuera de
  secuencia). No se lee `error.message` (inglés, R6.2 lo prohíbe). Test
  `conflict-reason.test.ts` cubriendo los nueve estados. [R3.7, R5.6]
- [x] 3.2 En `http-incidents-source.ts`, añadir las siete mutaciones: `accept`, `enRoute`
  (ambas con `IncidentEtaRequest` **opcional** — cuando no hay ETA se omite el cuerpo entero),
  `reject`, `waitParts`, `resume`, `resolve` (cuerpo `ResolveIncidentRequest` con `final_cost`
  como **string** y `materials` **omitido** si viene vacío) y `uploadPhoto(tenantId, incidentId,
  file, stage)` construyendo un `FormData` y pasándolo por la opción `formData` de 1.1. [R3.1, R3.3, R4.1, R5.3]
- [x] 3.3 Ampliar `http-incidents-source.test.ts`: cada mutación golpea su ruta y método;
  `accept`/`enRoute` sin ETA **no** llevan cuerpo y con ETA lo llevan con offset de zona;
  `resolve` manda `final_cost` como string y omite `materials` vacío; `uploadPhoto` viaja por la
  vía `formData` con los campos `file` y `stage`. [R3.3, R4.1, R5.3]
- [x] 3.4 Crear `frontend/features/incidents/hooks/use-incident-cycle.ts` con
  `useIncidentCycleAction`, `useResolveIncident` y `useUploadIncidentPhoto`: `useMutation` con
  `retry: false` e invalidación en **`onSettled`** (éxito y fallo). Ciclo y cierre invalidan
  `incidentsKeys.detail`, `incidentsKeys.context` y el prefijo `incidentsKeys.listPrefix`; la
  subida invalida sólo `incidentsKeys.photos`. Sin parcheo optimista. [R3.6, R4.2, R5.5]
- [x] 3.5 En el mismo hook, el caso aparte de `reject` (D8): tras el `200` se hace
  `removeQueries` de `detail` y `context` de esa incidencia —invalidar pediría un `404`—, se
  invalida el prefijo de la lista y se navega a `/tech` con `router.replace`. [R3.5]
- [x] 3.6 Test `frontend/features/incidents/hooks/use-incident-cycle.test.tsx`: (a) cada acción
  invalida exactamente las claves de 3.4; (b) un `409` también invalida (rama `onSettled`) y no
  reintenta; (c) `reject` hace `removeQueries` de detalle y contexto, invalida el prefijo de lista
  y llama a `router.replace("/tech")`; (d) la subida invalida `photos` y nada más. [R3.5, R3.6, R3.7, R5.5]
- [x] 3.7 Actualizar el barril `frontend/features/incidents/index.ts` con la superficie nueva
  (`useIncidentContext`, `useIncidentPhotos`, los tres hooks de mutación, `conflictReason` y los
  tipos nuevos). [D1]

## 4. i18n: namespace `tech` (D13)

- [x] 4.1 Crear `frontend/locales/es/tech.json` y `frontend/locales/en/tech.json` con **todas** las
  cadenas de las dos pantallas: títulos, rótulos de los seis chips, aviso de que la lista incluye
  incidencias ya cerradas, «cargar más», rótulos del bloque de contexto (vivienda, dirección,
  instrucciones de acceso, nota del manager, zona horaria), rótulos de los campos de
  `IncidentResponse`, rótulos de las cinco acciones del ciclo, copias de los estados sin acción
  («a la espera de la propietaria», «cerrada»), etiquetas y errores del formulario de cierre,
  copia de `AWAITING_OWNER_APPROVAL` («el cierre no se ha aceptado»), rótulos de la galería y de
  `BEFORE`/`AFTER`, los **cuatro** mensajes de error de la subida (`409` por razón de D7, `413`,
  `422` **nombrando JPEG/PNG/WebP** y `502`), las tres razones de `409` del ciclo, y las copias de
  vacío/error/no-disponible. **Ninguna literal en los componentes.** Los rótulos de
  `status.*`, `severity.*`, `category.*` y `source.*` **no** se duplican: se toman del namespace
  `incidents` que ya existe. [R6.1, R3.2, R3.7, R4.3, R5.6]
- [x] 4.2 Registrar el namespace en `frontend/lib/i18n/resources.ts` (imports `esTech`/`enTech`,
  entrada en `NAMESPACES` y en `resources.es` / `resources.en`). `lib/i18n/catalog-parity.test.ts`
  debe pasar sin tocarlo: es el test que garantiza que ambos catálogos tienen las mismas claves. [R6.1]

## 5. Pantalla `/tech` — mis incidencias (D4, D5, D15, D17)

- [x] 5.1 Crear `frontend/features/tech/lib/format.ts` con `formatDateTime(iso, locale)` sobre
  `Intl.DateTimeFormat`, tomando el locale activo **como parámetro** (no el `undefined` del
  runtime). Test `format.test.ts` fijando que dos locales distintos producen salidas distintas
  para el mismo instante. [R6.1]
- [x] 5.2 Crear `frontend/features/tech/components/list/tech-incidents-view.tsx`:
  `useIncidentsPages` sin ningún parámetro que identifique al técnico; sobre las filas devueltas,
  `useIncidentContexts`, con una entrada por fila bajo `incidentsKeys.context(tenantId, row.id)`
  —la misma clave del detalle—; un contexto de fila que falle degrada esa fila a `—` en vivienda y código sin
  tumbar la lista. Estados de la **lista** con `mapIncidentsError` + `LoadingState`
  (`aria-busy`) / `EmptyState` / `ErrorState` (`role="alert"`) de `@/components/states`, sin
  renderizar el detalle del error, y `retryPolicy` en la consulta. [R1.1, R1.2, R1.3, R1.6, R6.2]
- [x] 5.3 Crear `frontend/features/tech/components/list/tech-incident-row.tsx`: `<li>` de tarjeta
  pulsable (no `<table>`) con título, severidad, estado, categoría, fecha de creación,
  `propertyName` y `propertyInternalCode`. Badges con
  `TONE_BADGE_CLASS[severityColorGroup(...)]` de `features/incidents/lib/severity-tone.ts` — sin
  segunda tabla de colores. Objetivos táctiles ≥ 44×44 px. [R1.2, R6.3, R6.4]
- [x] 5.4 Crear `frontend/features/tech/components/list/tech-status-chips.tsx` con los **seis**
  chips (`ASSIGNED`, `ACCEPTED`, `IN_PROGRESS`, `WAITING_EXTERNAL_PARTS`,
  `AWAITING_OWNER_APPROVAL`, `RESOLVED`): un **único** valor `status` en el objeto de filtros
  —construido siempre con el mismo orden de claves para que la clave de query sea estable—, y un
  segundo clic sobre el chip activo vuelve a `{}` (sin filtro). Sin filtro, la lista se pide sin
  `status`, se presenta en el orden que sirve el backend **sin reordenar en cliente**, y una línea
  de copia avisa de que incluye incidencias ya cerradas. [R1.4, R1.5]
- [x] 5.5 Añadir a la vista el botón «cargar más» que acumula páginas sobre los defectos del
  backend (`page=1`, `per_page=20`); el `useQueries` de contextos se monta sobre la lista
  acumulada, de modo que las filas ya traídas conservan su contexto en caché. [R1.4]
- [x] 5.6 Tests `tech-incidents-view.test.tsx`, `tech-incident-row.test.tsx` y
  `tech-status-chips.test.tsx`: (a) la petición de lista no lleva ningún parámetro de técnico;
  (b) la fila muestra vivienda y código desde la clave de contexto, y un contexto fallido degrada
  a `—` sin tumbar la lista; (c) el chip activo re-pulsado quita el filtro y la clave vuelve a la
  de sin filtro; (d) lista vacía → `EmptyState`, fallo de la lista → `ErrorState` con
  `role="alert"` y sin detalle del error; (e) el orden renderizado es el de la respuesta.
  [R1.1, R1.2, R1.3, R1.4, R1.5, R1.6]

## 6. Pantalla `/tech/incidents/[id]` — detalle, ciclo, cierre y fotos (D6, D9–D12, D15)

- [x] 6.1 Crear `frontend/features/tech/lib/tech-actions.ts`:
  `CycleAction = "accept" | "reject" | "en-route" | "wait-parts" | "resume" | "resolve"` y
  `TECH_ACTIONS: Record<IncidentStatus, readonly CycleAction[]>` con exactamente la tabla de D6.
  La consulta se hace con `Object.hasOwn`, de modo que un estado desconocido por deriva de
  despliegue devuelve «ninguna acción» en lugar de reventar el render. Test `tech-actions.test.ts`
  cubriendo los nueve estados más un estado desconocido. [R3.1, R3.2]
- [x] 6.2 Crear `frontend/features/tech/components/detail/tech-incident-detail-view.tsx`: compone
  `useIncident` + `useIncidentContext`; un `404` de cualquiera de las dos se trata como
  «incidencia no disponible» —sin distinguir inexistente / otro tenant / otro técnico— con vuelta a
  `/tech`. Una sola columna (`mx-auto w-full max-w-md`), sin scroll horizontal a 360 px, y la barra
  de acciones al final del flujo. [R2.1, R2.6, R6.2, R6.3]
- [x] 6.3 Crear `frontend/features/tech/components/detail/tech-incident-fields.tsx`: renderiza de
  `IncidentResponse` título, descripción, severidad, categoría, estado, fuente, `etaAt`,
  `estimatedCost`, `approvedCost`, `finalCost`, `materials`, `ownerApprovalRequired`, `resolvedAt`
  y `createdAt`. Un campo nulo en línea dentro de una fila poblada se pinta con el em-dash `—`
  (U+2014), **sin** concatenar unidad y **sin** `?? ""`. Badges con la paleta de
  `severity-tone.ts`. [R2.2, R2.4, R6.4]
- [x] 6.4 Crear `frontend/features/tech/components/detail/tech-context-block.tsx`: de
  `IncidentContextResponse` muestra `propertyName`, `propertyInternalCode`, la dirección completa
  (`addressLine1`, `addressLine2`, `city`, `province`, `postalCode`, `country`), `timezone`,
  `accessNotes` como instrucciones de acceso —renderizadas **verbatim**, sin enmascarar ni
  reestructurar— y `assignmentNote` como nota del manager. Ninguna llamada a
  `/api/v1/properties/…` ni URL de almacenamiento construida en cliente. [R2.3, R2.5]
- [x] 6.5 Crear `frontend/features/tech/components/detail/tech-cycle-actions.tsx`: ofrece
  exactamente las acciones que `TECH_ACTIONS` devuelve para el estado actual; en
  `AWAITING_OWNER_APPROVAL`, `RESOLVED` y `CANCELLED` no ofrece ninguna y explica por qué. Ante un
  `409`, muestra el mensaje de la razón derivada por `conflictReason` sobre el estado **refrescado**
  y no reintenta. [R3.1, R3.2, R3.7]
- [x] 6.6 Crear `frontend/features/tech/components/detail/tech-eta-field.tsx`: `<input
  type="datetime-local">` **opcional** en «Aceptar» y «En ruta»; el valor se convierte con
  `new Date(value).toISOString()` (se interpreta en la zona del dispositivo y viaja con `Z`), y con
  el campo vacío se **omite el cuerpo entero**. No se replica ninguna validación de «no puede estar
  en el pasado»: un `422` del servidor se muestra junto al campo **sin perder lo escrito**. La
  `timezone` de la vivienda se muestra junto a la dirección pero no reinterpreta lo tecleado
  (`ASSUMPTION` documentada). [R3.3, R3.4]
- [x] 6.7 Crear `frontend/features/tech/components/detail/tech-resolve-form.tsx`, ofrecido sólo en
  `IN_PROGRESS`: `final_cost` obligatorio (`<input type="number" step="0.01" min="0"
  max="99999999.99">`) y `materials` opcional (`<textarea maxLength={2000}>`), sobre elementos
  nativos con clases de Tailwind. La validación local sólo **impide emitir** (obligatorio, ≥ 0,
  ≤ 99 999 999,99, dos decimales); un `422` del servidor se muestra **sin vaciar** el formulario.
  [R4.1, R4.5]
- [x] 6.8 Presentar la puerta de la propietaria **desde la respuesta** de `resolve`:
  `status = RESOLVED` presenta la incidencia cerrada con `finalCost`, `materials` y `resolvedAt`;
  `status = AWAITING_OWNER_APPROVAL` dice explícitamente que **el cierre no se ha aceptado** y
  queda a la espera de la propietaria, conserva visible el `finalCost` devuelto y **no inventa** un
  `resolvedAt` que llega `null`. El umbral `owner_approval_threshold_eur` no se calcula, no se
  muestra y no se anticipa. [R4.2, R4.3, R4.4]
- [x] 6.9 Crear `frontend/features/tech/components/detail/tech-photo-gallery.tsx`: lista
  `useIncidentPhotos` y pinta cada `url` **verbatim** en el `src` de un `<img>` (con el
  `eslint-disable-next-line @next/next/no-img-element` que ya usa
  `features/dashboard/components/detail/property-detail-sections.tsx`), agrupadas por `stage` y de
  la más antigua a la más reciente —el orden que sirve el backend—. Nada se persiste, reescribe ni
  reconstruye; no existe ninguna `storage_key` en el cliente. El `onError` de la imagen invalida
  `incidentsKeys.photos` **como mucho una vez por id de foto montado** (`useRef<Set<string>>`).
  Sin `staleTime` propio. No se ofrece borrar ninguna foto. [R5.1, R5.2, R5.7]
- [x] 6.10 Crear `frontend/features/tech/components/detail/tech-photo-upload.tsx`, ofrecido **sólo**
  en `IN_PROGRESS` y `WAITING_EXTERNAL_PARTS`: `<input type="file"
  accept="image/jpeg,image/png,image/webp" capture="environment">` más un control de dos opciones
  para `stage` (`BEFORE`/`AFTER`, enum cerrado, sin texto libre). **Sin** pre-validación de tamaño
  ni de formato: el `413` y el `422` son la frontera. Cuatro mensajes distintos y no reintento
  automático: `409` (razón derivada por `conflictReason`), `413` (tamaño), `422` **nombrando JPEG,
  PNG y WebP** y `502` (fallo del almacenamiento). La foto no se presenta como requisito del
  cierre. [R5.3, R5.6, R5.7]
- [x] 6.11 Tests del detalle (`tech-incident-detail-view.test.tsx` y los de cada bloque):
  (a) los campos de R2.2/R2.3 se renderizan y los nulos en línea salen como `—`;
  (b) por cada uno de los nueve estados se ofrecen exactamente las acciones de la tabla de D6;
  (c) «Aceptar» sin ETA no lleva cuerpo, con ETA lo lleva con offset, y un `422` conserva lo escrito;
  (d) un `409` muestra el mensaje de cada una de las tres razones tras el refresco;
  (e) `resolve` con `RESOLVED` y con `AWAITING_OWNER_APPROVAL` producen presentaciones distintas y
  la segunda no muestra `resolvedAt`;
  (f) validación local del cierre: no se emite petición, y un `422` no vacía el formulario;
  (g) la galería usa la `url` tal cual, agrupa por `stage`, y el `onError` invalida una sola vez
  por foto;
  (h) la subida sólo se ofrece en los dos estados admitidos y produce cuatro mensajes distintos
  para `409`/`413`/`422`/`502`;
  (i) un `404` de detalle o de contexto renderiza «no disponible» con vuelta a `/tech`.
  [R2.1–R2.6, R3.1–R3.7, R4.1–R4.5, R5.1–R5.7]
- [x] 6.12 Crear `frontend/features/tech/index.ts` exportando las dos vistas. [D1]

## 7. Rutas: los dos placeholders desaparecen

- [x] 7.1 Sustituir el `RoutePlaceholder` de `frontend/app/(field)/tech/page.tsx` por la vista de
  lista, conservando `generateMetadata()` con `routeMetadata("tech")`. [R1.1]
- [x] 7.2 Sustituir el `RoutePlaceholder` de `frontend/app/(field)/tech/incidents/[id]/page.tsx`
  por la vista de detalle, conservando `generateMetadata()` con `routeMetadata("tech-incident")` y
  pasando el `id` del segmento. [R2.1]
- [x] 7.3 Comprobar que `frontend/app/route-coverage.test.ts` y `frontend/app/route-wiring.test.tsx`
  siguen en verde con las dos rutas ya funcionales; si alguno asume una lista cerrada, ampliarla
  explícitamente en lugar de relajar el assert. El `AuthGuard allow={["TECHNICIAN"]}` del layout no
  se toca: ninguna decisión de negocio se deriva del rol en el cliente. [R6.5]

## 8. Documentación (`steering/documentation.md`)

- [x] 8.1 Añadir a `docs/maintenance.md` la sección «La app del técnico»: las dos pantallas, el
  ciclo desde el móvil, la galería y la subida antes/después, y la puerta de aprobación de la
  propietaria tal como se **muestra** (no como se calcula). Orientada a cómo se usa/opera; enlaza
  a las specs en vez de duplicarlas. [documentación]
- [x] 8.2 Revisar el `README.md` de la raíz y actualizarlo. **Enmendada en el gate de
  `/sdd:review` (2026-08-29)**: la redacción original acotaba la revisión a «el recuento o la
  descripción de las carpetas de `frontend/features/`», y ese recorte es lo que dejó pasar tres
  afirmaciones falsas. La norma de `sdd/steering/documentation.md` no habla de carpetas, sino de
  que «el README describe el sistema *actual*».
  - §Estructura (`README.md:304`) **no enumera** las carpetas de `frontend/features/`: no-op,
    anotado aquí como el propio paso exigía.
  - §Arrancar (`README.md:21`) sí enumera las superficies funcionales, y ahí hubo tres arreglos:
    añadir `/tech` (+detalle) al inventario, acotar «quedan fuera de alcance desde la web» a las
    cuatro mutaciones del manager —seis de las once se emiten ya desde esta pantalla— y sustituir
    la ruta `start`, que no existe en el contrato publicado desde que `tech-cycle-completion` la
    renombró a `en-route`. [documentación]

## 9. Verification

- [x] 9.1 Suite completa del frontend en verde: `docker compose exec -T frontend npm test`.
  **La cifra de referencia se mide, no se recuerda**: anotar el recuento de ficheros/tests de una
  ejecución de partida **antes** de tocar nada y comparar contra ella. En worktree enlazado hay que
  reponer antes los ficheros que dos tests leen por encima de `/app` (bloque de `docker compose cp`
  de `sdd/project.md`), o `workflow-contract.test.ts` y `build-identity-contract.test.ts` dan
  `ENOENT` ajenos a este change. Usar `rtk proxy` para leer las cifras reales. [verificación]
  **Medido**: partida **155 ficheros / 1531 tests** en verde (antes de tocar nada, con los
  `docker compose cp` ya repuestos); al cerrar, **163 ficheros / 1653 tests** en verde. Con la
  paralelización por defecto la suite da fallos que cambian de fichero entre ejecuciones y que
  pasan aislados —el host de Docker tiene 7,6 GB para cuatro stacks de worktree vivos—, así que la
  cifra buena se toma con `npx vitest run --maxWorkers=2`. **Incluso a dos workers hay flake
  residual**: una pasada dio 2 fallos en `features/cleaning` y `features/pricing` (features que
  este change no toca) que en aislado pasan enteros —33 ficheros / 447 tests en verde—. El conjunto
  que falla cambia en cada ejecución, que es la firma de la contención y no de una regresión.
- [x] 9.2 Typecheck en verde: `docker compose exec -T frontend npm run typecheck`. [verificación]
- [x] 9.3 Lint en verde: `docker compose exec -T frontend npm run lint`. [verificación]
  **Matiz**: `npm run lint` sobre el árbol entero muere con `Killed` (OOM del host, no del
  código). Se corrió en dos mitades —`npx eslint app components lib` y `npx eslint features test`,
  más los sueltos de la raíz— y las dos salen limpias, que cubre lo mismo.
- [x] 9.4 Confirmar que el diff **no** toca `backend/`, `backend/openapi.json`,
  `frontend/lib/api/generated/openapi.d.ts` ni `.env.example` (`git diff --name-only` contra la
  base). Si alguno aparece, el change se ha salido de su alcance: parar y abrir una entrada `[BE]`
  como se hizo el 2026-08-19. [alcance]
- [x] 9.5 Comprobación manual del flujo de punta a punta con un usuario `TECHNICIAN`: `/tech`
  lista con vivienda por fila, chips que filtran y se apagan, «cargar más»; abrir una fila **no**
  vuelve a pedir su contexto (verificable en la pestaña de red); recorrer
  `ASSIGNED → ACCEPTED → IN_PROGRESS → RESOLVED`, subir una foto `BEFORE` y otra `AFTER`, y cerrar
  con coste y materiales. [verificación]
- [x] 9.6 Revisar a 360 px de ancho que ninguna de las dos pantallas produce desplazamiento
  horizontal y que los objetivos táctiles son cómodos. [R6.3]

> **9.5 y 9.6 hechas el 2026-08-29**, en este mismo worktree y contra un backend vivo, con
> `make up PORT_OFFSET=10` (frontend en `:3010`, backend en `:8010`), `make bootstrap` +
> `make seed-demo`, y un navegador real a 360×780 conducido con Playwright. Lo que se midió:
>
> - **La premisa de que un worktree con `PORT_OFFSET` no hidrata es falsa.** `sdd/project.md` lo
>   afirmaba desde `cleaning-assign-preconditions` (2026-08-23) y es lo que mantuvo estas dos
>   tareas aparcadas. La app hidrata y es completamente interactiva: se hizo login, se navegó y se
>   ejecutó el ciclo entero. La afirmación caduca se ha corregido en `sdd/project.md`.
> - **Ciclo completo**: `ASSIGNED → ACCEPTED → IN_PROGRESS → RESOLVED`. La barra de acciones ofreció
>   en cada estado exactamente lo que manda R3.1 (Aceptar/Rechazar → En ruta/Rechazar → Esperando
>   piezas/Cerrar), y al quedar `RESOLVED` no ofreció ninguna (R3.2).
> - **Fotos**: una `BEFORE` y una `AFTER` subidas por el camino `multipart` nuevo de
>   `createApiClient` (R5.4) contra el backend real —la primera vez que ese código se ejerce fuera
>   de los tests—, agrupadas por etapa («Antes», «Después») y pintadas con la URL firmada tal cual
>   (R5.1). Al pasar a `RESOLVED` el formulario de subida se retiró (R5.3).
> - **Cierre**: enviar con el coste vacío mostró «Indica el coste final.» y **no emitió petición**
>   (R4.5); con `87.50` y materiales, la incidencia quedó cerrada mostrando coste, materiales y
>   fecha de resolución (R4.2).
> - **R1.1 confirmada en red**: la lista se pidió como `GET /api/v1/incidents?page=1&per_page=20`,
>   sin ningún parámetro que identifique al técnico.
> - **R1.3 se cumple, y la prueba es el código, no la red.** La cláusula normativa es la identidad
>   de clave («bajo la **misma clave**»), y eso se demuestra leyendo: hay **un** solo
>   `incidentsKeys.context(tenantId, incidentId)` en `features/incidents/hooks/query-keys.ts`, y lo
>   llaman los dos consumidores —`useIncidentContexts` para la fila y `useIncidentContext` para el
>   detalle— en `features/incidents/hooks/use-incidents.ts`. Dos tests lo fijan
>   (`tech-incidents-view.test.tsx` y `use-incidents.test.tsx`, ambos leyendo la entrada con
>   `client.getQueryData(incidentsKeys.context(...))`).
>
>   La medida de red —volver a la lista y reabrir la fila añadió **0** peticiones de `/context`— es
>   **compatible** con eso, pero **no lo discrimina**, y la primera redacción de esta nota afirmó
>   que sí. No lo hace: con claves distintas, la entrada propia del detalle se puebla en la primera
>   apertura y vive en el mismo `QueryClient`, así que reabrir dentro de los 60 s de `staleTime`
>   también costaría 0. Es más: el propio 0 obliga a que la reapertura cayera dentro de esa
>   ventana, porque fuera de ella `refetchOnMount` habría disparado también sobre la clave
>   compartida. Las dos hipótesis predicen lo mismo.
>
>   En el primer montaje sí se vio **una** petición extra, y **no se aisló su causa**. La
>   atribución inicial a StrictMode era errónea y se corrige aquí: con el `staleTime: 60_000` de
>   `frontend/lib/query/query-client.ts`, un remontaje de StrictMode sobre una entrada *fresca* no
>   emite ninguna petición. La explicación que encaja con lo medido es que entre cargar la lista y
>   abrir la fila pasó más de un minuto, la entrada venció y `refetchOnMount` la revalidó una vez —
>   comportamiento correcto **que también ocurre en producción**. Queda dicho para que nadie lea
>   aquí una garantía de «cero peticiones al abrir»: el `de modo que` de R1.3 es el motivo de la
>   regla, no una promesa absoluta, y más allá de los 60 s se revalida a propósito. Ese
>   `staleTime` no es de este change: lo fija `frontend/lib/query/query-client.ts`, que cita la
>   decisión de `frontend-foundation` (su D11, «Estrategia TanStack Query»). Los números D son por
>   change, así que un «(D11)» a secas aquí apuntaría a la D11 de `tech-app`, que es otra cosa
>   —la subida que no pre-valida—.
> - **R6.3**: a 360 px reales, **ninguna de las dos pantallas** produce desplazamiento horizontal —
>   cero elementos desbordados dentro de `main` en la lista y en el detalle—, y los objetivos
>   táctiles miden 44 px. La página sí desborda (`scrollWidth` 433), pero el desbordamiento está en
>   la cabecera del `TechnicianShell`, que este change no toca; se reproduce idéntico en
>   `/dashboard`, que tampoco toca. Es un defecto **preexistente del shell compartido**, no deuda
>   de `tech-app`, y queda anotado como candidato de roadmap en el §«Trabajo pendiente para
>   `/sdd:archive`» de `proposal.md` (punto 4), que es quien puede escribir el roadmap.
>
>   Con todo, conviene leer «R6.3 cumplida» con precisión: se cumple **para el contenido que estas
>   dos pantallas gobiernan**. Un técnico a 360 px sí tiene desplazamiento horizontal, porque las
>   dos pantallas viven dentro de ese shell. La parte del criterio que no se cumple no es
>   alcanzable sin salirse del alcance que declara el propio proposal: este change son **las dos
>   pantallas de `(field)/tech`**, y su §Out of scope deja fuera todo lo demás. (`features/shell` no
>   aparece en ninguna de sus listas de ficheros afectados.)
