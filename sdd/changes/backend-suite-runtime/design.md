# Design: backend-suite-runtime

## Context

La suite del backend son **5 364 casos** (2 476 `def test_`, parametrizados) que en CI tardan
**15m 34s** en el paso `pytest -q -rs` y **10m 06s** en esta máquina. El coste no está en unos pocos
tests lentos: está en la fixture `test_engine` de `backend/tests/conftest.py:75-96`, que es
*function-scoped* y hace `Base.metadata.create_all` al entrar y `drop_all` al salir, sobre una base
de datos desechable por ejecución cuyo nombre construye `backend/tests/db_names.py`
(`<db>_test_<pid>`, fijable con `PYTEST_DB_SUFFIX`). La piden **1 332 casos** directamente o a través
de `db_session`.

Alrededor hay tres piezas que este diseño no puede romper: el workflow de tres jobs
`.github/workflows/backend-tests.yml` (detección → suite → publicación con `if: always()`), la
cadena real de migraciones que `backend/tests/test_migrations.py` prueba contra **su propia** base
desechable con `DROP DATABASE IF EXISTS`, y el motivo por el que la fixture es como es: su docstring
documenta que un engine por test con `NullPool` es lo que evita los fallos «attached to a different
loop» / «another operation is in progress» al no reutilizar una conexión asyncpg entre los bucles de
evento por test de pytest-asyncio.

## Medición (R1)

Hecha el **2026-08-10** en este worktree (`docker compose exec backend uv run pytest`), con un plugin
de atribución que envuelve `pytest_fixture_setup` y las tres fases de cada test. El procedimiento y los dos
scripts, comprobados tal como están escritos, quedan en
`sdd/changes/backend-suite-runtime/measurement.md`. Resultado sobre
**5 329 pasados + 35 omitidos en 618,51s** (la instrumentación cuesta ~2 % sobre los 606,71s del
proposal):

| Causa | Tiempo | % |
|---|---|---|
| Creación del esquema por test (`create_all`, dentro del setup de `test_engine`) | 343,53s | 55,5 % |
| Borrado del esquema por test (`drop_all` + `dispose`, fase teardown) | 136,67s | 22,1 % |
| Resto de fixtures (semillas: `tenant_a` 25,40s/977, `users_by_role_a` 7,11s/512, …) | 39,86s | 6,4 % |
| Cuerpo de los tests (fase `call`) | 92,42s | 14,9 % |
| Recolección y arranque/parada de la sesión | 2,40s | 0,4 % |
| **Atribuido** | **614,88s** | **99,4 %** |

La segunda fila se atribuye a `test_engine` y no solo se declara: el teardown total son 136,67s
repartidos entre los 1 332 tests que tienen esa fixture (**103 ms** cada uno), y la medición
independiente de `drop_all` da **121 ms**. R1.3 queda cubierto con holgura (99,4 % ≥ 80 %).

Coste unitario de cada pieza, medido aparte contra las 29 tablas reales (medianas de dos ejecuciones
del banco, 8-10 repeticiones cada una):

| Operación | Ejecución 1 | Ejecución 2 |
|---|---|---|
| `Base.metadata.create_all` | 303,6 ms | 195,8 ms |
| `Base.metadata.drop_all` | 120,8 ms | 93,9 ms |
| `TRUNCATE` de las 29 tablas | 112,5 ms | 119,6 ms |
| **Borrar todas las filas en una sola sentencia** | **21,1 ms** | **22,9 ms** |
| 29 `DELETE` en sentencias separadas | 28,8 ms | — |
| `create_async_engine` + primera conexión | 29,9 ms | — |

El DDL varía bastante entre ejecuciones del banco (158-337 ms en `create_all`), así que **la cifra
por test que manda es la de la tabla de arriba** —258 ms de setup + 103 ms de teardown = **361 ms**,
medidos dentro de la suite real—; el banco sirve para comparar estrategias, y para eso su margen
sobra: crear y tirar el esquema cuesta entre 13 y 20 veces lo que vaciar las filas.

**Lo que falta y lo pone la implementación**: la mitad en CI de R1.1 —tres ejecuciones antes y tres
después sobre la misma referencia— porque necesita el branch publicado. La medición local ya está
hecha y es la que sostiene las decisiones de abajo.

## Decisions

### D1 — El esquema se construye una vez por ejecución; entre tests se borran las filas

**Chosen:** `create_all` pasa a una fixture de sesión y `test_engine` deja de crear y tirar el
esquema; lo que hace en cada test es vaciar todas las tablas. Medido de punta a punta con un
prototipo: **618s → 168s** (mediana de dos ejecuciones completas: 165,74s y 170,66s), **3,6×**, con
el mismo recuento exacto —5 329 pasados, 35 omitidos, mismo motivo de omisión— y **sin tocar ni un
fichero de test**. Ataca el 77,6 % que la medición señala y deja el cuerpo de los tests intacto,
que es lo que R3 exige.

Rejected: **transacción con rollback por test** (la salida clásica, ~1 ms) — la rompen **17 usos en
8 ficheros** que abren una segunda sesión o conexión sobre `test_engine`
(`tests/auth/test_last_owner_concurrency.py`, `tests/integrations/test_webhook_endpoints.py`,
`tests/notifications/test_escalate_slas_atomicity.py`, `tests/test_db_session.py`…): dos de ellos
prueban **carreras entre transacciones concurrentes** a propósito, y una transacción externa sin
confirmar es invisible para otra conexión, así que dejarían de ver lo que verifican. Rescatarlos
sería reescribir tests de concurrencia, que es lo que «Out of scope» excluye.
Rejected: **una base de datos por test creada desde un `template`** — `CREATE DATABASE` cuesta más
que los 361 ms que se quieren eliminar.
Rejected: **`test_engine` con ámbito de sesión o de módulo** — reintroduce exactamente el
compartir-conexión-entre-bucles que el docstring de la fixture documenta como origen de
«attached to a different loop».

### D2 — El vaciado es una sola sentencia con un `DELETE` por tabla

**Chosen:** una sentencia `WITH d0 AS (DELETE FROM "…"), d1 AS (DELETE FROM "…") … SELECT 1`
generada desde `Base.metadata.sorted_tables`. **21,1 ms** frente a los 112,5 ms de `TRUNCATE`
—cinco veces menos— y un solo viaje de ida y vuelta. Los `DELETE` comparten snapshot y las
comprobaciones de clave ajena ocurren al final de la sentencia, así que el orden entre tablas es
irrelevante; y no hay secuencias que reiniciar porque en todo el árbol hay **una sola** definición
de clave primaria y es un UUID (`backend/app/core/db.py:29`).

Que la lista salga de la metadata es la garantía de que no se queda corta: una tabla nueva entra
sola en el vaciado, igual que entra sola en `create_all`, y una tabla que **no** esté en la metadata
tampoco existe en la base de datos de la suite.

Rejected: **`TRUNCATE`** — 112,5 ms, y el coste es de operaciones de fichero y bloqueos, no de WAL:
`synchronous_commit = off` no lo mejora (119,1 ms medido), así que no hay ajuste que lo rescate.
Rejected: **29 `DELETE` sueltos** — 28,8 ms y 29 viajes; además asyncpg **rechaza** varias órdenes en
una sentencia preparada (`cannot insert multiple commands into a prepared statement`), que es lo que
descartó la forma ingenua `DELETE …; DELETE …`.
Rejected: **`synchronous_commit = off` en la base de la ejecución** — medido, ~1 ms de diferencia;
una pieza móvil más sin premio.

### D3 — La base de datos de la ejecución se construye desde cero al arrancar la sesión

**Chosen:** la fixture de sesión hace `DROP DATABASE IF EXISTS … WITH (FORCE)` + `CREATE DATABASE` +
`create_all` al empezar, y el `DROP` que ya existía al terminar. Hoy el «crear si falta» es inocuo
porque cada test recreaba el esquema entero; con el esquema construido una sola vez, heredar una
base de datos que dejó una ejecución muerta significaría heredar **su** esquema — y el caso es real
precisamente en CI, donde `PYTEST_DB_SUFFIX: ci` fija el nombre y lo hace reutilizable.

Rejected: `DROP SCHEMA public CASCADE` + `CREATE SCHEMA` — equivalente en efecto y sin ventaja
medible, y deja vivos los ajustes de la base de datos, que es lo contrario de «desde cero».

### D4 — `test_engine` y `db_session` conservan nombre, firma y ámbito de función

**Chosen:** el contrato que ven los 209 ficheros de test no cambia: `test_engine` sigue siendo un
engine con `NullPool` creado por test, y `db_session` sigue colgando de él. Con eso R3.1 y R3.2 se
cumplen **por construcción** —mismos tests, mismo orden, mismos recuentos— y el motivo documentado
de `NullPool` sigue en pie. El precio es 23,2 ms por test de crear engine, conectar y vaciar, que es
el 6 % de los 360 ms actuales.

Rejected: renombrar o dividir las fixturas para «dejar claro el nuevo modelo» — sería un diff de 209
ficheros a cambio de nada que ningún requisito pida.

### D5 — El test de la carrera del índice único pasa a ser determinista

**Chosen:** `tests/integrations/test_webhook_endpoints.py::test_an_insert_that_loses_the_unique_race_is_a_domain_refusal`
deja de confiar en la planificación de `asyncio.gather` y fuerza el solape: los dos llamantes se
citan en una barrera **después** de su `SELECT` y **antes** del `flush`, con lo que el resultado
—exactamente uno pierde el índice— no depende de quién llegue primero.

No es teoría: **falló en una de las dos ejecuciones completas del prototipo**, con
`assert len(failures) == 1` recibiendo `0 = len([])`. Cero fallos solo puede significar que el
`SELECT` del segundo llamante corrió **después** del `COMMIT` del primero, así que tomó la rama de
actualización y nunca llegó al índice. Es una fragilidad **preexistente** que el modelo viejo
enmascaraba: 361 ms de DDL por test hacían el solape abrumadoramente probable. Sin arreglarla, R3.5
(tres ejecuciones consecutivas verdes) es una lotería.

Rejected: marcarlo `flaky`/reintentar — R3.2 prohíbe pagar el ahorro con la señal, y un reintento
convierte una carrera real en ruido.
Rejected: dejarlo como está y confiar en que el prototipo tuvo mala suerte — una ejecución roja de
cada dos es la definición del problema, no de la mala suerte.

### D6 — Paralelismo con `pytest-xdist`, en una segunda fase y con aislamiento por worker

**Chosen:** después de D1-D5, `pytest -n 4` en CI. Medido en local sobre 4 678 tests: **176,69s
serie → 55,97s con `-n 4`**, en verde, **3,16×**. En el runner de GitHub no se transferirá entero
—`ubuntu-latest` tiene 4 vCPU y ahí dentro también corren PostgreSQL y Redis, mientras esta máquina
tiene 12— así que la proyección honesta es **2-2,5×**.

Exige cuatro cosas, y las cuatro salen de haberlo intentado, no de imaginarlo:

1. **El id del worker en el sufijo de las bases de datos.** `PYTEST_DB_SUFFIX` está **fijado** a
   `ci` en el workflow, así que sin el worker los cuatro procesos calculan el mismo nombre y el
   `DROP DATABASE IF EXISTS` de la fixture de migraciones borra la base que otro está usando — el
   fallo exacto que `db_names.py` existe para evitar.
2. **`make db-clean-test` tiene que reconocer los nombres nuevos.** Su patrón es
   `_(test|migrations)_[0-9a-z]+$`, y `autohostai_test_ci_gw0` no encaja porque `[0-9a-z]` no
   incluye el guion bajo: sin tocarlo, dejaría huérfanas justo las bases que el paralelismo crea.
3. **Ids de test deterministas en tres ficheros.** Con `-n 4` la suite **no llega ni a arrancar**:
   `Different tests were collected between gw0 and gw3`, porque `tests/reservations/test_authorization.py`,
   `tests/auth/test_user_admin_authorization.py` y `tests/properties/test_state_machine.py` meten
   `uuid.uuid4()` en los valores de `@pytest.mark.parametrize` y cada worker recolecta ids distintos.
   El arreglo es una constante con un UUID literal donde hoy hay uno aleatorio: son identificadores
   de «recurso que no existe», así que un valor fijo además se lee mejor.
4. **Una base lógica de Redis por worker.** `tests/scheduler/test_dispatch_task.py:53` toma el
   **nombre de cerradura de producción** (`dispatch_notifications`) sobre el Redis compartido, y hay
   otro test que exige encontrarla libre: en workers distintos pueden cruzarse. Todos los clientes
   de la suite y el propio `get_redis()` salen de `settings.redis_url`, así que basta derivar el
   índice de base lógica del id del worker en el `conftest` raíz — con un guardián que falle a la
   cara si el índice pasa de 15, que es cuanto tiene Redis por defecto.

Rejected: `--dist loadfile` como sustituto de (3) o (4) — no arregla ninguna de las dos; la
recolección divergente aborta igual y las claves de Redis se comparten entre ficheros.
Rejected: `-n auto` en CI — hoy daría 4 y mañana lo que el runner traiga, y (4) tiene un techo de 15;
el número se declara.
Rejected: dejar la suite en serie también en local — no hace falta declarar nada: quien quiera
`-n auto` lo pasa por la línea de órdenes, y la salida en serie sigue siendo la legible para
`pytest -k`.

### D7 — El presupuesto de tiempo vive en el workflow y lo compara el job que ya publica siempre

**Chosen:** **dos cifras** —presupuesto y techo, decisión del usuario en la pregunta abierta 1— se
declaran como `env:` a nivel de workflow en `.github/workflows/backend-tests.yml` (dato versionado,
revisable en el diff, ajeno a la UI de GitHub — R4.1 y la norma IaC-first de `steering/infra.md`).
Pasar el presupuesto emite un aviso destacado en el resumen; pasar el techo pone el check en rojo. El paso de `pytest` se cronometra y publica su duración como **salida del
job**; el job `backend-tests`, que ya corre con `if: always()`, la compara con el presupuesto y la
escribe en el resumen nombrando ambas cifras. Si la suite se ejecutó pero la duración **no llegó**,
el resumen lo dice con esas palabras y el veredicto no es verde (R4.3); si la suite se saltó por el
camino corto, no hay duración que comparar y eso no es una laguna. La ruta de publicación no se
toca, así que R4.4 se mantiene: no hay rama nueva por la que el check deje de reportarse.

Cronometrar dentro del propio paso, y no restando marcas de tiempo de la API de GitHub, es
deliberado: la duración tiene que existir aunque `pytest` falle, así que el paso captura el código
de salida, escribe la duración y solo después se rinde con ese código.

Rejected: un fichero `backend/tests/time_budget.json` — igual de versionado, pero el job que reporta
no hace `checkout` hoy y habría que añadirle uno para leer un solo número.
Rejected: usar `timeout-minutes` como presupuesto — es una guillotina a los 20 minutos, y su
incumplimiento se lee como avería de infraestructura, no como regresión de rendimiento. Se **queda
como está**: bajarlo a ras del nuevo tiempo convertiría la variabilidad del runner en rojos, y para
la regresión ya está el presupuesto.

### D8 — R5: la aserción se invierte, y la redacción del requisito también estaba invertida

**Chosen:** `test_subclasses_come_before_their_base` comprobará, para cada par de filas *(i, j)* con
*i < j*, que **la fila posterior no es subclase de la anterior** — que es lo que «primera
coincidencia gana» exige: una base colocada antes de su subclase se traga a la subclase y devuelve
el status de la base. Hoy comprueba `not issubclass(anterior, posterior)`, que prohíbe justo la
disposición **correcta** y permite la rota; es vacío porque todos los errores de `cleaning` son
hijos directos de `CleaningDomainError`, que no es fila.

**Ojo con el enunciado de R5.1**: su primera oración —«ninguna fila posterior de `_MAPPING` es clase
base de una anterior»— describe la aserción **actual**, no la correcta. La segunda —«ninguna
subclase queda después de su base»— es la buena y es la que coincide con la nota de roadmap. Este
diseño implementa la segunda. Y R5.2 cita «la regla 13(c) de `steering/security.md`» para pedir la
demostración en rojo: esa regla habla de datos de tarjeta en fixtures versionados, no de demostrar
tests en rojo. La práctica que pide es correcta y se hace —una fila con una subclase colocada
después de su base, el test en rojo, y fuera— pero la cita no la respalda.

## Changes by area

| Área | Ficheros | Cambio |
|---|---|---|
| Fixtures de la suite | `backend/tests/conftest.py` | Fixture de sesión que crea la base y el esquema (D3); `test_engine` vacía las tablas con la sentencia de D2 y ya no hace `create_all`/`drop_all`; `SET lock_timeout` antes del vaciado |
| Nombres de bases | `backend/tests/db_names.py` | Fase 2: el sufijo incorpora `PYTEST_XDIST_WORKER` |
| Aislamiento de Redis | `backend/tests/conftest.py` | Fase 2: índice de base lógica de Redis por worker sobre `settings.redis_url`, con tope de 15 |
| Limpieza de huérfanas | `Makefile` (`db-clean-test`) | Fase 2: el patrón acepta sufijos con guion bajo (`_test_ci_gw0`) |
| Dependencias | `backend/pyproject.toml`, `backend/uv.lock` | Fase 2: `pytest-xdist` en el grupo `dev` |
| Ids de test estables | `backend/tests/reservations/test_authorization.py`, `backend/tests/auth/test_user_admin_authorization.py`, `backend/tests/properties/test_state_machine.py` | Fase 2: UUID literal donde hoy hay `uuid.uuid4()` dentro de `parametrize` |
| Carrera determinista | `backend/tests/integrations/test_webhook_endpoints.py` | Barrera entre el `SELECT` y el `flush` de los dos llamantes (D5) |
| Guardián de orden | `backend/tests/cleaning/test_errors.py` | Aserción invertida corregida y demostrada en rojo (D8) |
| Workflow | `.github/workflows/backend-tests.yml` | Paso de `pytest` cronometrado con salida de job; presupuesto en `env:`; comparación en el job consolidador; fase 2: `-n 4`; cabecera con la cifra nueva fechada |
| Especificación | `sdd/specs/backend-ci.md` | §Coste con la medición fechada nueva y su procedimiento; §Aislamiento con el modelo de esquema una vez y, en fase 2, la base por worker; requisito nuevo del presupuesto |
| Convenciones | `sdd/steering/testing.md` | La convención de fixtures compartidas dice que el esquema se construye una vez por ejecución y que el aislamiento entre tests es por vaciado de filas |
| Medición | `sdd/changes/backend-suite-runtime/measurement.md` (ya escrito en esta fase) | Procedimiento repetible de R1: plugin de atribución, banco de coste unitario, resultados locales y cómo se miden las tres ejecuciones en CI (esa parte la completa la implementación) |

## Data & interfaces

- **Sin cambios de esquema, de API ni de contrato OpenAPI.** Nada de esto sale de `backend/tests/`,
  el `Makefile`, el workflow y los documentos.
- **Variables de entorno**: `PYTEST_DB_SUFFIX` sigue significando lo mismo; en fase 2 el nombre
  efectivo pasa a ser `<db>_test_<sufijo><worker>` y `PYTEST_XDIST_WORKER` la aporta xdist, nadie la
  configura. En el workflow, dos valores nuevos en `env:` para el presupuesto (una cifra o dos,
  según la pregunta abierta 1).
- **Salidas de job nuevas** en `backend-tests-suite`: la duración en segundos del paso de `pytest`,
  consumida por `backend-tests`.
- **Procedimiento de medición en CI** (R1.1, R2.1): tres `workflow_dispatch` sobre la misma
  referencia, **secuenciales**. No es un detalle de comodidad: el workflow declara
  `concurrency: backend-tests-${{ github.ref }}` con `cancel-in-progress: true`, así que tres
  disparos solapados se cancelan entre sí y solo sobreviviría el último. La duración de cada paso se
  lee de `/repos/{owner}/{repo}/actions/runs/{id}/jobs`.

## Risks & mitigations

- **Un test que deja una transacción abierta bloquearía el vaciado del siguiente.** Hoy no ocurre
  (el modelo actual haría lo mismo con `drop_all`), pero el fallo sería un cuelgue en vez de un
  rojo: `SET lock_timeout` en la conexión que vacía lo convierte en error inmediato y legible.
- **Fuga entre tests si el vaciado se queda corto.** La sentencia se deriva de
  `Base.metadata.sorted_tables`, la misma fuente que `create_all`, así que no hay lista paralela que
  mantener. Verificación explícita: un test que siembre padre e hijo y compruebe que ambos
  desaparecen.
- **Dependencias de orden que el esquema por test enmascaraba.** Medidas, no supuestas: la suite
  completa dio verde con los mismos recuentos y apareció **una sola** (D5). R3.5 —tres ejecuciones
  consecutivas verdes— es el cierre, y en fase 2 se repite con `-n 4` y con un `-n` distinto, porque
  un reparto diferente prueba independencia del worker mejor que repetir el mismo.
- **El 3,16× de xdist no se transfiere entero a CI** (4 vCPU compartidos con PostgreSQL y Redis
  frente a 12 aquí). Es la razón de que R2.1 se mida en CI y no se declare por extrapolación, y de
  que la proyección honesta sea 2-2,5×.
- **Objetivo de R2.1 con la fase 1 sola**: 168s locales × 1,54 (la razón medida CI/local) ≈
  **4m 18s**. Cumple los 5m 00s con **~42s de margen** sobre una suite que creció 2,5× en seis días.
  Con la fase 2, ~**2m** y margen de verdad. Es exactamente el material de la pregunta abierta 2.
- **El presupuesto puede volverse ruido si se ajusta al tiempo medido.** Se declara con margen sobre
  la mediana medida, no sobre el mejor caso, y el resumen nombra siempre las dos cifras para que un
  rojo o un aviso se pueda juzgar sin abrir el log.

## Open questions

Las dos que había están **resueltas por el usuario el 2026-08-10**, y quedan aquí con su decisión
porque son las que dan forma a D6 y D7:

1. **Superar el presupuesto: ¿rojo o aviso?** (R4.2). **Decidido: dos umbrales.** Aviso destacado en
   el resumen al pasar el presupuesto (5m 00s) y rojo al pasar un techo declarado (7m 30s, sujeto a
   la cifra que salga de la medición en CI). Un solo umbral obliga a elegir entre convertir la
   variabilidad del runner —±20-30 %— en bloqueos de merge, o publicar un aviso que nadie mira. Las
   dos cifras son las que van en `env:` según D7, y el resumen nombra siempre la medida y las
   declaradas.
2. **¿La fase 2 (xdist) entra en este change?** **Decidido: sí, las dos fases.** La fase 1 sola deja
   ~42s de margen frente a un crecimiento medido de 2,5× en seis días; los cuatro requisitos de D6
   están identificados y medidos, así que el riesgo es conocido. Consecuencia para `/sdd:tasks`: dos
   bloques con verificación propia —R2.1 se mide al final de cada uno— y la fase 2 no arranca hasta
   que la fase 1 esté verde en CI, para que un fallo de xdist no arrastre el ahorro que ya está
   ganado.

Nada más quedó pendiente de decisión: el resto de alternativas se descartaron con medición y consta
en cada decisión.
