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
  memoria, purgar la caché de consultas del `QueryClient` singleton y devolver
  la UX a `/login`.
- IF el `POST /api/v1/auth/logout` falla o no existe sesión, THEN THE SYSTEM
  SHALL purgar igualmente la caché de consultas del `QueryClient` singleton y
  limpiar el almacén en memoria — la limpieza local es incondicional.
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
- `frontend/lib/auth/auth-provider.tsx` — contexto y ciclo de sesión.
- `frontend/lib/auth/session-cache-purge.ts` — purga del `QueryClient`
  singleton en cada transición de identidad del runtime.
- `frontend/lib/query/query-client.ts` — `QueryClient` singleton y
  `QueryClient.clear()` consumido por `session-cache-purge.ts`.
- `frontend/lib/api/client.ts` — transporte tipado y hook de `401`.
- `frontend/features/auth/components/login-form.tsx` — formulario y retorno seguro.
- `frontend/features/auth/components/auth-guard.tsx` — guard client-side de UX.
- `frontend/app/providers.tsx` — composición de providers.
- `frontend/locales/{es,en}/auth.json` — estados localizados.
