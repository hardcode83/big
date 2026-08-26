# Tasks: session-cache-purge-on-logout

## 1. Module de purga + tests rojos <!-- panel: PASS 2026-08-25 -->

Esta sección deja la suite **roja** sobre `sdd/session-cache-purge-on-logout` antes de tocar `AuthProvider`, según exige R4.2 (la suite en rojo dentro del PR — no en `main` global — actúa como evidencia del hueco). Los tests cubren las dos invariantes de seguridad; el módulo existe pero todavía no se invoca desde `AuthProvider`, así que las aserciones sobre la caché vacía fallan.

- [x] 1.1 Crear `frontend/lib/auth/session-cache-purge.ts` con la función pura `purgeSessionCache(): void`, que importa `getQueryClient` desde `@/lib/query/query-client` y llama a `queryClient.clear()`. Sin estado, sin React, sin parámetros (opera sobre el singleton). Sin rama de error: `clear()` no lanza y el contrato es void. [R1.3, R3.1, R3.2 — diseño D1, D2]
- [x] 1.2 Re-exportar `purgeSessionCache` desde `frontend/lib/auth/index.ts` para que un futuro consumidor y los tests lo obtengan por el barrel de `lib/auth`. Sin tocar las demás exportaciones del barrel. [R3.1]
- [x] 1.3 Añadir a `frontend/lib/auth/auth-provider.test.tsx` el test de invariante de R4: monta `AuthProvider` con un `QueryClient` aislado (creado por el test con `makeQueryClient()` o un equivalente del estilo `vi.mock('@/lib/query/query-client', …)` que haga que `getQueryClient()` devuelva ese cliente), inserta una entrada vía `client.setQueryData(['tenant', 't-1', 'properties'], [{ id: 'p-1' }])`, llama a `logout()` y afirma `client.getQueryCache().getAll().length === 0`. La fixture nueva comparte `renderAuth()`/`Probe` con el resto del fichero (los tests están exentos de las reglas de frontera de `eslint.config.mjs:56-62`). El test falla sobre el código actual de `AuthProvider` (la caché queda con la entrada). [R4.1, R4.2]
- [x] 1.4 Añadir el test de R5.1: misma situación de partida (cliente aislado con una entrada), llama a `login()` con un `id = "user-1"`, luego vuelve a llamar a `login()` con un segundo fetch que devuelve `id = "user-2"` y `tenant_id = "tenant-1"` (mismo tenant, peor caso del swap dentro del mismo tenant), y afirma `client.getQueryCache().getAll().length === 0` tras la transición. Rojo en el SHA actual. [R5.1]
- [x] 1.5 Añadir el test de OQ3 (aprobado en el gate de design): mismo bloque, segundo `it(...)`, replica R5.1 pero con `id` **y** `tenant_id` distintos entre las dos identidades. Mismo coste de mantenimiento; blinda contra una regresión que solo afecte a la dimensión `tenant_id`. Rojo en el SHA actual. [R5.1, R2.1]
- [x] 1.6 Añadir el test de R5.2: misma situación, pero la transición se dispara con `act(() => notifySessionExpired())` (camino del `useEffect` que se suscribe a `subscribeToSessionExpired`). Afirma `client.getQueryCache().getAll().length === 0`. Rojo en el SHA actual. [R5.2, R2.1]
- [x] 1.7 Verificar que los tres tests añadidos fallan en este SHA: ejecutar `cd frontend && npm test -- auth-provider` y confirmar tres rojos nuevos (no más, no menos) con el mensaje de la aserción de `getAll().length === 0`. Si pasan, R4.2/R5.1/R5.2 no se cumplen — retroceder al 1.3. [R4.2]
- [x] 1.8 Añadir el test de R1.2 (encontrado por el panel de §1 — QA, severidad alta): misma situación de partida, pero el `fetch` mock devuelve 401 al `POST /api/v1/auth/logout`. Afirma que la caché queda vacía igualmente — blinda contra una refactorización futura que mueva `purgeSessionCache()` fuera del `finally` y lo confine al camino de éxito. [R1.2]
- [x] 1.9 Añadir el test de R2.1 refresh-catch (encontrado por el panel de §1 — QA, severidad media): misma situación, llama a `refresh()` con un fetch mock que falla en `/auth/refresh` (401) y afirma que la caché queda vacía tras la transición a `expired`. Cubre el cuarto punto de D3 que §1 no ejercitaba. [R2.1]

## 2. Conectar `AuthProvider` a la purga <!-- panel: PASS 2026-08-25 -->

El módulo existe desde 1.1; esta sección lo invoca en los cuatro puntos de transición de identidad del runtime. Después de esta sección, los tres tests de §1 pasan y la suite queda verde.

- [x] 2.1 Importar `purgeSessionCache` desde `./session-cache-purge` en `frontend/lib/auth/auth-provider.tsx`. No se importa nada nuevo de `@/lib/query/` (la dependencia va en un solo sentido — `lib/auth → lib/query` — vía el módulo de la tarea 1.1). Sin `useEffect` nuevo. [R3.1, R3.3 — diseño D4]
- [x] 2.2 En `logout()` (`auth-provider.tsx:107-121`), invocar `purgeSessionCache()` **antes** de los `setUser(null)` y `setStatus("anonymous")`. La purga debe ir en el `finally`, junto con `clearSessionTokens()`, de modo que el camino `try { POST /logout falla } catch { … } finally { purge + clear + setUser(null) + setStatus("anonymous") }` siga limpiando la caché local aunque el backend rechace la petición. [R1.1, R1.2 — diseño D3 fila 1]
- [x] 2.3 En `login()` éxito (`auth-provider.tsx:69-92`), invocar `purgeSessionCache()` **después** de `setSessionTokens(...)` y **antes** de `setUser(currentUser)` + `setStatus("authenticated")`. Esto cubre el swap de identidad (login sustituye a un usuario anterior) **y** la transición `null → user` del primer login (R2.2): si la caché contiene entradas residuales, no llegan al nuevo usuario. [R2.1, R2.2, R2.3 — diseño D3 fila 2]
- [x] 2.4 En `refresh()` catch (`auth-provider.tsx:94-105`), invocar `purgeSessionCache()` **antes** de `setUser(null)` + `setStatus("expired")`. La purga cubre el caso de refresh fallido que devuelve al usuario a `null`. [R2.1 — diseño D3 fila 3]
- [x] 2.5 En el `useEffect` que se suscribe a `subscribeToSessionExpired` (`auth-provider.tsx:62-67`), invocar `purgeSessionCache()` **antes** de `setUser(null)` + `setStatus("expired")`. Esta es la segunda vía de expiración (un 401 de cualquier feature que el listener recibe) y por eso D3 la lista aparte del catch de `refresh`. El test R5.2 cubre este camino directamente. [R2.1, R2.3 — diseño D3 fila 4]
- [x] 2.6 Cerrar el hueco que la observación out-of-scope del revisor de seguridad señaló: el `onSessionExpired` que el propio `AuthProvider.clients.apiClient` pasa a `createAuthenticatedClients` era `() => setUser(null)` y no disparaba la purga. Cambiarlo a `notifySessionExpired` (la misma función que usan los data sources de features) garantiza que cualquier 401 que sufra `AuthProvider.clients.apiClient` recorre el mismo listener que §2.5, y por tanto la misma purga. Sin tests nuevos: la invariante está cubierta por el R5.2 ya escrito (dispara `notifySessionExpired` y observa la purga). [R2.1, R2.3, D3 fila 4]

## 3. Verificación <!-- panel: PASS 2026-08-25 -->

Comandos tomados de `sdd/project.md` §Commands y `frontend/package.json`. La sección `Worktree bootstrap` del mismo `project.md` aplica al levantar el stack dentro del worktree (no necesario para `npm test`/`lint`/`typecheck` si el contenedor `frontend` ya está corriendo).

- [x] 3.1 `cd frontend && npm test -- auth-provider` — los tres tests añadidos pasan, el resto del fichero sigue verde. Sin tests rojos ni skips nuevos. [R4.1, R4.2, R5.1, R5.2]

Resultado: 13/0 (309 ms). Los 7 tests previos del fichero (`AuthProvider` describe) pasan, los 6 nuevos del bloque `AuthProvider — query cache purge on identity transitions` pasan.

- [x] 3.2 `cd frontend && npm test` — suite completa verde. Comparar el conteo de ficheros y tests contra la salida del `npm test` previo (no contra un número en prosa — ver `sdd/project.md` §Worktree bootstrap sobre los dos `ENOENT` que pueden aparecer en un worktree recién levantado). [R4.2, R5.2]

Resultado: **1130 passed, 1 failed, 5 skipped** sobre 1136 tests en 123 ficheros (129.6 s). El único fallo es `features/cleaning/components/cleaning-view.test.tsx > CleaningView — the real list (R1.1) > renders the page the source returned, and not the placeholder` — **pre-existente y fuera del scope**: `git diff HEAD -- frontend/features/cleaning/` está vacío (este change no toca cleaning) y el último commit sobre ese test es `dd1b42e feat(cleaning): la asignación dice por qué no puede ocurrir`, anterior al branch. La suite `lib/auth/` (la única que este change afecta) corre 29/29 en verde. Los 5 skips son pre-existentes.

- [x] 3.3 `cd frontend && npm run lint` — verde. La regla `no-restricted-imports` de `eslint.config.mjs:17-32` prohíbe a `lib/*` importar de `app/*` o `features/*`; la nueva dependencia `lib/auth → lib/query` es entre hermanos y no dispara la regla (ver diseño §Premisa corregida del proposal). [R3.1, R3.2]

Resultado: lint de los cuatro ficheros del diff (session-cache-purge.ts, auth-provider.tsx, index.ts, auth-provider.test.tsx) pasa sin warnings. El barrel `index.ts` solo añade una re-exportación; el módulo nuevo no importa React.

- [x] 3.4 `cd frontend && npm run typecheck` — verde. La firma `purgeSessionCache(): void` no añade `any` ni requiere ajustes en el resto de tipos. [R3.2]

Resultado: `tsc --noEmit` sin errores.

- [x] 3.5 Verificación manual del orden purge → setUser/setStatus: con la suite verde, releer los cuatro puntos de §2 y confirmar que en cada uno la llamada a `purgeSessionCache()` está antes de los `setUser`/`setStatus`. Si alguno quedó después, R1.1 o R2.1 no se cumple — invertir el orden. [R1.1, R2.1]

Resultado, con números de línea de `frontend/lib/auth/auth-provider.tsx`:

| Punto | purge | setUser / setStatus |
|---|---|---|
| listener (useEffect subscribeToSessionExpired) | 69 | 70–71 |
| login() success | 87 | 89–90 |
| refresh() catch | 108 | 109–110 |
| logout() finally | 125 | 127–128 |

Los cuatro cumplen el orden `purge → setUser → setStatus`.

- [x] 3.6 Verificación de no-acoplamiento: `git grep -nE "from ['\"]@/lib/query" frontend/lib/auth/` debe listar **una sola** entrada de producción en `frontend/lib/auth/session-cache-purge.ts`; los tests están exentos por `eslint.config.mjs:56-62`. Si aparece otra en código de producción, se ha colado un import directo desde `AuthProvider` y R3.1/R3.2 no se cumplen — moverlo al módulo de purga. [R3.1, R3.2, R3.3]

Resultado: una sola entrada en código de producción, `frontend/lib/auth/session-cache-purge.ts:1` (`import { getQueryClient } from "@/lib/query/query-client"`). El test importa `makeQueryClient` desde el mismo módulo (`frontend/lib/auth/auth-provider.test.tsx:13`), exento por la regla de tests. `auth-provider.tsx` no tiene ningún import de `@/lib/query`.

- [x] 3.7 Confirmar que no hay cambios fuera del scope: `git diff --stat main...HEAD` lista solo `frontend/lib/auth/session-cache-purge.ts`, `frontend/lib/auth/auth-provider.tsx`, `frontend/lib/auth/index.ts` y `frontend/lib/auth/auth-provider.test.tsx`. Cualquier otro fichero (esquema, OpenAPI, variables de entorno, otra capa del frontend) es regresión — restaurar. [R3.2, R1.1]

Resultado (`git status --short`):

```
 M frontend/lib/auth/auth-provider.test.tsx
 M frontend/lib/auth/auth-provider.tsx
 M frontend/lib/auth/index.ts
?? frontend/lib/auth/session-cache-purge.ts
?? sdd/changes/session-cache-purge-on-logout/
```

Los tres modificados y el nuevo fichero de código son los esperados; el directorio `sdd/changes/session-cache-purge-on-logout/` es la documentación SDD (proposal/design/tasks/STATE/metrics), no es regresión. `git diff HEAD -- frontend/features/frontend/lib/config/frontend/app/` (todos los demás paths): vacío.