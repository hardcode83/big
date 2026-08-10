# Texto para `sdd/specs/backend-ci.md`, redactado aquí y aplicado por `/sdd:archive`

Las specs vivas solo las escribe el archivado (`steering/documentation.md`), así que este change
deja el texto listo en vez de tocarlas. Cuatro bloques, cada uno con qué sustituye.

Las cifras son ya las **definitivas** (tarea 8.1 cerrada): mediana de tres ejecuciones sobre el
commit final, con la fase 2 aplicada.

---

## (a) §Coste — sustituye el bloque entero de las tres viñetas actuales

> ## Coste
>
> - **Medido el 2026-08-10**: la suite tarda **~2m44s** y el paso dominante sigue siendo `pytest`.
>   Es la **mediana de tres ejecuciones consecutivas** sobre la misma referencia (145s · 164s ·
>   172s), no una muestra: el runner varía lo suficiente como para que una sola cifra no signifique
>   nada. El camino corto —diff que no toca el backend— cuesta **segundos**, porque el job de
>   detección no levanta `services:` ni instala dependencias: solo necesita git.
> - **De dónde viene esa cifra**: la misma medición sobre `main` el mismo día dio **15m30s**
>   (954s · 930s · 858s). Son **5,7×**, en dos mitades: dejar de construir y tirar el esquema de la
>   base de datos en cada test —el 77,6 % del tiempo, medido— bajó a 4m03s, y paralelizar con
>   `pytest-xdist` bajó de ahí a 2m44s.
> - **El runner tiene 2 vCPU, no 4**: es un repositorio privado y los runners estándar de repos
>   privados traen dos núcleos, compartidos además con PostgreSQL y Redis. Por eso el paralelismo se
>   declara como `-n 2`: medido, `-n 4` sobresuscribe y sale peor (227-233s frente a 205s). El paso
>   de la suite imprime el tamaño del runner en el log para que la próxima persona no tenga que
>   suponerlo.
> - El procedimiento es repetible y está descrito en el archivo del change: tres
>   `workflow_dispatch` **secuenciales** sobre la misma referencia, leyendo la duración del paso
>   `Suite completa …` de `/repos/{owner}/{repo}/actions/runs/{id}/jobs`. Secuenciales por
>   obligación: el workflow declara `concurrency: backend-tests-${{ github.ref }}` con
>   `cancel-in-progress: true`, así que tres disparos solapados se cancelan entre sí.
> - La cifra se registra **fechada y con el paso dominante identificado** a propósito, y esta es la
>   tercera vez que se corrige. Primero afirmaba «~1 minuto» y sobre ella se decidió ejecutar la
>   suite en todos los PR; luego «~6m15s» del 2026-08-03, que en seis días se había quedado corta
>   2,5×. Envejece sin que nada falle, que es precisamente por lo que ahora hay un presupuesto que
>   el propio check comprueba.

Se **retira** la tercera viñeta actual («Reducir esos 6m15s queda fuera de esta capacidad…»): ese
trabajo es exactamente lo que hizo este change.

## (b) §Aislamiento entre ejecuciones concurrentes — sustituye la primera viñeta y añade dos

> - THE SYSTEM SHALL dar a cada proceso de pytest sus propias bases de datos, con un sufijo por
>   proceso (`<db>_test_<pid>`, `<db>_migrations_<pid>`), y borrarlas al cerrar la sesión.
> - WHERE la suite se ejecuta en paralelo (`pytest -n`), THE SYSTEM SHALL incorporar además el id
>   del worker al sufijo (`<db>_test_ci_gw0`), y dar a cada worker su propia **base lógica de
>   Redis**, con un guardián que falle si el número de workers supera las 16 que Redis sirve por
>   defecto.
> - ⚠️ `make db-clean-test` **no distingue una base huérfana de una viva**: lanzado con una suite
>   corriendo la destroza (medido: 771 errores). Filtrar por conexiones vivas no lo arregla, porque
>   `NullPool` deja ventanas de cero conexiones en toda base en uso.
> - El id del worker no es redundante con el pid: en CI `PYTEST_DB_SUFFIX` está **fijada** a `ci`,
>   así que sin él los cuatro procesos calcularían el mismo nombre y el `DROP DATABASE IF EXISTS`
>   de la fixture de migraciones borraría la base que otro está usando — el fallo exacto que el
>   sufijo existe para evitar. Redis lo necesita por otro motivo: la suite usa nombres de cerradura
>   de **producción** a propósito, y dos workers sobre una sola base lógica se cruzan.
> - THE SYSTEM SHALL construir la base de datos de la ejecución **desde cero** al arrancar la
>   sesión (`DROP DATABASE IF EXISTS … WITH (FORCE)` + `CREATE DATABASE` + `create_all`). Con el
>   esquema construido una sola vez, heredar una base que dejó una ejecución muerta significaría
>   heredar **su** esquema; crear-si-falta era inocuo solo mientras cada test recreaba el esquema
>   entero.

## (c) §Requirements — requisito EARS nuevo para el presupuesto de tiempo

Va como subsección nueva, después de «Aislamiento entre ejecuciones concurrentes»:

> ### Presupuesto de tiempo de la suite
>
> - THE SYSTEM SHALL declarar el presupuesto de tiempo como **dato versionado** en
>   `.github/workflows/backend-tests.yml` (`env:` a nivel de workflow), nunca como un ajuste de la
>   UI de GitHub.
> - Son **dos cifras y no una**: un presupuesto que emite aviso y un techo que pone el check en
>   rojo. Con un solo umbral hay que elegir entre convertir la variabilidad del runner —±20-30 %—
>   en bloqueos de merge, o publicar un aviso que nadie mira.
> - WHEN la suite se ejecuta, THE SYSTEM SHALL cronometrar el paso de `pytest` y publicar su
>   duración como salida del job, y el job consolidador SHALL nombrar en el resumen la duración
>   medida y las dos cifras declaradas, siempre.
> - IF la duración supera el presupuesto, THEN THE SYSTEM SHALL emitir un aviso destacado sin
>   bloquear; IF supera el techo, THEN el veredicto SHALL ser `fail`.
> - IF la suite se ejecutó pero su duración no llegó al consolidador —o no es un entero—, THEN el
>   resumen SHALL decirlo explícitamente y el veredicto **no** SHALL ser verde. Que la suite se
>   saltara por el camino corto no es ese caso: ahí no hay duración porque no hubo nada que medir.
> - El cronometraje vive **dentro del paso**, no en marcas de tiempo de la API: la duración tiene
>   que existir aunque `pytest` falle, así que el paso captura el código de salida, publica los
>   segundos y solo después se rinde con él. Requiere `set +e` explícito, porque GitHub invoca los
>   `run:` con `bash -e {0}` y `set -uo pipefail` no lo desactiva.
> - Esto **no** sustituye a `timeout-minutes`, que es otra cosa: una guillotina cuyo
>   incumplimiento se lee como avería de infraestructura, no como regresión de rendimiento.

## (d) §Key files — añadir dos entradas

> - `Makefile` (`db-clean-test`) — barrido de bases desechables huérfanas, incluidas las que crea
>   el paralelismo (`…_test_ci_gw0`).
> - `backend/tests/test_table_wipe.py` — demuestra que el vaciado entre tests alcanza a las tablas
>   hijas y cubre exactamente las de la metadata.

Y actualizar la línea existente de `backend/tests/conftest.py`, que hoy dice «creación y borrado de
la base de datos de la suite»:

> - `backend/tests/conftest.py` — construcción de la base de datos de la ejecución, vaciado de
>   tablas entre tests y base lógica de Redis por worker.
