# Tasks: rule11-guard-trigger-and-scope

Orden elegido para que el árbol quede sano en cada corte: la guardia nueva **convive** con la vieja
hasta que las dos comparaciones de R1.5 estén registradas (1.4 y 1.5); sólo entonces se borra el
fichero de `backend/tests/` (4.1). Las secciones 1-3 dejan el sistema con guardia nueva, gatillo y
suite propia; la 4 retira la superficie vieja; la 5 alinea autoridad y documentación; la 6 es la
demostración en rojo que R4 exige y no puede hacerse antes de que exista el check run.

## 1. La guardia se muda a `scripts/`, con su alcance como dato <!-- panel: PASS 2026-08-31 -->

- [x] 1.1 Crear `scripts/rule11-ownership.py` portando la lógica de
  `backend/tests/test_rule11_ownership.py` **sin tocar todavía ningún eje**: `_markdown_blocks`,
  `_python_blocks`, `_offending_blocks`, `SINK_TERMS` (los 21 de hoy, intactos),
  `OWNERSHIP_PATTERNS` (los 13), `AUTHORITY`, `TABLE_HEADER`, `MINIMUM_MARKDOWN_FILES`. Raíz del
  árbol con **un solo origen** (`Path(__file__).resolve().parents[1]`): el candidato `/workspace/`
  desaparece con el bind mount (D1). Forma de guardia ejecutable copiada de
  `scripts/compose-ports.py`: `GuardError`, `main() -> int`, `if __name__ == "__main__"`. Cada
  hallazgo imprime **fichero, línea y la frase exacta** que disparó el eje, conducta conservada
  literal. Sólo stdlib (`ast`, `re`, `pathlib`): ni Postgres, ni Redis, ni `.env`, ni secret.
  [R1.3, R2.5]

- [x] 1.2 Sustituir `_prose_roots()`, `_code_files()`, `EXCLUDED_DIRECTORIES` y
  `DECLARED_EXCEPTIONS` por la tupla `SCOPE` de `ScopeEntry(path, kind, reason)` con el `Kind` de
  D4 (`AUTHORITY`, `CENSUS_PROSE`, `CENSUS_CODE`, `OUT_OF_CENSUS`, `EXCEPTION`) en
  `scripts/rule11-ownership.py`. `_prose_files()` y `_code_files()` se derivan de `SCOPE` y **no
  queda ninguna ruta literal fuera de ella**. Entradas de partida: la autoridad
  (`sdd/steering/security.md`), `sdd/` y `docs/` como censo de prosa, `backend/app`,
  `backend/alembic/versions` y `backend/tests` como censo de código, `sdd/changes` y `docs/adr`
  fuera de censo con su motivo actual conservado palabra por palabra, y la excepción del propio
  fichero de la guardia apuntando ya a `scripts/rule11-ownership.py`. `reason` obligatoria y no
  vacía en todas. [R2.1]

- [x] 1.3 Añadir a `SCOPE` las dos entradas `OUT_OF_CENSUS` de D5 —`sdd/roadmap.md` y
  `sdd/roadmap`— con su motivo escrito (una entrada de roadmap **declara trabajo no hecho**, así
  que decir que una columna todavía no tiene escritor es su función y no una reafirmación del
  censo), y **borrar** la excepción declarada `sdd/roadmap/rule11-ownership-single-source.md`, que
  queda cubierta por la exclusión y por tanto muerta. [R2.2]

- [x] 1.4 **Primera comparación de R1.5: la mudanza, con el eje sin tocar.** Con `SINK_TERMS`
  todavía completo, correr las dos vías sobre este mismo árbol y **pegar las dos salidas aquí
  abajo**: la vieja (`docker compose exec backend uv run pytest tests/test_rule11_ownership.py`) y
  la nueva (`python3 scripts/rule11-ownership.py`). Deben reportar **el mismo censo**: los tres
  bloques de `sdd/specs/access-notifications.md` (372, 525 y 689). Esta igualdad es la que prueba
  que la mudanza no movió el conjunto escaneado — la de 1.5 no puede probarlo porque ambas darán
  cero. Registrar también el número de ficheros recorridos por cada vía. [R1.5]

  **Medido el 2026-08-31 en este worktree, con `SINK_TERMS` completo en las dos vías.**

  Vía vieja — `docker compose exec -T backend uv run pytest tests/test_rule11_ownership.py -q`:

  ```
  E       AssertionError: these blocks name a rule 11 sink AND say who writes it:
  E           sdd/specs/access-notifications.md:372 — 'sin escritor'
  E           sdd/specs/access-notifications.md:525 — 'tienen escritor'
  E           sdd/specs/access-notifications.md:689 — 'sin escritor'
  1 failed, 4 passed in 43.23s
  ```

  Vía nueva — `python3 scripts/rule11-ownership.py`:

  ```
  fichero: sdd/specs/access-notifications.md:372   frase: 'sin escritor'
  fichero: sdd/specs/access-notifications.md:525   frase: 'tienen escritor'
  fichero: sdd/specs/access-notifications.md:689   frase: 'sin escritor'
  infractores: 3
  EXIT=1
  ```

  **Censo idéntico: 3 = 3, los mismos tres bloques y las mismas tres frases.**

  Ficheros recorridos: la vieja **180 markdown + 789 python = 969**; la nueva **94 + 800 = 894**.
  La diferencia no es ruido y se comprobó por diferencia de conjuntos, no por resta: los 86
  markdown que sólo ve la vieja son **exactamente** el árbol del roadmap (`sdd/roadmap.md` más
  los 85 de `sdd/roadmap/`), que es la exclusión de 1.3; los 11 python que sólo ve la nueva son
  **exactamente** `scripts/*.py`, que entra en censo porque la guardia se muda ahí y sin él su
  propia excepción sería una entrada muerta. Ningún otro fichero cambia de lado en ninguna de las
  dos direcciones. Coste medido de añadir `scripts/` al censo: **0 bloques** — ningún script
  distinto de la propia guardia encaja los dos ejes.

  La cifra de python sube a **801** en 1.5 y no es deriva: entre las dos medidas se creó
  `scripts/test_rule11_ownership.py` (tarea 2.1), que el censo de código recorre como cualquier
  otro. Cada número está medido contra el árbol que había en su momento.

- [x] 1.5 **D3 y la segunda comparación.** Quitar del eje de sumideros los **cinco** términos de
  meta-vocabulario (`regla 11`, `rule 11`, `censo`, `sumidero de texto en claro`, `cleartext
  sink`), dejando sólo las columnas y tablas del censo, en `scripts/rule11-ownership.py` **y** en el
  fichero viejo (que se borra en 4.1). Re-correr las dos vías y pegar las salidas: **cero
  infractores por las dos**. Escribir en el docstring del módulo por qué salen los cinco: medido el
  2026-08-31 no aportan ni un verdadero positivo dentro del alcance y aportan los tres falsos
  positivos de `main`; **volver a medirlo contra el árbol al implementar**, no copiar la cifra del
  design. [R1.5, R2.6, R3.1]

  **Medido el 2026-08-31, re-contado contra el árbol y no copiado del design** (que decía 49/38 y
  16; el árbol se ha movido desde entonces). Sobre el corpus entero —1442 ficheros, árboles
  excluidos incluidos, para no juzgar con la muestra recortada—: **50 bloques encajan el eje de
  sumideros por una columna o tabla del censo** y **20 lo encajan sólo por meta-vocabulario**. De
  esos 20, diecisiete ya estaban fuera de censo o exentos (catorce bajo `sdd/changes/`, uno bajo
  `sdd/roadmap/`, y uno en cada uno de los dos ficheros de la guardia); los **tres** restantes son
  `sdd/specs/access-notifications.md:372`, `:525` y `:689`. Cero verdaderos positivos en alcance,
  tres falsos.

  Vía nueva — `python3 scripts/rule11-ownership.py`:

  ```
  ficheros markdown recorridos: 94
  ficheros python recorridos: 801
  veredicto: ningún bloque fuera de la tabla de la regla 11 declara quién escribe un sumidero del censo
  EXIT=0
  ```

  Vía vieja — `docker compose exec -T backend uv run pytest tests/test_rule11_ownership.py -q`:
  `5 passed in 45.72s`.

  **Cero por las dos: 0 = 0.** Al quitar los cinco términos del fichero viejo, su
  `test_every_declared_exception_still_earns_its_place` se puso en rojo nombrando
  `sdd/roadmap/rule11-ownership-single-source.md` — la excepción que D5 predijo que quedaría
  muerta. Se retiró también allí, y por eso la vía vieja vuelve a estar entera en verde mientras
  las dos conviven.

- [x] 1.6 Fallo cerrado con mensaje propio (D7), en `scripts/rule11-ownership.py`: `GuardError` +
  salida ≠ 0 en los cuatro puntos — árbol de prosa no alcanzable (mensaje **reescrito**: habla de
  checkout incompleto, ya no de `make down && make up`), `SyntaxError` en un `.py` del alcance
  nombrando fichero y error, menos de `MINIMUM_MARKDOWN_FILES` markdown visibles con la cifra vista,
  y `SCOPE` vacía o entrada `CENSUS_*` que no resuelve. Nunca verde en vacío y nunca `skip`: un
  `skip` se lee como «no aplica», que es lo peor que puede decir un control de seguridad cuando su
  entrada ha desaparecido. [R1.4, R4.3]

## 2. Las meta-pruebas de la guardia <!-- panel: PASS 2026-08-31 -->

- [x] 2.1 Crear `scripts/test_rule11_ownership.py` cargando el módulo con
  `importlib.util.spec_from_file_location` (la forma exacta de `scripts/test_compose_ports.py`,
  obligada porque el nombre kebab-case no es importable) y portando las cinco pruebas de hoy: el
  centinela del árbol visible, el censo sin infractores, `test_the_scan_catches_what_it_claims_to`
  (los cuatro positivos —markdown, bullet partido en dos líneas, docstring y tirada de `#`— y los
  negativos de un solo eje), `test_what_this_guard_does_not_catch` y
  `test_every_declared_exception_still_earns_its_place`. Comprobar que los cuatro positivos siguen
  encajando tras D3: los cuatro nombran una columna real del censo. [R1.4, R2.5]

- [x] 2.2 Prueba de `SCOPE` en `scripts/test_rule11_ownership.py`: toda entrada resuelve a una ruta
  que el escaneo recorre, toda `reason` es no vacía, y una entrada muerta —exclusión o excepción que
  ya no corresponde a una ruta recorrida— pone la prueba **en rojo nombrando la entrada**, que es lo
  que hoy hace `test_every_declared_exception_still_earns_its_place` sólo para las excepciones.
  [R2.4]

- [x] 2.3 Prueba de alcance vacío en `scripts/test_rule11_ownership.py` (R4.3): con `SCOPE` vacía y
  con el árbol de prosa ausente, la guardia levanta `GuardError` en vez de reportar «cero
  infractores». Es el fallo peor de todos porque es silencioso. [R4.3, R1.4]

- [x] 2.4 Re-medir y reescribir las cifras de `test_what_this_guard_does_not_catch` en
  `scripts/test_rule11_ownership.py`, **contando contra el árbol y sin incrementar el número
  anterior**: (a) el residual 5 dice «36 bloques» en `sdd/changes/` y está desfasado —el design
  midió 49 con el eje viejo y 38 con el de D3, y esas dos cifras también hay que re-medirlas
  porque dependen del árbol—; (b) el coste medido de la exclusión del roadmap, que R2.3 manda
  registrar aquí igual que la de `sdd/changes/` registra la suya; (c) el **residual nuevo** que abre
  D3 —una atribución que nombra la columna por referencia sin nombrarla deja de encajar— con su
  ejemplo medido y su coste de hoy en alcance; (d) la aclaración de D6 sobre el residual 8, que se
  queda: la atribución de un **miembro de enum** no es la de un **sumidero** para este guardián, y
  los tres bloques de `main` eran ese caso cazado por accidente a través de la palabra `censo`.
  [R2.3, R3.4]

- [x] 2.5 Ancla prosa↔`SCOPE` (D11), en `scripts/test_rule11_ownership.py`: leer la sección
  «Sumideros de texto en claro (regla 11)» de `sdd/steering/security.md`, localizarla por su
  encabezado literal y su frase de alcance por un marcador estable, y afirmar **en las dos
  direcciones** que toda ruta que la frase nombra está en `SCOPE` y toda entrada de `SCOPE` está
  nombrada en la frase. Ancla **rutas**, no cifras y no motivos, y sólo esa frase, no la sección
  entera. Si el marcador no aparece, la prueba falla **en alto nombrándolo** — nunca pasa en vacío.
  [R5.1, R5.2]

**Panel de las secciones 1-2** (se revisaron juntas: la guardia y sus meta-pruebas son un solo
par y ninguna es evaluable sin la otra). Arquitecto, seguridad, QA y documentación; tenencia e
i18n no se lanzaron por no tener superficie en el diff —ni consultas por tenant ni cadenas de
UI— y CI/CD entra en la sección 3, que es donde llega el workflow.

Dos rondas de arreglo. La primera cerró seis hallazgos de seguridad y uno de documentación; la
segunda, el que abrió la primera: `assert_no_dead_entry` se había quedado en un subconjunto de
lo que comprobaba la suite, y con `backend/app` declarado `OUT_OF_CENSUS` el escaneo pasaba de
801 ficheros python a 408 y seguía diciendo «cero infractores» con código 0. Está en `b395416`,
con las tres comprobaciones por árbol y `MINIMUM_PYTHON_FILES`.

**Dos hallazgos rechazados, con la evidencia por la que se rechazan**, para que no vuelvan a
levantarse: el revisor de documentación afirmó que `scripts/` no se escanea —citando el
`_code_files()` del fichero **viejo**, que en efecto sólo recorre los tres árboles del backend—
y que los dos ficheros de `scripts/` no existen. El guardián nuevo deriva su recorrido de
`SCOPE`: recorre 801 ficheros de código, doce de ellos `scripts/*.py`, y los dos ficheros están
en `d05cca6` (712 y 471 líneas). Lo midió también QA por su cuenta.

**Un hallazgo aplicado fuera del tope de dos rondas y sin revisión posterior**, y consta porque
el tope existe por algo: F7, que el revisor levantó al verificar la segunda ronda. Era una frase
del residual 5d que atribuía a `assert_no_dead_entry` un caso que no puede ver —borrar la
*entrada* de un árbol de censo, en vez de excluirlo—, con el arreglo ya dictado por el propio
revisor. Se verificó ejecutándolo antes de escribirlo: quitar la entrada de
`backend/alembic/versions` retira 17 ficheros y sale en verde. Es corrección de prosa sobre un
residual, no de conducta.

## 3. El gatillo: la guardia se ejecuta donde tiene que hablar <!-- panel: PASS 2026-08-31 -->

- [x] 3.1 `Makefile`: target `check-rule11-ownership: python3 scripts/rule11-ownership.py`, junto a
  `check-compose-ports` y `check-version-parity`, **fuera de `$(COMPOSE)`** y añadido a `.PHONY`.
  Con su comentario diciendo por qué queda fuera (es una herramienta host-side de stdlib: no
  necesita el stack, y meterla en `$(COMPOSE)` la ataría a un contenedor que ya no monta el árbol de
  prosa). [R1.3]

- [x] 3.2 Crear `.github/workflows/rule11-ownership.yml`: `on: pull_request: {}` +
  `push: branches: [main]` + `workflow_dispatch: {}`, **sin `paths:`** y **sin detección de área
  dentro** (D2 — un gate de área sería un segundo sitio donde equivocarse sobre el alcance, que es
  el defecto que este change arregla); `permissions: contents: read`; `concurrency` por `github.ref`
  con `cancel-in-progress`; **un solo job llamado `rule11-ownership`**, porque el check run toma el
  nombre del job y no el del workflow; `timeout-minutes: 10`. Pasos: `actions/checkout` con el mismo
  SHA pineado que `compose-ports.yml`, `astral-sh/setup-uv` (sólo para el paso de la suite),
  `make check-rule11-ownership`, y
  `uv run --no-project --with 'pytest==9.1.1' python -m pytest scripts/test_rule11_ownership.py -q`.
  Ni Postgres, ni Redis, ni `.env`, ni secrets, y que eso sea **verificable leyendo el fichero**.
  Cabecera explicando el gatillo, la prohibición de `paths:` de `sdd/specs/backend-ci.md` y por qué
  no hay gate de área. [R1.1, R1.2, R1.3]

- [x] 3.3 Dejar `.github/workflows/compose-ports.yml` **sin cambios** y comprobar que su paso
  `pytest scripts/ -q` recoge también `scripts/test_rule11_ownership.py`. Se deja el glob ancho a
  propósito: estrecharlo crearía una lista que el próximo script hay que acordarse de ampliar.
  [R1.1]

- [x] 3.4 Comprobar que el check nuevo es **distinto** del de `backend-tests`: nombre de job propio,
  workflow propio, y que un PR de sola prosa lo ejecuta mientras `backend-tests-suite` sigue
  saliendo `skipped` — que es exactamente la forma del run 33409418091 que dejó pasar el defecto.
  [R1.1]

  **Verificado estructuralmente el 2026-08-31**, que es lo que se puede probar sin push; los ids
  de run son 6.1 y 6.2. El gate de `backend-tests.yml:186` es
  `case "$f" in backend/* | .github/workflows/backend-tests.yml)`, así que un diff de sola prosa
  deja `backend=false` y `backend-tests-suite` en `skipped`. El workflow nuevo no tiene `paths:`
  en `on:` ni puerta de área ninguna —comprobado parseando el YAML— así que corre igual. Y el
  nombre del job, `rule11-ownership`, no colisiona con ninguno de los diez workflows del
  repositorio: los de `backend-tests.yml` son `backend-tests-detect`, `backend-tests-suite` y
  `backend-tests`.

## 4. Retirar la superficie vieja <!-- panel: PASS 2026-08-31 -->

- [x] 4.1 Borrar `backend/tests/test_rule11_ownership.py`, **una vez registradas las dos
  comparaciones de 1.4 y 1.5**. Comprobar que nada más lo importa y correr la suite del backend:
  misma cifra de partida menos ese fichero, sin fallos nuevos. Medir la cifra de partida **antes** de
  borrar. [R1.5]

- [x] 4.2 `docker-compose.yml`: retirar `./sdd:/workspace/sdd:ro` y `./docs:/workspace/docs:ro` con
  el comentario que las justifica (hoy líneas 111-122). **No tocar** los otros **tres** montajes de
  `/workspace/` (`deploy-dev.yml`, `demo-reset.yml`, `.env.example`), que tienen consumidores vivos.
  *(La tarea decía «cuatro» y son **tres** en `docker-compose.yml`, contados en el fichero: eran
  cinco y quedan tres. «Cuatro» sólo se sostiene contando además el `deploy-dev.yml` que declara
  `docker-compose.worktree.yml`, que es un fichero distinto del que la tarea nombra.)*
  Verificar antes de borrar que ningún otro fichero bajo `backend/` lee `/workspace/sdd` ni
  `/workspace/docs`. [R1.3]

- [x] 4.3 Actualizar las **cuatro citas vivas** de la ruta vieja, ninguna funcional:
  `sdd/specs/incident-photos.md:396`, `backend/tests/cli/test_demo_reset.py:292` y `:2774`, y
  `backend/tests/notifications/test_writer_census.py:113`. Ojo con las dos de `test_demo_reset.py`:
  no basta con repathear, porque citan la **forma de dos candidatos** de `_prose_roots()`, que este
  change elimina — hay que reescribir la frase o apuntar al ejemplo que siga siendo cierto. Los
  registros bajo `sdd/changes/archive/` **no se tocan**: son inmutables. [R5.2]

- [x] 4.4 Recontar los recuentos que el target nuevo falsea, **contra el `Makefile` y sin
  incrementar el número anterior**: `Makefile:344` («es el tercero de los **cuatro** targets
  host-side que no lo usan», enumerándolos), `Makefile:401` («es el **cuarto** target host-side») y
  el `SHALL` de `sdd/specs/local-environment.md:458`, que enumera «los **cuatro** targets que
  delegan en un script host-side —`check-version-parity`, `compose-stacks`, `check-compose-ports` y
  `ports`—» y ahora tiene uno más. La cuenta de los **diez** targets que invocan `docker compose`
  desde el `Makefile` no cambia: `check-rule11-ownership` no invoca Compose. [R5.3]

**4.4 se adelantó a la sección 3**, y consta el motivo: es 3.1 —el target nuevo— lo que falsea
esos tres recuentos, así que recontarlos en la sección 4 habría dejado el árbol mintiendo entre
dos commits. Recontados contra el `Makefile` y contra la propia frase, no incrementados: los
targets host-side fuera de `$(COMPOSE)` pasan de cuatro a **cinco**, `check-compose-ports` sigue
siendo el tercero y `ports` el cuarto, y los que quedan fuera **por decisión** pasan de tres a
**cuatro**, con su bullet propio en `sdd/specs/local-environment.md`. La cuenta de los targets que invocan `docker compose`
desde el `Makefile` no se mueve por este change —`check-rule11-ownership` no invoca Compose— pero
**estaba mal, y se vio al recontarla en vez de arrastrarla**: eran once y no diez. El que faltaba
es `check-frontend-build`, que invoca `$(COMPOSE) exec -T` en su receta y no aparecía ni en esa
enumeración ni en la de los host-side. Lo levantó el panel de la sección 3, y con razón: 4.4 se
presentaba como un recuento, así que dar «diez» por bueno sin contarlo era exactamente lo que la
obligación de R5.3 prohíbe.

  **Y preguntar por los hermanos encontró otro**, fuera del alcance de este change y corregido
  igualmente porque estaba en un fichero que este change ya abre y era falso de forma
  comprobable: `sdd/specs/local-environment.md` decía que el worker ejecuta «las **ocho** tareas
  periódicas … las **cuatro** nombradas por PRD §8.3». Son **nueve** y **cinco**: `revenue-pricing`
  añadió `generate_price_recommendations` y no actualizó esta frase, mientras que
  `sdd/specs/celery-jobs.md` —la autoridad, citada en la misma frase— sí lo dice bien. Contado
  contra `backend/app/scheduler/tasks.py`: nueve `@celery_app.task`. Se corrige aquí y consta que
  es una corrección ajena a este change, no un recuento suyo.

  La prosa de procedencia del recuento salió además **fuera del bullet `SHALL`**, a un párrafo
  propio: es la convención que esta misma spec sigue para la nota de `compose-ports-guard`, y
  metida dentro obligaba a leer la historia del error para encontrar la afirmación normativa.

  **Medido el 2026-08-31, las dos pasadas completas y con marcador de fin** (los intentos previos
  murieron por memoria y hubo que distinguir «terminó» de «la mataron»):

  ```
  antes:    9218 passed, 41 skipped in 750.58s   EXIT=0
  después:  9213 passed, 41 skipped in 737.50s   EXIT=0
  ```

  **9218 − 5 = 9213**, que son exactamente los cinco tests del fichero borrado. Ni un fallo nuevo
  y los `skipped` no se mueven. Antes de borrar se comprobó con python —no con `grep`, que en este
  repo esconde coincidencias— que **ningún fichero lo importa**: el único acierto era una frase de
  docstring en `scripts/test_rule11_ownership.py`.

  Con el fichero se fueron **a la vez** su entrada transitoria de `SCOPE` y su mención en la frase
  de alcance de `sdd/steering/security.md`. No es limpieza opcional: el ancla de D11 verifica las
  rutas en las dos direcciones, así que borrar sólo el fichero habría puesto la prueba en rojo
  nombrando la entrada muerta — que es exactamente para lo que se escribió.

  **4.3, y por qué dos de las cuatro no se repathearon.** `test_writer_census.py:113` e
  `incident-photos.md:396` sí apuntan ya al camino nuevo. Las dos de `test_demo_reset.py` (292 y
  2774) **no citaban la ruta sino la forma de dos candidatos** de `_prose_roots()`, que este change
  elimina: repathearlas habría dejado una frase describiendo algo inexistente. Se reescriben para
  decir lo que sigue siendo cierto — esa forma sobrevive ahí porque **esa** suite sigue corriendo
  dentro del contenedor, y el guardián dejó de necesitarla al salir de él.

  Comprobado después: no queda ninguna cita viva de la ruta vieja ni de los dos montajes. Los tres
  aciertos restantes son legítimos —una frase histórica en el docstring del fichero nuevo y dos
  entradas de `sdd/roadmap.md`, que está fuera de censo y sólo escribe `/sdd:archive`.

## 5. La autoridad, la spec y las docs <!-- panel: PASS 2026-08-31 -->

- [x] 5.1 `sdd/steering/security.md`, § «Sumideros de texto en claro (regla 11)»: reescribir contra
  `SCOPE` la línea 126 (qué recorre el guardián y desde dónde se ejecuta) y la 128 (qué excluye y
  cuáles son sus excepciones declaradas, de las que la del roadmap desaparece). Nombrar el check run
  `rule11-ownership` y la vía local `make check-rule11-ownership`, y citar la spec nueva. La frase de
  alcance queda en la forma exacta que el ancla de 2.5 lee, con su marcador estable. [R5.1, R5.2]

- [x] 5.2 En esa misma sección, **recontar contra la tabla y no incrementar** sus recuentos —
  columnas del censo, filas, ejes del guardián y excepciones declaradas — y corregir los que hayan
  quedado desviados. Es obligación que la propia sección se impone, y ya envejeció cuatro veces.
  [R5.3]

- [x] 5.3 Crear `sdd/specs/rule11-ownership-guard.md` (D8), con requisitos EARS: propósito, gatillo
  sin `paths:` y sin gate de área, check run propio y su **estado** (se ejecuta y reporta **sin** ser
  obligatorio para fusionar mientras el repositorio no tenga protección de rama compatible, igual
  que `api-contract`, `compose-ports` y `frontend-tests` y por el mismo motivo de plan de GitHub),
  fallo cerrado en sus cuatro puntos, dónde vive el alcance (`SCOPE`, **citado como fuente, no
  reproducido**), la vía local y el coste declarado de D1. Y la decisión de D6 escrita: la
  atribución de un **miembro de enum** no es la de un **sumidero** para este guardián, y por eso los
  tres bloques de `sdd/specs/access-notifications.md` no eran infractores. Criterio operativo, que se
  comprueba al terminar: **la spec no contiene ninguna lista que `SCOPE` o la tabla de la regla 11 ya
  contengan**. [R1.1, R3.4, R5.2]

- [x] 5.4 `sdd/project.md` § Commands: añadir la vía local `make check-rule11-ownership` (host,
  `python3`, sin Docker y sin stack levantado) y el **coste declarado de D1** — el `pytest` del
  backend ya no ejecuta el guardián, así que un docstring infractor en `backend/app/**` se ve en CI
  y no en la suite local. [R1.3]

- [x] 5.5 `README.md`: añadir `make check-rule11-ownership` al bloque de comandos (hoy líneas 29-35,
  junto a `check-version-parity` y `check-compose-ports`), con una línea de qué comprueba. Lo exige
  `sdd/steering/documentation.md`: un comando de Makefile nuevo actualiza el README raíz. [R1.3]

- [x] 5.6 Confirmar por escrito que `sdd/specs/access-notifications.md` **no se toca**: las líneas
  372, 525 y 689 se quedan exactamente como están (D6), no se reubica ningún hecho porque ya está en
  su sitio, y **R3.3 no se ejerce** — el fichero no se declara excepción. Verificar con la guardia
  nueva que ninguna de las tres se reporta. [R3.1, R3.2, R3.3]

  **5.2, recontado contra la tabla el 2026-08-31 y no incrementado.** Dos cifras estaban
  desviadas y las dos se corrigen: la tabla tiene **veintinueve** filas y decía «veintiocho», y
  `messages.content` ocupa **cuatro** filas y no tres. Es el mismo hecho por dos sitios — el cuarto
  escritor de esa columna es el seed de demostración, que entró después de que `messaging-ai`
  escribiera «el primer caso de una columna con tres escritores» y no tocó ninguna de las dos
  frases. Las otras dos cifras **sí** cuadran: veintiuna columnas distintas (parseando la primera
  celda de cada fila y descontando los tres cualificadores de escritor, que no son columnas) y las
  veintiuna vivas.

  **5.6 verificado, no afirmado.** `git diff origin/main -- sdd/specs/access-notifications.md` sale
  vacío; la guardia nueva reporta **0** bloques en ese fichero; y el fichero **no** figura en
  `SCOPE`, así que R3.3 no se ejerce por ninguna vía. Las líneas 372, 525 y 689 siguen literalmente
  donde estaban.

  **5.3 cumple el criterio operativo de D8, comprobado y no supuesto**: la spec nueva no cita **ni
  uno** de los términos del censo (verificado contra `SINK_TERMS`) y no reproduce la enumeración de
  alcance —para el contrato remite a la regla 11, y para el alcance a `SCOPE`—. La guardia la
  recorre como a cualquier otro documento y reporta cero. Y resuelve la referencia colgante que el
  panel de la sección 3 levantó: `sdd/specs/local-environment.md` ya la citaba.

## 6. Demostración en rojo de la superficie nueva (R4)

- [ ] 6.1 **Las dos vías de diff.** Registrar aquí el id de run del check `rule11-ownership` sobre un
  push cuyo diff sea **sólo prosa** (`sdd/**` o `docs/**`) y otro cuyo diff sea **sólo `backend/**`**.
  La rama de este change produce los dos de forma natural; anotar además que en el de sola prosa
  `backend-tests-suite` sale `skipped` y el check nuevo no. [R4.1]

- [ ] 6.2 **Rojo por cada forma que la guardia dice cazar.** Commit temporal que meta un bloque
  infractor en un `.md` y otro en un docstring (o tirada de `#`) de un `.py`; registrar el id de run
  con el check **en rojo** y pegar aquí la salida local de `make check-rule11-ownership`; revertir
  el commit acto seguido y comprobar que el check vuelve a verde. [R4.2]

- [ ] 6.3 **Verde sobre la base.** Tras el merge de `main` en la rama que hace `/sdd:ship`, el check
  `rule11-ownership` reporta **cero** infractores. Se mide sobre la rama fusionada, no sobre la rama
  sola, porque `origin/main` se mueve mientras esto está en vuelo. [R3.1]

## 7. Verification

- [ ] 7.1 `make check-rule11-ownership` → cero infractores y salida 0.
- [ ] 7.2 `uv run --no-project --with 'pytest==9.1.1' python -m pytest scripts/ -q` en verde —
  recoge las meta-pruebas nuevas y las de los otros cuatro scripts, que es lo mismo que hará
  `compose-ports.yml`.
- [ ] 7.3 Suite del backend: `docker compose exec backend uv run pytest` (o
  `docker compose run --rm backend uv run pytest` con el stack parado). Comparar contra la cifra de
  partida medida en 4.1: un fichero menos, ningún fallo nuevo.
- [ ] 7.4 `make check-compose-ports` y `make check-version-parity` en verde — `docker-compose.yml` se
  ha tocado en 4.2.
- [ ] 7.5 `make down && make up` en este worktree: el stack levanta sin los dos bind mounts
  retirados, y la suite del backend sigue verde dentro del contenedor.
- [ ] 7.6 Los dos tests de frontend que leen el árbol por encima de `/app` siguen verdes tras tocar
  `docker-compose.yml` — en particular `lib/config/build-identity-contract.test.ts`, que lo lee
  entero. Requiere los `docker compose cp` que documenta `sdd/project.md` § Worktree bootstrap.
- [ ] 7.7 Repasar que ningún documento vivo cita ya `backend/tests/test_rule11_ownership.py`
  (grepeando el árbol completo, `sdd/changes/archive/` aparte) ni describe un guardián que no
  existe. **Medido ya, y queda una que este change no puede arreglar**: la entrada
  `template-label-sink-census` de `sdd/roadmap.md` dice que `tests/test_rule11_ownership.py`
  vigila el censo, y es un documento **vivo** apuntando a un fichero borrado. No se toca aquí
  porque la regla 1 del toolkit reserva la escritura del roadmap a `/sdd:archive`: **queda
  encargado a `/sdd:archive`**, que debe repathear esa entrada a `scripts/rule11-ownership.py`
  al archivar este change. Las demás coincidencias del árbol son legítimas: una frase
  histórica en el docstring del fichero nuevo, los registros de este change, y
  `sdd/changes/archive/`, que es inmutable.
