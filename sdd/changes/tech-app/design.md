# Design: tech-app

## Context

Las dos rutas del segmento `(field)/tech` existen y son `RoutePlaceholder`:
`frontend/app/(field)/tech/page.tsx` y `frontend/app/(field)/tech/incidents/[id]/page.tsx`, bajo
`frontend/app/(field)/tech/layout.tsx` (`TechnicianShell` + `AuthGuard allow={["TECHNICIAN"]}`) y
con su `error.tsx` de segmento ya puesto. El registro de rutas ya declara `tech` y `tech-incident`
con `profile: "technician"` (`frontend/features/shell/navigation/route-registry.ts:329-348`).

El lado de datos existe a medias. `frontend/features/incidents/` habla hoy con **dos** rutas —
`GET /api/v1/incidents` y `GET /api/v1/incidents/{id}` — a través de `HttpIncidentsSource`
(`data/http/http-incidents-source.ts`), un punto de composición único (`data/index.ts`), claves
tenant-scoped (`hooks/query-keys.ts`) y un mapeador de errores a estados de UI
(`lib/error-mapping.ts`). Le faltan las trece restantes que esta pantalla necesita: `context`,
`photos` (GET y POST), y las seis del ciclo. `IncidentDetailDto` enumera 18 campos y
`IncidentResponse` ya trae **20** — `eta_at` y `materials` entraron con `tech-cycle-completion` y
el DTO todavía no los nombra.

Dos hechos del contrato publicado, verificados contra `backend/openapi.json` y el código, que
mandan sobre casi todas las decisiones de abajo: la `url` de una foto es **relativa** para el
backend `LOCAL` (`/api/v1/incident-photos/{id}?exp=…&sig=…`, deliberadamente relativa —
`backend/app/integrations/infrastructure/storage/local.py:108-115`) y absoluta y presignada para
`S3`; y los **tres** `409` distinguibles del ciclo comparten `code: "CONFLICT"`
(`backend/app/maintenance/api/errors.py:42-45`), de modo que sólo se diferencian por su `message`
técnico en inglés.

El transporte no admite `multipart` hoy: `createApiClient` (`frontend/lib/api/client.ts`)
serializa **siempre** con `JSON.stringify(body)`. (Precisión sobre R5.4: la cabecera
`Content-Type: application/json` sí es condicional — sólo se pone si el llamante no la trajo,
`client.ts` línea `if (hasBody && !finalHeaders.has("Content-Type"))`; lo incondicional, y lo que
de verdad bloquea, es el `JSON.stringify`.) No hay ni un `FormData` en todo el árbol del frontend.

## Decisions

### D1 — La capa de datos crece en `features/incidents`; las pantallas viven en `features/tech`

**Chosen:** las nueve llamadas nuevas (contexto, fotos GET/POST y las seis del ciclo) se añaden a
`HttpIncidentsSource`, a `incidentsKeys` y a los hooks de `features/incidents`; las dos superficies
del técnico se escriben en una feature nueva `frontend/features/tech/`, que importa esa capa por el
barril `@/features/incidents`. Una feature = un dominio del backend en la capa de datos, así que
existe **una sola frontera snake_case→camelCase** para `IncidentResponse` y **una sola** fábrica de
claves — que es exactamente lo que hace que R1.3 salga gratis en lugar de exigir coordinación entre
dos módulos. Y una feature = una familia de superficies en la capa de presentación: la pantalla del
técnico tiene otro shell, otro rol y otro vocabulario que la del manager.

El import cruzado entre features no es un patrón nuevo: `features/shell/components/technician-shell.tsx`
importa `@/features/auth` y `features/shell/components/shell-footer.tsx` importa
`@/features/provenance`.

Rejected: meter también las pantallas en `features/incidents/components/tech/` — dejaría una
carpeta sirviendo a dos shells sin ninguna frontera que lo declare.
Rejected: una `features/tech` autónoma con su propia `HttpTechSource` — duplicaría el mapeo de
`IncidentResponse` y obligaría a que dos fábricas de claves acordaran la de contexto, que es
precisamente lo que R1.3 prohíbe dejar al azar.

### D2 — `formData` como opción explícita de `createApiClient`, no un `fetch` a pelo

**Chosen:** `RequestOptions` gana un campo `formData?: FormData`. Cuando está presente, `request()`
**no** pone `Content-Type` por defecto (el navegador debe escribirlo él para incluir el `boundary`)
y envía `formData` como cuerpo en lugar de `JSON.stringify(body)`. Todo lo demás del cliente
compartido se conserva sin tocarlo: la cabecera `Authorization` que inyecta `getHeaders`, el
reintento único ante `401` vía `onUnauthorized` y el `parseApiError` que convierte el sobre PRD §23
en `ApiError` — los tres requisitos literales de R5.4.

Un campo aparte y no `body` porque el tipo de `body` sale de `RequestBodyFor<…>`, que sólo extrae
`content["application/json"]`: para `POST /incidents/{id}/photos` eso es `never`, así que un
`FormData` por ahí no compilaría. El `FormData` es reutilizable entre `fetch`es, de modo que el
reintento tras `401` (que vuelve a entrar en el bucle y reconstruye la petición) sigue funcionando.

Rejected: un `fetch` propio en la fuente de datos — perdería las tres cosas que R5.4 exige conservar.
Rejected: ensanchar `RequestBodyFor` con la rama `multipart/form-data` — haría que `body` aceptara
un objeto plano para esa ruta y que el `JSON.stringify` siguiera siendo el camino por defecto.

### D3 — El proxy same-origin no se toca (verificado, no supuesto)

**Chosen:** nada que cambiar en `frontend/app/api/[...path]/route.ts`. Reenvía el cuerpo en
streaming (`body: request.body` con `duplex: "half"`) y sólo borra cabeceras hop-by-hop y de
reenvío, así que el `Content-Type: multipart/form-data; boundary=…` que escribe el navegador llega
intacto al backend. El `413` de `MaxBodySizeMiddleware` vuelve por el mismo camino.

Se hace explícito porque el proposal no lo menciona y era la vía más probable por la que R5 podía
resultar irrealizable sin tocar backend.

### D4 — El contexto por fila con `useQueries`, bajo la clave del detalle

**Chosen:** la lista pide `GET /api/v1/incidents` con `useIncidents` y, sobre las filas que
devuelva, monta un `useQueries` (TanStack v5) con una entrada por fila cuya `queryKey` es
`incidentsKeys.context(tenantId, row.id)` — **la misma** que usa `useIncidentContext` en el
detalle. Abrir una fila no vuelve a pedir su contexto (R1.3) porque es literalmente la misma
entrada de caché.

Un contexto de fila que falle degrada esa fila a `—` en vivienda y código, sin tumbar la lista:
R1.6 gobierna el fallo de **la petición de la lista**, no el de una proyección accesoria.

Rejected: pedir los contextos dentro del `queryFn` de la lista — quedarían bajo la clave de la
lista y el detalle los volvería a pedir, incumpliendo R1.3.
Rejected: no mostrar la vivienda en la lista — R1.2 la exige, y es la razón por la que la pantalla
existe («a qué piso voy»).

Coste asumido, no escondido: hasta `per_page` peticiones extra por página renderizada. Ver *Risks*.

### D5 — Los chips de estado son un valor único y se apagan al segundo clic

**Chosen:** `status` viaja como **un** valor (el contrato no admite varios) dentro del objeto
`IncidentFilters`, que es parte de la clave de la lista. El chip activo pulsado otra vez vuelve a
`{}` (sin `status`). El objeto de filtros se construye siempre con el mismo orden de claves, como
avisa el comentario de `incidentsKeys.list`, para que dos renders equivalentes produzcan la misma
clave.

La lista pagina con un botón **«cargar más»** que acumula páginas sobre los defectos del backend
(`page=1`, `per_page=20`), resuelto en el gate de `/sdd:design` (OQ1, 2026-08-29). R1.4 habla de
«la página» en singular y R1 no pide paginar, pero una lista truncada en veinte **sin ninguna
señal** contradice el «saber qué tengo pendiente» de R1. Se descartó subir `per_page` a 50 con una
línea «mostrando X de Y» (mueve el corte, no lo elimina) y dejar una sola página de 20 (deja la
truncación invisible). El `useQueries` de D4 se monta sobre la lista acumulada, así que las filas
ya traídas conservan su contexto en caché.

Los seis chips son los del `ASSUMPTION` de R1: `ASSIGNED`, `ACCEPTED`, `IN_PROGRESS`,
`WAITING_EXTERNAL_PARTS`, `AWAITING_OWNER_APPROVAL`, `RESOLVED`. Sin filtro, la lista se presenta
en el orden que sirve el backend y **no se reordena en cliente** (R1.4), con una línea de copia que
avisa de que incluye incidencias ya cerradas.

### D6 — Una tabla estado→acciones, exhaustiva en tiempo de compilación

**Chosen:** `features/tech/lib/tech-actions.ts` declara
`TECH_ACTIONS: Record<IncidentStatus, readonly CycleAction[]>` con exactamente la tabla de R3.1,
que es la lectura del `_TRANSITIONS` de `backend/app/maintenance/domain/entities.py:227-251`
acotada a las seis operaciones que `EXECUTE_INCIDENTS` alcanza:

| Estado | Acciones ofrecidas |
|---|---|
| `ASSIGNED` | Aceptar (`accept`), Rechazar (`reject`) |
| `ACCEPTED` | En ruta (`en-route`), Rechazar (`reject`) |
| `IN_PROGRESS` | Esperando piezas (`wait-parts`), Cerrar (formulario de R4) |
| `WAITING_EXTERNAL_PARTS` | Reanudar (`resume`) |
| `AWAITING_OWNER_APPROVAL` | ninguna — copia «a la espera de la propietaria» |
| `RESOLVED`, `CANCELLED` | ninguna — copia «cerrada» |
| `OPEN`, `CLASSIFIED` | ninguna (no alcanzables: sin asignatario no llegan a esta pantalla) |

Al ser un `Record` sobre `IncidentStatus` —que viene del contrato generado— añadir un décimo estado
al backend rompe la compilación en vez de dejar un botón fantasma. Un estado desconocido llegado
por deriva de despliegue cae en «ninguna acción», nunca en un `undefined` que reviente el render.
Esto es presentación del contrato, no autorización: el backend refuta con `409` de todas formas
(R6.5).

Rejected: derivar los botones de los permisos del rol en cliente — R6.5 lo prohíbe y además el rol
no es lo que decide, el estado sí.

### D7 — El `409` se explica desde el estado refrescado, no desde el sobre del error

**Chosen:** `features/incidents/lib/conflict-reason.ts` traduce un `409` a una de tres razones
—`closed`, `awaiting-owner`, `out-of-order`— **releyendo el estado de la incidencia** después del
refresco que R3.6/R3.7 ya exigen, en el mismo orden en que el dominio las decide
(`_refuse_if_closed_or_awaiting_owner`: cerrada primero, a la espera de la propietaria después,
fuera de secuencia lo que sobreviva a las dos).

Es la única vía honesta: los tres errores comparten `code: "CONFLICT"` y sólo se distinguen por un
`message` técnico **en inglés**, que R6.2 prohíbe renderizar. Y el estado refrescado es además la
respuesta más útil, porque describe por qué la acción no cabe *ahora*, que es lo que el técnico
necesita saber.

La misma función sirve al `409` de la subida de fotos, cuyos tres casos son los mismos tres y en el
mismo orden (`ensure_accepts_photo`).

Rejected: leer `error.message` — inglés, no localizable, y R6.2 lo prohíbe.
Rejected: un único mensaje genérico de `409` — incumple R3.7 literalmente.

### D8 — Mutar es invalidar, nunca parchear; y `reject` además desmonta

**Chosen:** las siete mutaciones (`accept`, `reject`, `en-route`, `wait-parts`, `resume`,
`resolve`, `photos`) usan `useMutation` con `retry: false` e invalidación en `onSettled` — en el
fallo tanto como en el éxito, exactamente por el motivo que escriben `useAssignCleaningTask` y
`useDecideRecommendation`: tras un `409` la fila en pantalla está, por definición, en un estado que
este cliente ya no cree.

Qué invalida cada una:

- ciclo (`accept`/`en-route`/`wait-parts`/`resume`/`resolve`): `incidentsKeys.detail(t, id)`,
  `incidentsKeys.context(t, id)` y el prefijo `incidentsKeys.listPrefix(t)`.
- subida de foto: `incidentsKeys.photos(t, id)` (R5.5) y nada más — subir una foto no mueve el
  estado ni la lista.
- `reject` (R3.5): es el caso aparte. Tras el `200`, `GET /incidents/{id}` responde `404` a quien
  rechazó, así que **invalidar el detalle sería pedir un `404`**: se hace `removeQueries` de
  `detail` y `context` de esa incidencia, se invalida el prefijo de la lista y se navega a `/tech`
  con `router.replace`.

Rejected: parcheo optimista — habría un instante mostrando una transición que el backend no
confirmó, que es justo el caso que el `409` de R3.7 hace visible.

### D9 — La ETA se lee en la zona del dispositivo y viaja en UTC

**Chosen:** un `<input type="datetime-local">` opcional en «Aceptar» y en «En ruta». Su valor es un
instante ingenuo que se convierte con `new Date(value).toISOString()` — es decir, se **interpreta
en la zona del dispositivo** y viaja con `Z`, que satisface el «must carry a timezone» del backend
(R3.3). Cuando el campo está vacío se **omite el cuerpo entero** de la petición: el router lo toma
como `IncidentEtaRequest | None = None` y un `POST` sin cuerpo sigue siendo válido.

No se replica ninguna validación de «no puede estar en el pasado» (R3.4): la frontera es el `now`
del servidor. Un `422` se muestra junto al campo sin vaciar lo escrito.

El `timezone` de la vivienda que trae `IncidentContextResponse` se **muestra** junto a la
dirección, pero no se usa para reinterpretar lo que el técnico teclea: hacerlo desplazaría en
silencio la hora que acaba de escribir y exigiría una librería de zonas que el árbol no tiene.
`ASSUMPTION`: el técnico teclea la hora del reloj que tiene delante.

### D10 — Las fotos se pintan con `<img src>` verbatim y se recuperan re-listando

**Chosen:** `<img src={photo.url}>` tal cual, con el `eslint-disable-next-line
@next/next/no-img-element` que ya usa `features/dashboard/components/detail/property-detail-sections.tsx`
para las fotos de limpieza. Funciona en los dos backends de almacenamiento sin que la pantalla
sepa cuál hay: la URL `LOCAL` es **relativa** y el navegador la resuelve contra el origen de la
página, que es donde vive el proxy `/api/`; la de `S3` es absoluta y presignada.

Nada se persiste, reescribe ni reconstruye (R5.2). No hay `storage_key` en ningún cuerpo. La
recuperación ante una firma caducada es **volver a listar**: el `onError` de la imagen invalida
`incidentsKeys.photos(t, id)` **como mucho una vez por id de foto montado** (un `useRef<Set<string>>`
guarda los ya reintentados), para que una foto realmente ilegible no entre en bucle de refetch.

Sin `staleTime` propio: el defecto de TanStack (0) revalida al montar, muy por debajo de los 3600 s
de la firma.

Rejected: `next/image` — exigiría declarar `remotePatterns` para un host de S3 que depende del
tenant, y no hay loader para URLs firmadas externas.

### D11 — La subida no pre-valida ni el tamaño ni el formato

**Chosen:** `<input type="file" accept="image/jpeg,image/png,image/webp" capture="environment">`
más un control de dos opciones para `stage` (`BEFORE`/`AFTER`, enum cerrado, sin texto libre). El
`accept` y el `capture` son ayudas del selector, no validación: **el backend decide el formato
leyendo los bytes** y nunca consulta el `Content-Type` que mande el cliente.

No hay comprobación de tamaño en cliente: el tope es `PHOTO_UPLOAD_MAX_BYTES`, una variable de
entorno del backend que no se publica en ningún contrato, así que copiarla aquí sería inventar un
número que puede diferir del real. El `413` es la frontera, igual que el `now` del servidor lo es
para la ETA.

Cuatro mensajes distintos y no tres (R5.6, enmendado en el gate de `/sdd:design` — OQ1 del
proposal): `409` (estado que no admite fotos, con la razón derivada por D7), `413` (tamaño), `422`
**nombrando los formatos admitidos** y `502` (fallo del almacenamiento). El `422` tiene mensaje
propio porque su causa frecuente en un móvil es un HEIC de iPhone y la acción que lo resuelve es
cambiar el formato, no reintentar; la otra causa del `422` —un `stage` fuera del enum— no es
alcanzable desde esta pantalla.

Estados que ofrecen subir: `IN_PROGRESS` y `WAITING_EXTERNAL_PARTS`, y ningún otro (R5.3). No se
ofrece borrar (la API no lo expone) ni se presenta la foto como requisito del cierre (R5.7).

### D12 — El cierre manda `final_cost` como **string** y omite `materials` vacío

**Chosen:** formulario con `final_cost` obligatorio (`<input type="number" step="0.01" min="0"
max="99999999.99">`) y `materials` opcional (`<textarea maxLength={2000}>`), sobre elementos
nativos con clases de Tailwind — el patrón de `features/conversations/components/thread/conversation-reply-form.tsx`,
porque `components/ui/` no tiene primitivas de formulario y añadirlas sería alcance que nadie pidió.

Dos precisiones que salen de leer `ResolveIncidentRequest` y que no son cosméticas:

1. `final_cost` se envía como **string** (`"120.50"`), que el contrato admite con el patrón de dos
   decimales, y no como `number`. Es el mismo motivo por el que `fmtDecimal` sólo convierte a
   número **para formatear**: un ida y vuelta por `float` de un valor monetario es exactamente la
   corrupción que su representación como cadena existe para evitar.
2. `materials` vacío se **omite del cuerpo**. El esquema tiene `str_strip_whitespace=True` con
   `min_length=1`, así que mandar `""` es un `422`: «sin materiales» se dice omitiendo el campo.

La validación local sólo impide emitir (R4.5) — obligatorio, ≥ 0, ≤ 99 999 999,99, dos decimales —
y un `422` del servidor se muestra sin vaciar el formulario.

La puerta de la propietaria se lee de la **respuesta** (R4.2/R4.3): `status = RESOLVED` presenta la
incidencia cerrada con `final_cost`, `materials` y `resolved_at`; `status = AWAITING_OWNER_APPROVAL`
dice explícitamente que **el cierre no se ha aceptado**, conserva el `final_cost` que devuelve la
respuesta y no inventa un `resolved_at` que viene `null`. El umbral no se calcula, no se muestra y
no se anticipa (R4.4): el rol no puede leer `TenantConfig`.

### D13 — Namespace `tech` nuevo; los rótulos de enum se reutilizan de `incidents`

**Chosen:** `frontend/locales/es/tech.json` y `frontend/locales/en/tech.json`, registrados en
`NAMESPACES` y en `resources` de `lib/i18n/resources.ts`. Las pantallas usan
`useTranslation(["tech", "incidents", "states"])` y toman de `incidents` los rótulos de
`status.*`, `severity.*`, `category.*` y `source.*` que ya existen — no se crea una segunda tabla
de rótulos de enum, por el mismo motivo por el que R6.4 prohíbe una segunda tabla de colores.

`lib/i18n/catalog-parity.test.ts` ya obliga a que los dos catálogos tengan las mismas claves, así
que R6.1 queda cubierto por un test que existe.

### D14 — Estados compartidos, y `mapIncidentsError` como tabla de ramas

**Chosen:** `LoadingState` (`role="status"` + `aria-busy`), `EmptyState` y `ErrorState`
(`role="alert"`) de `@/components/states`, que ya traen la semántica que R6.2 pide. La rama la
elige `mapIncidentsError` de `features/incidents/lib/error-mapping.ts`, reutilizado tal cual: `401`
se queda en `loading` (lo lleva el flujo de expiración de sesión), `404` es `not-found` — que es
como R2.6 exige tratar los tres casos indistinguibles —, y ningún detalle de error se renderiza.
`retry: retryPolicy` en las consultas (sin reintento en 4xx), `retry: false` en las mutaciones.

### D15 — Mobile-first: una columna, tarjetas, y la barra de acciones abajo

**Chosen:** ambas pantallas en una sola columna (`mx-auto w-full max-w-md`), sin scroll horizontal a
360 px. La lista es un `<ul>` de tarjetas pulsables, **no** una `<table>` como la del manager: una
tabla de seis columnas no cabe en 360 px sin desplazamiento lateral. Las acciones del detalle van
en una barra al final del flujo con objetivos táctiles ≥ 44×44 px, sobre el `Button` de
`components/ui/`. Badges de severidad y estado con `TONE_BADGE_CLASS[severityColorGroup(...)]`
de `features/incidents/lib/severity-tone.ts` sobre `lib/ui/status-tone.ts` (R6.4).

Nulos en línea dentro de una fila poblada: em-dash `—` (U+2014) sin concatenar unidad y sin
`?? ""` (R2.4), como hace `fmtCost` en `incident-detail-sections.tsx`.

### D16 — Sin diagrama nuevo

**Chosen:** no se genera ninguno. El único que este change podría mover es
`docs/diagrams/2026-08-23_autohost-secuencia-mantenimiento.png`, y la regla de
`steering/architecture.md` es que se regenera cuando cambia **un paso** de la secuencia —su nombre,
sus orígenes, su destino, su ruta o el evento de timeline—, no cuando cambia quién lo dispara. Aquí
no cambia ningún paso: es la misma máquina, operada desde otra pantalla. La tabla de D6 dice lo que
un diagrama diría, y con los nombres exactos de las rutas.

### D17 — Formateador de fecha local, y la extracción anotada como candidato de roadmap

**Chosen:** `features/tech/lib/format.ts` con su propio `formatDateTime(iso, locale)` sobre
`Intl.DateTimeFormat`, tomando el locale activo como parámetro y no el `undefined` del runtime —
la enmienda que `pricing-web` escribió a su D14 y cuyo motivo se repite aquí: un usuario con
navegador en inglés que elige español leería el formato equivocado en una pantalla española.

Es la **quinta** copia del mismo formateador en el árbol (`features/dashboard/lib/format.ts`,
`features/conversations/components/list/conversations-view.tsx`,
`features/cleaning/components/cleaning-task-row.tsx`, `features/pricing/lib/format.ts`), y la regla
que el proyecto se escribió a sí mismo —extraer al tercer consumidor, D22 de `pricing-web`, que es
como nació `lib/ui/status-tone.ts`— pediría extraerlo ya a `lib/format/`. Resuelto en el gate de
`/sdd:design` (OQ2, 2026-08-29) a favor de **no** extraerlo aquí: la extracción tocaría cuatro
features que el proposal declara fuera de alcance, con `blocked-transitions-web` en vuelo sobre el
mismo árbol. Se anota como candidato de roadmap al archivar (`shared-datetime-formatter`), con la
cuenta de consumidores en el momento de escribirlo.

Rejected: extraer ahora a `lib/format/` — el alcance, no la técnica.
Rejected: crear `lib/format/` y migrar sólo esta feature — dejaría cinco copias con una etiquetada
«la buena», que es lo peor de las dos opciones.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Transporte HTTP | `frontend/lib/api/client.ts` | `RequestOptions.formData?: FormData`; sin `Content-Type` por defecto y sin `JSON.stringify` cuando está presente (D2) |
| Transporte HTTP | `frontend/lib/api/client.test.ts` | Casos: `FormData` viaja sin `Content-Type` propio; `JSON.stringify` no se aplica; el reintento tras `401` reenvía el mismo `FormData` |
| Datos (dominio) | `frontend/features/incidents/data/dto.ts` | `IncidentDetailDto` gana `etaAt` y `materials`; nuevos `IncidentContextDto`, `IncidentPhotoDto`, `IncidentPhotoStage`, `ResolveIncidentInput`, `CycleAction` |
| Datos (dominio) | `frontend/features/incidents/data/http/http-incidents-source.ts` | `getIncidentContext`, `listPhotos`, `uploadPhoto`, `accept`, `reject`, `enRoute`, `waitParts`, `resume`, `resolve`; `mapIncidentDetail` mapea los dos campos nuevos |
| Datos (dominio) | `frontend/features/incidents/hooks/query-keys.ts` | `context`, `photos`, `listPrefix` |
| Datos (dominio) | `frontend/features/incidents/hooks/use-incidents.ts` | `useIncidentContext`, `useIncidentPhotos` |
| Datos (dominio) | `frontend/features/incidents/hooks/use-incident-cycle.ts` *(nuevo)* | `useIncidentCycleAction`, `useResolveIncident`, `useUploadIncidentPhoto` (D8) |
| Datos (dominio) | `frontend/features/incidents/lib/conflict-reason.ts` *(nuevo)* | Las tres razones de `409` derivadas del estado refrescado (D7) |
| Datos (dominio) | `frontend/features/incidents/index.ts` | Exporta la superficie nueva |
| Pantallas | `frontend/features/tech/**` *(nuevo)* | `components/list/` (vista, fila, chips, «cargar más»), `components/detail/` (vista, bloque de contexto, acciones de ciclo, campo ETA, formulario de cierre, galería, subida), `lib/tech-actions.ts`, `lib/format.ts`, `index.ts` y sus tests |
| Rutas | `frontend/app/(field)/tech/page.tsx`, `frontend/app/(field)/tech/incidents/[id]/page.tsx` | Sustituyen `RoutePlaceholder` por las vistas; `generateMetadata` con `routeMetadata` se conserva |
| i18n | `frontend/locales/{es,en}/tech.json` *(nuevos)*, `frontend/lib/i18n/resources.ts` | Namespace `tech` registrado (D13) |
| Docs | `docs/maintenance.md` | Sección «La app del técnico»: las dos pantallas, el ciclo desde el móvil y la puerta de aprobación tal como se muestra (`steering/documentation.md`) |
| Docs | `README.md` (raíz) | Sólo si el recuento de carpetas de `frontend/features/` que describe queda desfasado al añadir `tech/` |

**Lo que NO cambia, dicho para el panel de review:** ni `backend/`, ni `backend/openapi.json`, ni
`frontend/lib/api/generated/openapi.d.ts`. Este change no toca el contrato, así que no corre
`make openapi` ni `npm run api:generate` — las dos mitades del puente de `steering/documentation.md`
no se disparan. Tampoco hay variable de entorno nueva, así que `.env.example` no se toca.

## Data & interfaces

Sin cambios de esquema, de migraciones ni de contrato publicado. Las quince rutas consumidas ya
existen en `frontend/lib/api/generated/openapi.d.ts`. Interfaces nuevas, todas en el frontend:

```ts
// lib/api/client.ts
export interface RequestOptions<Body, Method extends string> {
  // …lo que ya hay…
  /** Cuerpo multipart. Excluyente con `body`: el navegador escribe el Content-Type y su boundary. */
  formData?: FormData;
}

// features/incidents/data/dto.ts
export type IncidentPhotoStage = components["schemas"]["IncidentPhotoStage"]; // "BEFORE" | "AFTER"

export interface IncidentContextDto {
  propertyName: string;  propertyInternalCode: string;
  addressLine1: string | null;  addressLine2: string | null;
  city: string | null;  province: string | null;  postalCode: string | null;
  country: string;  timezone: string;
  accessNotes: string | null;  assignmentNote: string | null;
}

export interface IncidentPhotoDto {
  id: string; incidentId: string; stage: IncidentPhotoStage;
  uploadedBy: string; createdAt: string;
  /** URL firmada, de un solo uso práctico: se pinta tal cual y no se persiste (D10). */
  url: string;
}

export interface ResolveIncidentInput { finalCost: string; materials?: string }

// features/tech/lib/tech-actions.ts
export type CycleAction = "accept" | "reject" | "en-route" | "wait-parts" | "resume" | "resolve";
export const TECH_ACTIONS: Record<IncidentStatus, readonly CycleAction[]>;

// features/incidents/lib/conflict-reason.ts
export type ConflictReason = "closed" | "awaiting-owner" | "out-of-order";
export function conflictReason(status: IncidentStatus): ConflictReason;
```

Claves de consulta nuevas, sobre `tenantScopedKey`:

- `incidentsKeys.context(tenantId, incidentId)` → `['tenant', t, 'incidents-context', id]`
- `incidentsKeys.photos(tenantId, incidentId)` → `['tenant', t, 'incidents-photos', id]`
- `incidentsKeys.listPrefix(tenantId)` → `['tenant', t, 'incidents-list']` (prefijo del existente)

## Requisitos sin implicación de diseño

- **R2.5** (no llamar a `/api/v1/properties/…` ni construir URLs de almacenamiento) y **R5.7** (ni
  borrado de fotos ni puerta de evidencia en `resolve`) son prohibiciones: se cumplen por ausencia.
  Lo que las hace verificables es que la única fuente de datos que estas pantallas alcanzan es
  `HttpIncidentsSource`, que no conoce ninguna ruta de propiedades ni ningún borrado.
- **R6.5** (la autorización la decide el backend) tampoco añade código: el `AuthGuard` ya está
  montado en el layout desde `frontend-foundation` y ninguna decisión de D6 sale del rol.
- **R2.3** (`access_notes` como instrucción de acceso) se renderiza **verbatim**, sin enmascarar ni
  reestructurar. No es un descuido: es lo que la excepción 6 del censo de la regla 11 de
  `steering/security.md` autoriza y describe — el técnico asignado es uno de sus tres lectores
  declarados.

## Risks & mitigations

- **N+1 de contextos en la lista (D4).** Hasta `per_page` peticiones extra por página renderizada.
  Mitigado en parte: TanStack deduplica por clave, el detalle reaprovecha lo que la lista trajo, y
  un fallo por fila degrada a `—` sin tumbar la pantalla. No se mitiga del todo, y no puede
  mitigarse desde aquí: la salida real es que `GET /api/v1/incidents` proyecte el nombre y el
  código de la vivienda en cada fila, y eso es una entrada `[BE]` propia. Se propone anotarla como
  candidato de roadmap al archivar (`incident-list-property-projection`).
- **Firma caducada en una pantalla abierta mucho rato.** Mitigado por el `onError` de D10, acotado
  a un reintento por foto. Residual aceptado: una foto que falle por otro motivo se ve rota tras
  ese único reintento, que es preferible a un bucle de listados.
- **`blocked-transitions-web` comparte árbol.** Está en vuelo en otro worktree y es también `[FE]`
  sobre el dominio de incidencias. Ninguna de sus superficies es `/tech`, pero si toca
  `features/incidents/data` o `hooks`, el conflicto aparece al abrir el PR. Mitigación: es un
  conflicto de merge, no una dependencia — se resuelve en `/sdd:ship` poniendo la rama al día con
  un **merge** de la base (nunca un rebase, que borraría el `implementation_sha` certificado).
- **Deriva de despliegue en los enums.** Un estado o una severidad que el frontend compilado no
  conozca. Mitigado por construcción: `severityColorGroup` degrada a gris y `TECH_ACTIONS` se
  consulta con `Object.hasOwn`, devolviendo «ninguna acción» en lugar de reventar.
- **El `formData` de D2 toca infraestructura compartida.** `createApiClient` lo usa todo el
  frontend. Mitigación: el camino nuevo está detrás de un campo opcional que nadie más pasa, de
  modo que el comportamiento de las llamadas existentes es idéntico por construcción; los tests
  nuevos de `client.test.ts` fijan las dos ramas.

## Open questions

Ninguna abierta. Las cuatro que este design levantó se resolvieron en su gate el 2026-08-29:

- **OQ1 — Paginación en `/tech`.** Resuelta: botón «cargar más» que acumula páginas. Recogida en D5.
- **OQ2 — Dónde vive `formatDateTime`.** Resuelta: formateador local en `features/tech/lib/format.ts`
  y la extracción a `lib/format/` anotada como candidato de roadmap (`shared-datetime-formatter`)
  al archivar. Recogida en D17.
- **OQ3 — El `422` de la subida de fotos no estaba en R5.6.** Resuelta: cuarto mensaje distinto,
  nombrando los formatos admitidos. **Es una enmienda a un requisito y ya bajó a `proposal.md`**
  (R5.6, con su nota de gate); aquí está recogida en D11.
- **OQ4 — Supuesta frase truncada en *Coordinación* del proposal.** **Retirada: no existe.** El
  párrafo está entero (`…comparten árbol en 'frontend/locales/*/' y potencialmente en
  'frontend/features/incidents/'. Merece una comprobación de conflictos al abrir el PR, no una
  dependencia declarada.`). La truncación era del filtro de `rtk` sobre la lectura del fichero, no
  del documento. No se tocó nada.
