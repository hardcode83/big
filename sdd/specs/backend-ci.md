# Integración continua del backend

## Purpose

Esta capacidad ejecuta en GitHub Actions, sobre un entorno limpio y en cada Pull Request,
la misma verificación que `sdd/project.md` manda ejecutar en local: migraciones, coherencia
esquema↔modelos y la suite completa del backend. Existe para que "la suite está verde" sea
un hecho reproducible por cualquiera y no una afirmación de la máquina de quien la ejecutó.

Es una capacidad separada del despliegue (`app-deploy-dev`): valida, no publica ni despliega.

No es el único workflow que valida el backend en cada PR: `api-contract` comprueba que
`backend/openapi.json` corresponde al código (`specs/api-contract.md`). Vive aparte porque no
necesita PostgreSQL ni Redis y da señal en segundos, y porque mezclar ambas señales haría que
olvidar regenerar el contrato cortara la ejecución antes de la suite.

## Requirements

### Disparadores y alcance

- WHEN se abre o actualiza un Pull Request, o se hace push a `main`, THE SYSTEM SHALL
  ejecutar el workflow `backend-tests`.
- THE SYSTEM SHALL **reportar siempre un resultado del check `backend-tests`**, toque el diff
  el backend o no. Este es el invariante del que dependen los demás: un check requerido que
  *no se ejecuta* deja el Pull Request bloqueado esperando indefinidamente uno que no va a
  llegar, mientras que uno que se ejecuta y reporta verde en segundos no bloquea a nadie.
- THE SYSTEM SHALL conseguirlo **sin `paths:` en `on:`**. La prohibición sigue en pie y por el
  motivo original: un filtro de rutas a nivel de disparador no produce check alguno en los PR
  que no tocan esas rutas. El filtrado ocurre **dentro** del workflow, no en su disparador.
- THE SYSTEM SHALL estructurarlo en tres jobs: `backend-tests-detect` decide el área a partir
  del diff, `backend-tests-suite` corre la verificación completa **solo si** la detección dice
  que el diff toca el backend, y `backend-tests` publica el resultado con `if: always()` — que
  es lo que garantiza el invariante incluso cuando la suite se salta.
- THE SYSTEM SHALL cancelar la ejecución anterior de la misma referencia cuando llega una
  nueva (`concurrency` con `cancel-in-progress`), y limitar cada job a su propio tope: 5
  minutos para detección y publicación, 20 para la suite.
- THE SYSTEM SHALL conceder al workflow solo `contents: read`.

### Detección del área y camino corto

- THE SYSTEM SHALL derivar del diff una decisión booleana sobre si el cambio afecta al backend,
  y exponerla junto a un **motivo legible** como salidas del job de detección.
- WHEN la detección concluye que el diff **no** toca el backend, THE SYSTEM SHALL saltarse la
  suite y publicar el check en verde con ese motivo, de modo que un PR que solo toca
  documentación o `sdd/` obtenga su resultado en segundos en lugar de esperar la suite entera.
- WHEN la detección concluye que **sí** lo toca, THE SYSTEM SHALL ejecutar la verificación
  completa descrita abajo **sin recortarla**: el camino corto es una vía rápida para diffs
  ajenos al backend, nunca una versión reducida de la verificación.
- IF la detección falla o no puede determinar el área, THEN THE SYSTEM SHALL decidir a favor de
  ejecutar la suite: la decisión **arranca en «sí toca»** y solo una comprobación afirmativa la
  baja. Equivocarse hacia «ejecuta» cuesta minutos; equivocarse hacia «salta» publica un verde
  que no verificó nada.
- THE SYSTEM SHALL leer el diff con las rutas **sin escapar** (`core.quotePath=false`) y
  separadas por NUL (`-z`). Por defecto git escapa las rutas no ASCII y las entrecomilla, con lo
  que un patrón anclado en `backend/` no casaría: un PR cuyo único cambio de backend fuera un
  fichero con acento se saltaría la suite y el check saldría **verde**.
- THE SYSTEM SHALL leer el diff **sin detección de renombrados** (`--no-renames`). Con
  renombrados activos un movimiento colapsa a la ruta destino, así que un PR que **saca** un
  módulo de `backend/` se juzgaría «no toca el backend» y publicaría verde con código del
  backend desaparecido.
- THE SYSTEM SHALL comparar cada ruta individualmente en lugar de aplicar una expresión regular
  sobre el conjunto concatenado, para que un acierto parcial no pueda decidir por el conjunto.

### Servicios de los que depende

- THE SYSTEM SHALL levantar PostgreSQL 16 **y** Redis 7 como services, ambos con
  healthcheck.
- Redis no es opcional: los tests del adaptador de throttle (la única implementación de
  producción del límite por IP y del bloqueo por cuenta) están escritos deliberadamente
  **sin** `skip`, así que sin ese servicio fallan en rojo en lugar de desaparecer en el
  contador de omitidos.

### Pasos verificados

- THE SYSTEM SHALL aplicar `alembic upgrade head` sobre una base de datos PostgreSQL recién
  creada. La suite construye su esquema con `Base.metadata.create_all`, así que por sí sola
  no probaría la cadena real de migraciones.
- THE SYSTEM SHALL ejecutar `alembic check`, que falla si los modelos y el esquema migrado
  han divergido.
- THE SYSTEM SHALL ejecutar la suite completa (`pytest -q -rs`), que incluye autenticación,
  rotación y reutilización concurrente de tokens, RBAC, aislamiento por tenant y el test
  estructural de autorización de rutas. El flag `-rs` deja en el log el motivo de cada test
  omitido, para que el recuento de omitidos sea auditable y no un número opaco.
- THE SYSTEM SHALL ejecutar `alembic downgrade base`, que ningún test cubre y es lo que
  ejecuta un operador cuando un deploy sale mal.

### Secretos y dependencias

- WHEN el job arranca, THE SYSTEM SHALL generar una clave JWT de usar y tirar con
  `openssl rand -hex 32`. La configuración exige una clave de al menos 32 caracteres al
  importar, pero esa clave no firma nada que salga del job — así no hay ningún valor con
  apariencia de secreto versionado (regla 8 de `steering/security.md`).
- THE SYSTEM SHALL instalar las dependencias con `uv sync --frozen`, que falla si
  `uv.lock` no está sincronizado con `pyproject.toml`.
- THE SYSTEM SHALL pinear cada action de terceros por SHA de commit, siguiendo la
  convención de los demás workflows del repo.

### Aislamiento entre ejecuciones concurrentes

- THE SYSTEM SHALL dar a cada proceso de pytest sus propias bases de datos, con un sufijo
  por proceso (`<db>_test_<pid>`, `<db>_migrations_<pid>`), y borrarlas al cerrar la sesión.
- WHERE la suite se ejecuta en paralelo (`pytest -n`), THE SYSTEM SHALL incorporar además el
  id del worker al sufijo (`<db>_test_ci_gw0`), y dar a cada worker su propia **base lógica
  de Redis**, con un guardián que falle si el número de workers supera las 16 que Redis
  sirve por defecto.
- Es un requisito, no una comodidad: la fixture de migraciones abre con
  `DROP DATABASE IF EXISTS`, así que con nombres fijos una segunda ejecución concurrente
  borraría la base de datos que la primera está usando, y el fallo se leería como un test
  inestable en lugar de como una colisión.
- El id del worker no es redundante con el pid: en CI `PYTEST_DB_SUFFIX` está **fijada** a
  `ci`, así que sin él todos los procesos calcularían el mismo nombre y el
  `DROP DATABASE IF EXISTS` de la fixture de migraciones borraría la base que otro está
  usando — el fallo exacto que el sufijo existe para evitar. Redis lo necesita por otro
  motivo: la suite usa nombres de cerradura de **producción** a propósito, y dos workers
  sobre una sola base lógica se cruzan.
- WHERE `PYTEST_DB_SUFFIX` está definida, THE SYSTEM SHALL usar ese sufijo en lugar del pid,
  para que un job de CI pueda fijar un nombre reproducible.
- THE SYSTEM SHALL construir la base de datos de la ejecución **desde cero** al arrancar la
  sesión (`DROP DATABASE IF EXISTS … WITH (FORCE)` + `CREATE DATABASE` + `create_all`). Con
  el esquema construido una sola vez, heredar una base que dejó una ejecución muerta
  significaría heredar **su** esquema; crear-si-falta era inocuo solo mientras cada test
  recreaba el esquema entero.
- WHEN un test termina, THE SYSTEM SHALL vaciar las filas de las tablas en lugar de
  reconstruir el esquema, y la lista de tablas SHALL salir de la propia metadata —la misma
  fuente que usa `create_all`—, para que una tabla nueva entre en el vaciado sin que nadie
  tenga que acordarse de añadirla.
- `make db-clean-test` borra las bases huérfanas que deje una ejecución interrumpida, sin
  tocar la base de datos de desarrollo, incluidas las que crea el paralelismo
  (`…_test_ci_gw0`).
- ⚠️ `make db-clean-test` **no distingue una base huérfana de una viva**: lanzado con una
  suite corriendo la destroza (medido: 771 errores). Filtrar por conexiones vivas no lo
  arregla, porque `NullPool` deja ventanas de cero conexiones en toda base en uso.

### Presupuesto de tiempo de la suite

- THE SYSTEM SHALL declarar el presupuesto de tiempo como **dato versionado** en
  `.github/workflows/backend-tests.yml` (`env:` a nivel de workflow), nunca como un ajuste
  de la UI de GitHub.
- Son **dos cifras y no una**: un presupuesto que emite aviso y un techo que pone el check
  en rojo. Con un solo umbral hay que elegir entre convertir la variabilidad del runner
  —±20-30 %— en bloqueos de merge, o publicar un aviso que nadie mira.
- WHEN la suite se ejecuta, THE SYSTEM SHALL cronometrar el paso de `pytest` y publicar su
  duración como salida del job, y el job consolidador SHALL nombrar en el resumen la
  duración medida y las dos cifras declaradas, siempre.
- IF la duración supera el presupuesto, THEN THE SYSTEM SHALL emitir un aviso destacado sin
  bloquear; IF supera el techo, THEN el veredicto SHALL ser `fail`.
- IF la suite se ejecutó pero su duración no llegó al consolidador —o no es un entero—,
  THEN el resumen SHALL decirlo explícitamente y el veredicto **no** SHALL ser verde. Que
  la suite se saltara por el camino corto no es ese caso: ahí no hay duración porque no
  hubo nada que medir.
- El cronometraje vive **dentro del paso**, no en marcas de tiempo de la API: la duración
  tiene que existir aunque `pytest` falle, así que el paso captura el código de salida,
  publica los segundos y solo después se rinde con él. Requiere `set +e` explícito, porque
  GitHub invoca los `run:` con `bash -e {0}` y `set -uo pipefail` no lo desactiva.
- Esto **no** sustituye a `timeout-minutes`, que es otra cosa: una guillotina cuyo
  incumplimiento se lee como avería de infraestructura, no como regresión de rendimiento.

## Coste

- **Medido el 2026-08-10**: la suite tarda **~2m44s** y el paso dominante sigue siendo `pytest`.
  Es la **mediana de tres ejecuciones consecutivas** sobre la misma referencia (145s · 164s ·
  172s), no una muestra: el runner varía lo suficiente como para que una sola cifra no signifique
  nada. El camino corto —diff que no toca el backend— cuesta **segundos**, porque el job de
  detección no levanta `services:` ni instala dependencias: solo necesita git.
- **De dónde viene esa cifra**: la misma medición sobre `main` el mismo día dio **15m30s**
  (954s · 930s · 858s). Son **5,7×**, en dos mitades: dejar de construir y tirar el esquema de la
  base de datos en cada test —el 77,6 % del tiempo, medido— bajó a 4m03s, y paralelizar con
  `pytest-xdist` bajó de ahí a 2m44s.
- **El runner tiene 2 vCPU, no 4**: es un repositorio privado y los runners estándar de repos
  privados traen dos núcleos, compartidos además con PostgreSQL y Redis. Por eso el paralelismo se
  declara como `-n 2`: medido, `-n 4` sobresuscribe y sale peor (227-233s frente a 205s). El paso
  de la suite imprime el tamaño del runner en el log para que la próxima persona no tenga que
  suponerlo.
- El procedimiento es repetible y está descrito en el archivo del change: tres
  `workflow_dispatch` **secuenciales** sobre la misma referencia, leyendo la duración del paso
  `Suite completa …` de `/repos/{owner}/{repo}/actions/runs/{id}/jobs`. Secuenciales por
  obligación: el workflow declara `concurrency: backend-tests-${{ github.ref }}` con
  `cancel-in-progress: true`, así que tres disparos solapados se cancelan entre sí.
- La cifra se registra **fechada y con el paso dominante identificado** a propósito, y esta es la
  tercera vez que se corrige. Primero afirmaba «~1 minuto» y sobre ella se decidió ejecutar la
  suite en todos los PR; luego «~6m15s» del 2026-08-03, que en seis días se había quedado corta
  2,5×. Envejece sin que nada falle, que es precisamente por lo que ahora hay un presupuesto que
  el propio check comprueba.

## Estado

- **Limitación conocida**: el repositorio es privado en un plan que no permite protección de
  rama (la API responde `403: Upgrade to GitHub Pro or make this repository public`), así
  que este check **no puede marcarse como obligatorio** todavía. Se ejecuta y reporta en
  cada PR, pero nada impide fusionar con él en rojo. Convertirlo en gate real exige GitHub
  Pro o hacer público el repositorio; queda como decisión pendiente.
- No hay comando de lint ni de typecheck en el proyecto: `sdd/project.md` no declara ninguno
  y este workflow no inventa uno.
- El frontend tiene su workflow independiente `frontend-tests`, descrito en
  `sdd/specs/frontend-ci.md`; `backend-tests` no duplica sus verificaciones.

## Key files

- `.github/workflows/backend-tests.yml`.
- `backend/tests/db_names.py` — sufijo por ejecución de las bases de datos desechables.
- `backend/tests/conftest.py` — construcción de la base de datos de la ejecución, vaciado de
  tablas entre tests y base lógica de Redis por worker.
- `backend/tests/test_migrations.py` — cadena de migraciones contra una base desechable.
- `backend/tests/test_table_wipe.py` — demuestra que el vaciado entre tests alcanza a las tablas
  hijas y cubre exactamente las de la metadata.
- `Makefile` (`db-clean-test`) — barrido de bases desechables huérfanas, incluidas las que crea
  el paralelismo (`…_test_ci_gw0`).
