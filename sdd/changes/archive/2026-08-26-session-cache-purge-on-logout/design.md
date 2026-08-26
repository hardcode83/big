# Design: session-cache-purge-on-logout

## Context

`frontend/lib/query/query-client.ts:22-34` mantiene un `QueryClient` singleton
por navegador (`browserQueryClient`), compartido por todas las features
(`QueryProvider` lo monta una vez en `frontend/lib/query/query-provider.tsx:10`).
`frontend/lib/auth/auth-provider.tsx:107-121` implementa `logout()` descartando
tokens y reseteando `user` a `null` sin tocarlo, así que una segunda sesión
en la misma pestaña —sea `logout` + `login`, sea una transición
`null → user` por re-login tras refresh fallido, sea un swap de `user.id` por
re-login sobre sesión aún activa— puede leer las entradas cacheadas de la
anterior sin que salga ninguna petición, y por tanto sin que un 403 pueda
intervenir. La costura entre `lib/auth` (que conoce la transición) y
`lib/query` (que posee el `QueryClient`) es la decisión de diseño real.

## Premisa corregida del proposal

R3.1 dice «el lint ya enforza la dirección `lib/auth` ↛ `lib/query`». **No es
así**: `frontend/eslint.config.mjs:17-32` solo prohíbe a `lib/*` importar de
`app/*` o `features/*`. `lib/auth` y `lib/query` son hermanos dentro de `lib/`
y un import cruzado entre ellos **no** dispara la regla. Lo que R3.1
persigue —que `lib/auth` no termine dependiendo de `lib/query` y
viceversa— es por tanto un principio de diseño, no un requisito del lint.
La consecuencia práctica es la misma que el proposal pidió (un módulo
nuevo que ambos importan) pero por una razón distinta, y conviene dejarla
escrita para que nadie la confunda con una restricción del eslint.

## Decisions

### D1 — Módulo nuevo `frontend/lib/auth/session-cache-purge.ts` con una función pura

**Elegido:** un módulo nuevo bajo `lib/auth/` —el directorio que ya posee la
noción de transición de identidad— que exporta una sola función
`purgeSessionCache(): void` y la implementa llamando a
`getQueryClient().clear()` importado desde `@/lib/query/query-client`.
`AuthProvider` la invoca en los cuatro puntos donde la identidad cambia
(`logout`, login que sustituye a un usuario, refresh que pasa a `expired`, y
listener de `onSessionExpired`); `QueryProvider` **no** la importa y la
dirección de la dependencia queda en un solo sentido
(`lib/auth` → `lib/query`), que es lo que R3.1 quería en la práctica.

Rejected: poner la función dentro de `lib/query/` — invertiría la dependencia
y obligaría a `lib/auth` a importarla desde el módulo equivocado, y a
`QueryProvider` (que ya monta el `QueryClient`) a entrar en la decisión de
cuándo purgar, que es exactamente lo que R3.3 prohíbe (un `useEffect`
paralelo). Y rechazada también la opción de un módulo neutral en `lib/` al
mismo nivel que `auth/` y `query/` — ganaría simetría pero pierde vecindad
con el código que conoce las transiciones, y la siguiente persona que
toque `auth-provider` no la va a buscar ahí.

### D2 — `purgeSessionCache()` llama a `queryClient.clear()`, no a `invalidateQueries` ni `removeQueries`

**Elegido:** la única operación que satisface R1.3 (purgar **todo**, sin
discriminar por clave) es `QueryClient.clear()`, que vacía
`queryCache`, `mutationCache` y `queryClient` no reactivos a la vez. Es
además la única que el camino del cambio de identidad puede invocar sin
conocer la clave del dato cacheado — que es justamente el problema, porque
la identidad anterior puede haber escrito bajo
`tenantScopedKey(tenantA, "properties", …)` y la nueva bajo
`tenantScopedKey(tenantB, "properties", …)`, y un `removeQueries({ queryKey:
["tenant", tenantA, …] })` dejaría en pie las claves de la sesión anterior
que **no** llevan `tenant_id` (globales del runtime, si los hay), además de
ser más código por más覆盖面 que necesita.

Rejected: `queryClient.removeQueries()` con filtro por prefijo — deja
mutaciones en `mutationCache` y todo lo que no lleve `tenant_id` en la
clave; tampoco cubre el caso de `null → user` (R2.2) donde la identidad
anterior era `null` y la purga no puede filtrar por «lo del null». Y
`queryClient.invalidateQueries()` — no borra nada, solo marca como
`stale`; un consumidor que ya tiene la promesa en vuelo recibiría el
dato cacheado.

### D3 — `AuthProvider` invoca la purga **antes** de los `setUser`/`setStatus` en cada transición de identidad

**Elegido:** cada uno de los cuatro puntos donde `user` o `status` cambia
como efecto de una transición (no como efecto de una carga de identidad
nueva sobre sesión vacía) hace `purgeSessionCache()` y **después** los
`setX(...)`. Los cuatro puntos, con el sitio en el código actual:

| Punto | Línea actual | Transición que cubre |
|---|---|---|
| `logout()` `finally` | `auth-provider.tsx:117-119` | R1.1, R1.2 |
| `login()` éxito tras `setSessionTokens` | `auth-provider.tsx:82-83` | R2.1 (login sustituye a un usuario anterior), R2.2 (primer login sobre `null`) |
| `refresh()` catch | `auth-provider.tsx:101-103` | R2.1 (refresh fallido → `expired`, vuelve a `null`) |
| `useEffect` que escucha `subscribeToSessionExpired` | `auth-provider.tsx:62-67` | R2.1 (otra vía de expiración — un 401 de cualquier feature) |

En los cuatro el orden es: purga → setUser → setStatus. R1.1 y R2.1 lo
exigen explícitamente («antes de que el nuevo estado sea visible»), y la
secuencia es trivial porque `queryClient.clear()` es síncrono y va en el
mismo tick del event loop que las llamadas a `setState`; el siguiente
render ya observa el estado nuevo con la caché vacía. La función
`purgeSessionCache` es la misma en los cuatro sitios, exactamente como
R2.3 pide («logout explícito y cambio de identidad son el mismo hecho
desde el punto de vista de la caché»).

Rejected: un `useEffect` en `AuthProvider` que escuche cambios de `user` y
purgue — R3.3 lo prohíbe por un motivo bueno: introduce una suscripción
paralela al estado de React, con un frame de carrera entre el `setUser` y
el `useEffect` durante el cual la UI ya observa la nueva identidad con la
caché vieja aún poblada. Es exactamente el bug que R1.1/R2.1 quieren
impedir, montado dos componentes más arriba. Y rechazado también un
listener sobre `session-store.getSessionGeneration()` — la generación
cambia en `setSessionTokens` y `clearSessionTokens`, que **no** cubre la
vía de `onSessionExpired` cuando el backend fuerza el logout sin tocar
tokens (la limpiadora hace un click y la sesión cae sin re-login), y
añadir esa cobertura re-metería un `useEffect` paralelo, con el mismo
problema.

### D4 — `QueryClient` sigue siendo propiedad de `lib/query` y `QueryProvider` no se toca

**Elegido:** la purga se pide desde fuera (`AuthProvider` llama a
`purgeSessionCache()`, que internamente hace `getQueryClient().clear()`).
`QueryProvider` no importa nada nuevo, no monta un `useEffect`, y su
cuerpo de tres líneas no cambia. R3.2 lo pide así, y la razón es la
misma que en D1: la asimetría «`lib/auth` conoce la transición,
`lib/query` posee la caché» se mantiene si la dependencia va en un solo
sentido. La función `purgeSessionCache` es la única excepción a esa
asimetría — necesita el cliente — y por eso vive en `lib/auth/` (que
conoce cuándo) y solo ella importa `lib/query/` (que posee qué).

Rejected: pasar el `QueryClient` por contexto y que `QueryProvider` lo
exponga a `AuthProvider` — invierte la dirección real del problema:
ahora `lib/query` sabe de `lib/auth`. Mover la purga a un
`useEffect` de `QueryProvider` que escuche cambios del contexto de
auth — R3.3 lo prohíbe y, peor, **no** podría ejecutarse en el orden
correcto (un `useEffect` siempre corre después de que el estado es
visible).

### D5 — Tests de invariante en `frontend/lib/auth/auth-provider.test.tsx`, rojos sobre `main` antes del fix

**Elegido:** los dos tests viven en el fichero de tests de `AuthProvider`
— los tests están exentos de las reglas de frontera
(`eslint.config.mjs:56-62`), así que pueden importar `getQueryClient` para
insertar entradas cacheadas y luego montar `AuthProvider` sobre ese
mismo cliente. La forma exacta:

- **R4.1**: monta `AuthProvider` con un `QueryClient` de test
  (`makeQueryClient()`), llama a `client.setQueryData(["tenant", "t-1",
  "properties"], [{...}])`, dispara `logout()` y afirma
  `client.getQueryCache().getAll().length === 0`. Rojo en `main` (el
  `logout` actual no toca la caché), verde con el fix.
- **R5.1**: misma situación de partida, llama a `login()` con un usuario
  de `id = "user-1"`, luego dispara `login()` con un segundo fetch que
  devuelve `id = "user-2"` y `tenant_id = "tenant-1"`, y afirma
  `client.getQueryCache().getAll().length === 0` tras la transición.
  Rojo en `main` (el segundo `setUser` no purga), verde con el fix.
- **R5.1b** (OQ3, aprobada): segundo `it(...)` en el mismo bloque, con
  `id` y `tenant_id` ambos distintos entre las dos identidades. Mismo
  coste de mantenimiento y blinda contra una regresión que solo afecte
  a la dimensión `tenant_id` del swap.
- **R5.2**: misma situación, dispara `notifySessionExpired()` (ya
  expuesto por `lib/api/authenticated-client.ts:22` y usado por el test
  de expiración existente) y afirma lo mismo. Rojo en `main`, verde con
  el fix.

Los tres tests se commitean **junto al fix**, no antes: R4.2 lo exige
explícitamente («la suite en rojo sobre `main` actúa como evidencia del
hueco»), y la manera de que la suite esté roja en `main` es que el
commit del fix y el commit del test vayan juntos, dejando `main` con
tests rojos sólo en el SHA del fix. Lo que esto significa para
`/sdd:run`: la tarea 1 introduce el módulo de purga + un test rojo
*sin* el `purgeSessionCache()` aún invocado desde `AuthProvider`; la
tarea 2 invoca la purga en los cuatro puntos y los tres tests pasan.

Rejected: tests separados en `frontend/lib/query/` — el comportamiento
que cubren es de `AuthProvider` (no se rompe la caché por su culpa), y
tener el test junto al sujeto lo deja más cerca del cambio que lo haría
regresar. Y rechazada la opción de un test E2E con Playwright — R4.2
pide tests unitarios rojos sobre `main`, no una grabación de navegador
que se rompe o se queda verde por motivos no relacionados con la
purga.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Frontend / lib/auth | `frontend/lib/auth/session-cache-purge.ts` (nuevo) | Exporta `purgeSessionCache(): void`, que llama a `getQueryClient().clear()`. Sin estado, sin React. |
| Frontend / lib/auth | `frontend/lib/auth/auth-provider.tsx` | Importa `purgeSessionCache`. La invoca antes de los `setUser`/`setStatus` en los cuatro puntos de D3. Sin `useEffect` nuevo. Sin cambio en la forma del contexto. |
| Frontend / lib/auth | `frontend/lib/auth/index.ts` | Re-exporta `purgeSessionCache` para que los tests (y un futuro consumidor) lo tengan en el barrel de auth. |
| Frontend / lib/query | `frontend/lib/query/query-client.ts`, `frontend/lib/query/query-provider.tsx` | **Sin cambios**. La decisión de D4 deja ambos ficheros intactos. |
| Frontend / tests | `frontend/lib/auth/auth-provider.test.tsx` | Añade los tres tests de D5. Comparte con el resto del fichero la fixture `renderAuth()` y `Probe`. |
| Spec | `sdd/specs/frontend-auth-session.md` | El commit de archivado añadirá al apartado "Guards y cierre de sesión" la obligación de purgar el `QueryClient` en el logout y en cualquier cambio de identidad. El proposal lo nombra como `Affected specs`; aquí se deja escrito para que `/sdd:tasks` lo recoja como tarea del run, no del design. |

## Data & interfaces

**Sin cambios de schema, sin migraciones, sin endpoints, sin variables de
entorno, sin cambios en el contrato HTTP.** El gancho opera exclusivamente
sobre estado en memoria del navegador (`browserQueryClient`).

**Firma del módulo nuevo** (sin código más allá de la firma, como
marca la skill):

```ts
// frontend/lib/auth/session-cache-purge.ts
export function purgeSessionCache(): void;
```

Sin parámetros porque opera sobre el singleton global; sin返回值
distinto de `void` porque el llamante no necesita confirmación. Si en
el futuro la caché se monta por usuario, este es el único punto que
cambia.

## Risks & mitigations

- **Orden de purga vs. `setUser`/`setStatus` (R1.1, R2.1)**. Riesgo: que
  React agrupe las actualizaciones y un consumidor vea primero la caché
  vacía y el estado nuevo, mientras que otro vea el estado nuevo con
  la caché aún poblada durante el mismo render. Mitigación: las pruebas
  de D5 leen el estado **fuera** de un `act` o un `findBy` que espere
  re-render; `queryClient.clear()` es síncrono, así que en el tick del
  `fireEvent` que dispara la transición, la caché ya está vacía cuando
  el siguiente render se ejecuta. Si en el futuro se introduce una
  transición asíncrona, ese día se añade un test que cubra el orden.

- **Tests rojos sobre `main` durante la ventana entre el commit del
  test y el commit del fix**. R4.2 lo pide a propósito. Mitigación: el
  PR se abre con los dos commits, no por separado, y la rama
  `sdd/session-cache-purge-on-logout` no se pushea ni se mergea con la
  suite en rojo. La frase «la suite en rojo sobre `main` actúa como
  evidencia del hueco» se refiere a la suite de **ese** PR, no a
  `main` global, y el diseño la respeta: la suite está roja sólo en
  el SHA que introduce el test sin el fix, y verde en el siguiente
  SHA, dentro de la misma rama.

- **Cobertura del camino `onSessionExpired` del `useEffect`**. D3 lo
  lista como uno de los cuatro sitios. El test R5.2 lo cubre
  directamente (`notifySessionExpired()` dispara la transición). Si el
  `useEffect` que se suscribe a `subscribeToSessionExpired` cambia de
  orden respecto a la inicialización del `QueryClient`, R5.2 falla —
  esto es deliberado, porque la invariante que el test protege es
  exactamente ésa.

- **El `QueryClient` de test no se comparte con el singleton del
  navegador**. Mitigación: el test importa `makeQueryClient` (no
  `getQueryClient`), crea su propio cliente y se lo pasa a
  `QueryClientProvider` dentro de un `MemoryRouter` o un wrapper. El
  `QueryProvider` real del árbol queda intacto, así que el singleton
  del navegador no se ensucia entre tests. Revisable durante
  `/sdd:tasks`.

## Open questions

_Ninguna abierta al cierre del gate._ Las tres preguntas del draft inicial
quedaron resueltas en el gate:

- **OQ1** (¿distinguir entre `mutationCache` y `queryCache`?): **no**.
  Se mantiene `queryClient.clear()`, que cubre ambas con una llamada.
- **OQ2** (¿añadir telemetría?): **no**. El proyecto no tiene capa de
  analítica en el frontend; instrumentar la purga hoy sería
  infraestructura para un consumidor que no existe.
- **OQ3** (¿cuarto test con `tenant_id` distinto?): **sí**. Como
  segundo `it(...)` en el mismo bloque, mismo coste de mantenimiento.
