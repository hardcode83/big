# Design: reservations-web

## Context

El frontend ya tiene la ruta `/reservations` registrada en el shell (`route-registry.ts:125-135`) y sus claves i18n en `locales/{es,en}/navigation.json` (`routes.reservations.title` / `.description`), pero la página renderiza `RoutePlaceholder routeId="reservations"`. El cliente HTTP tipado del frontend ya conoce los cuatro endpoints de `/api/v1/reservations` (`openapi.d.ts:448-475`); no hay que regenerar nada ni negociar contrato. La sesión autenticada viene de `frontend-auth-session` archivado, y la frontera de paginación `{data, page, per_page, total, total_pages}` ya está estandarizada por `frontend/features/dashboard/data/http/http-dashboard-source.ts:34-51` — el precedent más directo a copiar.

El backend ya tiene `reservations` archivado, y la spec del backend (`specs/reservations.md`) fija el contrato que este change consume tal cual, sin renegociar formas.

## Decisions

### D1 — Sin seam `ReservationsDataSource`: el factory exporta directamente `HttpReservationsSource`

**Chosen:** `frontend/features/reservations/data/index.ts` exporta `getReservationsDataSource()` que devuelve un singleton `HttpReservationsSource` (no una interfaz), construido contra el `ApiClient` autenticado, igual que el composition point del dashboard (`features/dashboard/data/index.ts`).

**Why:** El precedent de `dashboard-web.md` lo discute y descarta para este caso: *"aquí no hay mock previo que sustituir ni UI previa que respetar: se va directo a HTTP contra `lib/api`, sin la indirección `Mock*Source` que allí existía sólo porque la UI se adelantó al backend"*. Mantener la indirección cuando no hay mock que preservar solo añadiría una capa sin el problema que la justificaba. Las pruebas unitarias del source usan `vi.fn().mockResolvedValue(...)` contra `ApiClient`, igual que `http-dashboard-source.test.ts`, sin necesidad de un mock por encima.

**Rejected:**
- *Interfaz `ReservationsDataSource` + `HttpReservationsSource` + `MockReservationsSource`* — es el patrón de `dashboard-web`, pero aquí no hay UI preexistente que dependa de la interfaz; añadirla solo mueve la frontera sin beneficiario.
- *Llamar `ApiClient.request` directamente desde los hooks* — pierde el composition point único (los tests del source son la única forma de fijar el contrato HTTP sin levantar la suite del navegador, y necesitan un `ApiClient` que poder mockear a nivel de método).

### D2 — Un único fichero de locale nuevo: `reservations.json`

**Chosen:** Crear `frontend/locales/{es,en}/reservations.json` con dos secciones: `status` (las siete etiquetas de `ReservationStatus`) y `fields` (etiquetas de columnas y campos del detalle). Reutilizar `frontend/locales/{es,en}/states.json` para los textos comunes de carga/error/vacío que ya existen.

**Why:** Las dos secciones son específicas de esta capacidad — no las reutiliza otra feature — y mezclarlas en `states.json` o en `dashboard.json` haría que un futuro cambio de etiquetas aquí obligara a tocar un fichero que también mira el resto del workspace. `dashboard.json` ya contiene `card.reservation` con un sentido distinto (es la etiqueta de la card del dashboard, no del detalle) y no es razonable ampliarlo. Los textos de carga/error/vacío **no** se duplican: `states.json` ya provee `loading.label`, `error.title`, `error.description`, `error.retry`, `empty.title`, `empty.description`, y eso es exactamente lo que R2.4 y R3 piden.

**Rejected:**
- *Reutilizar `dashboard.json`* — sus claves son del dashboard agregado (`propertyCode`, `operationalState`), no de la pantalla de reservas. Mezclar dominios invita a renombrados al cruzar.
- *Un fichero por requisito (lista/detail/status/fields)* — cuatro ficheros para una entrada `size: S` es ceremonia.

### D3 — DTOs `camelCase` con un mapper snake_case → camelCase, sin genérico de sobre

**Chosen:** Modelar `ReservationSummaryDto` y `ReservationDetailDto` (camelCase) como tipos UI, y mapear los responses de la API con funciones explícitas — un `mapReservationSummary`, un `mapReservationDetail`, un `mapGuestSummary` — siguiendo el precedent de `http-dashboard-source.ts:53-142`. El `ReservationPageResponse<T>` (sobre genérico `{data, page, per_page, total, total_pages}`) se tipifica con el DTO de summary dentro; el DTO de detalle **no** se mete en el sobre, sólo en el método del source que devuelve un único objeto.

**Why:** El codebase ya estandariza dos cosas: (a) los DTOs UI son camelCase y el resto del frontend los consume así; (b) los mappers son funciones nombradas en `http-*-source.ts` y no `pick`/`omit` dinámicos. Reutilizar el shape del sobre del dashboard tiene un límite: el detalle no es paginado, así que mezclarlo bajo el mismo genérico (`PaginatedResponse<ReservationDetailDto>`) es mentira estructural.

**Rejected:**
- *Devolver directamente los tipos `components["schemas"][...]`* — pierde la frontera de PII de R3.4 y la normalización a `camelCase`; los componentes quedarían filtrándose capa a capa hasta los componentes de presentación.
- *Un `PaginatedResponse<T>` genérico reutilizado del dashboard* — exportable, pero el detalle rompe la homogeneidad: no es un sobre. Mejor un tipo local `ReservationList` que un genérico mal aplicado.

### D4 — Filtros v1: `status` (enum tipado), `date_from`/`date_to` (YYYY-MM-DD civil), sin `property_id`; la query key recibe el objeto de filtros normalizado

**Chosen:** La query del hook `useReservations` admite en v1 `{ status?: ReservationStatus; dateFrom?: string; dateTo?: string; page?: number; perPage?: number }` en camelCase UI. **`propertyId` no se expone en v1**: añadir ese filtro exigiría un selector de propiedad (cuyas propiedades hay que listar desde `/api/v1/properties`, lo que o vuelve a la entrada `M`/`L` por el selector, o pide al usuario pegar un UUID a mano, que no es UI). El endpoint del backend sigue aceptando `property_id` —sólo no se le envía desde esta pantalla—. Las fechas se envían y reciben como **fecha civil `YYYY-MM-DD`**, sin conversión de zona horaria en ninguna dirección: lo que el usuario teclea es lo que viaja al backend, y lo que el backend devuelve en `check_in_date`/`check_out_date` se pinta tal cual, sin restar ni sumar nada. `ReservationStatus` se mantiene como enum del `openapi.d.ts`, de modo que un valor no enumerado falle en `tsc` antes de llegar a runtime.

La query key del listado se construye como `reservationsKeys.list(tenantId, filters)` pasando el **objeto de filtros normalizado directamente** como último segmento (precedent: `dashboardKeys.propertyTimeline(tenantId, propertyId, filters)` en `frontend/features/dashboard/hooks/query-keys.ts:18-22` — recibe el objeto entero, no un `JSON.stringify`). El objeto se construye una sola vez por render con sus claves en un orden estable, así dos renders con los mismos filtros producen la misma key y TanStack Query no invalida.

**Why:** La regla «enviar `YYYY-MM-DD` como fecha civil» es la única que cuadra la API ya tipada con lo que la UI produce: `date_from`/`date_to` son `format: date` en el OpenAPI (string ISO `YYYY-MM-DD`), el backend trabaja en UTC y devuelve estancias por solape, y mostrar al usuario la fecha que él tecleó elimina la sorpresa del día siguiente tras medianoche en otra zona. Convertir a local implicaría asumir una zona por defecto, que es una decisión de UX-política, no de esta entrada. La query key como objeto directo evita dos trampas: (a) `JSON.stringify` no es estable frente al orden de claves de un objeto literal TS, así que dos renders con `filters` equivalentes pero construidos en orden distinto generarían keys distintas y duplicarían cache; (b) un comparador a mano duplica la lógica de igualdad que TanStack Query ya hace con `deepEqual` sobre la parte serializada. El `tenantScopedKey` del shell (`lib/query/query-keys.ts`) ya aísla la cache por tenant, así que el último segmento puede ser el objeto entero sin riesgo cross-tenant. La razón para no exponer `property_id` en v1 no es técnica (el endpoint lo acepta), es de scope: el selector de propiedad abre un combo/async que duplica `usePropertiesList`, y eso vuelve a entrar en la decisión de «esta entrada es `size: S`». Cuando llegue el momento, una entrada propia con su design lo añade.

**Rejected:**
- *Aceptar `status: string` libre* — pierde el guard de tipos del proposal R2.6 y abre la puerta a que un estado renombrado rompa en runtime.
- *Exponer `propertyId` en v1 con un selector* — multiplica la entrada por 2-3: fetch de propiedades, estado del selector, deep-linking de la selección. Rompe `size: S`.
- *Pedir al usuario pegar un UUID a mano* — no es UI; es depuración.
- *`JSON.stringify(filters)` para la query key* — `JSON.stringify({a:1,b:2}) !== JSON.stringify({b:2,a:1})` en algunas plataformas, y los filters se construyen desde varios sitios (URL, estado, defaults) donde el orden de claves puede divergir.
- *Convertir fechas a la zona local del usuario antes de enviarlas* — implica asumir una zona por defecto (la del navegador, en el mejor caso) y es una decisión de UX-política que el proposal no toma.
- *Validar `propertyId` con un `Zod` schema en runtime* — el tipado estático ya cubre lo que se decide tipar (R2.6 sobre `status`); un `Zod` paralelo duplica la fuente de verdad sin añadir cobertura que el backend no dé ya vía `404`.

### D5 — Columnas mínimas de la lista; el resto va al detalle

**Chosen:** La tabla de `/reservations` muestra, y solo estas, en este orden: **huésped** (cuando `guestId` no sea nulo y el detalle del huésped esté disponible, con fallback a `«—»` o al `id` interno si no), **propiedad** (mostrando la `propertyId` como referencia identificable, sin nombre —el endpoint de lista no devuelve nombre de propiedad, sólo el id—), **check-in / check-out** (las dos fechas en la misma columna, en `YYYY-MM-DD` civil), **estado** (etiqueta localizada del enum, R4), **canal** (`channel`: `MANUAL`, `DIRECT`, `BOOKING`, `AIRBNB`…) e **importe** (`grossAmount` formateado con la `currency` de la reserva). El resto de campos del detalle —`checkInTime`, `checkOutTime`, `adults`, `children`, `nights`, `otaCommission`, `netAmount`, `paymentStatus`, `cleaningRequired`, `accessStatus`, `internalNotes`, `specialRequests`, `createdAt`, `updatedAt` y el bloque `guest` completo— se reservan al detalle y **no** se renderizan en la tabla, ni como columna secundaria ni como expansión de fila.

**Why:** El endpoint de lista no devuelve nombre de propiedad ni bloque `guest`; pintar la `propertyId` en la columna «propiedad» es la única información que la lista tiene, y fingir un nombre con un fetch extra por reserva vuelve a la entrada `M`. El huésped puede llegar sin `guestId` (importaciones CSV, canales OTA sin huésped todavía enlazado), así que el componente trata ese caso explícitamente en lugar de fallar al renderizar. La densidad de la tabla es lo que la hace útil en una pantalla de operaciones: si la tabla replica el detalle deja de ser tabla. Y el `nights` se calcula de las dos fechas, así que pintarlo separado en la lista es redundancia; en el detalle sí tiene valor.

**Rejected:**
- *Mostrar todas las 25 columnas* — la lista deja de ser lista, se vuelve un detalle horizontal.
- *Hacer fetch de la propiedad por cada fila para sacar el nombre* — convierte la pantalla `size: S` en una que no entra en el change, y mete latencia de N peticiones por carga.
- *Expandir la fila al click para mostrar campos extra* — duplica la ruta `/reservations/[id]` sin ganar nada que el detalle no dé ya; el comportamiento canónico es navegar al detalle, que es deep-linkable.
- *Ampliar a `/properties` o `/dashboard/properties` para conseguir el nombre* — fuera de scope, requiere aprobación explícita.

### D6 — Ruta de detalle sin `href` ni `navigationGroup`, y la lista de PRD §24 se queda como está

**Chosen:** Añadir el descriptor de `reservation-detail` en `route-registry.ts` con `pattern: "/reservations/[id]"`, `match: "exact"`, **sin** `href` y **sin** `navigationGroup` — replicando `property-detail` (`route-registry.ts:114-122`). Las claves `routes.reservation-detail.{title,description}` se crean en los dos locales, y la lista `PRD_24_SURFACES` de `route-registry.test.ts` se queda como está: ya contiene `/reservations` y eso es lo que verifica, no contiene `/properties/[id]`-con-id- concreto ni lo va a contener el nuevo id — la lista es de **superficies** de navegación, no de patterns.

**Why:** Replicar `property-detail` evita tres regresiones a la vez (las suites de `route-registry`, `route-metadata` y `breadcrumbs` cubren el contrato, y un descriptor mal formado las pone en rojo). Modificar la lista de superficies para añadir `/reservations/[id]` la desincronizaría del precedent `/properties/[id]`, que tampoco aparece como superficie con id — la suite prueba la ruta padre, no la hija parametrizada.

**Rejected:**
- *Añadir `/reservations/[id]` a `PRD_24_SURFACES`* — introduce una inconsistencia con `properties`, que tampoco está.
- *Poner `navigationGroup` y `href` en la ruta de detalle* — la haría aparecer en la barra lateral, que no es lo que la spec pide ni lo que `property-detail` hace.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Shell | `frontend/features/shell/navigation/route-registry.ts` | Add `reservation-detail` descriptor. |
| Locales (nav) | `frontend/locales/{es,en}/navigation.json` | Add `routes.reservation-detail.{title,description}`. |
| Locales (feature) | `frontend/locales/{es,en}/reservations.json` | New file: `status` (7 keys) + `fields` (column/detail labels). |
| Data | `frontend/features/reservations/data/index.ts` | New: composition point exporting `getReservationsDataSource()`. |
| Data | `frontend/features/reservations/data/dto.ts` | New: `ReservationSummaryDto`, `ReservationDetailDto`, `GuestSummaryDto`, `ReservationList`, `ReservationStatus` (re-export from openapi), `ReservationFilters`. |
| Data | `frontend/features/reservations/data/http/http-reservations-source.ts` | New: `HttpReservationsSource` with `listReservations` and `getReservation`, plus `mapReservationSummary`, `mapReservationDetail`, `mapGuestSummary`. |
| Data | `frontend/features/reservations/data/http/http-reservations-source.test.ts` | New: unit tests for the two methods (mappers + paths). |
| Hooks | `frontend/features/reservations/hooks/query-keys.ts` | New: `reservationsKeys` (list, detail) using `tenantScopedKey`. |
| Hooks | `frontend/features/reservations/hooks/use-reservations.ts` | New: `useReservations(filters)` and `useReservation(id)` with `retry` policy from `use-dashboard-data.ts:35-40`. |
| Hooks | `frontend/features/reservations/hooks/use-reservations.test.tsx` | New: hook tests against a mocked `HttpReservationsSource` (or a fake inline). |
| Components | `frontend/features/reservations/components/list/reservations-view.tsx` | New: client view that consumes `useReservations`, renders tabla con paginación y estado vacío/error. |
| Components | `frontend/features/reservations/components/list/reservations-view.test.tsx` | New: render tests (loading / loaded / empty / error). |
| Components | `frontend/features/reservations/components/list/reservations-filters.tsx` | New: filtros (`status`, `dateFrom`, `dateTo`) con control tipado. Sin `propertyId` en v1 (D4). |
| Components | `frontend/features/reservations/components/list/reservations-filters.test.tsx` | New: tests del comportamiento del filtro. |
| Components | `frontend/features/reservations/components/detail/reservation-detail-view.tsx` | New: client view que consume `useReservation(id)`, renderiza todos los campos y trata `guest === null`. |
| Components | `frontend/features/reservations/components/detail/reservation-detail-view.test.tsx` | New: tests (loading / loaded / not-found / error / guest null). |
| Components | `frontend/features/reservations/components/detail/reservation-detail-sections.tsx` | New: bloques reutilizables del detalle (cabecera, huésped, finanzas, notas). |
| Components | `frontend/features/reservations/index.ts` | New: barrel export. |
| Pages | `frontend/app/(workspace)/reservations/page.tsx` | Replace placeholder with the list view. |
| Pages | `frontend/app/(workspace)/reservations/[id]/page.tsx` | New: detail page that calls `routeMetadata('reservation-detail')` and renders `<ReservationDetailView reservationId={id} />`. |

## Data & interfaces

**Sin cambios de schema, sin migraciones, sin variables de entorno.** Todo el contrato ya existe en `backend/openapi.json:10713-11058`.

**API consumida (read-only, ya tipada):**
- `GET /api/v1/reservations?page&per_page&property_id&status&date_from&date_to` → `ReservationPageResponse` (snake_case en sobre, con DTOs snake_case dentro).
- `GET /api/v1/reservations/{reservation_id}` → `ReservationDetailResponse`.

**DTOs UI (camelCase, exportados desde `features/reservations/data/dto.ts`):**
- `ReservationStatus` — re-export del enum generado, las 7 constantes literales.
- `GuestSummaryDto` — `{ id, fullName, email, phone, preferredLanguage, documentStatus, legalRegistrationStatus }`.
- `ReservationSummaryDto` — `{ id, propertyId, status, checkInDate, checkOutDate, nights, totalGuests, guestId, channel, currency, grossAmount, paymentStatus }` (subset del detalle para la tabla; el detalle carga el resto).
- `ReservationDetailDto` — extiende summary con `checkInTime`, `checkOutTime`, `adults`, `children`, `otaCommission`, `netAmount`, `cleaningRequired`, `accessStatus`, `externalChannelId`, `externalPmsId`, `internalNotes`, `specialRequests`, `createdAt`, `updatedAt`, `guest: GuestSummaryDto | null`.
- `ReservationList` — `{ data: ReservationSummaryDto[]; page: number; perPage: number; total: number; totalPages: number }` (mismo sobre que el backend, renombrado a camelCase en la frontera).
- `ReservationFilters` — `{ status?: ReservationStatus; dateFrom?: string; dateTo?: string; page?: number; perPage?: number }` (v1, sin `propertyId` por D4).

**Errores relevantes** (de `lib/api/errors.ts`): `ApiError` con `status` 401, 403, 404, 422, 5xx. Mapeo a UI ya está en R3.5 y R5.4.

## Risks & mitigations

- **Riesgo: la PII del huésped se filtra a un log o a un componente que no la espera.** Mitigación: el mapper `mapGuestSummary` enumera los campos explícitamente — un `GuestSummaryResponse` que mañana gane un campo no se filtra automáticamente. La `boundary.test` (`http-reservations-source.test.ts`) fija el sobre de salida.
- **Riesgo: la pantalla de detalle intenta mostrar `internal_notes`/`special_requests` como HTML por accidente.** Mitigación: el componente `ReservationDetailSections` los pinta con un wrapper que renderiza sólo `{value}` (texto plano), nunca `dangerouslySetInnerHTML`. Los tests del componente verifican que el valor se renderiza como texto aunque contenga `<script>`.
- **Riesgo: la query key del listado no incluye los filtros, así que cambiar de página en la misma vista reusa la respuesta cacheada de otra página.** Mitigación: `reservationsKeys.list(tenantId, filters)` recibe el **objeto de filtros normalizado** directamente como parte de la key (D4; precedent: `dashboardKeys.propertyTimeline(tenantId, propertyId, filters)` en `query-keys.ts:18-22`). El objeto se construye con sus claves en orden estable, no se serializa con `JSON.stringify`.
- **Riesgo: `status` enviado como string libre pasa el typecheck pero la API devuelve 422.** Mitigación parcial por R2.6 (tipo `ReservationStatus`); el resto se cubre con el test de mapper, que verifica que un `ReservationStatus` se serializa al nombre exacto del enum del backend.
- **Riesgo: el `ApiError 404` del detalle entra por la rama genérica de error y oculta la distinción que pide R3.5.** Mitigación: el componente distingue `404` por `instanceof ApiError && status === 404`; un test cubre el caso.
- **Riesgo: regenerar `openapi.d.ts` en otro change futuro introduce un campo nuevo en `ReservationDetailResponse` que no aparece en el mapper.** Mitigación: el mapper enumera campos explícitamente (D3), así que un campo nuevo es invisible al UI hasta que se mapee — exactamente el comportamiento que el precedent de `properties-crud` demostró necesario. No es un riesgo nuevo ni específico de este change.

## Open questions

*(Resueltas durante el gate de design, **2026-08-17**:*

- *Filtros de fecha y zona horaria → fechas civiles `YYYY-MM-DD`, sin conversión local, D4.*
- *Estabilidad de la query key con filtros → objeto normalizado directo en la key, sin `JSON.stringify`, D4.*
- *Origen del filtro `property_id` → no se expone en v1, queda para una entrada propia con su design, D4.*
- *Afirmación de tipado UUID en compile time → rectificada: `string` no es UUID, sólo `ReservationStatus` se mantiene como enum, D4.*
- *Densidad de la tabla y columnas mínimas → huésped (cuando exista), propiedad, check-in/check-out, estado, canal, importe; el resto al detalle, D5.*

*No queda ninguna abierta para `tasks.md`: la entrada puede pasar a tareas sin más gates.)*
