# Tasks: backend-suite-runtime

Notas de orden que vienen del diseño y no son opcionales:

- **Dos fases con verificación propia** (pregunta abierta 2 del design, decidida el 2026-08-10):
  la §6 (xdist) **no arranca hasta que la fase 1 esté verde y medida en CI** (§5), para que un
  fallo de paralelismo no arrastre el ahorro ya ganado.
- **`sdd/specs/backend-ci.md` no se toca en este change.** Las specs vivas las escribe
  `/sdd:archive` (`steering/documentation.md`); lo que sí se hace aquí es dejar el texto redactado
  y con la cifra medida (§8.1). `sdd/steering/testing.md` sí es del change.
- **Todo lo que se mide se ejecuta desde el stack de este worktree** (`make up`), no desde el del
  principal: el contenedor `backend` sirve el árbol desde el que se levantó (`sdd/project.md`
  §Worktree bootstrap).
- **Dos correcciones al enunciado de los requisitos**, ya razonadas en D8 y que se implementan
  según el diseño, no según la letra del proposal: (a) R5.1 describe en su primera oración la
  aserción **actual** —la rota—; la buena es la segunda; (b) R5.2 cita «la regla 13(c) de
  `steering/security.md`» para pedir la demostración en rojo, y esa regla habla de datos de
  tarjeta en fixtures: la práctica se hace igual, la cita no la respalda.

## 1. Medición del coste (R1) — hecha en `/sdd:design`

- [x] 1.1 Procedimiento repetible de medición local, con el plugin de atribución y el banco de
  coste unitario pegables tal cual — **Files:** `sdd/changes/backend-suite-runtime/measurement.md`
  §1-§3 — *(preexistente: verificado leyendo el fichero; ambos scripts están completos y las
  condiciones de la medición fechadas el 2026-08-10)* [R1.1 (mitad local)]
- [x] 1.2 Atribución del tiempo a causas nombradas y cuantificadas: `create_all` por test 343,53s
  (55,5 %), `drop_all`+`dispose` 136,67s (22,1 %), resto de fixtures 39,86s, cuerpo de los tests
  92,42s, recolección y sesión 2,40s — **Files:** `measurement.md` §1 — *(preexistente)* [R1.2]
- [x] 1.3 El atribuido llega al **99,4 %** (614,88s de 618,51s), por encima del 80 % que exige
  R1.3, así que no hay laguna que registrar — **Files:** `measurement.md` §1 — *(preexistente)*
  [R1.3]

## 2. Guardián de orden de errores (R5) <!-- panel: PASS 2026-08-10 -->

Independiente del resto del change; se hace primero porque es barato y no depende de nada.

- [x] 2.1 Invertir la aserción de `test_subclasses_come_before_their_base`
  (`backend/tests/cleaning/test_errors.py:119-124`): para cada par de filas *(i, j)* con *i < j*,
  comprobar que **la fila posterior no es subclase de la anterior** —
  `assert not issubclass(later_class, error_class) or later_class is error_class` — que es lo que
  la resolución *primera coincidencia gana* exige. Actualizar el docstring, que hoy describe la
  intención correcta sobre una aserción que hace lo contrario. **Hecho** = el test pasa con el
  `_MAPPING` real. [R5.1]
- [x] 2.2 Demostrarlo en rojo antes de darlo por bueno: añadir **temporalmente** a `_MAPPING` una
  fila con una subclase de un error ya mapeado colocada **después** de su base, comprobar que la
  aserción nueva **falla** y que la vieja **pasaba** con esa misma fila (es la prueba de que era
  vacía), y retirar la fila. **Hecho** = queda constancia de las dos ejecuciones en el commit o en
  el resumen de `/sdd:run`; el árbol no conserva la fila. [R5.2]

## 3. Fase 1 — el esquema se construye una vez por ejecución (D1, D2, D3, D4) <!-- panel: PASS 2026-08-10 -->

- [x] 3.1 Fixture de sesión que construye la base de datos de la ejecución **desde cero**:
  `DROP DATABASE IF EXISTS … WITH (FORCE)` + `CREATE DATABASE` + `Base.metadata.create_all` al
  arrancar, y el `DROP` que ya existe al terminar — **Files:** `backend/tests/conftest.py`
  (sustituye a `_ensure_test_database_exists`, que hoy solo crea si falta, y amplía
  `_remove_the_run_database_at_the_end`). Sigue siendo una fixture **síncrona** con `asyncio.run`,
  por el motivo que su docstring documenta (mezclar ámbitos de bucle es el origen de los
  «attached to a different loop»). **Hecho** = una ejecución que hereda una base de datos con
  esquema viejo de otra ejecución muerta pasa igual, verificado a propósito creando esa base antes
  de correr con el mismo `PYTEST_DB_SUFFIX`. [R2.1, R3.3]
- [x] 3.2 `test_engine` deja de hacer `create_all`/`drop_all` y pasa a **vaciar todas las tablas**
  con una sola sentencia `WITH d0 AS (DELETE FROM "…"), d1 AS (…) … SELECT 1` generada desde
  `Base.metadata.sorted_tables`, precedida de `SET lock_timeout` en esa conexión — **Files:**
  `backend/tests/conftest.py:75-96`. Conserva **nombre, firma, `NullPool` y ámbito de función**
  (D4): `db_session` no se toca y los 209 ficheros de test no ven cambio alguno. **Hecho** = la
  suite completa pasa en local con recuentos idénticos. [R2.1, R3.1, R3.2]
- [x] 3.3 Test que demuestra que el vaciado no se queda corto: siembra una fila padre y una hija
  (p. ej. `tenants` + `users`), fuerza el vaciado del test siguiente y comprueba que **las dos**
  tablas quedan vacías; y comprueba que la lista de tablas de la sentencia coincide exactamente
  con `Base.metadata.sorted_tables`, que es lo que garantiza que una tabla nueva entre sola —
  **Files:** `backend/tests/test_table_wipe.py` (fichero nuevo hermano). [R3.1, R3.2]
  *(desviación menor y deliberada respecto a la letra de la tarea: en vez de un par de tests
  ordenados —siembra en uno, comprobación en el siguiente— el vaciado se ejercita dentro del mismo
  test. Un par ordenado depende de que los dos casos caigan en el mismo proceso, y el `--dist load`
  por defecto de la fase 2 (§7) reparte por test, no por fichero: sería un test que la propia
  fase 2 rompería. La propiedad que 3.3 pide —que la fila hija desaparezca con la padre— se
  demuestra igual, sobre la misma sentencia que usa la fixture)*
- [x] 3.4 Suite completa en local y comparación de recuentos con la línea base:
  `docker compose exec backend uv run pytest -q -rs` → **mismos 5 329 pasados + 35 omitidos con
  los mismos motivos** que la ejecución de `measurement.md` §1, y `git diff` sin ningún `skip`,
  `xfail`, parametrización recortada ni fichero excluido. **Hecho** = ambas comprobaciones escritas
  con sus cifras. [R3.1, R3.2]
  *(2026-08-10: **5 331 pasados + 35 omitidos**. Los 35 omitidos son los mismos y por el mismo
  motivo —`tests/properties/test_state_machine.py:296: declared policy pair`—. Los pasados suben de
  5 329 a 5 331 por los **dos tests que añade 3.3**, no por ningún cambio de recolección: 5 329 + 2.
  El `git diff` no introduce ni un `skip`, ni un `xfail`, ni una parametrización recortada, ni un
  fichero excluido. **El tiempo de esa ejecución (653s) no es comparable con la línea base** y no se
  usa como cifra: la máquina tenía otra suite completa de otro worktree corriendo en paralelo (load
  average 16,7 sobre 12 núcleos). La comparación limpia está abajo, y la de verdad —la que manda
  para R2.1— es la de CI en §5)*

## 4. Estabilidad de la fase 1 (D5) <!-- panel: PASS 2026-08-10 -->

- [x] 4.1 Hacer determinista la carrera del índice único:
  `test_an_insert_that_loses_the_unique_race_is_a_domain_refusal` deja de confiar en la
  planificación de `asyncio.gather` y cita a los dos llamantes en una barrera **después** de su
  `SELECT` y **antes** del `flush` — **Files:**
  `backend/tests/integrations/test_webhook_endpoints.py`. Motivo medido: falló en 1 de las 2
  ejecuciones del prototipo con `assert len(failures) == 1` recibiendo `0`. **Hecho** = el test
  pasa 10 veces seguidas en aislamiento (`pytest -q -k … --count`/bucle de shell), no una.
  [R3.5]
  *(10/10 verdes en aislamiento. La barrera se pone envolviendo la **sesión** que ve el
  repositorio, no el repositorio: `upsert` no pasa por `find_for`, inlinea su propio `execute`, así
  que la costura está ahí. `asyncio.Barrier(2)` suelta a los dos llamantes justo después de su
  SELECT y antes del `flush`, que es el único estado en el que uno puede perder el índice)*
- [x] 4.2 **Tres ejecuciones consecutivas verdes** en local con la fase 1, comprobando en el log
  que no aparece `attached to a different loop` ni `another operation is in progress`, y que los
  tres recuentos coinciden entre sí y con 3.4 — **Files:** ninguno; queda la evidencia en el
  resumen del run. [R3.5, R3.1]
  *(2026-08-10, las tres verdes y con el mismo recuento —**5 331 pasados + 35 omitidos**, mismo
  motivo—: **196,61s · 311,83s · 186,50s**. Ni un `attached to a different loop` ni un `another
  operation is in progress`. Ninguna base desechable huérfana al terminar. La dispersión de la
  segunda cifra es carga de la máquina, no del cambio: R3.5 pide verde y recuento, y el tiempo que
  manda para R2.1 es el de CI)*
- [x] 4.3 Aislamiento con **dos ejecuciones concurrentes sobre el mismo PostgreSQL** (el caso real
  de dos worktrees): lanzar dos suites a la vez con `PYTEST_DB_SUFFIX` distintos y comprobar que
  ambas terminan verdes y que las dos bases desechables desaparecen al cerrar. **Hecho** = `\l`
  (o `make db-clean-test` sin nada que borrar) lo confirma después. [R3.3]
  *(2026-08-10, `PYTEST_DB_SUFFIX=conc1` y `conc2` a la vez: **5 331 + 35 las dos**, verdes, en
  191,71s y 192,65s. Ninguna base desechable en pie al terminar y `make db-clean-test` sin nada que
  borrar. Que dos suites simultáneas tarden lo mismo que una sola (186-196s) dice además que el
  cuello no es PostgreSQL)*

## 5. Medición en CI de la fase 1 (R1.1 mitad CI, R2.1)

Necesita la rama publicada. Los tres disparos son **secuenciales por obligación**: el workflow
declara `concurrency: backend-tests-${{ github.ref }}` con `cancel-in-progress: true`, así que
tres solapados se cancelan entre sí.

- [x] 5.1 Línea base en CI sobre `main`: `gh workflow run backend-tests --ref main` ×3,
  esperando cada una, y leer la duración del paso `Suite completa …` del job
  `backend-tests-suite` con
  `gh api /repos/autohostai-labs/AutoHostAI/actions/runs/<id>/jobs`. Anotar las tres cifras y su
  mediana — **Files:** `sdd/changes/backend-suite-runtime/measurement.md` §4. [R1.1]
  *(2026-08-10, las tres verdes: **954s · 930s · 858s**, mediana **930s (15m 30s)**. Runs
  `31397414664`, `31399030815`, `31400638035`. Ojo a la cifra: la spec declaraba 6m15s el
  2026-08-03 y el proposal midió 15m34s el 2026-08-09 — la mediana de hoy la confirma y la
  empeora un poco más. Eso es la deriva de R4, medida)*
- [x] 5.2 Misma operación ×3 sobre `sdd/backend-suite-runtime` con la fase 1 aplicada; registrar
  las tres cifras, la mediana y el paso dominante identificado — **Files:** `measurement.md` §4.
  [R1.1, R2.1]
  *(2026-08-10, commit `ab71ada`, las tres verdes: **246s · 217s · 243s**, mediana **243s
  (4m 03s)**. Runs `31397418050`, `31397960091`, `31398465326`. El paso dominante sigue siendo el
  mismo —`Suite completa …`—, que es justo lo que se quería: ya no lo domina el DDL por test)*
- [x] 5.3 Contrastar la mediana de 5.2 con el objetivo de **5m 00s**. Si lo cumple, dejarlo
  escrito con la fecha. Si **no**, registrar en `measurement.md` §4 el techo medido y su causa y
  **no** dar R2 por cumplido: la cifra objetivo se renegocia con el usuario (entrada en
  `BLOCKED.md` de tipo `decision` si el run no puede resolverlo). [R2.1, R2.3]
  *(2026-08-10: **se cumple**. Mediana de la rama **243s** frente a los **300s** del objetivo, con
  57s de margen, y **3,93×** sobre los 954s de `main`. No hace falta renegociar nada ni abrir
  entrada en `BLOCKED.md`. La cifra se reajusta en 8.1 después de la fase 2)*

## 6. Presupuesto de tiempo en el check (R4, D7) <!-- panel: PASS 2026-08-10 -->

Se hace después de §5 para poder declarar cifras con una medición detrás, y antes de §7 para que
la fase 2 ya se mida contra el presupuesto.

- [x] 6.1 Cronometrar el paso de `pytest` y publicar su duración en segundos como **salida del
  job** `backend-tests-suite` — **Files:** `.github/workflows/backend-tests.yml` (paso «Suite
  completa …», bloque `outputs:` del job). El paso captura el código de salida de `pytest`,
  escribe la duración y **solo después** se rinde con ese código: la duración tiene que existir
  aunque la suite falle. [R4.2]
- [x] 6.2 Declarar las **dos cifras** como `env:` a nivel de workflow —presupuesto 5m 00s (aviso)
  y techo 7m 30s (rojo), ajustables a lo que salga de 5.2— con un comentario que diga por qué son
  dos y no una — **Files:** `.github/workflows/backend-tests.yml`. Dato versionado y revisable en
  el diff, nunca un ajuste de la UI de GitHub (R4.1 y la norma IaC-first de `steering/infra.md`).
  [R4.1]
- [x] 6.3 Comparación en el job consolidador `backend-tests` (el que ya corre con `if: always()`):
  el resumen nombra **siempre** la duración medida y las dos declaradas; pasar el presupuesto
  emite un aviso destacado; pasar el techo pone el veredicto en `fail`; si la suite se ejecutó
  pero la duración **no llegó**, el resumen lo dice con esas palabras y el veredicto **no** es
  verde; si la suite se saltó por el camino corto no hay duración que comparar y eso **no** es una
  laguna — **Files:** `.github/workflows/backend-tests.yml`, paso «Consolidar el resultado del
  gate». [R4.2, R4.3]
- [x] 6.4 Ejercitar la lógica del consolidador en local antes de empujar: extraer el bloque `run:`
  y ejecutarlo con las combinaciones de entorno —duración por debajo del presupuesto, entre
  presupuesto y techo, por encima del techo, vacía, y camino corto sin suite— comprobando
  veredicto y texto en cada una. **Hecho** = las cinco salidas pegadas en el resumen del run.
  [R4.2, R4.3]
  *(hechas **siete**, no cinco: a las cinco pedidas se añaden «suite en rojo con duración» y
  «detección rota», que son las dos rutas preexistentes que el presupuesto podía estropear. El
  cuerpo del script se **extrae del propio YAML** en cada pasada en vez de copiarse a mano, porque
  una copia se queda vieja y entonces la comprobación miente. Resultados: 243s → `pass` sin aviso ·
  380s → `pass` **con** aviso destacado · 500s → `fail` · duración vacía con suite verde → `fail` y
  el resumen lo dice con esas palabras · camino corto → `pass` y «no aplica», sin laguna · suite en
  rojo → `fail` y la duración se sigue nombrando · detección rota → `fail`. **Las siete escriben
  resumen y veredicto**, que es lo que 6.5 exige.*
  *Y el panel de QA encontró que esas siete no bastaban: las comparaciones `[ … -gt … ]` van en
  posición de test de un `if`, **exenta de `set -e`**, así que un valor no numérico hacía fallar la
  comparación y bash leía el fallo como «no pasa del techo» → verde silencioso, justo lo que R4.3
  prohíbe. Dos entradas lo disparaban: `SUITE_SECONDS` no numérico, y `BUDGET`/`CEILING` vacíos con
  una duración realmente por encima del techo. Se cierra validando los tres valores como enteros
  **antes** de comparar —forma y rango, porque 30 dígitos pasan el filtro de caracteres y luego
  desbordan la aritmética, que es la misma laguna un paso más adentro—. Comprobado sobre el script
  extraído del YAML: `abc` → `fail` · `BUDGET=`/`CEILING=` con 500s → `fail` · 34 dígitos → `fail` ·
  `1000000000` → `fail` · `999999999` → se compara bien · y las siete originales sin cambio)*
- [x] 6.5 Comprobar que **ninguna** ruta nueva impide que el check se publique: las tres ramas que
  ya existían (detección rota, suite verde, suite omitida legítimamente) siguen produciendo
  resumen y veredicto, y el job `backend-tests` conserva `if: always()` y su nombre —
  **Files:** `.github/workflows/backend-tests.yml`. [R4.4]

## 7. Fase 2 — paralelismo con `pytest-xdist` (D6) <!-- panel: PASS 2026-08-10 -->

**No empezar hasta que §5 esté cerrada y la fase 1 verde en CI.**

- [x] 7.1 Añadir `pytest-xdist` al grupo `dev` — **Files:** `backend/pyproject.toml`,
  `backend/uv.lock` (regenerado con `uv lock`, no a mano). [R2.1]
- [x] 7.2 Incorporar el id del worker al sufijo de las bases de datos desechables:
  `run_suffix()` concatena `PYTEST_XDIST_WORKER` cuando existe — **Files:**
  `backend/tests/db_names.py`. Sin esto, con `PYTEST_DB_SUFFIX: ci` fijado en el workflow los
  cuatro procesos calculan el mismo nombre y el `DROP DATABASE IF EXISTS` de la fixture de
  migraciones borra la base que otro está usando. Actualizar el docstring del módulo, que hoy
  explica el sufijo solo como pid. [R3.3, R3.4]
- [x] 7.3 Hacer que `make db-clean-test` reconozca los nombres nuevos: su patrón
  `_(test|migrations)_[0-9a-z]+$` no acepta el guion bajo de `autohostai_test_ci_gw0` —
  **Files:** `Makefile:147-155`. **Hecho** = con dos bases `…_test_ci_gw0`/`…_test_ci_gw1`
  creadas a mano, el target las borra. [R3.3]
- [x] 7.4 Una base lógica de **Redis por worker**: derivar el índice desde `PYTEST_XDIST_WORKER`
  sobre `settings.redis_url` en el `conftest` raíz, con un guardián que falle a la cara si el
  índice supera **15** (cuanto tiene Redis por defecto) — **Files:** `backend/tests/conftest.py`.
  Motivo: `backend/tests/scheduler/test_dispatch_task.py:53` toma el nombre de cerradura de
  producción (`dispatch_notifications`) sobre el Redis compartido y hay otro test que exige
  encontrarla libre. **Hecho** = un test que compruebe que dos workers distintos resuelven
  índices distintos, y el guardián demostrado en rojo con un id de worker por encima del tope.
  [R3.4]
- [x] 7.5 Ids de test **deterministas** en los tres ficheros que hoy hacen abortar la recolección
  con `Different tests were collected between gw0 and gw3` — **Files:**
  `backend/tests/reservations/test_authorization.py:109-111`,
  `backend/tests/auth/test_user_admin_authorization.py:111-114`,
  `backend/tests/properties/test_state_machine.py`. En los dos primeros la causa es literal
  (`uuid.uuid4()` dentro de `@pytest.mark.parametrize`) y el arreglo es una constante de módulo
  con un UUID literal — son identificadores de «recurso que no existe», así que un valor fijo
  además se lee mejor. En el tercero **hay que confirmar la causa antes de tocar**: sus
  `parametrize` no llevan `uuid4()`, pero `EXPECTED_POLICY` (línea 175) mapea a **conjuntos** de
  enums y `DECLARED_POLICY_RELATIONS` / `INVALID_DESTINATIONS_FOR_DECLARED_PAIRS` los recorren, y
  el orden de iteración de un `set` de enums varía entre procesos; si es eso, el arreglo es
  ordenar de forma estable, no sustituir UUIDs. **Hecho** = `pytest --collect-only -q` sobre los
  tres ficheros da una lista **byte a byte idéntica** en dos procesos distintos. [R3.1, R3.4]
  *(la causa del tercero se confirmó antes de tocar, y la sospecha del diseño era la correcta pero
  **no completa**. Se comprobó que el `md5sum` de la recolección difería entre dos procesos
  mientras que el conjunto **ordenado** de ids era idéntico: luego lo que bailaba era el orden, no
  los ids — descarta `uuid4()` y señala a los conjuntos. Las fuentes reales eran **dos**:
  (a) `DECLARED_POLICY_RELATIONS`, que recorre los conjuntos de enums de `EXPECTED_POLICY`; y
  (b) `ContextualStateResolver.CONTEXTUAL_STATES`, un `frozenset` de **código de producción** que
  dos `parametrize` convertían en lista — esta segunda no estaba identificada en el diseño y solo
  apareció al repetir la comprobación. `INVALID_DESTINATIONS_FOR_DECLARED_PAIRS`, que el diseño
  también señalaba, resultó ser determinista: itera la clase enum y solo usa el conjunto para
  pertenencia. Se ordena en el test, no en producción: el conjunto de producción no tiene por qué
  estar ordenado y el requisito es del test. De paso se ordenaron dos `next(iter(...))` que elegían
  un destino distinto por proceso —no afectan a los ids, pero harían que el mismo test ejercitara
  un caso distinto en cada worker—. **Comprobado**: recolección idéntica byte a byte sobre los tres
  ficheros y, además, sobre la **suite entera** (5 371 ids; solo difiere la línea del tiempo))*
- [x] 7.6 Declarar el paralelismo en CI: `-n 4` en el paso de la suite (número declarado, no
  `-n auto`: hoy daría 4 y mañana lo que el runner traiga, y 7.4 tiene un techo de 15) —
  **Files:** `.github/workflows/backend-tests.yml`. La ejecución en serie sigue siendo la de
  local por defecto; quien quiera paralelo lo pasa por la línea de órdenes. [R2.1]
- [x] 7.7 Verificación de la fase 2 en local: **tres ejecuciones consecutivas verdes** con `-n 4`
  **más una con un `-n` distinto** (un reparto diferente prueba independencia del worker mejor que
  repetir el mismo), todas con los recuentos de 3.4 y sin `attached to a different loop` ni
  `another operation is in progress`; y comprobar que no quedan bases desechables huérfanas al
  terminar. [R3.1, R3.4, R3.5]
  *(2026-08-10, las cuatro verdes con **5 336 pasados + 35 omitidos** y el mismo motivo de omisión:
  `-n 4` → **57,39s · 56,11s · 53,16s**, y `-n 3` → **63,93s**. Ni un `attached to a different
  loop` ni un `another operation is in progress`, y ninguna base desechable en pie al terminar.
  Los 5 336 son los 5 331 de la fase 1 más los **5 tests de 7.4**. Contra los ~190s en serie de
  esta misma máquina, `-n 4` da **3,5×**)*

## Candidato para un change futuro (fuera de alcance aquí)

**`make db-clean-test` no distingue una base huérfana de una viva.** Borra con `WITH (FORCE)` toda
base que encaje el patrón, así que lanzarlo con una suite corriendo la destroza: medido a propósito
durante el panel de la §7 —una ejecución verde con `-n 4` convertida en **771 errores** de
`InvalidCatalogNameError`—. Es preexistente (una suite en serie también caía), pero el paralelismo
lo agrava: cuatro bases por ejecución en vez de una. Aquí solo se ha dejado el peligro escrito en el
propio target.

Filtrar por `pg_stat_activity` **no vale y está medido**: bajó el daño a 144 errores sin cerrarlo,
porque `NullPool` desecha el engine entre tests y toda base viva tiene ventanas de cero conexiones.
La salida que propuso el revisor de tenancy, y que parece la buena: que `_the_run_database` abra
**una conexión larga aparte** de las de `test_engine` y tome sobre ella un `pg_advisory_lock` de
sesión con el nombre de la base; el barrido intenta `pg_try_advisory_lock` sobre cada candidata y se
salta las que no consigue. Sobrevive a los huecos porque no pregunta «¿hay alguien conectado ahora?»
sino «¿sigue viva la conexión que representa la ejecución?». Antes de construirlo hay que comprobar
que la derivación de la clave no colisione con ningún advisory lock que tome la aplicación.

## 8. Medición final, presupuesto ajustado y documentación

- [ ] 8.1 Tres `workflow_dispatch` secuenciales sobre la rama con la fase 2, mediana del paso de
  `pytest`, y contraste con los 5m 00s de R2.1 — **Files:** `measurement.md` §4. Si la mediana lo
  cumple, ajustar presupuesto y techo de 6.2 a la cifra real **con margen sobre la mediana, no
  sobre el mejor caso**; si no lo cumple, aplicar 5.3 (techo medido, causa, y R2 sin dar por
  cumplido). [R2.1, R2.3, R4.1]
- [ ] 8.2 Actualizar la cabecera del workflow, que hoy afirma «~6m15s la suite, ~7m05s el
  workflow (medido el 2026-08-03)» y el reparto de los 49s restantes — **Files:**
  `.github/workflows/backend-tests.yml:14-19`. La cifra nueva va **fechada y con el paso dominante
  identificado**, que es la regla que la propia spec impone. [R2.2]
- [x] 8.3 Convención de fixtures compartidas al día: el esquema se construye **una vez por
  ejecución** y el aislamiento entre tests es por **vaciado de filas**, no por `create_all`/
  `drop_all` — **Files:** `sdd/steering/testing.md` (§Convenciones, línea 23). [R3.2]
- [ ] 8.4 README raíz: §Tests menciona el paralelismo disponible en local (`-n auto`) sin cambiar
  el comando canónico — **Files:** `README.md:210-220`. Solo si 7.1 entró; si la fase 2 se
  descartara, esta tarea desaparece con ella. [R2.1]
- [x] 8.5 Dejar **redactado en este change** el texto que `/sdd:archive` llevará a
  `sdd/specs/backend-ci.md` —las specs vivas solo las escribe el archivado
  (`steering/documentation.md`)—: (a) §Coste con la medición fechada nueva, su mediana de tres
  ejecuciones y el procedimiento, sustituyendo la de 2026-08-03 y retirando el párrafo «Reducir
  esos 6m15s queda fuera de esta capacidad»; (b) §Aislamiento entre ejecuciones concurrentes con
  el modelo de esquema una vez y la base desechable **por worker**; (c) un requisito EARS nuevo
  para el presupuesto de tiempo; (d) §Key files con `Makefile` si 7.3 entró — **Files:**
  `sdd/changes/backend-suite-runtime/spec-updates.md` (nuevo). [R2.2, R4.1]
- [ ] 8.6 Completar `measurement.md` §4 con lo realmente ejecutado —cifras de 5.1, 5.2 y 8.1, ids
  de los runs y la mediana de cada tanda— de modo que el procedimiento siga siendo repetible por
  cualquiera con los datos delante — **Files:** `measurement.md`. [R1.1]

## 9. Verification

- [ ] 9.1 Suite completa del backend en verde desde el stack de este worktree:
  `docker compose exec backend uv run pytest -q -rs`, con **5 329 pasados + 35 omitidos** y los
  mismos motivos de omisión que la línea base de `measurement.md` §1. [R3.1, R3.2]
- [ ] 9.2 Tres ejecuciones consecutivas verdes en la configuración final (con `-n 4` si la fase 2
  entró), sin `attached to a different loop` ni `another operation is in progress`. [R3.5]
- [ ] 9.3 Sin lint ni typecheck que correr: el proyecto no declara ninguno (`sdd/project.md`
  §Commands y `sdd/specs/backend-ci.md` §Estado lo dejan escrito). Se comprueba que sigue siendo
  cierto, no se inventa uno.
- [ ] 9.4 El check `backend-tests` reporta verde en el PR con la duración y las dos cifras del
  presupuesto en su resumen, y el camino corto (un PR que no toque `backend/**`) sigue reportando
  verde sin duración. [R4.2, R4.4]
- [ ] 9.5 `make db-clean-test` no encuentra bases desechables huérfanas tras las ejecuciones de
  9.1-9.2. [R3.3]
