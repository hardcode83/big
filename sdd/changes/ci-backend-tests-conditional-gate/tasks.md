# Tasks: ci-backend-tests-conditional-gate

Orden pensado para que el gate quede utilizable después de cada sección. La única
excepción deliberada es la sección 2: el renombrado del job y el consolidador **tienen que
aterrizar juntos**, porque entre uno y otro no existiría ningún job llamado `backend-tests` y
el contexto del check desaparecería. Se ejecutan como una sola unidad, no como dos pasos
independientes.

Todo el trabajo es de CI y documentación: **ningún fichero de `backend/` se toca**, así que la
suite no cambia de comportamiento ni de contenido.

## 1. Detección de área

Un job nuevo que todavía nadie consume: al terminar esta sección el gate se comporta
exactamente como hoy (la suite sigue ejecutándose siempre), solo que además publica su
decisión. Es lo que permite verificar la detección de forma aislada antes de que condicione
nada.

- [x] 1.1 Añadir el job `backend-tests-detect` a `.github/workflows/backend-tests.yml`:
  `runs-on: ubuntu-latest`, `timeout-minutes: 5`, `permissions: contents: read`, sin
  `services:`, con `actions/checkout` pineado por SHA (el mismo que ya usa el fichero) y
  `fetch-depth: 0`. Declara `outputs: backend`, `reason`. [R2, D1, D3]
- [x] 1.2 Escribir el paso de detección en bash con la forma del job `provenance` de
  `deploy-dev.yml:34-55`: variable inicializada a `backend=true` y bajada a `false` **solo** por
  una ruta afirmativa; tres ramas por evento (`pull_request` con `base.sha...head.sha` de tres
  puntos, `push` con `github.event.before`, `workflow_dispatch` → `true` sin calcular);
  comparación ruta a ruta con `case` contra `backend/*` y
  `.github/workflows/backend-tests.yml`; escritura de `backend`/`reason` a `$GITHUB_OUTPUT`.
  Abrir con **`set +e` explícito** seguido de `set -uo pipefail`: GitHub invoca los `run:` con
  `bash -e {0}`, así que sin `set +e` el fail-open de R2.4 no existiría (ver D3).
  [R2.1, R2.2, R2.3, D3, D4, D5]
- [x] 1.2b Leer el diff con `git -c core.quotePath=false diff -z --name-only` e iterarlo como
  array (`mapfile -d ''`), **no** con `grep` sobre la salida por defecto: git escapa las rutas no
  ASCII (`"backend/caf\303\251.py"`), con lo que un ancla `^backend/` no casa y un PR cuyo único
  cambio de backend fuese un fichero con acento se saltaría la suite en verde. [R2.4, D10]
- [x] 1.3 Cubrir explícitamente los tres caminos de *fail-open* con su `reason` propia:
  `github.event.before` con los 40 ceros, base o `before` inalcanzables, y salida no cero de
  `git diff`. Todos dejan `backend=true`. [R2.4, D4]
- [x] 1.4 Emitir la decisión al log del propio job con
  `echo "::notice::backend=<v> (<reason>)"` — `$GITHUB_OUTPUT` no imprime nada y el resumen lo
  escribe otro job, así que sin esto R2.1 queda sin mecanismo. [R2.1, D3]
- [x] 1.5 Imprimir la lista de ficheros considerados **prefijando cada línea con dos espacios**.
  Es contención, no formato: quien abre el PR elige los nombres, y un fichero llamado
  `::notice::…` o `::stop-commands::…` al principio de línea lo ejecuta el runner como comando de
  workflow, falsificando la anotación de la decisión o silenciando el log. [D10]
- [x] 1.6 Batería de casos adversariales sobre la lógica de detección, ejecutada con `bash` y con
  `-e` activo (como la invoca GitHub), sobre repositorios git de usar y tirar: rutas con acentos,
  con espacios, deleciones, el propio workflow, y las trampas `docs/backend-notes.md`,
  `frontend/backend/x.ts` y un fichero con nombre inyector. Es la mitigación que faltaba al
  riesgo 2 del design, porque las otras tres no atrapan un bug en la ruta afirmativa. [R2, D10]

## 2. El gate condicional (unidad indivisible)

- [x] 2.1 Renombrar el job actual a `backend-tests-suite` y añadirle
  `needs: backend-tests-detect` + `if: needs.backend-tests-detect.outputs.backend == 'true'`.
  **Conservar sin alterar** sus ocho pasos, `services:` (Postgres 16 + Redis 7 con
  healthcheck), el bloque `env:` completo (`DATABASE_URL`, `REDIS_URL`, `PYTEST_DB_SUFFIX`), el
  paso de la clave JWT de usar y tirar, `uv sync --frozen`, los SHA pineados,
  `permissions: contents: read` y `timeout-minutes: 20`. [R3.1, R3.2, R3.3]
- [x] 2.2 Añadir el job consolidador `backend-tests` —**este nombre exacto**, porque el check
  run toma el nombre del job y es el único contexto marcable como obligatorio— con
  `needs: [backend-tests-detect, backend-tests-suite]`, `if: always()`,
  `timeout-minutes: 5`, `permissions: contents: read` y sin `services:`. [R1.1, D1, D2]
- [x] 2.3 Implementar la tabla de verdad de D6 sobre `needs.*.result` enumerando los casos, no
  con un `!= 'failure'` abreviado: `suite == success` → verde; `suite == skipped` **y**
  `detect == success` **y** `backend == 'false'` → verde; `failure`/`cancelled` de cualquiera de
  los dos → rojo; y `skipped` con `backend == 'true'` → rojo por incoherencia. [R1.3, R1.4, D6]
- [x] 2.4 Escribir el resumen en `$GITHUB_STEP_SUMMARY` con la forma de tabla de
  `frontend-tests.yml:72-83`: camino tomado, `reason` de la detección y, en el camino corto,
  que la suite **no** se ejecutó. [R4.2, D7]
- [x] 2.5 Verificar que el disparador `on:` sigue siendo `pull_request: {}` + `push: main` +
  `workflow_dispatch`, **sin `paths:` ni `paths-ignore:`**, y que el grupo de `concurrency` con
  `cancel-in-progress` sigue intacto. [R1.2, R3.2]

## 3. Veracidad de la documentación

Tres sitios afirman hoy que el workflow no filtra rutas, y dos de ellos dan la cifra "~1
minuto". Al terminar la sección 2 las tres afirmaciones son falsas.

- [x] 3.1 Reescribir la cabecera de `.github/workflows/backend-tests.yml`: sustituir el "~1
  minuto" por la duración medida y fechada (~7m05s totales, `pytest` 6m15s, medido el
  2026-08-03) con el desglose del paso dominante, y explicar por qué `paths:` en `on:` sigue
  prohibido pese a que ahora la ejecución sea condicional. [R5.1]
- [x] 3.2 Actualizar `README.md:137-143`, que afirma "No lleva filtro de rutas a propósito — un
  check con filtro deja bloqueados los PR que no tocan esas rutas": describir el
  comportamiento nuevo (el check reporta siempre, la suite corre cuando el diff toca el
  backend) conservando la nota de que no está marcado como obligatorio. `steering/documentation.md`
  exige que ninguna doc describa comportamiento eliminado. [R5.2]
- [x] 3.3 Reescribir **solo el comentario** de `.github/workflows/api-contract.yml:18-20` y la
  cabecera de `.github/workflows/frontend-tests.yml:3-4` para que apunten al invariante nuevo.
  **Sin tocar `on:`, jobs, pasos ni comportamiento**: los dos siguen ejecutándose en todos los
  PR. [D8]

## 4. Verificación

El proyecto no declara comando de lint ni de typecheck (`sdd/specs/backend-ci.md` §Estado lo
hace explícito), y este change no toca `backend/`, así que la suite del backend no es la
verificación pertinente: lo que hay que probar es el comportamiento del propio workflow.

- [x] 4.1 El YAML es válido y tiene la estructura esperada, con `yq`: los tres jobs existen,
  el consolidador se llama exactamente `backend-tests`, `on:` no contiene ninguna clave `paths`
  ni `paths-ignore`, y los tres jobs declaran `timeout-minutes`.
  `yq '.jobs | keys' .github/workflows/backend-tests.yml` y
  `yq '.on' .github/workflows/backend-tests.yml`. [R1.1, R1.2, R3.2, D2]
- [ ] 4.2 **Camino largo**: el PR de este change toca `.github/workflows/backend-tests.yml`, que
  está dentro del área, así que su propia ejecución debe recorrerlo entero. Comprobar en el run
  del PR que `backend-tests-suite` se ejecutó, que los cuatro pasos de Alembic/pytest siguen
  presentes y verdes, y que el consolidador `backend-tests` reporta `success`. [R3.1, R1.3]
- [ ] 4.3 **Camino corto** (D9): añadir a esta misma rama un commit que toque **solo** un `.md`,
  **posterior** al commit del workflow —si va antes compara contra una base que todavía no
  tiene el gate nuevo—. Verificar en su run que `backend-tests-suite` sale `skipped`, que
  `backend-tests` reporta `success`, y medir la duración total. [R1.1, R1.3, R4.1]
- [ ] 4.4 El resumen del camino corto dice que la suite se omitió y por qué, de modo que un
  verde en segundos no se confunda con una suite que pasó. Comprobar el
  `$GITHUB_STEP_SUMMARY` del run de 4.3. [R4.2]
- [ ] 4.5 El camino corto tarda **menos de 60 segundos** de principio a fin. Medir con
  `gh run list --workflow=backend-tests.yml` sobre el run de 4.3 (`createdAt` → `updatedAt`);
  si no cumple, la salida descrita en D4 es el fetch acotado en lugar de `fetch-depth: 0`.
  [R4.1]
- [ ] 4.6 `workflow_dispatch` ejecuta la suite completa aunque el último diff no toque el
  backend: lanzarlo sobre la rama con `gh workflow run backend-tests.yml --ref
  sdd/ci-backend-tests-conditional-gate` y comprobar que `backend-tests-suite` **no** sale
  `skipped`. [R2.3]

## Cobertura de requisitos

| Requisito | Tareas |
|---|---|
| R1 — el check reporta siempre | 2.2, 2.3, 2.5, 4.1, 4.2, 4.3 |
| R2 — detección de área | 1.1, 1.2, 1.3, 1.4, 4.6 |
| R3 — el camino largo conserva la verificación | 2.1, 2.5, 4.1, 4.2 |
| R4 — el camino corto es rápido y legible | 2.4, 4.3, 4.4, 4.5 |
| R5 — la documentación deja de mentir | 3.1, 3.2 |
| D8 (alcance añadido en design) | 3.3 |
| D9 (verificación del camino corto) | 4.3 |

Los cinco requisitos del proposal quedan cubiertos por al menos una tarea de implementación y
al menos una de verificación.
