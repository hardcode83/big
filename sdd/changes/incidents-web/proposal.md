# Proposal: incidents-web

## Why

La ruta `/incidents` existe en el frontend desde `frontend-foundation` pero renderiza un `RoutePlaceholder`: es la única ruta del workspace apuntada por `sdd/roadmap.md` cuyo contenido es el módulo `maintenance` y que aún no pinta datos. El backend ya expone los dos endpoints necesarios (`GET /api/v1/incidents` y `GET /api/v1/incidents/{id}`), el cliente tipado del frontend los conoce desde `api-contract-export` y `frontend-api-contract-consumer`, y el dataset de `make seed-demo` siembra tres incidencias en REDES11/PAJARITOS8 (una `CLASSIFIED` WIFI, una `ASSIGNED` ACCESS de severidad `HIGH`, y una `CLASSIFIED` APPLIANCE) en el tenant activo, así que la lista y el detalle tienen con qué renderizar de verdad. La negociación de formas ya está hecha.

El plan acordado limita el alcance a la consulta: las once operaciones de mutación (`classify`, `triage`, `assign`, `accept`, `start`, `wait-parts`, `resume`, `resolve`, `cancel`) y la respuesta de aprobación (`POST /api/v1/owner-approvals/{id}/respond`) son superficie aparte, con su propia UX de confirmación, su auditoría por transición y su permiso (R8 de `specs/maintenance.md`). Acoplarlas a esta entrada la convertiría en algo distinto de `size: S`, y la forma que `reservations-web` acaba de cerrar (lista + detalle, sólo lectura) es exactamente lo que demuestra valor sin reabrir la spec.

Fuente de requisitos: `sdd/specs/maintenance.md` (R1, R2, R5, R8 y el §Estado) y `sdd/specs/frontend-auth-session.md` (sesión autenticada que el cliente HTTP consume). La spec `maintenance.md` está cerrada y este change **no** la modifica.

## What changes

Existirá una pantalla `/incidents` con listado paginado y filtrable por `status`, `severity` y `property_id`, y una pantalla `/incidents/[id]` con el detalle de una incidencia, ambas consumiendo los dos endpoints de lectura con el cliente HTTP centralizado (`lib/api`) y TanStack Query. La ruta de detalle se dará de alta en el registro de navegación con la misma forma que `property-detail` y `reservation-detail` (sin `href`, sin `navigationGroup`, `match: "exact"` y las claves i18n en ES/EN). Los nueve valores de `IncidentStatus`, los cuatro de `IncidentSeverity`, las seis de `IncidentCategory` y los seis de `IncidentSource` se expondrán con etiqueta localizada. El shell del workspace no cambia: las claves de `routes.incidents.{title,description}` ya estaban y ya prometen «Listado y detalle de incidencias». La sesión autenticada viene de `frontend-auth-session`, y la autorización RBAC del backend (R8 de `maintenance.md`) es quien realmente decide a qué datos llega cada usuario — `TECHNICIAN` solo ve sus asignadas, restricción que se deriva del token y nunca de un parámetro de la petición.

## Requirements

### R1 — Shell: ruta `/incidents` y registro de la ruta de detalle

**As a** usuario autenticado del workspace, **I want** que `/incidents` muestre contenido y que `/incidents/[id]` exista como destino navegable, **so that** la primera entrada del roadmap sobre el módulo `maintenance` quede resuelta y el flujo lista → detalle sea profundo-enlaceable.

Acceptance criteria:

1. WHEN se navega a `/incidents`, THE SYSTEM SHALL mostrar el listado de incidencias (R2) en lugar de un `RoutePlaceholder`.
2. THE SYSTEM SHALL registrar `incident-detail` en `frontend/features/shell/navigation/route-registry.ts` con `pattern: "/incidents/[id]"`, `match: "exact"`, **sin** `href` y **sin** `navigationGroup` —no aparece en la barra lateral—, y `breadcrumbKeys: crumbs("incidents", "incident-detail")`, replicando la forma de `property-detail` (`route-registry.ts:114-122`) y `reservation-detail` (`route-registry.ts:137-145`).
3. THE SYSTEM SHALL crear las claves `routes.incident-detail.title` y `routes.incident-detail.description` en `frontend/locales/{es,en}/navigation.json`, **sin** hardcodear la cadena en ningún componente.
4. WHEN se navega a `/incidents/[id]` con un `id` válido del tenant, THE SYSTEM SHALL mostrar el detalle (R3).
5. THE SYSTEM SHALL extender la lista `PRD_24_SURFACES` de `route-registry.test.ts` con `/incidents/[id]`, igual que ya contiene `/properties/[id]` y `/reservations/[id]`: la lista es de **superficies de navegación** con id, y la asimetría de excluir el hijo parametrizado sería una sorpresa para el siguiente descriptor detail.

### R2 — Listado paginado y filtrable en `/incidents`

**As a** manager del workspace, **I want** ver y paginar las incidencias del tenant con filtros por estado, severidad y propiedad, **so that** la lista deje de ser un placeholder y refleje lo que el backend ya sirve.

Acceptance criteria:

1. WHEN `/incidents` se monta autenticado, THE SYSTEM SHALL llamar a `GET /api/v1/incidents` con el `tenantId` implícito en el token y renderizar la respuesta.
2. THE SYSTEM SHALL pasar al endpoint, cuando la UI los exponga, los parámetros de filtro que correspondan: en v1, `status`, `severity` y `property_id`, además de `page` y `per_page`. Los nombres de parámetro y los tipos que acepta el endpoint son los ya declarados en `frontend/lib/api/generated/openapi.d.ts` (PRD §23, mantenimiento R8).
3. THE SYSTEM SHALL consumir el sobre `IncidentPageResponse` —`{items, total, page, per_page}` de mantenimiento R8— y SHALL **no** asumir la forma `{data, ...}` que otros módulos del frontend puedan usar; la adaptación concreta del cliente HTTP a ese sobre queda para `design.md`.
4. WHEN la lista carga, THE SYSTEM SHALL mostrar el estado de carga; WHEN la llamada falla, THE SYSTEM SHALL mostrar un error localizado; WHEN el sobre llega con `items` vacío, THE SYSTEM SHALL mostrar un estado vacío localizado —los tres estados ya tienen precedente en el resto del frontend.
5. THE SYSTEM SHALL permitir al usuario avanzar y retroceder de página usando `page` y `per_page`, y SHALL deshabilitar los controles en el extremo correspondiente cuando `page = 1` o `page = total_pages`.
6. THE SYSTEM SHALL pasar `status` y `severity` como enums tipados (`IncidentStatus` e `IncidentSeverity` del `openapi.d.ts`), **no** como cadenas sueltas, para que un valor inválido del lado de la UI falle en la compilación y no en runtime. `property_id` se enviará como UUID string cuando el selector lo elija.
7. THE SYSTEM SHALL construir la query key del listado como `incidentsKeys.list(tenantId, filters)` pasando el **objeto de filtros normalizado directamente** como último segmento (precedent: `reservationsKeys.list(tenantId, filters)` en `frontend/features/reservations/hooks/query-keys.ts`), sin `JSON.stringify` y con claves en orden estable, de modo que dos renders con los mismos filtros produzcan la misma key y TanStack Query no duplique cache.

### R3 — Detalle de una incidencia en `/incidents/[id]`

**As a** manager del workspace, **I want** abrir una incidencia por su enlace y ver todos sus campos, **so that** la consulta puntual desde líneas de timeline, notificaciones o deep links externos sea posible sin volver a la lista.

Acceptance criteria:

1. WHEN se navega a `/incidents/[id]` con un id del tenant, THE SYSTEM SHALL llamar a `GET /api/v1/incidents/{id}` y SHALL renderizar `IncidentResponse`.
2. THE SYSTEM SHALL mostrar los campos de la incidencia: `id`, `property_id`, `reservation_id`, `source`, `category`, `severity`, `status`, `title`, `description`, `ai_summary`, `assigned_technician_id`, `owner_approval_required`, `estimated_cost`, `approved_cost`, `final_cost`, `resolved_at`, `created_at`, `updated_at`. El campo `description` **sí** está en `IncidentResponse` (decisión deliberada, R8: el técnico y el manager lo necesitan) y SHALL renderizarse como **texto plano**, nunca como HTML — es un sumidero de texto libre del huesped o de la limpiadora y la regla 11 de `steering/security.md` ya documenta tres veces esta misma clase de riesgo.
3. THE SYSTEM SHALL **no** pedir, ni consultar por su cuenta, ni mostrar `reported_by_guest_token`, `reported_by_user_id` ni `ai_classification`: el schema de detalle no los expone (R8 cuarto párrafo), y este change no debe salir a buscarlos para «completar la ficha».
4. WHEN la carga falla por `404`, THE SYSTEM SHALL mostrar un estado localizado de "no encontrado" **distinto** del error genérico (un técnico que pide la de otro, o un manager de otro tenant, reciben el mismo `404` por R8 — la UI no debe filtrar existencia); WHEN falla por `401`/`403`/`5xx`, SHALL mostrar el estado de error genérico localizado.
5. THE SYSTEM SHALL mostrar `owner_approval_required = true` con el bloque del detalle que lo destaque, **sin** exponer botones de respuesta — la aprobación (`POST /api/v1/owner-approvals/{id}/respond`) queda fuera de esta entrada (R5).

### R4 — Enumeraciones etiquetadas en los dos locales

**As a** manager, **I want** que los nueve `IncidentStatus`, los cuatro `IncidentSeverity`, las seis `IncidentCategory` y los seis `IncidentSource` se muestren con etiqueta en mi idioma, **so that** el estado real de cada incidencia sea legible y no dependa de traducir la constante a mano.

Acceptance criteria:

1. THE SYSTEM SHALL localizar las nueve etiquetas de `IncidentStatus`: `OPEN`, `CLASSIFIED`, `AWAITING_OWNER_APPROVAL`, `ASSIGNED`, `ACCEPTED`, `IN_PROGRESS`, `WAITING_EXTERNAL_PARTS`, `RESOLVED`, `CANCELLED`.
2. THE SYSTEM SHALL localizar las cuatro etiquetas de `IncidentSeverity`: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.
3. THE SYSTEM SHALL localizar las seis etiquetas de `IncidentCategory` que `RuleBasedIncidentClassifier` reconoce (R2): `WIFI`, `ACCESS`, `APPLIANCE`, `PLUMBING`, `ELECTRICAL`, `OTHER`.
4. THE SYSTEM SHALL localizar las seis etiquetas de `IncidentSource`: `GUEST`, `CLEANER`, `CONVERSATION`, `LOCK_ALERT`, `MANAGER`, `OTHER`.
5. THE SYSTEM SHALL definir las claves en `frontend/locales/es/incidents.json` y `frontend/locales/en/incidents.json` y SHALL usarlas desde el componente, sin string hardcodeado.
6. THE SYSTEM SHALL aplicar la misma etiqueta localizada tanto en la columna de estado de la lista como en la cabecera del detalle, y la severidad con su color semántico (rojo para `CRITICAL`, ámbar para `HIGH`, etc., de forma consistente con `dashboard-web` §Property operational states).

### R5 — i18n, errores HTTP, coste y patrones del frontend

**As a** mantenedor, **I want** que esta entrada cumpla las reglas de `steering/frontend.md` sin excepciones, **so that** el panel de revisión no la devuelva por defectos ya conocidos.

Acceptance criteria:

1. THE SYSTEM SHALL mantener server state con TanStack Query v5, con una clave por recurso que incluya el `tenantId`, y SHALL **no** duplicar server state en Zustand u otro store.
2. THE SYSTEM SHALL **no** contener ningún string de UI en código: todo vive en `frontend/locales/{es,en}/`, y SHALL cubrir al menos los títulos, descripciones, etiquetas de las cuatro enumeraciones, textos de carga/errores/vacío, cabeceras de tabla y nombres de campos mostrados.
3. THE SYSTEM SHALL usar el cliente HTTP centralizado (`lib/api`) para las dos llamadas autenticadas; SHALL **no** usar `fetch` directo.
4. THE SYSTEM SHALL distinguir los códigos de error del backend al menos para los casos usados por la UI: `401` (sesión expirada, gestiona `frontend-auth-session`), `403` (sin permiso, error localizado), `404` (R3.4), `422` (validación: muestra el mensaje del envelope de PRD §23) y `5xx` (error genérico).
5. THE SYSTEM SHALL formatear los tres campos de coste (`estimated_cost`, `approved_cost`, `final_cost`) como importes en la `currency` del tenant (no hay columna de moneda en `IncidentResponse`; el locale del navegador decide el símbolo y los separadores, conforme al precedent de `dashboard`).
6. THE SYSTEM SHALL añadir tests de componente con Testing Library para la lista y el detalle, cubriendo al menos: render del estado de carga, render del sobre con datos, render del estado vacío, render del error, y `description` como texto plano aunque contenga `<script>`.
7. THE SYSTEM SHALL regenerar y commitear `backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts` en el mismo PR sólo si el contrato cambia (no debería: la API ya está publicada); el verificador del contrato (`steering/frontend.md` + `api-contract.md`) dirá la última palabra.

## Out of scope

- **Mutaciones de la incidencia** — `PATCH /api/v1/incidents/{id}` (triage), `POST /api/v1/incidents/{id}/{classify,assign,accept,start,wait-parts,resume,resolve,cancel}`. Cada una lleva su propio permiso (`MANAGE_INCIDENTS` o `EXECUTE_INCIDENTS`), su validación de transición (`IncidentAlreadyClosedError`, `InvalidIncidentTransitionError`, `IncidentBlockedByPendingApprovalError`), su UX de confirmación y su auditoría. Son superficie aparte, `size: M` por derecho propio; el cambio posterior que las cubra decide también cómo se interconecta con `/incidents` (botón en la lista, vista de detalle dedicada, etc.).
- **Responder aprobación** — `POST /api/v1/owner-approvals/{id}/respond`. Pertenece a la ruta `/approvals` (que sigue como `RoutePlaceholder`), en otro agregado, y la regla 11 de `steering/security.md` la ata a una decisión de UX sobre el flujo de la propietaria que no se toma aquí.
- **Creación de incidencias** — no existe `POST /api/v1/incidents` por diseño (`maintenance.md` R8): las altas llegan por el portal del huésped, por `messaging-ai` (intent `MAINTENANCE_ISSUE` / `ACCESS_PROBLEM`) y por `make seed-demo`. Este change no las introduce.
- **`tech-app`** — la app del técnico (`/tech`, `/tech/incidents/[id]`) vive en otra rama del roadmap y depende de tres entradas `[BE]` previas (`tech-incident-context`, `incident-photos`, `tech-cycle-completion`); la nota `sdd/roadmap/tech-app.md` lo documenta. No la toca este change.
- **`cleaner-incident-report` y `cleaner-app`** — la limpiadora aún no puede reportar una incidencia desde su tarea (`cleaner-incident-report` está en la frontera). Estructural y secuencialmente posterior.
- **`/cleaning`** (manager), **`/conversations`**, **`/approvals`**, **`/pricing`**, **`/statements`**, **`/reviews`**, **`/settings/*`** — cada una tiene su entrada en el roadmap. No se abren aquí.
- **Fotos de incidente** — `incident-photos` es una entrada `[BE]` independiente, en la frontera, que decide entidad, rutas y el par antes/después. Hasta que exista, el detalle no muestra fotos.
- **Dashboard agregado sobre incidencias** (KPIs, recurrencia, MTTR) — pertenece a la familia `dashboard-api` / `dashboard-web`, no a la lista global.
- **Acciones masivas** (selección múltiple, exportación a CSV, filtros guardados) — no son read-only; primera lectura no las necesita.
- **Notificaciones en tiempo real** — la pantalla se vuelve a leer al revalidar; un canal en vivo es otra capacidad.
- **Cualquier integración con un PMS real** — lo que se pinta es lo que el backend ya tiene; Beds24, Channex, webhooks e import CSV son historia de `reservations` / `pms-beds24-adapter` y `seed-data-demo`, no se invocan aquí.

## Affected specs

- **`sdd/specs/maintenance.md`** — esta capacidad ya está documentada. Este change **no la modifica** (acuerdo explícito, mismo que el de `reservations-web` con `specs/reservations.md`): el contrato del backend y la spec de la capacidad no entran en este diff. La nota del roadmap sobre `reservations-web` ya explica que el alcance de la spec del backend no se reabre.
- **`sdd/specs/frontend-auth-session.md`** — no se modifica. Se consume tal cual está: tokens en memoria, `AuthGuard` sobre la ruta workspace y refresh coordinado por el cliente HTTP. Cualquier cambio a esa superficie (p. ej. sobrevivir a un reload) es una entrada propia.
- **`sdd/specs/frontend-api-contract-consumer.md`** — no se modifica. El cliente tipado ya incluye los once endpoints de `/incidents` y la regeneración, si fuera necesaria, se hace en el cambio de backend que los haya añadido, no aquí.
- **`sdd/specs/frontend-foundation.md`** — no se modifica. El shell, el `RoutePlaceholder`, el `route-registry` y sus tests ya están; este change sustituye el placeholder en una ruta concreta y añade un descriptor simétrico a `property-detail` y `reservation-detail`.
- **`sdd/roadmap.md`** — se añade una línea ad-hoc para `incidents-web` en el bloque del workspace, con la nota de provenance ("no está en el plan original, añadida tras `reservations-web`") y sus metadatos (`needs: maintenance, frontend-auth-session · size: S · kind: feature`). El lugar natural va después de la línea de `reservations-web` y antes de `cleaning-manager-view`, por la misma razón de orden que ese cambio dejó escrita.
