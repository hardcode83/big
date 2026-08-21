# Proposal: reservations-web

## Why

La ruta `/reservations` existe en el frontend desde `frontend-foundation` pero renderiza un `RoutePlaceholder`: es la única ruta del workspace apuntada por el roadmap que no pinta datos. El backend ya expone los dos endpoints necesarios (`GET /api/v1/reservations` y `GET /api/v1/reservations/{id}`) y el cliente tipado del frontend los conoce desde que `api-contract-export` y `frontend-api-contract-consumer` se archivaron, así que la negociación de formas ya está hecha. Esta entrada cierra la primera pantalla de reservas con la única forma que admite el roadmap hoy: **lista + detalle, sólo lectura**, sin escritura ni cancelación desde la web.

El plan acordado limita el alcance a la consulta: el backend ya expone `POST`, `PATCH` y `DELETE` en su contrato, y este change **no** los consumirá desde la web —escribir o cancelar es una decisión de producto con su propia superficie de confirmación y de auditoría, y acoplarla a esta entrada la convertiría en algo distinto de `size: S`.

## What changes

Existirá una pantalla `/reservations` con listado paginado y filtrable, y una pantalla `/reservations/[id]` con el detalle de una reserva, ambas consumiendo los dos endpoints de lectura con el cliente HTTP centralizado (`lib/api`) y TanStack Query. La ruta de detalle se dará de alta en el registro de navegación con la misma forma que `property-detail` (sin `href`, sin `navigationGroup`, `match: "exact"` y las claves i18n en ES/EN), y sus siete valores de `ReservationStatus` se expondrán con etiqueta localizada. El shell del workspace no cambia: las claves de `routes.reservations.{title,description}` ya estaban y ya prometen «Listado y detalle de reservas». La sesión autenticada viene de `frontend-auth-session`, y la autorización RBAC del backend es quien realmente decide a qué datos llega cada usuario.

## Requirements

### R1 — Shell: ruta `/reservations` y registro de la ruta de detalle

**As a** usuario autenticado del workspace, **I want** que `/reservations` muestre contenido y que `/reservations/[id]` exista como destino navegable, **so that** la primera entrada del roadmap sin contenido quede resuelta y el flujo lista → detalle sea profundo-enlaceable.

Acceptance criteria:

1. WHEN se navega a `/reservations`, THE SYSTEM SHALL mostrar el listado de reservas (R2) en lugar de un `RoutePlaceholder`.
2. THE SYSTEM SHALL registrar `reservation-detail` en `frontend/features/shell/navigation/route-registry.ts` con `pattern: "/reservations/[id]"`, `match: "exact"`, **sin** `href` y **sin** `navigationGroup` —no aparece en la barra lateral—, y `breadcrumbKeys: crumbs("reservations", "reservation-detail")`, replicando la forma de `property-detail` (`route-registry.ts:114-122`).
3. THE SYSTEM SHALL crear las claves `routes.reservation-detail.title` y `routes.reservation-detail.description` en `frontend/locales/{es,en}/navigation.json`, **sin** hardcodear la cadena en ningún componente.
4. WHEN se navega a `/reservations/[id]` con un `id` válido del tenant, THE SYSTEM SHALL mostrar el detalle (R3).

### R2 — Listado paginado y filtrable en `/reservations`

**As a** manager del workspace, **I want** ver y paginar las reservas del tenant con filtros por propiedad, estado y rango de fechas, **so that** la lista deje de ser un placeholder y refleje lo que el backend ya sirve.

Acceptance criteria:

1. WHEN `/reservations` se monta autenticado, THE SYSTEM SHALL llamar a `GET /api/v1/reservations` con el `tenantId` implícito en el token y renderizar la respuesta.
2. THE SYSTEM SHALL pasar al endpoint, cuando la UI los exponga, los parámetros de filtro que correspondan: en v1, `status`, `date_from` y `date_to`, además de `page` y `per_page`; SHALL **no** pasar `property_id` desde esta pantalla —queda fuera del alcance de v1, se documenta en `design.md` D4 y se añadirá en una entrada propia cuando toque—. Los nombres de parámetro y los tipos que acepta el endpoint son los ya declarados en `frontend/lib/api/generated/openapi.d.ts:448-475` (PRD §23).
3. THE SYSTEM SHALL consumir el sobre `ReservationPageResponse` —`{data, page, per_page, total, total_pages}` de PRD §23— y SHALL **no** asumir la forma `{data, meta}` que otros módulos del frontend puedan usar; la adaptación concreta del cliente HTTP a ese sobre queda para `design.md`.
4. WHEN la lista carga, THE SYSTEM SHALL mostrar el estado de carga; WHEN la llamada falla, THE SYSTEM SHALL mostrar un error localizado; WHEN el sobre llega con `data` vacío, THE SYSTEM SHALL mostrar un estado vacío localizado —los tres estados ya tienen precedente en el resto del frontend.
5. THE SYSTEM SHALL permitir al usuario avanzar y retroceder de página usando `page` y `per_page`, y SHALL deshabilitar los controles en el extremo correspondiente cuando `page = 1` o `page = total_pages`.
6. THE SYSTEM SHALL pasar `status` como enum tipado (`ReservationStatus` del `openapi.d.ts`), **no** como cadena suelta, para que un valor inválido del lado de la UI falle en la compilación y no en runtime. `property_id` queda fuera de v1 por decisión de scope (ver `design.md` D4) y, por tanto, no aplica este requisito a ese parámetro.

### R3 — Detalle de una reserva en `/reservations/[id]`

**As a** manager del workspace, **I want** abrir una reserva por su enlace y ver todos sus campos con su huésped vinculado si existe, **so that** la consulta puntual desde notificaciones, líneas de timeline o deep links externos sea posible sin volver a la lista.

Acceptance criteria:

1. WHEN se navega a `/reservations/[id]` con un id del tenant, THE SYSTEM SHALL llamar a `GET /api/v1/reservations/{id}` y SHALL renderizar `ReservationDetailResponse`.
2. THE SYSTEM SHALL mostrar los campos de la reserva, **incluido** el bloque `guest` (`GuestSummaryResponse`) cuando venga no nulo, y SHALL mostrar un estado explícito y localizado cuando `guest` sea `null` — el schema lo declara anulable y omitir el caso rompe reservas importadas con huésped todavía sin enlazar.
3. THE SYSTEM SHALL mostrar `internal_notes` y `special_requests` como **texto plano**, nunca como HTML: ambas columnas son texto libre de terceros y `steering/security.md` ya documenta tres veces esta misma clase de riesgo.
4. THE SYSTEM SHALL **no** pedir, ni consultar por su cuenta, ni mostrar `document_number`, `date_of_birth`, `document_expiry_date` ni `nationality`: el schema de detalle no los expone, y este change no debe salir a buscarlos para "completar la ficha".
5. WHEN la carga falla por `404`, THE SYSTEM SHALL mostrar un estado localizado de "no encontrado" **distinto** del error genérico; WHEN falla por `401`/`403`/`5xx`, SHALL mostrar el estado de error genérico localizado.

### R4 — Estados de reserva etiquetados en los dos locales

**As a** manager, **I want** que los siete valores de `ReservationStatus` se muestren con etiqueta en mi idioma, **so that** el estado real de cada reserva sea legible y no dependa de traducir la constante a mano.

Acceptance criteria:

1. THE SYSTEM SHALL localizar las siete etiquetas: `PENDING`, `CONFIRMED`, `CANCELLED`, `CHECKED_IN_ESTIMATED`, `CHECKED_OUT_ESTIMATED`, `COMPLETED`, `NO_SHOW`.
2. THE SYSTEM SHALL definir las claves en `frontend/locales/es/reservations.json` y `frontend/locales/en/reservations.json` y SHALL usarlas desde el componente, sin string hardcodeado.
3. THE SYSTEM SHALL aplicar la misma etiqueta localizada tanto en la columna de estado de la lista como en la cabecera del detalle.

### R5 — i18n, errores HTTP y patrones del frontend

**As a** mantenedor, **I want** que esta entrada cumpla las reglas de `steering/frontend.md` sin excepciones, **so that** el panel de revisión no la devuelva por defectos ya conocidos.

Acceptance criteria:

1. THE SYSTEM SHALL mantener server state con TanStack Query v5, con una clave por recurso que incluya el `tenantId`, y SHALL **no** duplicar server state en Zustand u otro store.
2. THE SYSTEM SHALL **no** contener ningún string de UI en código: todo vive en `frontend/locales/{es,en}/`, y SHALL cubrir al menos los títulos, descripciones, etiquetas de estado, textos de carga/errores/vacío, cabeceras de tabla y nombres de campos mostrados.
3. THE SYSTEM SHALL usar el cliente HTTP centralizado (`lib/api`) para las dos llamadas autenticadas; SHALL **no** usar `fetch` directo.
4. THE SYSTEM SHALL distinguir los códigos de error del backend al menos para los casos usados por la UI: `401` (sesión expirada, gestiona `frontend-auth-session`), `403` (sin permiso, error localizado), `404` (R3.5), `422` (validación: muestra el mensaje del envelope de PRD §23) y `5xx` (error genérico).
5. THE SYSTEM SHALL añadir tests de componente con Testing Library para la lista y el detalle, cubriendo al menos: render del estado de carga, render del sobre con datos, render del estado vacío, render del error, y navegación a detalle.

## Out of scope

- **Alta manual desde la web** (`POST /api/v1/reservations`). El endpoint existe; una pantalla de alta con su flujo de confirmación, validación y auditoría es una entrada propia y más grande que `S`.
- **Edición y cancelación desde la web** (`PATCH` y `DELETE /api/v1/reservations/{id}`). Mismo motivo, más el matiz de que cancelar dispara transiciones de timeline y notificaciones que se decida caso por caso.
- **Cualquier integración con un PMS real** desde la web. Lo que se pinta es lo que el backend ya tiene; Beds24, Channex, webhooks e import CSV son historia de `reservations`/`pms-beds24-adapter` y se muestran aquí, no se invocan.
- **Acciones masivas** (selección múltiple, exportación a CSV, cambios en lote). No son read-only y no aportan a la primera pantalla.
- **Notificaciones en tiempo real** de cambios en una reserva. La pantalla se vuelve a leer al revalidar; un canal en vivo es otra capacidad.
- **Dashboard agregado** sobre reservas (KPIs, gráficos, tendencias). Pertenece a la familia de `dashboard-api`/`dashboard-web`, no aquí.

## Affected specs

- **`sdd/specs/reservations.md`** — esta capacidad ya está documentada. Este change **no la modifica** (acuerdo explícito: el contrato del backend y la spec de la capacidad no entran en este diff). La nota de la entrada en el roadmap ya explica que el alcance de la spec del backend no se reabre.
- **`sdd/specs/frontend-auth-session.md`** — no se modifica. Se consume tal cual está: tokens en memoria, `AuthGuard` sobre la ruta workspace y refresh coordinado por el cliente HTTP. Cualquier cambio a esa superficie (p. ej. sobrevivir a un reload) es una entrada propia.
- **`sdd/specs/frontend-api-contract-consumer.md`** — no se modifica. El cliente tipado ya incluye los cuatro endpoints de `/reservations` y la regeneración se hace en el cambio de backend que los haya añadido, no aquí.
