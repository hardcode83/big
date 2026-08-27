# Proposal: frontend-auth-role-routing

## Why

`public-zone-hardening` (archivado 2026-08-26) cierra los cinco síntomas de UX
observados en `autohostai.digitalsec.work` y deja cuatro huecos documentados
como §Out of scope, además de dos síntomas nuevos observados **después** de
ese deploy: (1) el botón «Volver a la landing» del `/login` no devuelve al
landing cuando hay cookie `autohostai.session.present` huérfana de un login
anterior —el visitante entra en un bucle `/login → / → /dashboard → /login`
que aparenta «el botón no hace nada»— y (2) abrir `https://autohostai.digitalsec.work`
después de un login previo lleva al visitante a `/login` en vez de al landing
porque la cookie persiste un año (`max-age=31536000`) mientras los JWT en
memoria se pierden en cada reload (`frontend-auth-session.md:46-49`). Ambos
síntomas son manifestaciones del mismo problema raíz: la `RootPage` server
confía solo en la cookie no sensible y nunca comprueba contra el backend que
el JWT siga siendo válido — exactamente el caso que el ítem (4) del roadmap
nombró como defensa en profundidad del logout real. Este change agrupa los
cuatro ítems del roadmap más los dos síntomas nuevos para evitar abrir
cuatro frentes en paralelo, en línea con la regla 1 de
`docs/adr/0001-roadmap-structure-and-concurrency.md` (un nombre, una
responsabilidad).

## What changes

Existirá al archivar:

- Una `RootPage` (`frontend/app/page.tsx`) que, cuando la cookie
  `autohostai.session.present` está presente, pregunta al backend
  (`GET /api/v1/auth/me`) antes de decidir: si responde 2xx redirige a
  `/dashboard` como hoy; si responde 401 purga la cookie vía
  `cookies().delete(SESSION_PRESENT_COOKIE)` y renderiza el landing —
  resolviendo el síntoma (2) en el camino del servidor, sin red extra cuando
  la cookie está ausente.
- Un `AuthGuard` endurecido por rol (`frontend/features/auth/components/auth-guard.tsx`)
  que acepta una prop opcional `allow: Role[]` y rechaza con `/login?denied=role`
  cuando el usuario autenticado no tiene un rol permitido — protegiendo
  `/cleaner`, `/tech` y el resto de shells del ítem (1).
- Una mini-landing autenticada (`frontend/app/(authenticated)/welcome/page.tsx`,
  ruta `/welcome`) con un CTA directo al shell del rol (`/cleaner` o `/tech`)
  para field users en dispositivos de un solo uso — sustituye al redirect
  directo de R4 de `public-zone-hardening` para esos dos roles y se elige
  con un flag `?compact=1` o, por defecto, vía `roleHome()` cuando el rol
  es `CLEANER` o `TECHNICIAN`.
- La función `useAuth().logout()` reescrita como TanStack Query mutation
  (`useLogoutMutation`) con invalidación explícita de queries de sesión
  — refactor de organización, mismo comportamiento.
- El link «Volver a la landing» de `LoginForm` llama a
  `clearSessionPresent()` antes de navegar a `/`, para que el camino del
  cliente salga del bucle cuando hay cookie huérfana aunque el servidor no
  haya llegado a ejecutar `RootPage` (defensa en profundidad del síntoma 1).

## Requirements

### R1 — AuthGuard endurecido por rol

**As a** operador del workspace, **I want** que `AuthGuard` rechace a
usuarios autenticados cuyo rol no pertenece al shell, **so that** un
`CLEANER` no pueda abrir `/dashboard` ni `/(workspace)/properties/*` aunque
la API se los sirviera, y la separación por rol viva en el routing además
de en el sidebar y el backend.

Acceptance criteria:

1. WHEN `AuthGuard` se monta con `allow={["CLEANER"]}` y el usuario
   autenticado tiene rol `TENANT_OWNER`, THE SYSTEM SHALL redirigir
   client-side a `/login?denied=role` y SHALL NOT renderizar `children`.
2. WHEN `AuthGuard` se monta con `allow={["CLEANER"]}` y el usuario
   autenticado tiene rol `CLEANER`, THE SYSTEM SHALL renderizar `children`
   sin redirigir.
3. WHEN `AuthGuard` se monta con `allow={["CLEANER"]}` y el usuario está
   en `anonymous` o `expired`, THE SYSTEM SHALL mantener el comportamiento
   actual (redirect a `/login?returnTo=...`) sin evaluar `allow`.
4. THE SYSTEM SHALL aplicar `AuthGuard` con `allow` específico en los
   segmentos `/cleaner` (allow `[CLEANER]`), `/tech` (allow `[TECHNICIAN]`),
   `/(workspace)/*` (allow `[TENANT_OWNER, PROPERTY_MANAGER]`) y SHALL NOT
   aplicarlo en `/(public)/*` ni `/guest/[token]`.
5. THE SYSTEM SHALL tratar el `denied=role` como informativo — la página
   `/login` muestra el estado localizado `auth.deniedRole` cuando el query
   param está presente, pero la redirección final al shell correcto la
   resuelve `roleHome()` como en `public-zone-hardening`.

### R2 — Mini-landing autenticada post-login para field users

**As a** limpiadora o técnico en un dispositivo compartido, **I want**
una pantalla intermedia tras el login con un único botón que me lleva a mi
shell, **so that** un toque a destiempo durante el login no me desvíe a
una pantalla que no es la mía y tenga un punto de retorno claro si me
equivoco de rol.

Acceptance criteria:

1. WHEN el `LoginForm` redirige tras un login sin `?returnTo=` y el rol
   resuelto por `roleHome()` es `CLEANER` o `TECHNICIAN`, THE SYSTEM SHALL
   navegar a `/welcome?role=<role>` en vez de a `/cleaner` o `/tech`
   directamente.
2. WHEN la `/welcome` recibe el query param `role=CLEANER` o
   `role=TECHNICIAN` y el `useAuth().user.role` coincide, THE SYSTEM SHALL
   renderizar un `StatePanel` con título localizado `auth.welcome.title`
   y un `Button` cuyo `href` (via `next/link`) es `roleHome(role)`, con
   `aria-label` localizado `auth.welcome.cta.<role>`.
3. WHEN `/welcome` se carga sin query param o con un `role` que no
   coincide con el del usuario autenticado, THE SYSTEM SHALL redirigir
   client-side a `roleHome(user.role)` sin mostrar la pantalla.
4. THE SYSTEM SHALL cubrir `/welcome` con `AuthGuard` (allow cualquier
   rol autenticado) y SHALL NOT cubrir `/welcome` con guard de rol
   específico: el propósito es precisamente aceptar a cualquier
   autenticado y dejar que el CTA decida el shell.
5. THE SYSTEM SHALL registrar `/welcome` en `frontend/app/(authenticated)/welcome/page.tsx`
   dentro del segmento `(authenticated)` para que los layouts autenticados
   (Topbar con `UserMenu`) se apliquen, en línea con
   `frontend-foundation.md` §Shells.

### R3 — `auth-provider.logout` migrado a TanStack Query mutation

**As a** mantenedor del frontend, **I want** que el cierre de sesión sea
una TanStack Query mutation cacheable y testeable, **so that** la lógica
de logout comparta la misma maquinaria que el resto de mutaciones
(invalidación de caché, retry best-effort, tipado del response) y no
quede como una excepción en `lib/api/authenticated-client`.

Acceptance criteria:

1. WHEN el `UserMenu` confirma el cierre de sesión, THE SYSTEM SHALL
   invocar `useLogoutMutation().mutate()` en lugar de `useAuth().logout()`,
   preservando el orden `mutateAsync → router.replace("/") →
   router.refresh()` documentado en `frontend-auth-session.md:78-80`.
2. WHEN la mutation resuelve (HTTP 2xx), THE SYSTEM SHALL purgar el
   `QueryClient` singleton vía `session-cache-purge` antes del
   `router.replace("/")`, igual que hoy — la limpieza local es
   incondicional y no depende del resultado del endpoint.
3. WHEN la mutation falla con error de red o 5xx, THE SYSTEM SHALL
   ejecutar la misma limpieza local (try/finally equivalente) y SHALL
   reintentar una sola vez si el fallo es transitorio (status ≥ 500 o
   `NetworkError`), reusando el helper `retry` de TanStack Query
   (`retry: 1`) sin reintroducir la cadena manual de
   `lib/api/authenticated-client`.
4. THE SYSTEM SHALL invalidar explícitamente la query `["auth", "me"]`
   al éxito vía `queryClient.removeQueries({ queryKey: ["auth", "me"] })`
   para que el siguiente `useAuth()` arranque en `anonymous`.
5. THE SYSTEM SHALL mantener `useAuth().logout()` como wrapper delgado
   sobre la mutation hasta que `UserMenu` y cualquier otro consumidor
   estén migrados, y SHALL marcarlo deprecated en JSDoc
   (`@deprecated use useLogoutMutation().mutateAsync()`).

### R4 — RootPage distingue cookie stale vs JWT revocado

**As a** visitante que cerró la pestaña y vuelve más tarde, **I want**
que la raíz `/` me muestre el landing cuando mi sesión ya no es válida,
**so that** pueda leer qué ofrece el producto y decidir si entro de
nuevo, en vez de aterrizar directamente en `/login` sin contexto.

Acceptance criteria:

1. WHEN la cookie `autohostai.session.present` está ausente, THE SYSTEM
   SHALL renderizar el landing sin hacer ninguna petición al backend
   (preservando el modelo «server decide sin red» para el caso
   anonimous).
2. WHEN la cookie está presente, THE SYSTEM SHALL llamar a
   `GET /api/v1/auth/me` desde el Server Component `RootPage` (usando el
   cliente HTTP centralizado con `apiBaseUrl` público) y SHALL propagar
   las cookies de la petición entrante (`next/headers` cookies) para que
   el bearer JWT en memoria del navegador llegue al backend.
3. WHEN `/auth/me` responde 2xx, THE SYSTEM SHALL redirigir a `/dashboard`
   vía `redirect("/dashboard", "replace")` (307 Temporal Redirect,
   comportamiento actual).
4. WHEN `/auth/me` responde 401, THE SYSTEM SHALL purgar la cookie vía
   `cookies().delete(SESSION_PRESENT_COOKIE)` y SHALL renderizar el
   landing — sin redirigir a `/login`, sin mostrar el shell.
5. WHEN `/auth/me` responde 5xx o falla por timeout/red, THE SYSTEM SHALL
   NO purgar la cookie (el fallo del backend no debe equivaler a logout)
   y SHALL redirigir a `/dashboard` igual que el camino feliz — el coste
   de una cookie stale tras un 5xx se corrige en la siguiente visita.
6. THE SYSTEM SHALL abortar la llamada a `/auth/me` con `signal: AbortSignal.timeout(2000)`
   para que la raíz nunca tarde más de 2 s en responder cuando hay
   cookie presente.
7. THE SYSTEM SHALL añadir el segmento `/auth/me` con `cookies: { forward: 'include' }`
   en el cliente HTTP centralizado para que el bearer llegue al backend
   desde Server Components — cambio mínimo de configuración, sin tocar
   el contrato del endpoint.

### R5 — Botón «Volver a la landing» sale del bucle con cookie huérfana

**As a** visitante en `/login` con una cookie `autohostai.session.present`
huérfana de un login anterior (sesión perdida al recargar), **I want**
que el botón «Volver a la landing» me lleve al landing, **so that** no
tenga que limpiar cookies del navegador para escapar del bucle
`/login → / → /dashboard → /login`.

Acceptance criteria:

1. WHEN el `LoginForm` se monta y existe un link visible «Volver a la
   landing», THE SYSTEM SHALL renderizar ese link como un
   `<button type="button">` (no `<a>`) que, en su `onClick`, ejecuta en
   este orden: `clearSessionPresent()` (helper ya existente en
   `lib/auth/auth-provider.tsx`) → `router.replace("/")` → `router.refresh()`.
2. WHEN el visitante hace click en ese botón, THE SYSTEM SHALL purgar la
   cookie `autohostai.session.present` **antes** de que el navegador
   emita la navegación a `/`, de forma que `RootPage` vea la cookie
   ausente y renderice el landing (R4 caso cookie ausente) sin
   necesidad de que el cliente ejecute `/auth/me`.
3. WHEN el visitante navega a `/` desde cualquier otro origen
   (`back-button` del navegador, link externo, URL pegada), THE SYSTEM
   SHALL seguir mostrando el bucle **a menos que** la cookie esté
   purgada — por eso R4 es defensa en profundidad de R5: el botón es la
   primera línea, R4 es la segunda.
4. THE SYSTEM SHALL mantener la accesibilidad del control: `role="link"`,
   `aria-label` resuelto vía `auth.backToLanding` (misma clave i18n que
   ya existe), y `tabIndex=0` por defecto.
5. THE SYSTEM SHALL cubrir el botón con un test que verifique el orden
   de llamadas (`clearSessionPresent` antes de `router.replace` antes
   de `router.refresh`) y la ausencia de la cookie en
   `document.cookie` tras el click.

### R6 — Visita a la URL tras login previo lleva al landing, no a `/login`

**As a** visitante que cerró la pestaña después de autenticarse y vuelve
horas o días después, **I want** que abrir `https://autohostai.digitalsec.work`
me muestre el landing público, **so that** pueda decidir si entro de
nuevo o me voy, en vez de aterrizar directamente en `/login` sin
explicación.

Acceptance criteria:

1. WHEN el visitante abre `https://autohostai.digitalsec.work/` y su
   navegador tiene la cookie `autohostai.session.present = "1"` pero
   sus JWT en memoria están perdidos (runtime nuevo o pestaña cerrada),
   THE SYSTEM SHALL renderizar el landing público tras purgar la cookie
   — el camino completo es R4 caso `/auth/me` → 401.
2. WHEN el visitante abre `https://autohostai.digitalsec.work/` sin
   cookie y sin JWT en memoria, THE SYSTEM SHALL renderizar el landing
   sin redirigir — comportamiento actual (R4 caso cookie ausente).
3. WHEN el visitante abre `https://autohostai.digitalsec.work/` con
   cookie y JWT válido en memoria, THE SYSTEM SHALL redirigir a
   `/dashboard` — comportamiento actual (R4 caso `/auth/me` → 2xx).
4. THE SYSTEM SHALL verificar el comportamiento de R6 con un test E2E
   (Playwright) que: (a) autentica al usuario, (b) cierra la pestaña y
   abre una nueva en la misma URL, (c) afirma que el contenido
   renderizado es el landing (`h1` con título de marketing), no
   `/login`. Este test entra en la suite E2E de `hardening-release`
   (DoD §28) cuando ese change se ejecute.
5. THE SYSTEM SHALL NO marcar la cookie `autohostai.session.present`
   con `max-age` mayor que el `access_token` (15 min) sin un mecanismo
   de refresh — la cookie persiste un año pero el JWT dura 15 min, así
   que el síntoma es estructural. La defensa la da R4; este requisito
   documenta que el comportamiento observado por el visitante es el
   correcto bajo esa defensa.

## Out of scope

- Reescritura de `AuthGuard` para más de los cuatro roles MVP
  (`TENANT_OWNER`, `PROPERTY_MANAGER`, `CLEANER`, `TECHNICIAN`). Si entra
  `SUPER_ADMIN` (ADR 0006), su ruta queda para `saas-cross-tenant`.
- Migración del `LocaleSwitcher` a un `Select` para más de dos idiomas —
  sigue siendo un único botón (D1 de `public-zone-hardening` lo dejó así).
- Persistencia de los JWT en `localStorage`/`sessionStorage` para
  resolver el síntoma (2) «eliminando» la cookie stale — sería un cambio
  de modelo de seguridad y contradice `frontend-auth-session.md:46-49` y
  la regla 4 de `sdd/steering/security.md` (RBAC en backend, no en
  cliente). El fix es server-side (R4), no client-side.
- Reducción del `max-age` de la cookie `autohostai.session.present` por
  debajo de la duración del `access_token` (15 min). La cookie es
  intencionalmente larga para que el badge «autenticado» en el landing
  no parpadee con cada refresh; acortarla introduce otro problema.
- Cambios en backend, esquema, migraciones o variables de entorno. El
  cambio es 100% frontend — el endpoint `GET /api/v1/auth/me` que R4
  consume ya existe.
- Reescritura completa del shell autenticado. Solo se modifica
  `AuthGuard`, `LoginForm`, `app/page.tsx`, `lib/auth/auth-provider.tsx`
  y `lib/auth/session-presence-cookie.ts` (este último solo si la
  migración a mutation de R3 lo exige).
- Migración de `useAuth()` a un patrón basado en Server Actions. La
  mutation es el cambio acordado; tocar el modelo cliente/servidor va a
  `frontend-refactor` o a un change posterior.

## Affected specs

- `sdd/specs/frontend-auth-role-routing.md` *(no existe aún — se creará
  al archivar)*: spec principal de este change, que agrupará los cuatro
  requisitos de routing por rol más las defensas de los síntomas (1) y
  (2).
- `sdd/specs/frontend-auth-session.md` (existente): R3 puede refinar el
  flujo de logout pero no contradice ningún criterio; R5 modifica la
  superficie del botón de LoginForm pero el resto de la sesión
  (tokens, refresh, purga de caché) sigue regida por esta spec. Si al
  archivar surge un conflicto, prevalece `frontend-auth-session.md` salvo
  que se justifique explícitamente la derogación.
- `sdd/specs/frontend-foundation.md` (existente): R2 introduce
  `/welcome` dentro del segmento `(authenticated)`; este cambio respeta
  el §Shells y los slots del Topbar sin modificar la spec base.