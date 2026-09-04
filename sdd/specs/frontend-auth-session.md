# Sesión de autenticación del frontend

## Purpose

El frontend conecta `/login` con el contrato de autenticación del backend y
expone la identidad autenticada a la interfaz. Mantiene los JWT solo durante el
runtime actual del navegador, coordina su renovación y ofrece guards client-side
para UX; el backend conserva la autoridad sobre autorización, RBAC y tenant.

## Requirements

### Login e identidad

- WHEN el usuario envía el formulario válido de `/login`, THE SYSTEM SHALL
  llamar a `POST /api/v1/auth/login` mediante el cliente HTTP centralizado y
  mantener los tokens recibidos únicamente en el almacén efímero.
- WHEN el login tiene éxito, THE SYSTEM SHALL llamar a `GET /api/v1/auth/me` y
  SHALL exponer `user`, `role` y `tenant_id` devueltos por el backend.
- IF el login o la carga de identidad falla, THEN THE SYSTEM SHALL limpiar la
  sesión local, mostrar un error localizado y mantener al usuario en `/login`.
- WHEN el login tiene éxito y la URL no trae `?returnTo=` válido (mismo origen,
  ruta que empieza por `/`), THE SYSTEM SHALL redirigir al usuario a la shell
  correspondiente a su rol: `/dashboard` para `TENANT_OWNER` y
  `PROPERTY_MANAGER`, `/cleaner` para `CLEANER`, `/tech` para `TECHNICIAN`. Un
  rol desconocido cae a `/dashboard` por defecto. El cálculo usa el `user.role`
  devuelto por `/auth/me` durante el login (no una petición extra) y SHALL
  delegarse en un único helper `roleHome(role)` cuya tabla es la fuente de
  verdad. WHEN el `?returnTo=` es válido, THE SYSTEM SHALL respetarlo sobre
  la redirección por rol — la intención del visitante manda.

### Sesión efímera y refresh

- THE SYSTEM SHALL mantener access y refresh JWT únicamente en memoria del
  runtime JavaScript actual.
- WHEN una petición autenticada elegible recibe `401`, THE SYSTEM SHALL
  ejecutar como máximo un refresh coordinado mediante
  `POST /api/v1/auth/refresh` y SHALL reintentar una sola vez la petición
  original si el refresh tiene éxito.
- THE SYSTEM SHALL excluir login, refresh, logout y peticiones sin bearer del
  refresh automático, y SHALL compartir una única operación entre peticiones
  concurrentes elegibles.
- IF el refresh falla o la sesión se invalida mientras está en curso, THEN THE
  SYSTEM SHALL limpiar los tokens, marcar la sesión como expirada y evitar
  nuevos reintentos automáticos para esa petición.
- WHEN ocurre un reload completo, se cierra la pestaña o comienza un nuevo
  runtime, THE SYSTEM SHALL perder la sesión y requerir un nuevo login.
- THE SYSTEM SHALL NOT escribir tokens ni credenciales en localStorage,
  sessionStorage, cookies, IndexedDB, Zustand ni otro almacenamiento persistente.
- THE SYSTEM SHALL llevar dos contadores monótonos independientes en
  `lib/auth/session-store.ts`, cada uno con un único dueño: **generación de
  caché** (`getSessionGeneration()`), que avanza en `setSessionTokens` y en
  `purgeSessionCache()` y es lo que permite a un consumidor saber que debe
  descartar un snapshot de caché sin suscribirse al provider — la usa la
  mutación optimista de `notifications-inbox-web` para no revertir sobre la
  caché de la sesión entrante—; y **generación de identidad**
  (`getTokenGeneration()`), que avanza únicamente en `setSessionTokens` y en
  `clearSessionTokens` — nunca en una purga de caché por sí sola — y es la que
  usa `refresh-coordinator.ts` para decidir si un refresco en vuelo sigue
  perteneciendo a la sesión que lo inició. Los dos contadores se movían como
  uno solo hasta que una purga de caché ajena a la sesión (p. ej. el listener
  de otro cliente de feature) podía hacer que esa guarda creyera erróneamente
  que la sesión había cambiado; la separación existe para que una purga sin
  escritura ni borrado de tokens no se confunda con un cambio de identidad
  (entrada de roadmap `auth-session-generation-semantics`, tercera ronda).
- WHEN se declara una sesión expirada, THE SYSTEM SHALL purgar la caché en el
  listener de la notificación y SHALL limpiar también los tokens siempre que,
  tras la purga, no queden tokens vivos de una sesión más nueva
  (`getSessionTokens()` es `null`) — no basta con purgar la caché: una sesión
  declarada expirada no debe conservar credenciales en memoria, y por dos
  caminos (`SessionInvalidatedError` y «No refresh token available») las
  conservaba. El listener honra la guarda del coordinador de `refresh`, que
  limpia tokens solo si la generación de identidad no se ha movido — así, la
  carrera del refresco viejo que resuelve después de un login nuevo se
  resuelve sin destruir los tokens de la sesión nueva, y la pérdida (un `401`
  que se recupera solo) se reduce a un caso de uso que ningún consumer actual
  desestructura. La decisión queda registrada en la entrada de roadmap
  `auth-session-generation-semantics`.
- Toda purga del `QueryClient` singleton —venga de donde venga, incluido el
  camino del `catch` de `refresh()`— avanza `sessionGeneration` en 1;
  `purgeSessionCache()` es la única función del módulo que bumpea el contador
  como efecto de purga. Las mutaciones optimistas de `use-mark-read.ts` y
  `use-mark-all-read.ts` confían en esa invariante para descartar el rollback
  cuando la sesión cambió bajo la mutación.

### Provider y transporte

- THE SYSTEM SHALL integrar `AuthProvider` en el orden
  `RuntimeConfigProvider → I18nProvider → AuthProvider → QueryProvider`.
- WHEN el cliente HTTP envía una petición autenticada, THE SYSTEM SHALL añadir
  el access token mediante `getHeaders` y SHALL delegar los `401` elegibles en
  `onUnauthorized`.
- THE SYSTEM SHALL crear la URL desde el `apiBaseUrl` público; el navegador SHALL
  NOT leer `BACKEND_INTERNAL_URL`.

### Guards y cierre de sesión

- WHEN una superficie protegida se renderiza sin sesión autenticada, THE SYSTEM
  SHALL redirigir client-side a `/login` y SHALL conservar solo una intención
  de navegación interna segura.
- WHEN el usuario cierra sesión, THE SYSTEM SHALL intentar
  `POST /api/v1/auth/logout` si existe sesión, limpiar siempre el almacén en
  memoria, purgar la caché de consultas del `QueryClient` singleton, purgar la
  cookie no sensible `autohostai.session.present` que marca la raíz como
  autenticada y devolver la UX al landing público (`/`) — no a `/login`. La
  raíz, al re-evaluar la cookie ausente en el siguiente Server Component
  render, sirve el landing directamente.
- WHERE el shell autenticado expone el control de cierre de sesión, THE SYSTEM
  SHALL montar un `UserMenu` en el slot `end` del `Topbar` de
  `WorkspaceShell`, `CleanerShell` y `TechnicianShell`; SHALL NOT montarlo en
  `PublicShell` (el login no muestra un usuario autenticado) ni en `GuestShell`
  (el guest accede por token, sin sesión que cerrar). El control dispara un
  `AlertDialog` de confirmación antes de invocar el cierre, y SHALL ejecutar
  tras la confirmación, en este orden:
  `useLogoutMutation().mutateAsync()` → `router.replace("/")` →
  `router.refresh()`, para que el botón «atrás» no devuelva a una ruta sin
  sesión y la raíz re-evalúe la cookie recién purgada. `useAuth().logout()` se
  conserva como envoltorio `@deprecated` para consumidores previos; ejecuta
  exclusivamente la limpieza local (purga de caché, borrado de tokens y de la
  cookie de presencia, reset a `anonymous`) sin viaje al servidor, y SHALL NOT
  ser usado por código nuevo — los call sites nuevos SHALL invocar
  `useLogoutMutation().mutateAsync()` directamente.
- IF el `POST /api/v1/auth/logout` falla o no existe sesión, THEN THE SYSTEM
  SHALL purgar igualmente la caché de consultas del `QueryClient` singleton,
  purgar la cookie `autohostai.session.present` y limpiar el almacén en
  memoria — la limpieza local es incondicional; el `try/finally` del
  `UserMenu` SHALL ejecutar `router.replace("/")` y `router.refresh()` aunque
  el endpoint haya devuelto 5xx o error de red.
- WHEN el `AuthProvider` reemplaza la identidad autenticada por un usuario
  cuyo `id` o `tenant_id` difiere del anterior —incluido el paso a `null` por
  expiración o por refresh fallido, y el paso `null → user` del primer login
  del runtime—, THE SYSTEM SHALL purgar todas las entradas del `QueryClient`
  singleton **antes** de que el nuevo estado sea visible para el resto de la
  app.
- THE SYSTEM SHALL purgar la caché con `QueryClient.clear()` (vacía
  `queryCache`, `mutationCache` y el estado no reactivo), sin discriminar por
  clave ni condicionar la purga al evento que disparó el cambio: el logout
  explícito y cualquier otra transición de identidad son el mismo hecho desde
  el punto de vista de la caché.
- THE SYSTEM SHALL integrar la función de purga como dependencia en un único
  sentido (`lib/auth → lib/query`), sin introducir un `useEffect` paralelo ni
  mover el `QueryClient` ni su ciclo de vida fuera de `lib/query`.
- THE SYSTEM SHALL proteger las superficies workspace, cleaner y technician
  con `AuthGuard`, y SHALL dejar sin guard JWT la shell pública y el portal guest.
- THE SYSTEM SHALL tratar rol y tenant como datos de contexto para UI y SHALL
  NOT implementar autorización de negocio, RBAC ni tenant isolation en frontend.
  Los guards no protegen HTML server-rendered ni sustituyen al backend.

### Estados localizados y verificación

- WHEN se muestra un estado visible de autenticación, THE SYSTEM SHALL resolver
  sus textos mediante el namespace `auth` presente en los catálogos ES y EN.
- IF falta una clave de `auth` en cualquiera de los locales, THEN THE SYSTEM
  SHALL fallar el test automatizado de paridad.
- THE SYSTEM SHALL verificar login, identidad, errores, refresh, logout, ausencia
  de persistencia, redirección client-side y purga del `QueryClient` singleton
  en cada transición de identidad del runtime (logout, swap de usuario, refresh
  fallido y expiración notificada) mediante tests.

## Key files

- `frontend/lib/auth/session-store.ts` — tokens efímeros.
- `frontend/lib/auth/refresh-coordinator.ts` — refresh single-flight.
- `frontend/lib/auth/auth-provider.tsx` — contexto y ciclo de sesión, incluido
  `logout()` (best-effort al endpoint, purga local incondicional) y
  `clearSessionPresent()` que borra la cookie `autohostai.session.present`.
- `frontend/lib/auth/session-cache-purge.ts` — purga del `QueryClient`
  singleton en cada transición de identidad del runtime.
- `frontend/lib/auth/session-presence-cookie.ts` — la cookie no sensible
  `autohostai.session.present` (`max-age=31536000`, `samesite=lax`) que
  `markSessionPresent()` escribe tras login y `clearSessionPresent()` borra
  tras logout; la raíz `/` la lee en Server Component para decidir landing
  vs redirect.
- `frontend/lib/query/query-client.ts` — `QueryClient` singleton y
  `QueryClient.clear()` consumido por `session-cache-purge.ts`.
- `frontend/lib/api/client.ts` — transporte tipado y hook de `401`.
- `frontend/features/auth/components/login-form.tsx` — formulario, redirección
  por rol vía `roleHome(user.role)` (con la interstitial `/welcome?role=<rol>`
  para `CLEANER` y `TECHNICIAN` cuando no hay `?returnTo=` válida; ver
  `frontend-auth-role-routing`) y control «Volver a la landing»
  implementado como `<button type="button">` con `role="link"` cuyo handler
  ejecuta `clearSessionPresent()` → `router.replace("/")` → `router.refresh()`
  en ese orden, para que la raíz re-evalúe la cookie ya purgada y sirva la
  landing sin red.
- `frontend/features/auth/components/user-menu.tsx` — control de cierre de
  sesión en el `Topbar` de las tres shells autenticadas (workspace, cleaner,
  technician); dispara `AlertDialog` de confirmación y ejecuta
  `logout() → router.replace("/") → router.refresh()`.
- `frontend/features/auth/lib/role-home.ts` — tabla `ROLE_HOME` (los cuatro
  roles MVP) y `roleHome(role)` con default a `/dashboard`.
- `frontend/features/auth/components/auth-guard.tsx` — guard client-side de UX.
- `frontend/app/providers.tsx` — composición de providers.
- `frontend/locales/{es,en}/auth.json` — estados localizados, incluyendo
  `backToLanding`, `logoutConfirmTitle`, `logoutConfirmBody`,
  `logoutConfirmCancel` y `logoutConfirmAction`.
- `frontend/locales/{es,en}/navigation.json` — `userMenu.triggerLabel`,
  `userMenu.logout`, `userMenu.anonymous`.
