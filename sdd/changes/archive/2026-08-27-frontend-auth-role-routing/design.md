# Design: frontend-auth-role-routing

## Context

El change agrupa seis arreglos del routing y de la sesión autenticada que comparten raíz: la `RootPage` server confía solo en la cookie `autohostai.session.present` (`frontend/app/page.tsx:35-40`) y la sesión client vive en memoria (`frontend/lib/auth/auth-provider.tsx:84-93`). Esa combinación produce el bucle `/login → / → /dashboard → /login` con cookie huérfana y el «logout tras login» que el visitor percibe como botón que no hace nada. A eso se le suma que `AuthGuard` (`frontend/features/auth/components/auth-guard.tsx:10-55`) solo filtra por «autenticado sí/no» y no por rol — un `CLEANER` puede abrir `/dashboard` mientras el sidebar y el backend lo bloquean. `UserMenu` (`frontend/features/auth/components/user-menu.tsx:53-128`) consume el `logout()` del contexto, que es un callback ad-hoc y no una TanStack Query mutation como el resto de mutaciones del frontend. El redirect por rol vive en `LoginForm.handleSubmit` (`frontend/features/auth/components/login-form.tsx:42-60`) con la tabla `ROLE_HOME` (`frontend/features/auth/lib/role-home.ts:13-18`) — y manda al shell directamente, sin parada intermedia, lo que pierde al field user en un dispositivo compartido.

## Decisions

### D1 — `AuthGuard` endurecido por rol con prop `allow`

**Chosen:** añadir una prop opcional `allow?: readonly UserRole[]` a `AuthGuard`, tipada con `components["schemas"]["UserRole"]` (la unión `"SUPER_ADMIN" | "TENANT_OWNER" | "PROPERTY_MANAGER" | "CLEANER" | "TECHNICIAN"` que `permissions.ts:27` ya reutiliza). El comportamiento queda ramificado así, en el orden escrito:

1. `status ∈ {"loading", "refreshing"}` → `StatePanel aria-busy` (sin cambio).
2. `status === "expired"` → `StatePanel role="alert"` + redirect a `/login?returnTo=...` (sin cambio).
3. `status ∈ {"anonymous"}` → redirect a `/login?returnTo=...` (sin cambio; `allow` no se evalúa porque no hay rol).
4. `status === "authenticated"` y `allow` presente y `user.role ∉ allow` → redirect a `/login?denied=role` (nuevo). El ref `redirecting` se reaprovecha para no re-disparar.
5. `status === "authenticated"` y (`allow` ausente o `user.role ∈ allow`) → renderiza `children` (sin cambio).

El wrapper no declara `allow` por defecto para preservar el comportamiento actual de los tres layouts que ya usan `AuthGuard` (R1 #4 enumera los segmentos; los `layout.tsx` se actualizan para pasar `allow` explícitamente). El redirect a `?denied=role` se hace desde el mismo `useEffect` que ya hace los demás redirects, así la lectura del pathname y la escritura del `?returnTo` previo siguen el mismo patrón. `allow` se declara `readonly` para alinearse con `ROLE_UI_PERMISSIONS` y para que TypeScript rechace `push`/`pop` accidentales en runtime.

Rejected: usar un `Set<UserRole>` interno para `O(1)` lookup — solo hay cuatro entradas en `ROLE_HOME`, no se justifica el Set; un `Array.includes()` encaja con la convención del árbol. Pasar `allow` por contexto (un `<RoleAllowProvider>` envolviendo cada segmento) — un provider por segmento es más boilerplate que una prop en el layout y rompe la simetría con el resto de las props de `AuthGuard`. Reescribir `AuthGuard` como `<RequireAuth allow={...}>` y un `<RequireRole>`` separado — más superficie pública y dos guardas que comparten la mitad del código.

### D2 — Mini-landing `/welcome` en un route group `(authenticated)` nuevo

**Chosen:** crear `frontend/app/(authenticated)/` con su propio `layout.tsx` (Server Component, `ShellFrame` con `skipLink`, `topbar` mínimo — `Brand` + `UserMenu` en el slot `end`, sin `sidebar` ni `bottomNavigation` ni `footer`) y `welcome/page.tsx` (Client Component). El layout aplica `AuthGuard` sin `allow` (R2 #4): cualquier usuario autenticado entra, y la página decide a qué shell mandarlo vía `roleHome(user.role)`. La página renderiza un `StatePanel` con título `auth.welcome.title`, descripción `auth.welcome.body` y un `Button` (`next/link`) cuyo `href` sale de `roleHome(roleParam)`. Si `?role` falta o no coincide con `user.role` (R2 #3), redirige a `roleHome(user.role)` sin parpadear la pantalla — un `useEffect` con un `redirecting` ref lo ejecuta en el primer render tras `status === "authenticated"`.

La razón de un route group nuevo y no de colgar `/welcome` bajo `(public)` o `(workspace)` es doble: la página vive antes del shell (el usuario aún no ha elegido shell) y necesita un chrome mínimo con `UserMenu` para que el field user pueda cerrar sesión sin tener que volver a `/login`; cualquier shell existente arrastra navegación o sidebar que no aplican aquí. `ShellFrame` es la primitiva común de los cinco shells (`shell-frame.tsx:12-60`) y admite pasar `topbar` con los slots `start`/`end` directamente — CleanerShell y TechnicianShell son buenos moldes (`cleaner-shell.tsx:22-55`, `technician-shell.tsx:22-55`), pero el de `/welcome` no necesita `ThemeSwitcher`/`LocaleSwitcher`/`PageTitle`/footer (los dos últimos son ruido en una pantalla que existe solo para decidir a qué shell ir).

Rejected: colgar `/welcome` en `(public)` con un `if (status === "authenticated")` dentro de la página — `(public)` no monta `UserMenu` y/o `AuthGuard`, así que tendríamos que reimplementar lo que `ShellFrame` ya da. Reusar `CleanerShell` o `TechnicianShell` directamente — `PageTitle` muestra «Mis tareas» / «Mis incidencias» y los shells son mobile-first sin bottom-nav solo porque su perfil tiene un único destino navegable (`frontend-foundation.md` §Shells), lo que no aplica a `/welcome` donde el usuario aún no está en ninguno.

### D3 — `useLogoutMutation` envuelve a `useAuth().logout()` y `UserMenu` migra a la mutation

**Chosen:** crear `frontend/features/auth/hooks/use-logout-mutation.ts` con un `useMutation` que llama `clients.apiClient.request("/api/v1/auth/logout", { method: "POST" })` (mismo endpoint que hoy en `auth-provider.tsx:121-125`), envuelve la purga local en `try/finally` (mutación → `purgeSessionCache()` → `clearSessionTokens()` → `clearSessionPresent()`), expone `mutateAsync` con `retry: 1` reutilizando `retryPolicy` (`lib/api/retry-policy.ts:4-9`) parametrizada a 1 reintento (no 2) — los `ApiError` 4xx siguen sin reintentar. En `onSuccess` se invoca `queryClient.removeQueries({ queryKey: ["auth", "me"] })` explícitamente (R3 #4). En `onSettled` no se hace nada: la purga local del `try/finally` ya ocurrió.

`UserMenu.handleLogout` (`user-menu.tsx:66-80`) reescrito como `await logoutMutation.mutateAsync()` → `router.replace("/")` → `router.refresh()` (R3 #1, mismo orden que `frontend-auth-session.md:78-80`). `useAuth().logout()` se queda como wrapper delgado (R3 #5): si los tokens están presentes llama `useLogoutMutation().mutateAsync()` y devuelve, si no llama directamente a `purgeSessionCache()` + `setStatus("anonymous")` (mantiene el comportamiento del caller actual, ya obsoleto). Marcado `@deprecated use useLogoutMutation().mutateAsync()` en JSDoc.

La razón de un wrapper thin en lugar de eliminar `useAuth().logout()` es que R3 #5 lo pide explícitamente; eliminarlo sería derogación silenciosa. La migration de `UserMenu` ocurre en el mismo change, así que el wrapper queda como una reliquia documentada para cualquier consumidor futuro, no como código caliente.

Rejected: reescribir `useAuth().logout()` directamente sin wrapper — R3 #5 obliga al wrapper, y derogarlo en un design sin reabrir el requisito sería unaSurface sprawl. Poner `useLogoutMutation` en `lib/api/` — los hooks de mutation viven con su dominio; `lib/api/` es el transporte y no debería saber de la sesión. Usar `useMutation` con `mutationKey: ["auth", "logout"]` y cachear — el logout no se beneficia de caché; `mutationKey` solo añade un punto de invalidación sin uso.

### D4 — `serverFetch` para que `RootPage` llame `/auth/me`

**Chosen:** crear `frontend/lib/api/server-client.ts` (`import "server-only"`) con una función `serverFetch<Path>(path, options)` que:

- lee `getServerConfig().backendInternalUrl` y construye la URL absoluta hacia el backend (sin pasar por el proxy `/api/[...path]` — el proxy añade un hop y forwardea headers que no nos interesan aquí);
- reenvía la cabecera `Cookie` desde `cookies()` de `next/headers` por defecto (opt-out con `forwardCookies: false`);
- impone `signal: AbortSignal.timeout(2000)` (R4 #6);
- tipa el path y el response con la misma `paths`/`components` de `lib/api/generated/openapi.d.ts` (sin reescribir tipos);
- devuelve el response parseado o lanza con la misma forma que `parseApiError` en errores no-2xx.

`RootPage` (`frontend/app/page.tsx:35-48`) sustituye la lectura actual de cookie por:

1. lee la cookie `autohostai.session.present`;
2. si ausente → renderiza el landing sin red (R4 #1, comportamiento actual);
3. si presente → `serverFetch("/api/v1/auth/me", { forwardCookies: true })` con timeout 2 s;
4. `2xx` → `redirect("/dashboard", "replace")` (R4 #3, comportamiento actual);
5. `401` → `cookies().delete(SESSION_PRESENT_COOKIE)` y renderiza el landing (R4 #4);
6. `>=500` o timeout/red → `redirect("/dashboard", "replace")` sin tocar la cookie (R4 #5 — un 5xx no equivale a logout).

La capa `server-only` está justificada porque lee `BACKEND_INTERNAL_URL` (única excepción al `no-restricted-imports` que la steering permite a `app/api/[...path]/route.ts`; aquí el lector vive en `lib/`, no en `app/`, así que cumple la regla). El forward de cookies es opt-in y solo lo usa `/auth/me`: el resto del código cliente pasa por `lib/api/client.ts` que es client-side.

Rejected: pasar por el proxy `/api/[...path]` desde el Server Component — añade un hop y arrastra cabeceras que el proxy reescribe (R5 de `ingress-https-dev`) para un caso de uso que no las necesita. Crear un cliente paralelo que respete el contrato OpenAPI a mano — `lib/api/generated/openapi.d.ts` ya da los tipos y `parseApiError` ya da los errores; duplicar esSurface sprawl.

#### Issue a resolver antes de implementar D4 (también como OQ1)

La propuesta R4 #2 dice "para que el bearer JWT en memoria del navegador llegue al backend". El JWT vive en `session-store.ts` (un módulo en memoria del navegador, no persistente por regla de `frontend-auth-session.md:47-48`); el Server Component que renderiza `/` corre en Node, sin acceso al JavaScript runtime del navegador, y `cookies()` solo expone cookies — el JWT no es una cookie. Por tanto, `serverFetch("/api/v1/auth/me")` **siempre** recibe un `401` desde el backend (sin `Authorization: Bearer`), porque el backend no puede reconstruir el bearer desde ninguna cabecera disponible para el Server Component.

La consecuencia operativa de R4 tal como está:

- visitante con sesión en memoria + cookie presente → R4 siempre dispara el caso 5 (`>=5xx`/`401`) → la cookie se purga y se renderiza el landing, perdiendo el redirect a `/dashboard` que R4 #3 promete como "comportamiento actual";
- el caso 4 ("`2xx` → `/dashboard`") es inalcanzable desde un Server Component con el modelo de auth actual.

R6 #1 lo describe como "**runtime nuevo o pestaña cerrada**" — el visitor ya no tiene sesión en memoria, lo que coincide con el caso de R4 → `401`. Pero R6 #3 dice "cookie y JWT válido en memoria → redirigir a `/dashboard`", lo cual es exactamente el caso que el Server Component no puede verificar. La steering de seguridad lo prohíbe tajantemente: "THE SYSTEM SHALL NOT escribir tokens ni credenciales en localStorage, sessionStorage, cookies, IndexedDB, Zustand ni otro almacenamiento persistente." (`frontend-auth-session.md:47-48`).

Hay tres salidas posibles y se necesita la decisión del usuario antes de implementar — ver OQ1. La implementación que sigue es lo que la propuesta describe, con el conocimiento explícito de que el caso 4 es inalcanzable en el modelo actual. Si R4 sale como está, el comportamiento observable de `/` para un visitante autenticado con cookie cambia: antes iba a `/dashboard`, ahora va al landing (y el cliente debe navegar a `/dashboard` por su cuenta). Si eso es aceptable, D4 tal cual; si no, hay que resolver OQ1 primero.

### D5 — `LoginForm` «Volver a la landing» y `?denied=role`

**Chosen:** dos cambios en `frontend/features/auth/components/login-form.tsx`:

- R5: el `<Link href="/">` actual (`login-form.tsx:105-110`) pasa a `<button type="button">` con `role="link"` y `aria-label={t("backToLanding")}`. El handler ejecuta, en este orden: `clearSessionPresent()` → `router.replace("/")` → `router.refresh()` (R5 #1). El `clearSessionPresent` antes del `router.replace` garantiza que cuando `RootPage` re-evalúe en el siguiente Server Component render, la cookie esté ya ausente y tome el camino «sin red» de R4 #1 (R5 #2).
- R1 #5: cuando el query param `denied=role` está presente y `status === "authenticated"` (porque el visitante fue expulsado de un segmento por no tener rol permitido), la página muestra el `StatePanel` con título localizado `auth.deniedRole` durante un único render y luego redirige a `roleHome(user.role)`. El redirect usa el mismo `useEffect` con ref `redirecting` que `AuthGuard` para evitar bucles si la redirección vuelve a fallar el guard.

El `<button type="button">` se justifica porque `<a href="/">` ejecuta la navegación nativa antes de cualquier `onClick`, así que la cookie seguiría presente en la siguiente petición a `RootPage` y volveríamos al bucle (R5 #2 explícito). `<button>` da el control del orden al handler.

Rejected: dejar el `<Link>` y purgar la cookie desde un `<Script>` antes de la navegación — un `<Script strategy="beforeNavigate">` ejecuta antes de la transición pero no garantiza el orden con `cookies()` porque la cookie es síncrona y el script también; `<button>` lo deja explícito en el handler. Usar `useNavigate` programático sin `router.replace` — la steering de auth pide `router.replace("/") → router.refresh()` literal (`frontend-auth-session.md:79-80`); cambiar la primitiva sería derogación silenciosa.

### D6 — Paridad i18n y `features/auth/index.ts`

**Chosen:** añadir a `locales/es/auth.json` y `locales/en/auth.json` las claves: `deniedRole`, `welcome.title`, `welcome.body`, `welcome.cta.CLEANER`, `welcome.cta.TECHNICIAN`. El `auth.welcome.cta.TENANT_OWNER` etc. no se añaden porque la mini-landing solo se renderiza para `CLEANER` y `TECHNICIAN` (R2 #2 explícito); el resto de roles van a `/dashboard` sin pantalla intermedia.

Exportar desde `frontend/features/auth/index.ts`:

- `AuthGuard` (ya está; no cambia la firma pero cambia el tipo — `allow` se vuelve parte del tipo público);
- `useLogoutMutation` (nuevo);
- `roleHome` (no estaba reexportado desde el índice del feature; se reexporta para que la nueva página `/welcome` y cualquier consumidor futuro lo importen del barrel en vez de `../lib/role-home`).

Rejected: añadir `welcome.cta` para los cuatro roles MVP — R2 #3 redirige a `roleHome(user.role)` sin mostrar la pantalla si `?role` no es `CLEANER` o `TECHNICIAN`; las claves huérfanas en `auth.json` fallarían el test de paridad de catálogos.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Guards | `frontend/features/auth/components/auth-guard.tsx` | Nueva prop `allow?: readonly UserRole[]`. Nuevo redirect a `/login?denied=role` cuando `allow` está definido y `user.role ∉ allow`. |
| Guards | `frontend/features/auth/components/auth-guard.test.tsx` | Añadir tests: `allow` definido + rol correcto → renderiza children; rol incorrecto → redirect a `/login?denied=role`; `allow` ausente → comportamiento previo. |
| Guards | `frontend/app/(workspace)/layout.tsx`, `frontend/app/(field)/cleaner/layout.tsx`, `frontend/app/(field)/tech/layout.tsx` | Pasar `allow={[TENANT_OWNER, PROPERTY_MANAGER]}`, `allow={[CLEANER]}`, `allow={[TECHNICIAN]}` respectivamente (R1 #4). |
| Login | `frontend/features/auth/components/login-form.tsx` | Reemplazar el `<Link>` de `backToLanding` por `<button type="button">` con handler `clearSessionPresent → router.replace("/") → router.refresh()`. Nuevo `useEffect` para `?denied=role` + `status === "authenticated"`: mostrar `auth.deniedRole` y redirigir a `roleHome(user.role)`. |
| Login | `frontend/features/auth/components/login-form.test.tsx` | Tests del orden del handler (R5 #5) y del flujo `?denied=role`. |
| Logout | `frontend/features/auth/hooks/use-logout-mutation.ts` | Nuevo hook `useLogoutMutation` con `useMutation` y `try/finally` para purga local. |
| Logout | `frontend/features/auth/components/user-menu.tsx` | `handleLogout` reescrito: `await logoutMutation.mutateAsync()` → `router.replace("/")` → `router.refresh()`. |
| Logout | `frontend/lib/auth/auth-provider.tsx` | `logout()` queda como wrapper delgado `@deprecated`, delega en `useLogoutMutation().mutateAsync()` si hay tokens. |
| Logout | `frontend/features/auth/index.ts` | Exportar `useLogoutMutation`. |
| Logout | `frontend/features/auth/components/user-menu.test.tsx` | Tests del nuevo flujo (mutación + redirect + refresh; purga local aunque la mutation falle). |
| Root | `frontend/app/page.tsx` | Si cookie presente → `serverFetch("/api/v1/auth/me")`. `2xx` → `redirect("/dashboard", "replace")`. `401` → `cookies().delete(SESSION_PRESENT_COOKIE)` + render landing. `5xx`/timeout → `redirect("/dashboard", "replace")` sin tocar cookie. |
| Root | `frontend/lib/api/server-client.ts` | Nuevo helper server-only (`import "server-only"`). Usa `getServerConfig().backendInternalUrl`. `forwardCookies: true` por defecto. `AbortSignal.timeout(2000)` configurable. Tipa con `paths`/`components` de openapi. |
| Welcome | `frontend/app/(authenticated)/layout.tsx` | Nuevo: Server Component. `ShellFrame` con `topbar` (`Brand` + `UserMenu` en `end`), `skipLink`. Sin `sidebar`/`bottomNavigation`/`footer`. Aplica `AuthGuard` sin `allow`. |
| Welcome | `frontend/app/(authenticated)/welcome/page.tsx` | Nuevo: Client Component. Lee `?role=`, verifica contra `useAuth().user.role`, renderiza `StatePanel` + `Button` (next/link) a `roleHome(role)`. Si falta o no coincide, redirige a `roleHome(user.role)`. |
| Welcome | `frontend/app/(authenticated)/welcome/page.test.tsx` | Tests: `?role=CLEANER` + `user.role=CLEANER` → renderiza CTA con `href=/cleaner`; `?role=TENANT_OWNER` + `user.role=CLEANER` → redirige a `/cleaner`; `?role` ausente → redirige a `roleHome(user.role)`. |
| i18n | `frontend/locales/{es,en}/auth.json` | Añadir `deniedRole`, `welcome.title`, `welcome.body`, `welcome.cta.CLEANER`, `welcome.cta.TECHNICIAN`. |
| i18n | `frontend/features/auth/index.ts` | Exportar `useLogoutMutation` y `roleHome`. |
| Auth | `frontend/lib/auth/auth-provider.tsx` (JSDoc) | Marcar `useAuth().logout()` con `@deprecated use useLogoutMutation().mutateAsync()`. |

## Data & interfaces

No schema, no migraciones, no variables de entorno. El endpoint `GET /api/v1/auth/me` ya existe y la cookie `autohostai.session.present` ya existe. La nueva mini-landing introduce una superficie nueva en el router (`/welcome`) pero no toca el contrato del backend. La nueva `useLogoutMutation` consume el endpoint `/api/v1/auth/logout` que ya está en el openapi; no hay wrapper manual de endpoint.

`serverFetch` no expone una URL pública nueva — usa `BACKEND_INTERNAL_URL` que ya está en `getServerConfig()`. Cumple la regla de `frontend-foundation.md` que limita los lectores de `BACKEND_INTERNAL_URL`: el lector vive en `lib/`, no en `app/`.

## Risks & mitigations

- **Riesgo (R4) — regresión de UX para usuarios con sesión válida**: el Server Component no puede verificar el JWT, así que `/` siempre purga la cookie y renderiza el landing para un visitante autenticado que aún tiene `autohostai.session.present`. Antes iba a `/dashboard`. Mitigación: la sesión client sigue viva en memoria; el visitante puede llegar a `/dashboard` por la URL, el sidebar de un shell, o un link dentro de un email. La pantalla de landing expone el flujo «Entrar» como hoy. Si la regresión es inaceptable, OQ1 propone tres salidas.
- **Riesgo (R1) — falsa sensación de protección**: `allow` es un guard UX, no RBAC (`permissions.ts:7-13` lo dice explícito). Un `CLEANER` con un JWT válido aún puede llamar `/dashboard` si conoce la URL — el backend rechaza con `403`. Mitigación: el R1 #1 ya lo dice en la propuesta y `lib/auth/permissions.ts:7-13` lo afirma; el JSDoc nuevo de `AuthGuard` lo recordará.
- **Riesgo (D3) — purga local en `useLogoutMutation` corre aunque la mutation falle**: el `try/finally` ejecuta `purgeSessionCache()` + `clearSessionTokens()` + `clearSessionPresent()` incluso si el endpoint devuelve `5xx`. Esto es lo que hoy hace `auth-provider.tsx:127-134` y la spec lo fija como regla (`frontend-auth-session.md:81-86`). El cambio mantiene la regla.
- **Riesgo (R3 #1) — orden de `mutateAsync → router.replace → router.refresh`**: si el caller no respeta el orden, el cookie purged no llega a `RootPage` en el siguiente Server Component render. Mitigación: tests fijos al orden en `user-menu.test.tsx` (mismo patrón que ya fija `frontend-auth-session.md:79-80`).
- **Riesgo (welcome) — `?role` mismatch**: un visitor autenticado como `CLEANER` que pega `/welcome?role=TENANT_OWNER` no debe ver el CTA de `/dashboard`. La R2 #3 ya lo prevé: redirect sin mostrar. Test cubre ambos casos.
- **Riesgo (back-to-landing) — orden de llamadas antes de la navegación**: si el handler ejecutara `router.replace` antes de `clearSessionPresent`, la cookie seguiría presente en el siguiente Server Component render y volveríamos al bucle (R5 #2). El test de orden lo blinda.

## Decisiones del gate

- **OQ1 (R4 server-side)**: aceptada la regresión. R4 se implementa tal cual está descrito: cualquier cookie presente termina en landing tras purga. La sesión client sigue viva; el visitor llega a `/dashboard` por link, sidebar o URL pegada. La consecuencia operativa (visible para QA) es que un visitante autenticado con cookie que abre `/` ya no aterriza en `/dashboard` automáticamente. No se introducen Server Actions ni cookies de sesión. El issue de la propuesta queda documentado aquí para no reabrirlo en `/sdd:review`.
- **OQ2 (chrome de `(authenticated)/welcome`)**: layout con `Brand` + `UserMenu` en el `topbar`, sin `ThemeSwitcher`, `LocaleSwitcher`, `PageTitle`, `footer`, `sidebar` ni `bottomNavigation`. `/welcome` es una pantalla de transición; los controles que solo tienen sentido dentro de un shell se omiten.
- **OQ3 (`useAuth().logout()`)**: queda como wrapper delgado `@deprecated use useLogoutMutation().mutateAsync()` que delega en la mutation si están los tokens, o aplica la purga local directamente si no. Cumplimiento literal de R3 #5.

## Plan de diagramas

No. La interacción entre los seis requisitos cabe en una tabla; las transiciones de estado de AuthGuard (cinco ramas) caben en una tabla markdown; el flujo de `RootPage` con cookie presente es lineal (cookie ausente → landing; cookie presente → `/auth/me` con tres ramas por status). Un SVG aquí costaría ~140k de contexto y diría lo mismo que este documento. Si surge ambigüedad durante `/sdd:review`, se genera con `/sdd:diagram`.