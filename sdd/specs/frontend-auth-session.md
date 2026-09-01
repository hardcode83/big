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
- THE SYSTEM SHALL llevar un contador monótono de **generación de sesión**
  (`lib/auth/session-store.ts`, expuesto como `getSessionGeneration()`), que
  avanza en los dos escritores del almacén efímero: al escribir tokens y al
  limpiarlos. Es lo que permite a un consumidor saber que la identidad cambió
  bajo sus pies sin suscribirse al provider — la usa la mutación optimista de
  `notifications-inbox-web` para no revertir sobre la caché de la sesión
  entrante.
- WHEN se declara una sesión expirada, THE SYSTEM SHALL limpiar los tokens en
  el listener de la notificación, y no solo purgar la caché: una sesión
  declarada expirada no debe conservar credenciales en memoria, y por dos
  caminos (`SessionInvalidatedError` y «No refresh token available») las
  conservaba. **Contrapartida aceptada a sabiendas**: eso anula la guarda de
  `refresh-coordinator.ts`, que limpiaba tokens solo si la generación no se
  había movido, de modo que un refresco viejo que resuelve después de un login
  nuevo tira los tokens de la sesión nueva y ésta se recupera sola en el
  siguiente `401`. Se aceptó porque antes de ese cambio la misma carrera ya
  terminaba en `expired` —lo que se pierde es una recuperación que nadie
  usaba— y porque la alternativa, una sesión expirada con credenciales vivas,
  es peor. La salida está escrita en la entrada de roadmap
  `auth-session-generation-semantics`.
- **Deuda conocida, latente**: el `catch` de `refresh()` llama a
  `purgeSessionCache()` sola, sin limpiar tokens y sin notificar expiración,
  así que es el único camino de purga que **no** mueve la generación. Hoy no
  la pisa nadie —ningún `useAuth()` del árbol desestructura `refresh`—, y el
  arreglo bueno es mover el incremento dentro de la propia purga, para que
  «toda purga invalida todo snapshot en vuelo» sea cierto por construcción.
  Misma entrada de roadmap.

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
