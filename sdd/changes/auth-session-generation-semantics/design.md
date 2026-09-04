# Design: auth-session-generation-semantics

## Context

`notifications-inbox-web` (archived 2026-08-29) reprodujo dos interleavings del módulo
`frontend/lib/auth/` que dependen de un único contador en memoria, `sessionGeneration`
(`frontend/lib/auth/session-store.ts:13`). Hoy ese contador sólo se mueve dentro de los dos
escritores de tokens (`setSessionTokens` línea 25 y `clearSessionTokens` línea 30), así que
cualquier camino de purga que no pase por uno de los dos deja el contador quieto — y las
mutaciones optimistas de `use-mark-read.ts:109` / `use-mark-all-read.ts:99` lo consultan para
decidir si su snapshot sigue perteneciendo a la sesión actual. El listener de
`AuthProvider` (`frontend/lib/auth/auth-provider.tsx:86-129`) compensa el agujero llamando a
`clearSessionTokens()` sin condición para forzar el avance, lo que anula la guarda del
coordinador (`refresh-coordinator.ts:57`) y deja una nota de deuda en la spec
(`frontend-auth-session.md:69-75`). El `refresh()` del propio provider (líneas 175-187) sólo
llama a `purgeSessionCache()` y deja el contador quieto — latente porque ningún `useAuth()`
desestructura `refresh`, pero pisable por el siguiente consumidor de mutaciones optimistas.

Este change mueve el avance del contador **dentro** de `purgeSessionCache()` y restaura la
guarda del coordinador en el listener, sin tocar la mecánica del refresh ni el endpoint.

## Decisions

### D1 — El avance del contador vive en `purgeSessionCache()` por construcción

**Chosen:** Mover `sessionGeneration += 1` desde `clearSessionTokens()` a
`purgeSessionCache()`, y eliminarlo de `clearSessionTokens()`. Toda purga del `QueryClient`
singleton avanza el contador en exactamente 1, en el mismo orden: primero el avance, después
el `getQueryClient().clear()`. La función sigue siendo `() => void` y el único efecto
observable nuevo es el avance.

**Rejected:** (a) Mover el avance a un wrapper nuevo `purgeSessionAndBump()` y dejar
`purgeSessionCache()` como está — multiplica el nombre sin reducir el riesgo, y cualquier
llamante que olvide el wrapper reproduce el agujero. (b) Avanzar dentro de `clearSessionTokens()`
y dejar `purgeSessionCache()` como está — invierte la garantía: quien limpie tokens sin purgar
la caché (el path del coordinador en `refresh-coordinator.ts:58`) no avanza, que es justo el
caso que la mutación optimista de `notifications-inbox-web` ya demostró que no puede permitirse.

### D2 — El comentario de "deuda conocida, latente" se borra del listener

**Chosen:** Eliminar de `frontend/lib/auth/auth-provider.tsx:88-123` el bloque JSDoc que
documenta la grieta de `refresh()` + `purgeSessionCache()`, y reemplazarlo por un comentario
breve que diga que `purgeSessionCache()` avanza el contador por construcción y enlaza con
`session-cache-purge.ts` y `use-mark-read.ts`. La nota de "contrapartida aceptada a sabiendas"
(que justificaba que el listener limpiara tokens sin condición) **sí** desaparece en parte
(D5) pero no toda — la mitad que documenta que dos rutas (`SessionInvalidatedError` y "No
refresh token available") llegan al listener con tokens vivos sí sobrevive, porque sigue
siendo cierto.

**Rejected:** Reescribir el bloque para que diga "ya no aplica" sin tocar el cuerpo del
listener — la mitad que documenta el trade-off aceptado deja de ser verdadera en parte (D5),
así que dejarla tal cual sería reintroducir la afirmación falsa que la propuesta dice
quitar.

### D3 — `clearSessionTokens()` deja de bumpear el contador

**Chosen:** En `frontend/lib/auth/session-store.ts:28-31`, eliminar la línea
`sessionGeneration += 1`. La función pasa a ser "nulificar `currentTokens`" a secas. La JSDoc
del módulo se reformula para decir que `sessionGeneration` se mueve en `setSessionTokens` y
`purgeSessionCache`, no en `clearSessionTokens`. El comentario al final del bloque de la
guarda del coordinador (`refresh-coordinator.ts:56-60`) se reformula en positivo: "si la
generación no se ha movido bajo esta promesa, la limpieza de tokens es segura; en otro caso,
los tokens actuales pertenecen a otra sesión y no se tocan".

**Rejected:** (a) Mover el avance desde `clearSessionTokens` a `purgeSessionCache` sin
tocar el comentario del coordinador — el comentario seguiría describiendo "limpia tokens sólo
si la generación no se movió" sin nombrar la nueva invariante ("toda purga bumpea"), que es
lo que hace que la guarda del coordinador **funcione** con el listener restaurado en D5.
(b) Dejar `clearSessionTokens` avanzando y duplicar el avance en `purgeSessionCache` —
rompería el invariante de R1 ("THE SYSTEM SHALL avanzar `getSessionGeneration()` en
exactamente 1" por llamada a `purgeSessionCache`), y haría que el listener (D5) avanzara
el contador 2 veces por notificación.

### D4 — `purgeSessionCache()` documenta la invariante en su JSDoc

**Chosen:** En `frontend/lib/auth/session-cache-purge.ts`, el bloque JSDoc existente (líneas
3-11) se reemplaza por uno que declare en una frase: "vacía el `QueryClient` singleton y
avanza `getSessionGeneration()` en exactamente 1, sin tocar tokens. La invariante
—toda purga invalida por construcción los snapshots en vuelo— es la que sostiene las
guardas de `use-mark-read.ts:109` y `use-mark-all-read.ts:99`: comparan
`getSessionGeneration()` con la del `onMutate` para descartar el rollback cuando la sesión
cambió bajo la mutación. Añadir un nuevo camino de purga sin pasar por aquí reintroduce el
agujero."

**Rejected:** Dejar el JSDoc como está y añadir un comentario al lado de la firma — el JSDoc
existente documenta **qué** purga pero no **por qué**, y un comentario al lado de la firma
duplica el sitio donde leer la invariante. Mover el JSDoc a `index.ts` o a un barrel — el
lector que abra `session-cache-purge.ts` buscando la invariante no debería tener que saltar
a otro fichero para encontrarla.

### D5 — El listener captura la generación, avanza vía `purgeSessionCache`, y limpia tokens sólo cuando no hay tokens vivos

**Chosen:** En `frontend/lib/auth/auth-provider.tsx:86-129`, el listener pasa a:

1. Capturar `const captured = getSessionGeneration()` al entrar.
2. Llamar a `purgeSessionCache()` — esto avanza la generación en 1 (R1) y vacía el `QueryClient`.
3. Si `getSessionTokens()` es no-nulo, **retornar** sin tocar tokens, presencia ni `status`
   (R3.2). Esos tokens pertenecen a la sesión instalada por `login()` que ganó la carrera
   al refresco viejo (R4.2), y `login()` ya escribió `status="authenticated"` y la cookie
   `autohostai.session.present`.
4. Si `getSessionTokens()` es nulo, ejecutar el resto del cleanup: `clearSessionTokens()`
   (idempotente bajo R1, no avanza el contador), `setUser(null)`, `clearSessionPresent()`,
   `setStatus("expired")`.

El `captured` se conserva como anclaje del comentario y como futuro punto de extensión si se
añade un `await` al cuerpo del listener (hoy ninguno; sync). El bloque JSDoc nuevo dice:
"Captura la generación al entrar para detectar la carrera descrita en R3.2: si un `login()`
escribió tokens entre el momento en que el `refresh-coordinator` decidió notificar y este
listener, `getSessionTokens()` los devuelve no-nulos al pasar la guarda, y los dejamos
intactos. La invariante de la guarda del coordinador (`refresh-coordinator.ts:57`) ya
expresa la misma idea — 'si la generación no se ha movido, la limpieza es segura'— y este
listener la honra en lugar de anularla."

**Rejected:** (a) Comprobar `captured === getSessionGeneration()` antes de avanzar — en un
cuerpo síncrono es siempre cierto, así que la guarda no diferencia Case A de Case B y deja
tokens de login vivos en B. No detecta la carrera. (b) Comprobar `captured + 1 ===
getSessionGeneration()` después de avanzar — sólo es falso si otro listener adelantó la
generación entre la entrada de este y su propio `purgeSessionCache()`, lo cual es un caso
futuro (múltiples listeners) que el diseño de `subscribeToSessionExpired` aún no tiene
nadie que ejercite. La señal fiable hoy es el null-check de tokens, y queda registrada en
JSDoc para que el siguiente listener la respete. (c) Eliminar la captura y avanzar siempre
sin guarda — equivalente al estado actual del listener para el path "No refresh token
available", pero pierde la guarda de R3.2 para el path `SessionInvalidatedError`. Es el
comportamiento que hoy se acepta como deuda y que esta propuesta dice sustituir.

### D6 — La spec `frontend-auth-session.md` deja de enunciar la deuda y documenta el nuevo contrato

**Chosen:** En `sdd/specs/frontend-auth-session.md`: (a) la línea que define el contador
(`THE SYSTEM SHALL llevar un contador monotono de generación de sesión ... expuesto como
getSessionGeneration()`) gana una frase: "que avanza en `setSessionTokens` y en
`purgeSessionCache()`". (b) El párrafo "Deuda conocida, latente" (líneas 69-75) se elimina y
se sustituye por: "Toda purga del `QueryClient` singleton —venga de donde venga, incluido el
camino del `catch` de `refresh()`— avanza `sessionGeneration` en 1; `purgeSessionCache()` es
la única función del módulo que bumpea el contador como efecto de purga. Las mutaciones
optimistas de `use-mark-read.ts` y `use-mark-all-read.ts` confían en esa invariante para
descartar el rollback cuando la sesión cambió bajo la mutación." (c) El párrafo
"Contrapartida aceptada a sabiendas" (líneas 60-68) se acorta para reflejar D5: ya no es
una "contrapartida aceptada", es la guarda del coordinador que el listener honra — la
carrera del refresco viejo que resuelve después de un login nuevo se resuelve sin destruir
los tokens de la sesión nueva, y la pérdida (un `401` que se recupera solo) se reduce a un
caso de uso que ningún consumer actual desestructura.

**Rejected:** Reescribir el párrafo "Contrapartida" sin tocar la sección de "Deuda" — son
dos caras del mismo cambio y dejarlas asíncronas reintroduce la contradicción que el panel
de `notifications-inbox-web` ya documentó. Reescribirlo como advertencia en lugar de
contrato positivo — el steering `documentation.md` exige afirmaciones en positivo sobre el
comportamiento vigente, y el comportamiento vigente es "toda purga bumpea".

## Changes by area

| Area | Files | Change |
|---|---|---|
| `frontend/lib/auth` (módulo) | `session-cache-purge.ts` | `getQueryClient().clear()` y `sessionGeneration += 1` (D1); JSDoc reescrito en positivo, cita `use-mark-read.ts` / `use-mark-all-read.ts` (D4). |
| `frontend/lib/auth` (módulo) | `session-store.ts` | `clearSessionTokens` ya no avanza `sessionGeneration`; JSDoc reformula en positivo y cita `purgeSessionCache` (D3). |
| `frontend/lib/auth` (provider) | `auth-provider.tsx` | Listener `subscribeToSessionExpired` reescrito (D5): captura, avanza vía `purgeSessionCache`, retorna temprano si `getSessionTokens()` es no-nulo. Bloque JSDoc de la deuda conocido eliminado; comentario nuevo cita `refresh-coordinator.ts:57` y `purgeSessionCache` (D2). |
| `frontend/lib/auth` (coordinador) | `refresh-coordinator.ts` | Bloque JSDoc de la guarda del catch (líneas 56-60) reformulado en positivo; el código no cambia — el invariante ya estaba bien (D3, segunda mitad). |
| `frontend/lib/auth` (tests) | `session-store.test.ts` | Sin cambios al código de tests. Los asserts existentes siguen pasando porque ninguno cuenta el contador. |
| `frontend/lib/auth` (tests) | `auth-provider.test.tsx` | Actualizar el comentario del test "moves the session generation on every purge" (línea 708) para que diga que el avance vive en `purgeSessionCache`. Añadir dos tests nuevos: R4.2 (interleaving `SessionInvalidatedError`, login gana) y R4.3 ("No refresh token available", tokens ya null al entrar al listener, cleanup completo). |
| `frontend/lib/auth` (tests, nuevo) | `session-cache-purge.test.ts` | **Nuevo.** Tres tests: `purgeSessionCache()` avanza `getSessionGeneration()` en cada llamada; lo hace aunque el `QueryClient` ya esté vacío (R4.1, R1.3); no toca `getSessionTokens()` (R1.2). |
| `frontend/features/notifications` (tests) | `use-mark-read.test.tsx` | Añadir un test (R4.4) que reproduzca el escenario del roadmap: una mutación con snapshot en gen N, mientras la mutación está en vuelo `refresh()` entra a su `catch` y purga la caché (sin tocar tokens), el revert consulta la generación y ve que ya no coincide, no escribe nada. Sin D1 el test falla porque el contador no se mueve; con D1 pasa. |
| Specs | `sdd/specs/frontend-auth-session.md` | Reescribir los dos párrafos "Deuda conocida, latente" y "Contrapartida aceptada a sabiendas" según D6; añadir la frase "que avanza en `setSessionTokens` y en `purgeSessionCache()`" al bullet del contador (D6). |

## Data & interfaces

**Ninguno.** Sin cambios de esquema, sin migraciones, sin nuevos endpoints, sin cambios en la
firma pública de `subscribeToSessionExpired` (R3.4), sin nuevos `Permissions`. El cambio
vive dentro de `frontend/lib/auth/` y `frontend/features/auth/`; afecta a tres pruebas
existentes y a un fichero de test nuevo.

## Risks & mitigations

- **Riesgo**: que la cobertura de `clearSessionTokens()` sin avanzar deje algún call-site
  contando con el avance y rompa en silencio. **Mitigación**: barrido de todos los call-sites
  de `clearSessionTokens()` con `grep -rn "clearSessionTokens" frontend/` antes de cerrar
  el change. Los cuatro vivos son `refresh-coordinator.ts:58`,
  `auth-provider.tsx:124` (listener, se reformula en D5), `auth-provider.tsx:165`
  (login catch, no le afecta: ningún `purgeSessionCache()` previo en ese path → el contador
  no avanza, pero el contador tampoco importa en ese path porque no hay mutación optimista
  pendiente) y `use-logout-mutation.ts:83` (precedido por `purgeSessionCache` en la línea
  anterior, así que el avance ya ocurrió por D1). El path `auth-provider.tsx:211` (logout
  deprecated) va seguido de `purgeSessionCache`, mismo razonamiento.

- **Riesgo**: que el listener D5 confunda el caso "tokens presentes por un login legítimo
  antes de que `notifySessionExpired` se dispare" con el caso "tokens de la sesión vieja que
  `refresh-coordinator` no llegó a limpiar". **Mitigación**: el segundo caso no existe en la
  práctica. La guarda del coordinador (`refresh-coordinator.ts:57`) limpia los tokens de la
  sesión vieja en su `.catch`; si la guarda salta es porque `login()` ya escribió nuevos
  tokens y avanzó la generación, y entonces `getSessionTokens()` los devuelve no-nulos. El
  caso límite es "tokens presentes por un set que no sea `login()`" — no existe en
  `frontend/lib/auth` (los únicos escritores son `setSessionTokens` y la línea 25 del
  módulo, llamado desde `login()` y `refreshSession()`).

- **Riesgo**: que el conteo de la suite de frontend cambie entre el run de
  `notifications-inbox-web` y el de este change, y no sepamos si los rojos vienen de la
  regresión o del ruido del worktree. **Mitigación**: R4.5 exige correr la suite desde el
  worktree con la receta documentada en `sdd/project.md` §«Worktree bootstrap» (los
  `docker compose cp` de los nueve ficheros que `npm test` lee por encima de `/app`),
  reportar el total **medido** (no memorizado) en `evidence.md`, y comparar contra el del
  run anterior, también medido. Si difieren en más de lo que explica el ruido del entorno
  (los dos ENOENT documentados), se investiga.

- **Riesgo**: que un nuevo `useAuth()` o nuevo consumidor futuro desestructuren `refresh`
  y dependan del comportamiento "purga sin bumpear" que D1 elimina. **Mitigación**: R2.2 +
  R2.3 reformulan la afirmación como "toda purga bumpea"; un consumidor nuevo que lea la
  spec ya no encuentra la nota de deuda que justificaría un comportamiento diferente.

## Open questions

_Ninguna pendiente al cierre del gate. Las dos preguntas resueltas en este turno se
incorporan al diseño como sigue:_

- **(RQ1, resuelta 2026-09-04):** R3.1 se interpreta como "la señal fiable es
  `getSessionTokens() === null`, no la comparación del contador". El listener (D5) usa
  el null-check y conserva `captured` como anclaje de jSDoc y como hook para un futuro
  cuerpo async o múltiples listeners. La guarda basada en comparación de generaciones se
  deja documentada como el mecanismo que tomaría el relevo si el cuerpo del listener
  pasara a ser async — sigue sin ser útil hoy, pero ya está nombrada.
- **(RQ2, resuelta 2026-09-04):** el JSDoc de `refresh()` (`auth-provider.tsx:175-187`) no
  se toca. El de `purgeSessionCache` (D4) ya enuncia la invariante en el único sitio que
  importa; duplicarla en `refresh()` la envejece por separado. Si en el futuro se observa
  que un lector abre `refresh()` sin abrir `purgeSessionCache`, se añade la línea — hasta
  entonces, no.
