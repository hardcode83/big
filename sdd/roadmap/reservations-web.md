# reservations-web

[FE] **la primera pantalla real de reservas: lista y detalle, sólo lectura**, consumiendo `GET /api/v1/reservations` y `GET /api/v1/reservations/{id}` desde el frontend. La ruta ya existe en el shell pero no muestra datos: `frontend/app/(workspace)/reservations/page.tsx` renderiza `RoutePlaceholder routeId="reservations"`, igual que las demás rutas sin contenido.

## Alcance, y lo que queda deliberadamente fuera

**Dentro**: listado paginado con los filtros que el endpoint ya acepta, detalle de una reserva, y los estados de carga, error y vacío que el resto del frontend ya tiene resueltos.

**Fuera, aunque la API lo sirva hoy**: `POST /api/v1/reservations` (alta manual), `PATCH /api/v1/reservations/{id}` (edición) y `DELETE /api/v1/reservations/{id}` (cancelación) existen en el contrato —`backend/openapi.json`, y por tanto en el cliente tipado— pero **no** tienen UI aquí. Tampoco entra ninguna integración con un PMS real: lo que se pinta es lo que el backend ya tiene almacenado, venga de donde venga (`MockPMSAdapter`, import CSV, webhooks o el adapter de Beds24). Escribir y cancelar desde la web es una decisión de producto con su propia superficie de confirmación y de auditoría, y colgarla de aquí convertiría una entrada `S` en otra cosa.

## Por qué depende de lo que depende

- **`needs: reservations`** — es quien entrega los dos endpoints que esto consume. Ya está archivada (`changes/archive/2026-07-31-reservations/`), así que la dependencia está satisfecha y esta entrada es atacable.
- **`needs: frontend-auth-session`** — ambos endpoints son del tenant autenticado, y quien pone el token en las llamadas es la sesión del frontend. Archivada el 2026-08-08. Es la misma razón por la que `dashboard-web` la declaró.

No declara `needs: api-ingress-routing` porque esa dependencia ya la absorbió `frontend-auth-session`, que es quien la arrastra.

## El contrato ya está congelado y el cliente tipado ya lo conoce

No hay nada que negociar al llegar, y esto es lo que baja la entrada a `size: S`:

- **Lista** — `GET /api/v1/reservations` acepta `page` (≥1), `per_page` (1..100, por defecto 20), `property_id`, `status`, `date_from` y `date_to`. Devuelve `ReservationPageResponse`, que la propia spec del schema describe como *«el sobre de paginación de PRD §23, verbatim»*: `{data, page, per_page, total, total_pages}`. **No es un sobre `meta` anidado** — quien asuma la forma de otro módulo sin mirar se equivocará.
- **Detalle** — `GET /api/v1/reservations/{reservation_id}` devuelve `ReservationDetailResponse`, que es `ReservationResponse` **más** `guest` (`GuestSummaryResponse`, **anulable**: hay reservas sin huésped enlazado, así que el detalle tiene que renderizar ese caso y no asumirlo presente).
- **Estados** — `ReservationStatus` tiene siete valores: `PENDING`, `CONFIRMED`, `CANCELLED`, `CHECKED_IN_ESTIMATED`, `CHECKED_OUT_ESTIMATED`, `COMPLETED`, `NO_SHOW`. Los siete necesitan etiqueta en ES y EN; no hay «los tres de siempre».
- **Tipos** — `frontend/lib/api/generated/openapi.d.ts:448-475` ya declara las cuatro operaciones de ambas rutas. El fichero se genera desde `backend/openapi.json` (`frontend/scripts/generate-api-types.mjs`) y la CI lo verifica, así que **no hay que escribir tipos a mano ni regenerar nada**: los endpoints ya están ahí porque `reservations` está archivada.

## PII: es lo único de esta entrada que no es rutinario

`GuestSummaryResponse` trae `full_name`, `email`, `phone`, `preferred_language`, `document_status` y `legal_registration_status`. `steering/security.md` clasifica la PII de huéspedes como dato sensible, así que pintarla en pantalla es una decisión, no un detalle de maquetación. Dos observaciones que conviene heredar y no volver a derivar:

1. **El payload NO incluye número de documento ni fecha de nacimiento** — eso vive en `GuestDocumentResponse`, que es otro schema y otra ruta. El detalle de reserva no lo expone, y este change **no debe** ir a buscarlo para «completar la ficha».
2. **`internal_notes` y `special_requests` son texto libre de terceros.** `steering/security.md` ya documenta esta clase tres veces sobre otras columnas (`properties.access_notes`, aprobaciones, mensajería): la columna no es un sitio seguro para PII, y lo que un huésped o una propietaria escriben ahí se le enseña al operador tal cual. Aquí eso se traduce en dos obligaciones concretas: renderizar como texto, nunca como HTML, y decidir explícitamente si `internal_notes` se muestra en una pantalla que puede tener delante alguien que no sea el manager.

## Precedente directo que hay que seguir, no reinventar

`dashboard-web` (archivada el 2026-08-11) ya recorrió exactamente este camino y dejó la costura montada en `frontend/features/dashboard/data/`: `dto.ts` que replica el contrato de PRD §23, `boundary.test.ts` que vigila la frontera, `dashboard-source.ts` como interfaz y `http/` como implementación real. La diferencia —y es lo que hace esta entrada más barata que aquella— es que **aquí no hay mock previo que sustituir ni UI previa que respetar**: se va directo a HTTP contra `lib/api`, sin la indirección `Mock*Source` que allí existía sólo porque la UI se adelantó al backend. Replicar esa indirección «por simetría» sería añadir una capa sin el problema que la justificaba.

De `steering/frontend.md` aplican sin excepción: server state con TanStack Query v5 con clave por recurso+tenant, Zustand sólo para estado ligero de UI, y **cada string en `locales/es` y `locales/en`**, nada hardcodeado — incluidas las siete etiquetas de estado y los textos de los estados vacío y de error.

## Trabajo de shell que la ruta de detalle arrastra

La lista ya está registrada (`frontend/features/shell/navigation/route-registry.ts:125-135`: `pattern: "/reservations"`, `match: "exact"`, `navigationGroup: "work"`, `order: 1`) y sus claves i18n existen en `locales/{es,en}/navigation.json` (`routes.reservations.title` / `.description`, que ya dicen «Listado y detalle de reservas» — es decir, el registro ya prometía esta entrada).

**La ruta de detalle no existe todavía** y hay que darla de alta imitando `property-detail` (`route-registry.ts:114-122`), que es el único precedente de ruta de detalle en el registro: `pattern: "/properties/[id]"`, `match: "exact"`, **sin `href` y sin `navigationGroup`** —no aparece en la navegación— y con `breadcrumbKeys: crumbs("properties", "property-detail")`. Eso implica un `id` nuevo (`reservation-detail`) con sus claves `routes.reservation-detail.title` / `.description` en los dos locales; `route-registry.test.ts`, `route-metadata.test.ts` y `breadcrumbs.test.ts` cubren ese registro, así que el olvido de cualquiera de las dos piezas sale en rojo en la suite y no hace falta vigilarlo a mano.
