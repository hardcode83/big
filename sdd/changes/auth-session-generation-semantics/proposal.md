# Proposal: auth-session-generation-semantics

## Why

`notifications-inbox-web` (archived 2026-08-29) fue el primer consumidor de mutaciones optimistas
del frontend y, al serlo, destapó **dos grietas de semántica en `frontend/lib/auth/`** que
cambian el comportamiento del módulo compartido sin que ningún consumidor pueda verlas desde
fuera. No se arreglaron en aquella bandeja porque tocan la semántica del módulo del que dependen
las cinco shells, el transporte de la API y todas las mutaciones futuras; esa decisión no le
pertenece a una feature de notificaciones. La entrada de roadmap
`sdd/roadmap/auth-session-generation-semantics.md` los describe con los interleavings y la
evidencia que la originaron; este proposal los convierte en requisitos verificables.

Los dos hechos, medidos en el run de `notifications-inbox-web` y reconfirmados por su panel de
`/sdd:review`:

1. **`refresh()` purga la caché sin mover la generación.** El `catch` de `refresh()` en
   `frontend/lib/auth/auth-provider.tsx` llama a `purgeSessionCache()` sola, sin
   `clearSessionTokens()` ni `notifySessionExpired()`. Como `sessionGeneration` sólo se mueve
   dentro de los dos escritores de tokens (`lib/auth/session-store.ts`), ése es el único
   camino de purga que la deja quieta. Una mutación optimista cuyo snapshot se tomó en esa
   generación pasa la guarda de `features/notifications/hooks/use-mark-read.ts` y
   `use-mark-all-read.ts` (línea que compara `context.sessionGeneration !== getSessionGeneration()`)
   y reescribe las filas del usuario saliente sobre la caché recién vaciada — exactamente lo que
   `notifications-inbox-web` R3.4 prohíbe.

   Hoy es **latente**, no vivo: ningún `useAuth()` del árbol desestructura `refresh` (los veinte
   sitios leen sólo `status`, `user` y `login`). Verificado dos veces: en el run del change y de
   nuevo por el panel de review. El arreglo bueno es mover el incremento de generación **dentro**
   de `purgeSessionCache()`, para que «toda purga invalida todo snapshot en vuelo» sea cierto por
   construcción y no por inspección de los llamantes.

2. **Limpiar tokens al expirar la sesión anula una guarda del coordinador.** El listener de
   `subscribeToSessionExpired` llama ahora a `clearSessionTokens()` sin condición, porque una
   sesión declarada expirada no debe conservar credenciales en memoria y por dos rutas
   (`SessionInvalidatedError` y «No refresh token available») las conservaba. Eso **anula la
   guarda** de `lib/auth/refresh-coordinator.ts:57`, que limpia tokens **sólo** si la
   generación no se movió. Interleaving concreto: refresco pendiente en la generación G → el
   usuario vuelve a autenticarse (`login()` escribe G+1 y espera `/auth/me`) → el refresco
   viejo resuelve, lanza `SessionInvalidatedError`, y el listener tira los tokens **de la sesión
   nueva**; `login()` acaba poniendo `authenticated` sobre un almacén vacío y se recupera solo
   en el siguiente `401`. Se aceptó a sabiendas en `frontend-auth-session` — antes del cambio
   esa misma carrera ya terminaba en `expired` — pero la salida está escrita en la entrada de
   roadmap: llevar la generación dentro de la notificación de expiración y limpiar sólo cuando
   la sesión que expira siga siendo la vigente.

## What changes

`frontend/lib/auth/` deja de tener un observador de la generación que depende de la buena
voluntad de cada llamante. `purgeSessionCache()` se convierte en la **única función que avanza
la generación como efecto de purga**, y los dos sitios donde hoy el incremento está acoplado a
otro nombre (`setSessionTokens` y `clearSessionTokens`) se replantean alrededor de ese
contrato. El listener de expiración deja de limpiar tokens cuando la sesión que está expirando
ya no es la vigente, restaurando la guarda del coordinador que `frontend-auth-session` diseñó.

Principalmente `frontend/lib/auth/` y `frontend/features/auth/`. Sin backend, sin esquema, sin
migraciones, sin contrato de API. La verificación es la suite de frontend más tests nuevos que
reproduzcan los dos interleavings descritos arriba — hoy ninguno de los dos tiene un test que
falle, y son los que justifican este cambio.

**Actualización post-panel (segunda ronda de `/sdd:review`)**: sdd-security encontró que el
único disparador de producción que compone `onSessionExpired` con `onStatusChange` vive en
`frontend/lib/api/authenticated-client.ts`, fuera del alcance declarado arriba — sin tocarlo,
la garantía de R3.3 sólo se sostenía en los tests que disparan el listener a mano, no en el
camino real. El alcance se extiende a ese fichero (y a su test nuevo,
`authenticated-client.test.ts`) por esa razón puntual; ver D7 en `design.md`.

## Requirements

### R1 — `purgeSessionCache()` avanza la generación por construcción

**As a** consumidor de mutaciones optimistas que se suscribe al cambio de sesión, **I want**
que toda purga de la caché invalide por construcción los snapshots que comparan
`getSessionGeneration()`, **so that** no hace falta que cada nuevo llamante de
`purgeSessionCache()` recuerde mover la generación por su cuenta para que la invariante siga
siendo cierta.

Acceptance criteria:

1. WHEN `purgeSessionCache()` se invoca, THE SYSTEM SHALL avanzar
   `getSessionGeneration()` en exactamente 1, además de vaciar el `QueryClient` singleton, y
   SHALL devolver `void`.
2. THE SYSTEM SHALL NOT alterar la signatura pública de `purgeSessionCache()` (sigue siendo
   `() => void`); el único efecto observable nuevo es el avance de `sessionGeneration`.
3. IF una prueba de unidad fija `getSessionGeneration() === N`, llama a `purgeSessionCache()`
   y vuelve a leer `getSessionGeneration()`, THEN THE SYSTEM SHALL reportar `N + 1` o
   superior, sin importar el orden en que se observe la caché vacía respecto al contador.
4. THE SYSTEM SHALL NOT duplicar el avance de `sessionGeneration` en `clearSessionTokens()`
   una vez que `purgeSessionCache()` se haga cargo: el incremento que
   `session-store.ts:30` realiza dentro de `clearSessionTokens()` se elimina, y los llamantes
   que necesiten mover la generación como parte de una limpieza de tokens lo hacen vía
   `purgeSessionCache()` (que sigue llamándose antes o después de tocar `currentTokens`).

### R2 — `purgeSessionCache()` documenta la invariante en un único sitio

**As a** futuro contributor de `lib/auth/`, **I want** que la regla «toda purga invalida todo
snapshot en vuelo» viva como contrato en `session-cache-purge.ts`, **so that** añadir un
nuevo camino de purga no pueda reintroducir el agujero por no saber que hay que bumpear la
generación.

Acceptance criteria:

1. THE SYSTEM SHALL documentar en el bloque JSDoc de `purgeSessionCache()` que la función
   avanza `sessionGeneration` además de vaciar el `QueryClient`, citando como razón la
   guarda de `use-mark-read.ts` / `use-mark-all-read.ts` que descarta snapshots obsoletos
   cuando la generación no coincide.
2. THE SYSTEM SHALL eliminar de `auth-provider.tsx` el comentario en
   `subscribeToSessionExpired` que advertía de que el `catch` de `refresh()` deja la
   generación quieta, porque deja de ser cierto: tras este cambio toda purga — venga de
   donde venga — la mueve.
3. THE SYSTEM SHALL eliminar de la spec `frontend-auth-session.md` la nota «Deuda conocida,
   latente» sobre `refresh()` y `purgeSessionCache()`, y SHALL sustituirla por una frase
   positiva que diga que toda purga invalida por construcción los snapshots en vuelo.

### R3 — El listener de expiración limpia tokens sólo cuando la sesión que expira sigue vigente

**As a** usuario que se ha re-autenticado en la misma pestaña mientras un refresco viejo
estaba en vuelo, **I want** que la notificación de expiración del refresco viejo **no**
destruya los tokens de la sesión nueva, **so that** la sesión válida no quede sin credenciales
por una carrera ya ganada.

Acceptance criteria:

1. WHEN el listener de `subscribeToSessionExpired` se ejecuta, THE SYSTEM SHALL capturar
   `sessionGeneration` en el momento de entrada al listener (queda como anclaje de comentario
   para un futuro cuerpo async), SHALL avanzar la generación mediante `purgeSessionCache()`
   (cumpliendo R1) y SHALL limpiar tokens únicamente si, tras la purga, `getSessionTokens()`
   es `null`. La comparación literal contra la generación capturada es imposible por
   construcción — `purgeSessionCache()` ya avanzó el contador antes de esta comprobación, así
   que «la generación capturada sigue siendo la vigente» sería falso en cada invocación —; D5
   documenta por qué la señal real es la presencia de tokens, no la generación.
2. THE SYSTEM SHALL NOT saltarse la guarda del coordinador
   (`refresh-coordinator.ts:57`) por haber movido la generación dentro del listener: si la
   generación capturada ya no es la vigente —porque un `login()` ocurrió mientras el listener
   esperaba para limpiar tokens—, el listener SHALL dejar los tokens intactos y SHALL NOT
   tocar la presencia (`clearSessionPresent`) ni el `status` (que ya reflejarán la sesión
   nueva instalada por `login()`).
3. THE SYSTEM SHALL mantener la transición de `status` a `"expired"` sólo cuando el listener
   haya limpiado tokens efectivamente; si la sesión vigente es otra, SHALL dejar el `status`
   que la nueva sesión haya instalado.
4. THE SYSTEM SHALL NOT añadir parámetros a la firma de `subscribeToSessionExpired`: el
   cambio vive dentro del listener, donde ya se conoce la generación capturada.

### R4 — Tests reproducen los dos interleavings descritos en la nota de roadmap

**As a** mantenedor del módulo `lib/auth/`, **I want** tests que fallen sin los arreglos de
R1 y R3 y pasen con ellos, **so that** una futura regresión que vuelva a desacoplar la
generación de la purga se detecte en la suite y no en producción.

Acceptance criteria:

1. THE SYSTEM SHALL añadir una prueba en `lib/auth/session-cache-purge.test.ts` (o donde
   toque) que verifique R1 directamente: el contador `sessionGeneration` se incrementa en
   cada llamada a `purgeSessionCache()`, incluso si el `QueryClient` ya está vacío.
2. THE SYSTEM SHALL añadir una prueba en `lib/auth/auth-provider.test.tsx` que reproduzca
   el interleaving de R3: con un `refresh()` en vuelo en generación G, un `login()` previo
   que escribe G+1, y la posterior notificación de `SessionInvalidatedError`, los tokens del
   nuevo login SHALL seguir presentes tras ejecutarse el listener de expiración, y el
   `status` SHALL ser el instalado por `login()` (no `"expired"`).
3. THE SYSTEM SHALL añadir una prueba análoga para el camino «No refresh token available»
   que llega al listener sin haber pasado por el `refresh-coordinator`: un `login()`
   previo SHALL sobrevivir a la notificación de expiración posterior con los mismos efectos
   que en (2).
4. THE SYSTEM SHALL añadir una prueba en `features/notifications/hooks/use-mark-read.test.tsx`
   (o en `use-mark-all-read.test.tsx`) que reproduzca el escenario del roadmap (1):
   una mutación optimista con snapshot tomado en la generación N SHALL descartar el rollback
   cuando, mientras la mutación está en vuelo, `refresh()` entra a su `catch` y purga la
   caché, aunque esa purga no haya tocado `clearSessionTokens()`. Sin R1 el test falla;
   con R1 pasa.
5. THE SYSTEM SHALL ejecutar la suite de frontend completa (`cd frontend && npm test`)
   desde el worktree con la solución documentada en `sdd/project.md` §«Worktree bootstrap»
   para los tests que leen el árbol por encima de `/app`; SHALL verificar el total contra
   el del run del change anterior (medido, no memorizado), y SHALL reportar ambos números
   junto al conteo de la suite de partida en el `evidence.md` del run.

### R5 — Las invariantes del coordinador se documentan en la spec y en el módulo

**As a** futuro lector de `refresh-coordinator.ts`, **I want** que la guarda de la línea 57
— «limpia tokens sólo si la generación no se movió» — siga formulada en positivo y no
dependa de que el llamante haga lo correcto, **so that** el comportamiento del coordinador
sea leíble por sí solo, sin tener que leer `auth-provider.tsx` para entender quién invalida
qué.

Acceptance criteria:

1. THE SYSTEM SHALL reformular el bloque JSDoc de `clearSessionTokens` y del `catch` de
   `refresh-coordinator.ts` para que diga en positivo lo que hace ahora: «si la generación
   no se ha movido bajo esta promesa, la limpieza de tokens es segura; en otro caso, los
   tokens actuales pertenecen a otra sesión y no se tocan». El comportamiento de la guarda
   SHALL NOT cambiar; sólo la prosa.
2. THE SYSTEM SHALL añadir a la spec `frontend-auth-session.md` una línea que diga que
   `purgeSessionCache()` es la única función del módulo que avanza `sessionGeneration`
   como efecto de purga, citando `session-cache-purge.ts` y eliminando la nota de «deuda
   conocida, latente» sobre el `catch` de `refresh()` (lo mismo que R2.3, sin contradicción).
3. THE SYSTEM SHALL NOT tocar la rotación de tokens, el endpoint `/auth/refresh`, ni la
   coordinación de la promesa en vuelo: este cambio es de **semántica del contador**, no de
   la mecánica del refresh. (Nota post-panel: R6 introduce un segundo contador y cambia cuál
   compara la guarda del coordinador, pero el mecanismo de `inFlight` — dedupe por
   `refreshToken`, una sola promesa compartida, `.finally` que libera el slot — no cambia.)

### R6 — El contador de identidad de tokens no se confunde con una purga de caché ajena (añadido en la tercera ronda de `/sdd:review`)

**As a** usuario cuya sesión está en medio de un refresco cuando otra pestaña/cliente de la
misma app dispara una purga de caché no relacionada con mi sesión, **I want** que esa purga
ajena no haga que mi refresco en vuelo se trate como si mi sesión hubiera sido reemplazada,
**so that** ni pierdo un par de tokens legítimamente rotado ni mi sesión, si de verdad fue
revocada por el servidor, se quede pegada en `"authenticated"` para siempre.

Acceptance criteria:

1. THE SYSTEM SHALL exponer un contador de generación de identidad (`getTokenGeneration()`
   en `session-store.ts`) independiente de `sessionGeneration`, que avanza únicamente en
   `setSessionTokens()` y en `clearSessionTokens()` — nunca en `purgeSessionCache()` por sí
   sola.
2. `refresh-coordinator.ts` SHALL capturar y comparar `getTokenGeneration()` (no
   `getSessionGeneration()`) para decidir si un refresco en vuelo sigue perteneciendo a la
   sesión que lo inició.
3. IF un `refreshSession()` está en vuelo Y una purga de caché no relacionada avanza
   `sessionGeneration()` mientras tanto, THEN THE SYSTEM SHALL: (a) si el refresco
   finalmente tiene éxito, instalar el par rotado con normalidad — SHALL NOT descartarlo
   como si la sesión hubiera cambiado; (b) si el refresco falla, limpiar los tokens y la
   cookie de presencia con normalidad — SHALL NOT dejarlos vivos por creer que otra sesión
   los reclama.
4. La guarda del `catch` del coordinador (R5.1) SHALL purgar la caché (`purgeSessionCache()`)
   antes de limpiar tokens, para que la invalidación de caché y la limpieza de tokens
   permanezcan acopladas en ese sitio también, sin depender de que cada futuro llamante de
   `refreshSession()` purgue por su cuenta después.

## Out of scope

- **No es un endurecimiento del refresh ni del ciclo de sesión.** La rotación de tokens, el
  coordinador y la purga de `QueryClient` siguen siendo los definidos por `frontend-auth-session`.
  No se añaden reintentos, no se cambia el TTL, no se mueve el JWT de memoria.
- **No arregla nada que un usuario note hoy.** (1) es latente —ningún `useAuth()` desestructura
  `refresh`— y (2) degrada a un `401` que se recupera solo. Es deuda de semántica que el
  siguiente consumidor de mutaciones optimistas volverá a pisar.
- **No introduce un evento de «sesión invalidada por nuevo login».** La invariante nueva
  (R3) detecta la carrera dentro del listener, sin añadir un canal nuevo; un evento
  dedicado sería una refactorización mayor del módulo de sesión, no una corrección de las
  dos grietas.
- **No cambia el mapa de permisos del frontend.** `READ_PROPERTIES` y compañía siguen siendo
  materia del backend; este change no toca el route registry ni los guards más allá de lo
  que ya hace `frontend-auth-session`.
- **No migra a TanStack Query el flujo de login/refresh.** Eso vive en
  `frontend-auth-session` y se cerró con `notifications-inbox-web` en su D3/R3; este change
  no re-litiga esa decisión.

## Affected specs

- `sdd/specs/frontend-auth-session.md` — se reescriben los dos párrafos «Deuda conocida,
  latente» y la nota de «Contrapartida aceptada a sabiendas» para reflejar el nuevo
  contrato: «toda purga invalida por construcción» y «el listener sólo limpia tokens
  cuando la sesión vigente es la que está expirando».
- (no existe aún — se creará al archivar) Si el diseño requiere un test nuevo en una
  ubicación que no es `lib/auth/` ni `features/auth/` —por ejemplo, un test de integración
  de TanStack Query contra `QueryClient.clear()`—, se documenta en la spec correspondiente
  al archivar. No se prevén specs nuevas para este change.
