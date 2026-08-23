# Blocked / deferred — cleaner-photo-requirements

## 1. La rama arranca en `sdd/cleaner-app`, no en `origin/main`

- **phase**: new
- **type**: deferred
- **what & why**: `sdd/cleaner-photo-requirements` nace del commit `8dc7a18`
  (*«sdd(roadmap): partir cleaner-photo-requirements y aplazar cleaner-app»*), que crea la entrada
  del roadmap y su nota `sdd/roadmap/cleaner-photo-requirements.md` — la **premisa** de este change.
  Ese commit vivía solo en `sdd/cleaner-app`, sin mergear, y `origin/main` no tenía ni la entrada ni
  la nota (verificado el 2026-08-23 con `git show origin/main:sdd/roadmap.md` y `git cat-file`). Un
  worktree desde `origin/main` habría arrancado sin la semilla, así que el usuario eligió
  explícitamente basar esta rama en `sdd/cleaner-app` para que el split viaje con la feature.

  Dos consecuencias que hay que atender y que nadie más recuerda:
  1. El PR de este change **incluye ese commit** de roadmap sobre el aplazamiento de `cleaner-app`.
     Es deliberado, y la descripción del PR tiene que decirlo — un revisor que lo vea sin contexto
     lo leerá como ruido fuera de alcance.
  2. `sdd/cleaner-app` (local y remota) queda **sin contenido propio** una vez esto se mergee:
     `cleaner-app` está aplazada y no tiene `sdd/changes/cleaner-app/` en disco. Es candidata a
     borrado tras el merge, no antes. `retire` lista los refs pero no borra ninguno, a propósito.
- **exact resume command**: `/sdd:ship cleaner-photo-requirements` — al redactar el PR, nombrar el
  commit `8dc7a18` y su motivo, y anotar `sdd/cleaner-app` como rama a borrar tras el merge.
  Al hacerlo, borrar esta entrada.

## 2. La sección 3 agotó las dos rondas de arreglo sin veredicto de panel

- **phase**: run
- **type**: deferred
- **what & why**: los guards estructurales de la sección 3 pasaron por **dos** rondas de arreglo
  —el máximo que `/sdd:run` permite— y la segunda no llegó a revisarse. La historia importa
  porque explica qué hay que mirar:
  1. Panel inicial: el arquitecto vio que el guard era una lista de *nombres prohibidos*, no una
     comprobación de forma, y construyó la fuga (`{...} <= uploaded`, sin nombrar ninguno).
  2. Ronda 1 (añadí guards de forma por lista negra): el arquitecto la sorteó con un **bucle
     imperativo** (`NotIn` + `.append`, que la lista negra no nombraba) y QA la sorteó **desde
     `schemas.py`**, calculando el veredicto en `PhotoRequirementsResponse.build` y sacándolo
     por una cabecera — demostrado vivo, con 650 tests en verde.
  3. Ronda 2 (la actual): sustituí la lista negra por una **lista blanca** — cada función se
     fija por su forma exacta (`execute` son seis sentencias y un comprehension sin `if`; el
     handler son dos; los constructores de esquema son un `return`), y `schemas.py` entra en
     alcance. Reproduje las **cuatro** fugas documentadas y cada una cae en un guard distinto.
  Lo que falta es que un revisor independiente intente romper la lista blanca. La verifiqué yo,
  y quien escribió el fallo no es el mejor juez de si lo cerró.
  Por eso la sección 3 **no lleva anotación `panel: PASS`** en `tasks.md`: sin ella, `/sdd:review`
  la re-audita entera en vez de saltársela. La anotación ausente es el mecanismo, no un olvido.
- **exact resume command**: `/sdd:review cleaner-photo-requirements` — al cubrir la sección 3 y
  darla por buena, borrar esta entrada.
