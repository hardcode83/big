# Design: frontend-auth-session

## Context

El frontend ya tiene un transporte tipado en `frontend/lib/api/client.ts`, pero
su callback `onUnauthorized` solo recibe la respuesta y no puede renovar ni
reintentar una petición. `frontend/app/providers.tsx` conserva un hueco explícito
para `AuthProvider` entre i18n y TanStack Query; `/login` todavía renderiza
`RoutePlaceholder`.

El proxy same-origin ya existe en `frontend/app/api/[...path]/route.ts` y es el
único consumidor de `BACKEND_INTERNAL_URL`. Los tipos generados en
`frontend/lib/api/generated/openapi.d.ts` ya describen `login`, `refresh`,
`logout` y `me`, incluyendo `TokenPairResponse` y `CurrentUserResponse`, por lo
que el diseño no requiere cambios de contrato backend ni regeneración de
OpenAPI.

La arquitectura elegida es deliberadamente efímera: access JWT y refresh JWT
viven en un singleton de módulo del runtime del navegador. Un reload completo,
cierre de pestaña o nuevo runtime pierde ambos tokens y exige login; no existe
restauración de sesión en este change.

## Decisions

### D1 — Transporte same-origin y configuración pública

**Chosen:** añadir `apiBaseUrl` al snapshot de `frontend/lib/config/public.ts`,
con valor por defecto vacío para que `createApiClient` construya rutas
same-origin `/api/v1/...` y atraviese el Route Handler existente. El cliente
recibirá ese valor desde `RuntimeConfigProvider`; nunca leerá
`BACKEND_INTERNAL_URL` ni una variable server-only.

Esto conserva el límite de `api-ingress-routing`, evita que el navegador conozca
el host interno y hace explícito el origen que consume el cliente.

Rejected: llamar directamente al backend interno — viola el límite de red y la
frontera de configuración server-only.

Rejected: usar `next.config.ts` rewrites — el destino runtime quedaría horneado
durante build y rompería la configuración dinámica ya resuelta por el proxy.

### D2 — Almacén efímero de sesión bajo `lib/`

**Chosen:** crear un almacén de módulo en `frontend/lib/auth/session-store.ts`
con access token, refresh token y operaciones atómicas de lectura, escritura y
limpieza. `AuthProvider` mantendrá en React el estado derivado (`loading`,
`authenticated`, `anonymous`, `error`) y la identidad de `/auth/me`; los JWT no
se duplicarán en Zustand ni en el estado persistido de UI.

El almacén no tendrá efectos de hidratación ni restauración desde ningún medio.
Cerrar sesión, fallar `me` tras login o fallar refresh limpiará los dos tokens.

Rejected: `localStorage`, `sessionStorage`, IndexedDB o cookies — contradicen el
contrato de la Proposal y prolongarían la sesión fuera del runtime actual.

Rejected: almacenar tokens en Zustand — mezcla credenciales con estado ligero de
UI y facilitaría añadir persistencia accidental.

### D3 — AuthProvider y ciclo de identidad

**Chosen:** crear `frontend/lib/auth/auth-provider.tsx` como Client Component y
montarlo en `frontend/app/providers.tsx` en el orden
`RuntimeConfigProvider → I18nProvider → AuthProvider → QueryProvider`.
El provider construirá una única instancia del cliente API por runtime, expondrá
`user`, `status`, `login`, `logout` y `refresh`, y realizará `GET /api/v1/auth/me`
solo después de un login exitoso.

El login escribe los tokens en el almacén antes de llamar a `me`; si `me` falla,
limpia la sesión y deja al usuario en login. Tras reload el provider empieza como
anónimo porque el almacén de módulo está vacío.

Rejected: inicializar `me` desde Server Components — no existe token persistido ni
cookie que el servidor pueda leer, y eso introduciría una sesión server-side fuera
de alcance.

### D4 — Refresh elegible, un retry y concurrencia

**Chosen:** ampliar el contrato interno de `frontend/lib/api/client.ts` para que
el transporte conozca, por petición, si se envió un access token y si la ruta es
elegible para refresh. El transporte solo invocará la recuperación cuando:

- la respuesta sea `401`;
- la petición lleve `Authorization: Bearer ...` procedente de `getHeaders`;
- la petición no sea `login`, `refresh` ni `logout`; y
- la petición original aún no haya sido reintentada.

El callback de recuperación usará un cliente de auth sin callback de recuperación
para `POST /api/v1/auth/refresh`; así el refresh nunca se llama a sí mismo. Un
resultado exitoso reemplaza ambos tokens por la pareja rotada y el cliente repite
la petición original una vez con el nuevo access token. Un resultado fallido
limpia la sesión y no produce otro refresh.

La coordinación single-flight vivirá en `frontend/lib/auth/refresh-coordinator.ts`
(o en una responsabilidad equivalente encapsulada en la instancia estable del
servicio de auth), no en el lifecycle de React. Esa infraestructura mantendrá una
única operación compartida por pareja de tokens: las peticiones concurrentes
elegibles esperarán la misma promesa y reutilizarán la pareja rotada, sin abrir
una carrera ni ejecutar más de un refresh para el mismo estado de sesión.

Si el refresh compartido falla, el coordinador limpiará una sola vez la pareja de
tokens, resolverá el mismo fallo para todas las peticiones que esperaban esa
operación y no permitirá que ninguna reintente su petición original ni inicie un
segundo refresh. El `AuthProvider` consumirá ese resultado y reflejará el estado
`anonymous` o `expired` según el modelo de UI; la navegación a `/login` se
coordinará desde `AuthGuard`/la UI, nunca individualmente desde cada request.

`login`, `refresh`, `logout` y peticiones sin access token nunca entran en esta
ruta automática. Logout será best-effort: no se renueva un `401`, se limpia el
estado local y la UI coordina la redirección a login.

Rejected: hacer refresh ante cualquier `401` — activaría refresh para llamadas
anónimas y endpoints de auth, y podría crear bucles.

Rejected: dejar el retry a cada feature — duplicaría la política de expiración y
permitiría que distintos módulos excedieran el límite de un retry.

### D5 — Login, guards y autoridad de autorización

**Chosen:** reemplazar el placeholder de `frontend/app/(public)/login/page.tsx`
por una pantalla que componga un formulario en `frontend/features/auth/` y
consuma el contexto del provider. Crear un `AuthGuard` Client Component en la
misma feature para envolver las superficies operativas protegidas desde los
layouts de `workspace`, `cleaner` y `technician`.

El guard observa el estado del provider y usa navegación client-side para enviar
al usuario anónimo a `/login`, conservando solo una ruta interna segura para
volver después del login. Durante `loading` renderiza un estado localizado. No
se añade guard al portal guest ni a la shell pública.

El rol y `tenant_id` de `CurrentUserResponse` estarán disponibles para la UI y
para construir claves de datos futuras, pero no decidirán permisos de negocio.
El backend seguirá siendo la autoridad de JWT, RBAC y tenant isolation.

Rejected: `middleware.ts` — no puede observar tokens en memoria y requeriría
cookie o sesión server-side, expresamente fuera de alcance.

### D6 — Catálogo y estados de interfaz

**Chosen:** añadir el namespace `auth` a
`frontend/lib/i18n/resources.ts` y catálogos `frontend/locales/es/auth.json` y
`frontend/locales/en/auth.json`. El formulario y el provider usarán esas claves
para labels, errores genéricos, carga, refresh, expiración y logout; los errores
del backend se traducirán por código y nunca se mostrarán como detalle crudo.

El test existente de paridad (`frontend/lib/i18n/catalog-parity.test.ts`) seguirá
siendo la garantía de igualdad de claves.

Rejected: añadir textos a `common` o hardcodearlos en el formulario — diluye la
frontera del namespace y viola la convención ES/EN.

### D7 — Retirada del tenant de desarrollo sin integrar el dashboard

**Chosen:** sustituir únicamente `DEV_TENANT_ID` en
`frontend/features/dashboard/hooks/use-dashboard-data.ts` por el `tenant_id`
procedente del contexto de auth. No se refactoriza el dashboard, no se cambian
sus fixtures y no se conectan endpoints reales; todo ello pertenece a
`dashboard-web`.

Rejected: conservar `DEV_TENANT_ID` — dejaría dos fuentes de identidad y podría
mostrar fixtures bajo un tenant distinto al autenticado.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Runtime config | `frontend/lib/config/public.ts`, `frontend/app/providers.test.tsx`, `frontend/lib/config/public.test.tsx` | Exponer y probar `apiBaseUrl` público same-origin. |
| Auth core | `frontend/lib/auth/session-store.ts`, `frontend/lib/auth/refresh-coordinator.ts`, `frontend/lib/auth/auth-provider.tsx`, `frontend/lib/auth/index.ts` | Almacén efímero, coordinación single-flight/fan-out bajo `lib/auth`, contexto, login/me/logout; React solo refleja los resultados. |
| API transport | `frontend/lib/api/client.ts`, `frontend/lib/api/client.test.ts` | Elegibilidad de `401`, callback de recuperación, un retry y exclusión de endpoints auth. |
| Auth UI | `frontend/features/auth/components/login-form.tsx`, `frontend/features/auth/components/auth-guard.tsx`, `frontend/features/auth/index.ts`, `frontend/app/(public)/login/page.tsx` | Formulario real y guards client-side para shells operativas. |
| Provider tree | `frontend/app/providers.tsx`, `frontend/app/providers.test.tsx` | Insertar `AuthProvider` entre i18n y Query. |
| Routing/shell | `frontend/app/(workspace)/layout.tsx`, layouts de cleaner/technician y sus tests | Envolver solo superficies operativas; mantener pública y guest sin guard JWT. |
| i18n | `frontend/lib/i18n/resources.ts`, `frontend/locales/es/auth.json`, `frontend/locales/en/auth.json`, `frontend/lib/i18n/catalog-parity.test.ts` | Namespace `auth` con paridad ES/EN. |
| Dashboard compatibility | `frontend/features/dashboard/hooks/use-dashboard-data.ts` y su test asociado | Sustituir únicamente `DEV_TENANT_ID` por `tenant_id` del contexto de auth; conservar fixtures y no conectar endpoints reales. |
| Documentation/spec alignment | `frontend/README.md` y comentarios de integración existentes | Documentar sesión efímera, guards de UX y límites; retirar la afirmación de auth no implementada. |

No se modifican `backend/**`, `sdd/specs/auth-tenancy.md`, el contrato OpenAPI ni
`frontend/app/api/[...path]/route.ts`.

## Data & interfaces

- **Backend endpoints:** se consumen las operaciones existentes
  `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`, `POST
  /api/v1/auth/logout` y `GET /api/v1/auth/me`; no se cambian cuerpos,
  respuestas ni códigos.
- **Token pair:** `access_token`, `refresh_token`, `token_type` y `expires_in`
  se mantienen solo en memoria. `expires_in` puede servir para estado de UI, pero
  no sustituye el `401` del backend como fuente de verdad.
- **Identity:** el contexto usa `id`, `email`, `name`, `preferred_language`,
  `role` y `tenant_id` de `CurrentUserResponse`.
- **Client transport:** el callback de unauthorized debe recibir suficiente
  contexto (`path`, método, si se envió bearer y si ya hubo retry) para imponer
  la elegibilidad sin que cada feature conozca la política.
- **Config:** `apiBaseUrl` es público y no sensible; `BACKEND_INTERNAL_URL`
  continúa server-only. No hay nuevas variables secretas ni migraciones de datos.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| La rotación concurrente invalida un refresh legítimo. | Una `refreshPromise` singleton por runtime y sustitución atómica de la pareja. |
| Un `401` anónimo o del propio refresh causa un bucle. | Elegibilidad centralizada por bearer + endpoint y límite de un retry. |
| Un reload parece un logout inesperado. | Estado localizado y documentación explícita; no se añade persistencia fuera del scope. |
| El cliente trata RBAC como seguridad. | Guards descritos como UX; backend conserva autenticación, RBAC y tenant isolation. |
| El access token aparece en logs o errores. | No se incluye en estados, errores traducidos ni mensajes; tests revisan headers y almacenamiento. |
| El dashboard usa un tenant fijo durante la transición. | Eliminar `DEV_TENANT_ID` y derivar el contexto de auth sin convertir fixtures en API real. |
| Un cambio en `client.ts` rompe consumidores futuros. | Mantener la API tipada, probar explícitamente requests anónimas, elegibles, excluidas, refresh fallido y retry único. |

## Open questions

Ninguna. La decisión de no usar cookies, middleware de autenticación, BFF ni
persistencia está cerrada por la Proposal y por la aclaración del usuario. Una
futura migración a cookie/middleware o sesión server-side requerirá un change
arquitectónico separado.
