# Proposal: session-cache-purge-on-logout

## Why

El `QueryClient` del frontend es un singleton por navegador (`frontend/lib/query/query-client.ts:22-34`) y el `logout` de `AuthProvider` descarta tokens y usuario sin tocarlo (`frontend/lib/auth/auth-provider.tsx:107-121`). Un cambio de operador en la misma pestaña puede por tanto servir al segundo los datos cacheados del primero **sin que salga ninguna petición** — y por tanto sin ningún 403 que pueda intervenir. Las claves llevan ámbito de tenant (`tenantScopedKey`), así que la exposición es **mismo-tenant / distinto-rol**, no cruce de tenants; en este producto ese es justamente el modelo que separa a la propietaria y la manager de la limpiadora y el técnico, y `properties-web` puso en esa caché lo que ese permiso protege (`PropertySummaryDto`, con direcciones, códigos internos y SSID de WiFi de la cartera).

El hueco lo levantaron dos features independientes —el review de `conversations-inbox` (2026-08-22) y el panel de seguridad de `properties-web` (2026-08-22)— que llegaron a la misma conclusión sin hablarse, así que su casa natural es una entrada propia. El análisis largo está en `sdd/roadmap/session-cache-purge-on-logout.md`.

## What changes

Pasará a existir un gancho que purga la caché de consultas en cada transición de identidad del runtime —explícita (logout) e implícita (cambio de `user.id` o `tenant_id`, y expiración que devuelve al usuario a `null`)— antes de que el nuevo estado sea visible para el resto de la app. La costura entre `AuthProvider` (que conoce la transición) y `lib/query` (que posee el `QueryClient`) se mantiene dentro de los límites de dependencia que el lint ya enforza: `lib/auth` no importa `lib/query` ni viceversa; el gancho es un módulo nuevo al que ambos pueden llamar. La invariante queda fijada por dos tests que fallan si cualquier entrada sobrevive a un logout o a un swap de identidad.

## Requirements

### R1 — Purgar la caché de consultas en el logout explícito

**As a** review de seguridad, **I want** que la caché de consultas se vacíe cuando el usuario cierra sesión, **so that** un login posterior en la misma pestaña no reciba datos cacheados bajo la sesión anterior.

Acceptance criteria:

1. WHEN el `AuthProvider` ejecuta `logout()` y limpia los tokens, THE SYSTEM SHALL purgar todas las entradas del `QueryClient` singleton **antes** de que `status` transicione a `anonymous` y `user` quede a `null`.
2. IF el `POST /api/v1/auth/logout` falla, THEN THE SYSTEM SHALL purgar la caché de todas formas — la limpieza local es incondicional, igual que ya lo es la del almacén de tokens.
3. WHEN el gancho purga la caché, THE SYSTEM SHALL NO llamar a `invalidateQueries` ni a `removeQueries` por clave: la purga es completa y no discrimina.

### R2 — Purgar la caché ante cualquier cambio de identidad

**As a** review de seguridad, **I want** que la caché se vacíe cuando la identidad autenticada cambia por una ruta distinta al logout explícito, **so that** un swap de operador (login directo sobre una sesión ya caducada, refresh fallido que pasa a `expired`, o re-login con otro usuario) no sirva datos del anterior.

Acceptance criteria:

1. WHEN `AuthProvider` reemplaza `user` por un valor cuyo `id` o `tenant_id` difiere del anterior —incluido el paso a `null` por expiración o por refresh fallido—, THE SYSTEM SHALL purgar todas las entradas del `QueryClient` singleton **antes** de que el nuevo estado sea visible para el resto de la app.
2. THE SYSTEM SHALL considerar la transición `null → user` (primer login del runtime) como un cambio de identidad a efectos de esta regla: si la caché contiene entradas residuales de un runtime anterior (p.ej. un HMR que rehidrata), no llegan al nuevo usuario.
3. THE SYSTEM SHALL NO condicionar la purga al evento que disparó el cambio: el logout explícito de R1 y este cambio de identidad son el mismo hecho desde el punto de vista de la caché, y se cubren por la misma función.

### R3 — La costura entre `lib/auth` y `lib/query` no introduce acoplamiento

**As a** mantenedor del layering, **I want** que el gancho de purga viva en un módulo al que ambos puedan llamar sin violar la dirección de dependencias actual, **so that** el lint de fronteras (`test/eslint-boundaries.test.ts`) siga verde y la nueva función sea testeable por separado.

Acceptance criteria:

1. THE SYSTEM SHALL exportar la función de purga desde un módulo que `AuthProvider` pueda importar sin que `lib/auth` pase a depender de `lib/query`, y que `QueryProvider` (o quien monte el `QueryClient`) pueda invocar sin que `lib/query` pase a depender de `lib/auth`.
2. THE SYSTEM SHALL NO mover el `QueryClient` ni su ciclo de vida a `lib/auth`: el singleton sigue siendo propiedad de `lib/query` y el gancho solo le pide que se vacíe.
3. THE SYSTEM SHALL NO añadir un proveedor de React nuevo: la purga se invoca desde los callbacks que `AuthProvider` ya tiene, sin un `useEffect` adicional que monte un listener paralelo.

### R4 — Test de invariante: tras un logout, la caché está vacía

**As a** mantenedor, **I want** un test automatizado que falle si un cambio futuro deja una entrada en la caché tras un logout, **so that** la garantía de seguridad no pueda regresar silenciosamente.

Acceptance criteria:

1. THE SYSTEM SHALL incluir un test que monte `AuthProvider` sobre un `QueryClient` al que se le ha insertado al menos una entrada cacheada (basta con que `getQueryData` devuelva un valor para una clave cualquiera), invoque `logout()` y THEN SHALL afirmar que el cliente no conserva ninguna entrada (`queryClient.getQueryCache().getAll().length === 0`).
2. THE SYSTEM SHALL hacer pasar el test con la implementación actual de `logout` **antes** del fix (debe fallar) y SHALL hacerlo pasar **después** del fix; el commit del fix y el commit del test se entregan juntos, y la suite en rojo sobre `main` actúa como evidencia del hueco.

### R5 — Test de invariante: tras un cambio de identidad, la caché está vacía

**As a** mantenedor, **I want** un test análogo al de R4 que cubra el camino del swap de identidad sin logout explícito, **so that** la misma garantía se mantenga por la ruta implícita que R2 abre.

Acceptance criteria:

1. THE SYSTEM SHALL incluir un test que, con `AuthProvider` montado y un `QueryClient` que contiene entradas cacheadas bajo un `user.id` / `tenant_id` dados, reemplace al usuario por uno con `id` distinto (mismo `tenant_id` para reproducir el peor caso) y SHALL afirmar que el cliente no conserva ninguna entrada tras la transición.
2. THE SYSTEM SHALL incluir un test adicional que cubra la transición a `null` (expiración simulada): con la misma situación de partida, invocar el callback de sesión expirada y SHALL afirmar que la caché queda vacía.

## Out of scope

- Rediseñar el modelo de sesión efímera (memoria + refresh) ni mover el JWT a otro almacenamiento — `steering/frontend.md:18` y `specs/frontend-auth-session.md` siguen vigentes.
- Tocar el mapa de permisos del frontend: la ausencia de `READ_PROPERTIES` en ese mapa es una entrada distinta si se decide que debe estar; este change no la cierra.
- Purgar selectivamente por clave (p.ej. añadir `user.id` a `tenantScopedKey` o poner `gcTime: 0` por hook): la decisión de la entrada de roadmap es purga completa en la transición, no cosmética por hook; esos paliativos se mencionan en `sdd/roadmap/session-cache-purge-on-logout.md` y se rechazan por la misma razón que allí se da.
- Cambiar el comportamiento del backend: la revocación de tokens y el `logout` server-side están en `specs/auth-tenancy.md` y no se tocan.
- Añadir un evento nuevo en `lib/api/client.ts` para esta purga: el lugar correcto es el `AuthProvider`, que ya conoce la transición; añadir un canal paralelo partiría el conocimiento y complicaría los tests.

## Affected specs

- `sdd/specs/frontend-auth-session.md` — añadir al apartado "Guards y cierre de sesión" la obligación de purgar el `QueryClient` en el logout y en cualquier cambio de identidad (incluyendo expiración a `null`). El requisito actual solo menciona "limpiar el almacén en memoria" y "devolver la UX a `/login`", lo cual no cubre la caché de TanStack Query.
