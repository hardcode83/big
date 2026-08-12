# Design: guest-portal-web

## Context

El backend del portal ya está archivado en [`guest-portal-api`](../../specs/guest-portal-api.md): cuatro rutas anónimas bajo `/api/v1/guest/` cuyos schemas ya viven en `frontend/lib/api/generated/openapi.d.ts` (`StayInfoResponse`, `CheckinStatusResponse`, `SubmitCheckinRequest`, `CheckinSubmittedResponse`, `ReportIncidentRequest`, `IncidentReportedResponse`, más los enums `GuestDocumentType`, `GuestDocumentStatus`, `LegalRegistrationStatus`, `IncidentStatus`). La ruta `frontend/app/(guest)/guest/[token]/page.tsx` existe pero solo renderiza `<RoutePlaceholder routeId="guest" />`. Toda la infraestructura necesaria ya está: el descriptor `guest` en `route-registry.ts` (perfil `guest`, sin `href`), el `GuestShell` (Server Component sin navegación interna que nunca renderiza el token), la metadata `noindex/nofollow` genérica de `create-route-metadata.ts`, el `ApiClient` tipado de `lib/api/client.ts`, los componentes de estado en `components/states/`, TanStack Query v5 y react-i18next. El único precedente de feature con datos es `features/dashboard/` (interfaz de data source + impl HTTP + mapeo DTO + hooks con `retryPolicy`), y el único precedente de formulario es `features/auth/components/login-form.tsx` (`<form>` nativo, estado controlado, `noValidate`, `role="alert"`, sin librería de formularios). No hay `zod` ni `react-hook-form` en `package.json`.

Este change es **solo frontend**: implementa la superficie web sobre un contrato ya cerrado. No toca backend, tokens, persistencia ni autorización.

## Decisions

### D1 — Módulo `features/guest-portal/` espejando la capa de `features/dashboard/`

**Chosen:** un módulo nuevo `frontend/features/guest-portal/` con `data/` (interfaz `GuestPortalDataSource` + impl `HttpGuestPortalSource` + DTOs + punto de composición), `hooks/` (hooks de TanStack Query + query keys), `components/` (vista de página + subvistas + formularios) y un `index.ts`. Es exactamente la estratificación que `features/dashboard/` ya estableció como patrón del proyecto, así que la UI depende de una interfaz y no del cliente HTTP concreto.

Rejected: llamar al `ApiClient` directamente desde los componentes — pierde el mapeo DTO y la testabilidad que el resto del frontend ya tiene.

### D2 — Cliente anónimo: `createApiClient` plano, nunca `createAuthenticatedClients` (R5.1)

**Chosen:** el punto de composición construye `createApiClient({ baseUrl: "" })` **sin** `getHeaders`, de modo que estructuralmente no puede emitir `Authorization: Bearer` (el header solo lo pone `authenticated-client.ts` vía `getSessionTokens()`, que aquí no se importa). La rama `onUnauthorized`/refresh del cliente base queda inerte porque `hadAccessToken` es siempre `false` y no se pasa callback. `baseUrl: ""` enruta por el proxy same-origin `app/api/[...path]/route.ts`, que ya reenvía `CF-Connecting-IP` para el rate-limit por IP del backend. No se crea, guarda ni refresca ningún JWT ni sesión de huésped.

Rejected: reutilizar `createAuthenticatedClients` — adjuntaría Bearer y acoplaría el portal a `session-store`/`tenant`, justo lo que R5.1 prohíbe.

### D3 — Boundary de datos: `GuestPortalDataSource` con cuatro métodos y mapeo a DTO

**Chosen:** una interfaz con `getStayInfo(token)`, `getCheckinStatus(token)`, `submitCheckin(token, data)`, `reportIncident(token, data)`. `HttpGuestPortalSource` traduce los schemas generados (snake_case) a DTOs camelCase con funciones `map*` al estilo de `http-dashboard-source.ts`, y **solo** lee/escribe campos publicados por los schemas (R5.2): al enviar, el tipo de request generado (`SubmitCheckinRequest`, `ReportIncidentRequest`) es la única forma aceptada, así que `tenant_id`/`reservation_id`/fechas de reserva no son ni siquiera expresables. El `token` es **parámetro** de cada método, nunca estado del módulo (R1.3).

Rejected: exponer el cliente crudo o DTOs = schema — perdería el punto único donde se normalizan los `null` (R1.4) y se ignoran campos extra (R5.2).

### D4 — Cuatro rutas y nada más; sin superficie de lectura de incidencias (R3.4, R5.1)

**Chosen:** `GuestPortalDataSource` declara exactamente los cuatro métodos del contrato. **No existe** ningún método de listar/leer/modificar/asignar/resolver incidencias, así que la ausencia es estructural, no una restricción a vigilar. La respuesta del `POST` de incidencia (`id`/`status`/`created_at`) es la única lectura de una incidencia que el portal jamás ofrece. **El acuse mostrado al huésped es una confirmación localizada + el `status` traducido (D10) + `created_at` si aporta valor; el `id` (UUID) no se renderiza** — no es accionable para el huésped y la spec no exige mostrarlo. El mapper puede exponer `id` en el DTO, pero la vista no lo pinta.

Rejected: un método `getIncident` "por si acaso" — crearía una vía que R3.4 prohíbe.

### D5 — Una página móvil con tres secciones independientes (R4.3)

**Chosen:** `page.tsx` (Server Component) recibe `params.token` y lo pasa como prop a un client component `GuestPortalView`. La vista es una **única página scrollable** mobile-first con tres secciones apiladas: **Estancia** (R1), **Check-in** (R2) y **Comunicar incidencia** (R3). Cada sección es una unidad de datos/estado independiente (su propio `useQuery`/`useMutation` y sus propios estados), de modo que un fallo en una no derriba a las otras — salvo el gate de autorización de D6. La estancia se carga primero; check-in e incidencia cuelgan debajo.

Rejected: wizard multi-paso o pestañas — añade navegación y foco que el PRD (portal simple de móvil) no pide.

**Amendment (implementación):** las tres secciones se consolidaron en un único archivo
`components/guest-portal-view.tsx` (con `StayInfoSection`/`CheckinSection`/`IncidentSection`
como componentes internos), en lugar de tres archivos `*-section.tsx` separados. La página
sigue siendo una sola página scrollable con tres secciones independientes (cada una con su
propio estado/datos); solo cambia la granularidad de archivos. Cobertura completa por sección
en `components/guest-portal-view.test.tsx`.

### D6 — El `404` de `info` es el gate de autorización de toda la página (R1.2)

**Chosen:** la carga de `GET /info/{token}` es el gate. Si responde el `404 NOT_FOUND` público, la página entera muestra **un único estado localizado "enlace no válido"** que no distingue token inexistente, revocado, expirado, cancelado ni de otro tenant, y **no** renderiza las secciones de check-in ni incidencia (pedir datos sobre un enlace muerto no tiene sentido y multiplicaría el mismo `404`). El resto de códigos se mapean por sección (D7).

Rejected: cargar las tres secciones en paralelo y mapear cada `404` por separado — arriesga textos distintos para la misma causa y contradice "una sola respuesta de fallo".

### D7 — Mapa de códigos HTTP → estado de UI seguro (R2.3, R3.2, R3.3, R5.3)

**Chosen:** las excepciones son `ApiError` (de `lib/api/errors.ts`, ya con `status`/`code`/`details`). Mapeo:

| Código | Estado de UI |
|---|---|
| `404 NOT_FOUND` | En `info`: gate de página (D6). En check-in/incidencia: mismo estado "enlace no válido", sin distinguir causa. |
| `422 VALIDATION_ERROR` | Validación **por campo** en el formulario correspondiente, asociando `error.details` (loc/reason) a cada campo; nunca se renderiza el cuerpo crudo, trazas ni el valor rechazado. |
| `429 RATE_LIMITED` | Estado "espera un minuto". En incidencia, **nunca** se presenta como confirmación de que no se creó (R3.3): el texto dice "no sabemos si se registró, espera antes de reintentar". |
| `413 PAYLOAD_TOO_LARGE` | "Contenido demasiado grande" — solo en las operaciones cuyo contrato lo publica; los cuatro endpoints lo declaran, así que aplica a check-in e incidencia. |
| `5xx` / red / `502` del proxy | Estado de error genérico reintentable. |

El retry sigue la política de `features/dashboard`: no reintentar 4xx (definitivos), sí 5xx/red hasta 2 veces. Esa `retryPolicy` se **extrae** a `lib/api/retry-policy.ts` y la consumen dashboard y guest-portal (hoy vive inline en `use-dashboard-data.ts`). La extracción para dashboard es un refactor **estrictamente behavior-preserving**: la función se mueve sin cambiar su lógica ni su firma, `use-dashboard-data.ts` pasa a importarla, y los tests existentes de dashboard deben seguir verdes sin modificación de expectativas.

Rejected: reintentar 429 automáticamente — dispararía más `POST` de incidencia (no deduplicada) y agotaría el presupuesto por token.

### D8 — Check-in: los seis campos siempre, `missing_fields` es solo informativo (R2.1, R2.2)

**Chosen:** el formulario de check-in muestra **siempre los seis campos** del contrato (`full_name`, `nationality`, `date_of_birth`, `document_type`, `document_number`, `document_expiry_date`), porque `SubmitCheckinRequest` no es un patch parcial: los seis van juntos y requeridos. `GET /checkin/{token}` aporta `document_status`, `legal_registration_status` y `missing_fields`; estos se usan **solo** como resumen declarado por el backend (qué falta, según los nombres que publica), y el frontend **no** infiere desde `missing_fields` completitud, pasos, ni reglas de presentación, ni muestra/pide fechas de la reserva. `document_type` es un `<select>` sobre los miembros de `GuestDocumentType`. Se envían exactamente los seis campos; el número de documento no se muestra ni se hace eco tras el envío (R2.2).

Rejected: habilitar/ocultar campos según `missing_fields` — exactamente la inferencia que R2.1 prohíbe, y rompería el envío (el backend exige los seis).

### D9 — Formularios al patrón `login-form`, con primitivas de campo mínimas y accesibles (R4.3, R2.4)

**Chosen:** `<form noValidate>` con estado controlado y `role="alert"`, como `login-form.tsx`, pero extrayendo primitivas mínimas reutilizables (`GuestTextField`, `GuestTextareaField`, `GuestSelectField`) porque el check-in tiene seis campos que necesitan `id`/`htmlFor`, nombre accesible y asociación de error `aria-describedby`/`aria-invalid`. La validación cliente es **ligera** (requerido/no-vacío para UX); el backend es la autoridad y su `422` produce los errores por campo. Durante el envío: botón deshabilitado (impide duplicados) y una región `aria-live` anuncia el progreso (R2.4). Tras éxito de check-in se muestran los dos estados y se permite continuar/revisar sin crear sesión.

Rejected: añadir `react-hook-form` + `zod` — dependencias nuevas y validación runtime que R5.2 desaconseja duplicar sobre el contrato; el proyecto ya valida "a mano" en `login-form`.

**Amendment (implementación):** las primitivas de campo se unificaron en un único componente
accesible `components/fields/guest-fields.tsx` (`GuestField`, con variante `input`/`textarea`/
`select` por prop `as`), en lugar de tres primitivas separadas. Conserva lo que D9 exige:
`id`/`htmlFor`, nombre accesible, y asociación de error `aria-describedby`/`aria-invalid`. El
mapeo `422`→campo se implementó en `fieldErrorsFrom422` (lee solo `details.errors[].loc`,
renderiza copia localizada `guest:errors.invalidField`, nunca el cuerpo crudo).

### D10 — Estados del backend como copia localizada por valor canónico (R4.4)

**Chosen:** `document_status`, `legal_registration_status` e `IncidentStatus` se renderizan como copia localizada mediante un mapa indexado por el **valor exacto del enum** (los tipos generados hacen el `switch` exhaustivo con ayuda del compilador). Ninguna lógica de negocio ni de transición vive en el cliente; el frontend solo traduce el valor que el backend declara.

Rejected: derivar texto por heurística sobre el string — se rompería en cuanto el backend añada un miembro.

### D11 — Campos nullable de `StayInfo`: ausencia segura, nunca `null`/`undefined` (R1.4)

**Chosen:** el mapper normaliza cada nullable de `StayInfoResponse` (address_line1/2, city, province, postal_code, wifi_name, arrival_notes, access_code_masked, support_channel) a `null` explícito en el DTO, y la vista o bien omite la fila o muestra una copia localizada de "no disponible", nunca el literal. Los no-nullables (dates, times, property_name, country, timezone) se renderizan siempre. El `access_code_masked` llega **ya enmascarado** desde el backend; el frontend no lo desenmascara ni lo reconstruye.

Rejected: renderizar el objeto tal cual — imprimiría `null` y rompería el layout.

### D12 — Namespace i18n `guest`, ES/EN, todas las claves nuevas en ambos (R4.1)

**Chosen:** namespace nuevo `guest` con `locales/es/guest.json` y `locales/en/guest.json`, registrado en `lib/i18n/resources.ts` (`NAMESPACES` y `resources`). Toda cadena visible del portal se resuelve por i18n; la implementación crea en **ambos** catálogos todas las claves que introduzca, con `es` como fallback (ya configurado). Los estados de carga/error reutilizan el namespace `states` existente donde encaje; lo específico del portal va en `guest`.

Rejected: colgar las cadenas de `common`/`states` — hincharía namespaces compartidos; el precedente (`dashboard`, `auth`) es un namespace por feature.

### D13 — Token fuera de todo sumidero visible (R1.3)

**Chosen:** el token viaja en la URL porque **es** la credencial (inevitable), pero: (a) la metadata sigue siendo `routeMetadata("guest")` — genérica, `noindex/nofollow`, sin token, sin canonical (ya implementado, no se toca); (b) `GuestShell` no renderiza breadcrumbs ni navegación y no recibe el token; (c) el token no se escribe en `document.title`, ni en texto visible, ni en mensajes de error, ni se envía a analytics (no hay analytics en el portal); (d) las query keys de TanStack incluyen el token solo como discriminante **en memoria** — no es un sink renderizado, igual que `pathParams`. La superficie del huésped queda fuera de la navegación de usuario autenticado (perfil `guest`, sin `href` en el registry).

Rejected: derivar un hash del token para la query key — complejidad sin beneficio; la key en memoria no es un sumidero que R1.3 enumere.

### D14 — Regeneración de tipos: ya sincronizados; caveat de verificación en worktree (R5.4)

**Chosen:** los schemas guest ya están en `openapi.d.ts`, así que **no** hace falta regenerar para implementar. La sección Verification correrá `cd frontend && npm run api:check` para probar que siguen sincronizados con `backend/openapi.json` (nullable, enums, requests, códigos de error). **Caveat** (de `sdd/project.md`): ese comando literal **no funciona desde un worktree enlazado**; la salida verificada es el `docker compose cp ... && ln -sfn ... && npm run api:generate` que documenta `project.md`. La tarea de verificación debe usar esa variante.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Página | `frontend/app/(guest)/guest/[token]/page.tsx` | Sustituir `RoutePlaceholder` por `<GuestPortalView token={params.token} />`; conservar `generateMetadata → routeMetadata("guest")`. |
| Feature — data | `frontend/features/guest-portal/data/{guest-portal-source.ts, dto.ts, index.ts, http/http-guest-portal-source.ts}` | Interfaz `GuestPortalDataSource`, DTOs camelCase, punto de composición `getGuestPortalDataSource()` con cliente anónimo, impl HTTP + mappers. |
| Feature — hooks | `frontend/features/guest-portal/hooks/{query-keys.ts, use-stay-info.ts, use-checkin.ts, use-report-incident.ts}` | `useQuery` para info/checkin-status; `useMutation` para submit/incident; keys por token. |
| Feature — componentes | `frontend/features/guest-portal/components/{guest-portal-view.tsx, stay-info-section.tsx, checkin-section.tsx, incident-section.tsx, fields/*}` | Vista raíz + tres secciones + primitivas de campo accesibles; mapa enum→copia localizada. |
| Feature — barrel | `frontend/features/guest-portal/index.ts` | Export público (`GuestPortalView`). |
| API — retry | `frontend/lib/api/retry-policy.ts` (+ ajuste en `features/dashboard/hooks/use-dashboard-data.ts` para consumirlo) | Extraer `retryPolicy` compartida. |
| i18n | `frontend/lib/i18n/resources.ts`, `frontend/locales/{es,en}/guest.json` | Registrar namespace `guest`; catálogos ES/EN. |
| Tests | Colocados junto a cada módulo (`*.test.ts(x)`) | Mapeo DTO, gate 404, mapeo 422/429/413, missing_fields informativo, nullable, i18n parity, ausencia de vía de lectura de incidencias. |

## Data & interfaces

- **Sin cambios de contrato backend, sin migraciones, sin env vars nuevas.** Se consumen los schemas ya publicados.
- **Endpoints consumidos** (los cuatro, vía proxy same-origin): `GET /api/v1/guest/info/{token}`, `GET /api/v1/guest/checkin/{token}`, `POST /api/v1/guest/checkin/{token}`, `POST /api/v1/guest/incident/{token}`.
- **Requests emitidos** (solo campos permitidos): `SubmitCheckinRequest` (6 campos), `ReportIncidentRequest` (`title`, `description`).
- **Enums renderizados**: `GuestDocumentType`, `GuestDocumentStatus`, `LegalRegistrationStatus`, `IncidentStatus`.

## Risks & mitigations

- **[Gate operativo obligatorio, marcado por `guest-portal-api`] El log del túnel Cloudflare puede retener el URI completo, y el token va en la ruta.** La spec `guest-portal-api.md` (§ Deuda declarada) declara *literalmente* que "confirmar la retención del URI completo en esa cuenta es requisito previo de `guest-portal-web`". Ningún componente del repo escribe el token en un log, pero al hacer el portal realmente navegable el token empieza a viajar de verdad. **Resolución (cerrada):** **no bloquea** design/tasks/run, que son código de frontend y no cambian la exposición del token. Sí es un **gate operativo obligatorio antes de `READY_FOR_PR`/ship**: hay que verificar la política de logging del túnel de dev. Como `guest-portal-api` lo declara prerrequisito, **no se convierte automáticamente en deuda aceptada**; si en el momento del ship no se puede confirmar, se decide explícitamente (verificar, mitigar o aceptar con firma), no por defecto. Queda registrado en `BLOCKED.md` como `deferred` para que el flujo lo recoja antes del ship.
- **Colisión de caché entre dos tokens en el mismo navegador.** Improbable (un huésped, un enlace), mitigado por keyear las queries por token. Sin sink renderizado (D13).
- **Divergencia de tipos si el backend cambia el contrato.** Mitigada por `api:check` en Verification (con el caveat del worktree, D14).
- **Caracteres de formato `Cf` (spoofing visual) en `access_notes`/título de incidencia propia.** La spec lo asigna al change que traiga "esa superficie"; el portal solo renderiza texto de la propia estancia del huésped, no de terceros, así que no introduce la exposición del backoffice. Fuera de alcance, anotado.

## Open questions

Ninguna abierta. Resueltas en revisión de diseño:

- **Layout** → una sola página scrollable con tres secciones apiladas (D5).
- **Acuse de incidencia** → confirmación localizada + `status` traducido + `created_at` si aporta valor; **sin** renderizar el `id` UUID (D4/D10).
- **Diagrama** → no se genera SVG; el flujo queda descrito en texto (D5–D7).
- **Prerrequisito Cloudflare** → gate operativo obligatorio antes de `READY_FOR_PR`/ship, no bloquea design/tasks/run, y no se degrada a deuda aceptada por defecto (ver Risks; registrado en `BLOCKED.md`).
