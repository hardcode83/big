# Design: ci-backend-tests-conditional-gate

## Context

`.github/workflows/backend-tests.yml` es hoy **un workflow de un solo job**, llamado igual que
el workflow (`backend-tests`), con `services:` de PostgreSQL 16 y Redis 7 a nivel de job y
ocho pasos secuenciales. Su disparador es `pull_request: {}` + `push: main` +
`workflow_dispatch`, deliberadamente sin `paths:`, y las líneas 14-16 documentan por qué.

El repositorio ya tiene **dos clases de workflow con políticas opuestas**, y son coherentes
entre sí: los candidatos a check obligatorio (`backend-tests`, `frontend-tests`,
`api-contract`) van **sin** filtro de rutas, los tres con el mismo comentario; los de trabajo
condicional (`deploy-dev.yml:11-15`, `infra-dev.yml:4-6`,
`multiarch-build-check.yml:8-16`) van **con** filtro. Este change introduce el tercer caso —
un gate que reporta siempre pero trabaja condicionalmente — y por eso tiene que justificar
por qué no rompe la política existente, sino que la refina.

Dos patrones ya presentes en el repo cubren casi todo lo que este diseño necesita, así que se
reutilizan en vez de inventarse: el job `provenance` de `deploy-dev.yml:22-55` calcula valores
en bash con `set -euo pipefail` y los publica por `outputs:`/`$GITHUB_OUTPUT` para que otros
jobs los consuman; y `frontend-tests.yml:65-91` consolida resultados con `if: always()`,
escribe una tabla en `$GITHUB_STEP_SUMMARY` y falla el job si algo no es `success`
—cancelaciones incluidas.

**Verificado por medición, no por lectura**: los check runs de Actions se nombran por el
**job**, no como `workflow / job`. Los contextos que el repo publica hoy son `api-contract`,
`backend-tests`, `frontend-api-contract` y `frontend-tests`, a secas. Ese detalle condiciona
D2 y es la diferencia entre un gate que se puede marcar obligatorio y uno que no.

## Decisions

### D1 — Tres jobs (`backend-tests-detect` → `backend-tests-suite` → `backend-tests`), no un job con pasos condicionales

**Chosen:** separar quién decide, quién trabaja y quién reporta. Dos razones, y la segunda es
la que manda: `services:` **no se puede condicionar** —un job único pagaría los 24s de
arranque de PostgreSQL+Redis incluso en un PR de documentación, comiéndose el presupuesto de
R4.1—, y sobre todo **el check que se reporta es el job**: un job único con `if:` reportaría
`skipped`, que GitHub *no* cuenta como éxito al evaluar un check obligatorio. Es exactamente
el bloqueo que R1 existe para evitar, solo que trasladado del disparador al job. Únicamente un
job incondicional y distinto del que trabaja puede garantizar el invariante de R1.1.

**Los tres jobs llevan `timeout-minutes` explícito**: `backend-tests-suite` conserva sus 20, y
los dos nuevos reciben **5**. Sin declararlo heredarían el default de Actions, **360 minutos**:
un `git diff` colgado o un bash del gate bloqueado dejaría el PR esperando seis horas, que es
el mismo bloqueo indefinido que R1 y R4 existen para eliminar, reintroducido en los jobs nuevos
después de haberlo quitado del disparador. Lo señaló la revisión de arquitectura sobre la
primera versión de este diseño, que solo preservaba el límite del job que ya lo tenía.

Rejected: un job con pasos condicionales — paga el arranque de services siempre y no resuelve
el reporte.
Rejected: `paths:` en `on:` — es el mecanismo que R1.2 prohíbe; el workflow no arrancaría.
Rejected: dos jobs (detectar dentro del que reporta) — el que reporta tiene que ejecutarse
*después* de la suite, así que no puede ser también el que decide *antes*.

### D2 — El job que reporta conserva exactamente el nombre `backend-tests`

**Chosen:** el job consolidador se llama `backend-tests`; los auxiliares,
`backend-tests-detect` y `backend-tests-suite`. Como el check run toma el nombre del job
(verificado arriba), renombrar el job cambiaría el contexto publicado y dejaría inservible
cualquier selección futura de check obligatorio; y prefijar los auxiliares evita que aparezcan
en la lista de checks del PR como dos nombres genéricos (`detect`, `suite`) indistinguibles de
los de otros workflows.

Consecuencia que hay que registrar en la spec, porque es una trampa real para
`infra-github-iac`: **el único contexto que debe marcarse como obligatorio es
`backend-tests`**. `backend-tests-suite` se salta legítimamente en los PR que no tocan el
backend, así que marcarlo obligatorio reproduciría el bloqueo indefinido que este change
elimina — el mismo fallo, entrando por otra puerta.

Rejected: nombres `changes`/`suite` — se leerían como checks sueltos del repositorio.
Rejected: renombrar el gate a algo más descriptivo (`backend-tests-gate`) — rompe el contexto
publicado a cambio de estética.

### D3 — Detección con `git diff` en bash, no con una action de terceros

**Chosen:** checkout + un paso bash que resuelve la base según el evento y publica
`backend=true|false` y `reason=<texto>` por `$GITHUB_OUTPUT`, con la forma del job
`provenance` de `deploy-dev.yml:34-55`.

La razón decisiva es R2.4: la degradación tiene que ser **explícita y hacia el lado seguro** (si
no se puede determinar el diff, se ejecuta la suite), y una action de terceros falla el job
cuando algo va mal en lugar de degradar. Además evita añadir superficie externa que habría que
pinear por SHA y auditar para algo que son tres líneas de git.

**El paso desactiva `-e` de forma explícita con `set +e`**, porque GitHub invoca los `run:` con
`bash -e {0}`: `-e` está **activo por defecto** y un `set -uo pipefail` no lo apaga. El
consolidador, en cambio, sí usa `set -euo pipefail`: ahí un fallo inesperado **debe** dar rojo.

**Corrección de una afirmación previa de este documento, señalada por la revisión de
arquitectura y verificada.** Una versión anterior de D3 sostenía que sin `set +e` el fail-open de
R2.4 "no existiría" y que un `git diff` fallido abortaría el paso. **Es falso**: `-e` queda
suspendido en todo el cuerpo de una función invocada como test de un `if`/`elif` o negada con
`!`, y todos los comandos que pueden fallar (`git cat-file -e`, `read_diff`) se invocan
exactamente así, de modo que ya degradaban bien sin esa línea. Reproducido en ambos sentidos: una
función con un `/bin/false` incondicional llamada como `elif ! fn` no aborta bajo `bash -e`,
mientras que el mismo `/bin/false` fuera de un condicional sí aborta con `exit 127`.

El valor real de `set +e` es por tanto **defensivo y a futuro**, no correctivo: el día que alguien
añada a este paso un comando fuera de un condicional, su fallo pasaría a abortar el job y el gate
reportaría rojo en lugar de caer al camino completo. Se conserva por eso, con la justificación
correcta en lugar de la que había.

**La decisión se escribe además a stdout** con `echo "::notice::backend=<v> (<reason>)"` en el
propio paso de detección. No es redundante con D7: `$GITHUB_OUTPUT` es un canal entre jobs y
**no imprime nada en el log**, y el resumen de D7 lo escribe el job consolidador, no el que
toma la decisión. Sin este `echo`, R2.1 ("dejar esa decisión visible en el log") quedaría
cubierto solo de palabra — lo detectó la revisión de arquitectura.

Rejected: `dorny/paths-filter` — bien probada y resuelve los dos eventos, pero su modo de
fallo es abortar, no degradar, que es lo contrario de lo que R2.4 pide.
Rejected: `gh api .../compare/` — depende de red y de un token con permisos, para un dato que
el checkout ya tiene en local.

### D10 — El diff se lee sin quoting y separado por NUL, y las rutas nunca se imprimen al principio de línea

Las dos correcciones que la revisión de seguridad encontró sobre la primera implementación.
Ambas se verificaron reproduciéndolas en un repositorio de usar y tirar antes de aceptarlas, no
solo leyendo el código.

**`git -c core.quotePath=false diff -z --name-only`, e iteración de un array**, en lugar de
`git diff --name-only` volcado a una variable y filtrado con `grep -E '^backend/'`. Por defecto
git **escapa** las rutas no ASCII y las envuelve en comillas: `backend/café.py` sale como
`"backend/caf\303\251.py"`, con comilla inicial, así que un patrón anclado en `^backend/` **no
casa**. Consecuencia real y grave: un PR cuyo único cambio de backend fuese un fichero con
acento se saltaba la suite y el check salía **verde**. Es exactamente el falso verde del riesgo 2,
materializado. `-z` además separa por NUL, que es lo único seguro con rutas que contienen
espacios o saltos de línea.

La comparación pasa a ser un `case "$f" in backend/* | .github/workflows/backend-tests.yml)`
ruta a ruta, en vez de un regex sobre el conjunto pegado: no hay que escapar el punto de
`.github` y un acierto parcial deja de ser posible.

**Toda ruta que se imprime al log va prefijada con dos espacios.** No es formato, es contención:
quien abre el PR elige los nombres de los ficheros, y un fichero llamado `::notice::…`,
`::error::…` o `::stop-commands::…` impreso al principio de línea lo **ejecuta el runner como
comando de workflow**. Verificado: `git diff --name-only` emite un nombre así literal, sin
escapar. Permitía falsificar precisamente la anotación de la decisión que R2.1 exige, y con
`::add-mask::`/`::stop-commands::` silenciar el resto del log. Los valores que sí interpolamos
(`backend`, `reason`) salen de un conjunto cerrado de literales del propio script y no son
inyectables.

Alcance del riesgo, para no exagerarlo: el disparador es `pull_request` y no
`pull_request_target`, no hay ninguna referencia a `secrets.*` y el token es `contents: read`, así
que no había vía de exfiltración ni de escritura. Lo que había era falsificación de la señal y un
falso verde.

**El prefijo de dos espacios no basta solo, y por eso va acompañado de `%q`.** Un nombre de
fichero puede contener **saltos de línea**, y con `-z` llegan crudos: el prefijo protegería solo
la primera línea y las siguientes empezarían en la columna 0. Reproducido — un único fichero
llamado `backend/z\n::stop-commands::…\n::notice::…\n::error::….py` colocaba **tres** comandos de
workflow al principio de línea. `printf '  %q\n'` colapsa cada ruta a una sola línea
(`$'backend/z\n::error::…'`), con lo que el prefijo vuelve a cubrirla entera. Lo encontró la
segunda ronda de la revisión de seguridad, sobre la corrección de la primera.

**El listado se trunca a 50 rutas** (`"${files[@]:0:50}"`) para que un diff enorme no llene el log;
la **decisión** usa el array completo, sin truncar, así que el tope no puede afectarla. Con `%q`
cada elemento ocupa exactamente una línea, de modo que el tope cuenta líneas de verdad — antes,
un solo elemento con saltos podía expandirse a muchas.

Rejected: sanear con `sed` las líneas que empiecen por `::` — el prefijo más `%q` es más simple y
no puede fallar por un patrón mal escrito.
Rejected: envolver el listado entre `::stop-commands::<token>` y `::<token>::` — defensa en
profundidad razonable, pero si el paso muriera entre ambos marcadores dejaría el parseo de comandos
desactivado para lo que viniera después; `%q` resuelve el problema de raíz sin ese efecto lateral.
Rejected: no imprimir la lista de ficheros — es lo que hace diagnosticable una decisión
sorprendente.

**Casos que la lógica de detección debe seguir cumpliendo.** Se registran aquí porque la batería
se ejecutó fuera del repositorio y, mientras no exista como script versionado (ver más abajo), esta
tabla es lo único que sobrevive. Quien toque esa lógica debe volver a pasarlos, con `bash` y con
`-e` activo, que es como GitHub invoca los `run:`:

| Entrada | `backend` esperado | Por qué |
|---|---|---|
| `backend/app/main.py` | `true` | caso normal, ruta anidada (el glob `backend/*` de `case` sí cruza `/`) |
| `backend/café.py` | `true` | quoting de git; era falso verde |
| `backend/mi fichero.py` | `true` | espacios en la ruta |
| mover `backend/x.py` → `shared/x.py` | `true` | renombrado colapsado; era falso verde |
| mover `other/x.py` → `backend/x.py` | `true` | entra en el área |
| mover `backend/a/x.py` → `backend/b/x.py` | `true` | dentro del área |
| borrar `backend/z.py` | `true` | deleción también es cambio |
| `.github/workflows/backend-tests.yml` | `true` | el propio gate |
| `README.md` | `false` | solo documentación |
| `.github/workflows/frontend-tests.yml` | `false` | otro workflow |
| `docs/backend-notes.md` | `false` | coincidencia parcial del nombre |
| `frontend/backend/x.ts` | `false` | `backend/` en mitad de la ruta |
| mover `docs/x.md` → `other/x.md` | `false` | renombrado ajeno al área |
| fichero llamado `::notice::…` | `false` + no inyecta | nombre inyector |

**Deuda reconocida, y la candidata más valiosa que deja este change**: esa batería **no está
versionada**, así que nada impide que un cambio futuro reintroduzca cualquiera de los tres falsos
verdes. Dos revisores distintos encontraron sendos fallos en estas quince líneas de bash, lo que
dice bastante sobre su densidad de trampas. La forma correcta es extraer la lógica a
`.github/scripts/detect-backend-changes.sh` con un self-test versionado —el patrón que el roadmap
ya prevé para `.github/scripts/extract-pr.sh` en `app-version-provenance`— y que el workflow lo
invoque. **No se hace aquí a propósito**: cambia la forma de D1/D3 a mitad de implementación y
excede lo que las tareas describen. Queda como candidata explícita para un change propio.

**Tercera corrección, del mismo bloque y encontrada por la revisión de QA: `--no-renames`.** Git
detecta renombrados por defecto y con `--name-only` un movimiento **colapsa a una sola ruta, la
de destino**: mover `backend/app/x.py` a `shared/x.py` aparece únicamente como `shared/x.py`. Sin
el flag, un PR que **saca** un módulo de `backend/` se juzga «no toca el backend», se salta la
suite y el check sale verde — con código del backend desaparecido y sin que nada lo verifique.
Reproducido: sin el flag sale una ruta, con el flag salen las dos. El sentido del fallo importa:
mover *hacia* `backend/` ya daba `true` por la ruta destino, así que el agujero era solo en la
dirección de salida, que es justo la destructiva.

### D4 — La base del diff se resuelve por evento, y toda duda cae del lado de ejecutar

**Chosen:** tres ramas explícitas, y `backend=true` como valor inicial de la variable, de modo
que solo una ruta afirmativa del código la baja a `false`:

| Evento | Comparación |
|---|---|
| `pull_request` | `git diff --name-only <base.sha>...<head.sha>` (tres puntos: cambios de la rama desde el ancestro común, no ruido de `main`), con `fetch-depth: 0` |
| `push` a `main` | `git diff --name-only <github.event.before> <github.sha>` |
| `workflow_dispatch` | no se calcula nada: `backend=true` (R2.3) |

Caen a *fail-open* con su `reason` registrada: `github.event.before` con los 40 ceros (rama
nueva o primer push), base o `before` inalcanzables tras un force-push, y cualquier salida no
cero de `git diff`.

Rejected: `git diff BASE HEAD` con dos puntos en el PR — incluiría los commits que `main`
acumuló desde la bifurcación, así que un merge de `main` en la rama dispararía la suite sin
que el PR haya tocado el backend.
Rejected: `fetch-depth` acotado con `git fetch --depth=1 <base>` — más eficiente, pero hoy el
repositorio no tiene historia suficiente para que importe y complica el caso del force-push;
si el checkout llegara a pesar, R4.1 lo detectaría.

### D5 — El área es `backend/**` + `.github/workflows/backend-tests.yml`, y nada más

**Chosen:** esos dos patrones. Incluir el propio workflow es la convención ya establecida por
los tres workflows del repo que filtran (`deploy-dev.yml:15`,
`multiarch-build-check.yml:16`): si cambias el gate, el gate se ejecuta.

La investigación del código respalda que `backend/**` es el ámbito **exacto**, no una
aproximación prudente. Todas las lecturas de disco *de los tests* resuelven como máximo a
`backend/` — `tests/test_layering.py:16` y `tests/test_session_marking.py:30` parsean el AST de
`backend/app`, `tests/test_models_registry.py:16` y `tests/test_migrations.py:20` usan
`backend/`, y `tests/integrations/test_channex_probe.py:14` usa `backend/scripts/`.

**Con una excepción que hay que nombrar, porque una primera versión de este diseño afirmaba un
"nunca" que el código contradice** (la encontró la revisión de arquitectura):
`backend/app/core/config.py:6` resuelve `REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[3]
/ ".env"` y lo pasa como `env_file` (línea 14), con `settings = Settings()` instanciado a nivel
de módulo (línea 86). Cualquier test que importe `app.core.config` —por ejemplo
`tests/test_migrations.py`— intenta por tanto leer el **`.env` de la raíz del repositorio**, no
uno de `backend/`.

No invalida el ámbito de gating, por dos razones que se sostienen de forma independiente: ese
fichero está en `.gitignore:5` (`.env*`), así que **no puede aparecer en el diff de un PR** ni
disparar nada; y en CI no existe siquiera —el checkout es limpio y `pydantic-settings` ignora en
silencio un `env_file` ausente—, así que no influye en el resultado de la suite. `backend/**`
sigue siendo exacto **para decidir el gating**, que es lo que D5 necesita; lo que no era exacto
era la frase absoluta.

Quedan fuera a propósito, y conviene dejar dicho por qué para que nadie los añada "por si
acaso": `docker-compose.yml` y el `Makefile` no los ejecuta este gate (usa `services:`, no
compose), y `.env.example` de la raíz es inalcanzable para la suite —lo documenta
`tests/auth/test_bootstrap.py:237`—, así que tocarlos no puede cambiar el resultado de un
solo test.

Rejected: añadir `docker-compose.yml`/`Makefile`/`.env.example` — ampliaría el camino largo
sin poder cambiar ningún resultado.
Rejected: solo `backend/**` — un cambio en el propio gate se desplegaría sin ejecutarse nunca.

### D6 — El gate decide con una tabla de verdad explícita sobre `needs.*.result`

**Chosen:** `needs: [backend-tests-detect, backend-tests-suite]` + `if: always()`, y un paso
bash que evalúa:

| `detect` | `suite` | output `backend` | Conclusión |
|---|---|---|---|
| `success` | `success` | — | **success** |
| `success` | `skipped` | `false` | **success** + resumen "suite omitida" |
| cualquiera | `failure` / `cancelled` | — | **failure** |
| `failure` / `cancelled` | cualquiera | — | **failure** |
| `success` | `skipped` | `true` | **failure** (estado imposible: se saltó habiendo que ejecutar) |

**Chosen:** enumerar los casos en lugar de escribir `if: needs.…result != 'failure'`. Esa
forma abreviada daría verde ante una cancelación y ante un `detect` roto, que son precisamente
los dos falsos verdes que R1.4 prohíbe. `frontend-tests.yml:85-91` ya resuelve el mismo
problema con el mismo criterio explícito ("incluidas cancelaciones y verificaciones no
ejecutadas"), así que se reutiliza su forma. La última fila es una comprobación de coherencia
defensiva: no debería poder ocurrir, y si ocurre es un bug del gate, no un PR válido.

### D7 — El resumen distingue el camino corto del verde de una suite que pasó

**Chosen:** el job `backend-tests` escribe en `$GITHUB_STEP_SUMMARY`, con la forma de tabla de
`frontend-tests.yml:72-83`, qué camino se tomó, la `reason` que devolvió `detect` y —en el
camino corto— que la suite **no** se ejecutó. R4.2 lo pide por una razón concreta: un check
verde en 20 segundos es indistinguible a simple vista de una suite que pasó, y esa confusión
es el modo de fallo social de este diseño.

## Changes by area

| Area | Files | Change |
|---|---|---|
| CI | `.github/workflows/backend-tests.yml` | Reestructurado a tres jobs (D1). Nuevo `backend-tests-detect` (checkout `fetch-depth: 0` + bash de detección + `::notice::`, sin services, `timeout-minutes: 5`). El job actual pasa a `backend-tests-suite` con `if:` sobre el output y **sus ocho pasos, `services:`, `env:`, permisos y `timeout-minutes: 20` intactos** (R3.1, R3.2). Nuevo `backend-tests` consolidador (D6, D7), `timeout-minutes: 5`. Cabecera reescrita: duración medida y fechada en lugar del "~1 minuto" (R5.1), y la razón por la que `paths:` en `on:` sigue prohibido. |
| CI (solo comentarios) | `.github/workflows/api-contract.yml`, `.github/workflows/frontend-tests.yml` | D8: reescribir el comentario que justifica la ausencia de filtro para que apunte al invariante nuevo. **Sin tocar `on:`, jobs, pasos ni comportamiento** — ambos siguen ejecutándose en todos los PR. |
| Especificación | `sdd/specs/backend-ci.md` | **Al archivar, no ahora.** Sustituir el requisito "sin filtro de rutas" (línea 23) por el invariante de R1 conservando su razón original; añadir detección de área, camino corto y la nota de D2 sobre qué contexto es el marcable como obligatorio; corregir la duración declarada. |

Ningún fichero de `backend/` se toca. La suite no cambia: este change altera **cuándo** se
ejecuta, nunca **qué** verifica.

## Data & interfaces

Sin cambios de esquema, de API ni de dependencias. No se añade ninguna action de terceros
(D3), así que la lista de SHAs pineados no crece.

Interfaz nueva, interna al workflow — los `outputs` de `backend-tests-detect`:

| Output | Valores | Consumidor |
|---|---|---|
| `backend` | `'true'` \| `'false'` | `if:` de `backend-tests-suite`, tabla de verdad del gate |
| `reason` | texto libre (`workflow_dispatch`, `diff-touches-backend`, `no-backend-changes`, `base-unreachable`, …) | resumen de D7 |

Las variables de entorno del job actual (`DATABASE_URL`, `REDIS_URL`, `PYTEST_DB_SUFFIX`, y
`JWT_SECRET_KEY` generada en un paso) **se mueven con el job** a `backend-tests-suite`, sin
cambiar de valor. `backend-tests-detect` y el gate no necesitan ninguna: no importan la
aplicación ni tocan la base de datos.

## Risks & mitigations

1. **Un cambio de solo-frontend que rompa el backend deja de verificarse.** Riesgo aparente,
   no real: la hermeticidad verificada en D5 significa que la suite **ya hoy** no lee nada
   fuera de `backend/`, así que ese PR ya sale verde ahora mismo. No se pierde detección; se
   deja de pagar por una detección que no existe. Queda documentado para que nadie lo lea como
   una regresión introducida aquí.
2. **Falso verde por un bug en el bash de detección.** Es el modo de fallo grave del diseño:
   si `detect` devolviera `false` por error, la suite se saltaría en silencio. Mitigado por
   tres vías: el valor inicial de la variable es `true` y solo una ruta afirmativa la baja
   (D4), la `reason` viaja al resumen y queda auditable (D7), y la última fila de la tabla de
   verdad falla el gate ante el estado incoherente (D6).

   **No era un riesgo teórico: se materializó y el panel lo cazó.** La primera implementación
   filtraba el diff con `grep -E '^backend/'` sobre la salida por defecto de `git diff`, que
   escapa las rutas no ASCII — un fichero `backend/café.py` se saltaba la suite con el check en
   verde (ver D10). Las tres mitigaciones de arriba **no lo habrían atrapado**, porque el bug
   estaba en la ruta afirmativa misma: la variable bajaba a `false` "legítimamente". La
   mitigación que faltaba, y que ahora existe, es una batería de casos adversariales sobre la
   lógica de detección ejecutada fuera de CI (11 casos, incluidos acentos, espacios, deleciones
   y las trampas `docs/backend-notes.md` y `frontend/backend/x.ts`). Cualquier cambio futuro a
   esa lógica debe volver a pasarla.
3. **Deriva de coherencia documental.** `api-contract.yml:18-20` y `frontend-tests.yml:3-4`
   seguirán justificando "sin filtro de rutas" con el argumento que este change supera,
   citando además `specs/backend-ci.md`, cuyo texto habrá cambiado. **Mitigado por D8**: se
   reescriben los dos comentarios en este mismo change, sin tocar su comportamiento.
4. **El coste real para Marta solo baja a medias.** Un PR que toque `backend/` seguirá
   tardando ~7 minutos: este change no acelera la suite, solo evita ejecutarla cuando no
   procede. No es un riesgo del diseño sino su límite declarado, y lo recoge la entrada de
   roadmap `backend-suite-runtime`. Conviene decírselo explícitamente a Marta al entregar,
   para que el resultado no se lea como menos de lo prometido.
5. **Dos checks nuevos en la lista del PR.** `backend-tests-detect` y `backend-tests-suite`
   pasan a ser visibles. Coste cosmético aceptado: es el precio de que el gate pueda ser
   obligatorio (D1), y el prefijo (D2) los agrupa visualmente.
6. **`fetch-depth: 0` encarece el checkout si la historia crece.** Hoy es irrelevante y R4.1
   (<60s) actúa como detector: si el camino corto se acerca al límite, la salida es el fetch
   acotado que D4 dejó descrito.

## Open questions

Ninguna abierta. Las dos que este diseño planteó se resolvieron con el usuario el 2026-08-03 y
quedan registradas como D8 y D9.

### D8 — Se actualizan los comentarios de `api-contract.yml` y `frontend-tests.yml`

**Chosen:** reescribir **solo el comentario** de `api-contract.yml:18-20` y
`frontend-tests.yml:3-4` para que apunten al invariante nuevo, sin tocar su `on:`, su lógica ni
su comportamiento: ambos siguen sin filtro de rutas. Los dos citan hoy la razón que
`specs/backend-ci.md` va a dejar de contener, y es el tipo de inconsistencia que dentro de tres
meses hace que alguien reabra esta decisión con la información equivocada.

Ensancha ligeramente el alcance que declaró la propuesta (que dejaba esos workflows fuera), así
que la propuesta queda matizada aquí de forma explícita: fuera de alcance sigue estando
**cambiar su comportamiento**; su documentación no.

Rejected: dejarlos intactos — diff mínimo, a cambio de dos ficheros citando una regla
reescrita.

### D9 — El camino corto se verifica con un PR sonda cuya BASE es la rama de este change

**Corregido tras la revisión de QA, que demostró que la primera versión de esta decisión era
inservible.** Se documenta el error porque la trampa es sutil y volvería a picar a cualquiera.

La primera versión proponía añadir un commit de solo-`.md` a esta misma rama, posterior al del
workflow, y esperar que su ejecución tomara el camino corto. **No puede funcionar**: R2.2 fija
que en un `pull_request` la comparación es `base.sha...head.sha`, es decir el diff **acumulado**
de la rama contra la base del PR. Como esta rama ya modifica
`.github/workflows/backend-tests.yml` en un commit anterior, ese fichero sigue apareciendo en el
diff acumulado de cualquier commit posterior, así que `backend=true` y la ejecución toma siempre
el camino **largo**. Verificado reproduciendo ambos escenarios en un repositorio de usar y tirar.

El riesgo no era solo "no demostrar nada": era marcar R4 como verificado sin haberlo estado.

**Chosen:** un PR sonda desechable, `sdd/ci-backend-tests-conditional-gate-shortpath` →
**base `sdd/ci-backend-tests-conditional-gate`** (no `main`), con un único commit que toque un
`.md`. Así el `base...head` contiene exclusivamente ese `.md` —el workflow nuevo llega heredado
de la base, no como parte del diff—, de modo que el gate se ejecuta con el código de este change
y decide `backend=false`. Es el camino corto de verdad, con un evento `pull_request` real y la
semántica de comparación real. Se cierra sin fusionar una vez tomada la medida.

Es exactamente la alternativa que la primera versión rechazó "por ruido". El ruido de un PR
desechable es un precio menor que un requisito marcado como verificado sin evidencia.

Rejected: commit de solo-docs en esta misma rama — imposible por la semántica de `base...head`,
según lo demostrado arriba.
Rejected: `workflow_dispatch` comparativo — R2.3 hace que siempre ejecute la suite completa, así
que no puede ejercitar el camino corto por diseño.
Rejected: verificar después de fusionar, con el siguiente PR de documentación que llegue — es
evidencia válida, pero llega tarde para el PR que introduce el gate, y R4.1 quedaría sin
respaldo justo en la revisión que decide si entra.
