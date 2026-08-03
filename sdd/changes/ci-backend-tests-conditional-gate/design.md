# Design: ci-backend-tests-conditional-gate

## Context

`.github/workflows/backend-tests.yml` es hoy **un workflow de un solo job**, llamado igual que
el workflow (`backend-tests`), con `services:` de PostgreSQL 16 y Redis 7 a nivel de job y
diez pasos secuenciales. Su disparador es `pull_request: {}` + `push: main` +
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

**Con una desviación deliberada de la convención del repo, encontrada al implementar**: el paso
usa `set -uo pipefail`, **sin `-e`**. Con `-e`, un `git diff` que falle abortaría el paso → el
job entra en `failure` → el gate reporta rojo (D6). Pero R2.4 dice lo contrario: cuando el diff
no se puede determinar hay que **ejecutar la suite**, no bloquear el PR. Con `-e` el requisito
sería inalcanzable, así que cada comando que puede fallar se comprueba de forma explícita
(`if ! git cat-file …`, `if ! changed="$(git diff …)"`) y la variable arranca en `true`. El resto
de pasos bash del change (el consolidador) sí usa `set -euo pipefail`: ahí un fallo inesperado
*debe* dar rojo.

**La decisión se escribe además a stdout** con `echo "::notice::backend=<v> (<reason>)"` en el
propio paso de detección. No es redundante con D7: `$GITHUB_OUTPUT` es un canal entre jobs y
**no imprime nada en el log**, y el resumen de D7 lo escribe el job consolidador, no el que
toma la decisión. Sin este `echo`, R2.1 ("dejar esa decisión visible en el log") quedaría
cubierto solo de palabra — lo detectó la revisión de arquitectura. Un `::notice::` lo deja
además visible en la propia página del run, no solo enterrado en el log del paso. La razón decisiva es R2.4: la degradación tiene que
ser **explícita y hacia el lado seguro** (si no se puede determinar el diff, se ejecuta la
suite), y una action de terceros falla el job cuando algo va mal en lugar de degradar. Además
evita añadir superficie externa que habría que pinear por SHA y auditar para algo que son tres
líneas de git.

Rejected: `dorny/paths-filter` — bien probada y resuelve los dos eventos, pero su modo de
fallo es abortar, no degradar, que es lo contrario de lo que R2.4 pide.
Rejected: `gh api .../compare/` — depende de red y de un token con permisos, para un dato que
el checkout ya tiene en local.

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
| CI | `.github/workflows/backend-tests.yml` | Reestructurado a tres jobs (D1). Nuevo `backend-tests-detect` (checkout `fetch-depth: 0` + bash de detección + `::notice::`, sin services, `timeout-minutes: 5`). El job actual pasa a `backend-tests-suite` con `if:` sobre el output y **sus diez pasos, `services:`, `env:`, permisos y `timeout-minutes: 20` intactos** (R3.1, R3.2). Nuevo `backend-tests` consolidador (D6, D7), `timeout-minutes: 5`. Cabecera reescrita: duración medida y fechada en lugar del "~1 minuto" (R5.1), y la razón por la que `paths:` en `on:` sigue prohibido. |
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

### D9 — El camino corto se verifica con un commit de solo-docs en la propia rama

**Chosen:** un commit que toque únicamente un `.md` dentro de la rama del change. El PR de este
change toca `.github/workflows/backend-tests.yml`, que está *dentro* del área (D5), así que por
sí solo ejercita el camino **largo** y no demuestra nada sobre el corto: sin este commit, R4.1
se quedaría sin evidencia. Un commit de solo-docs dispara el camino corto con el evento
`pull_request` real y la comparación contra la base, y deja la medición registrada en el propio
PR.

`/sdd:tasks` debe convertirlo en tarea explícita, con el orden importando: el commit de docs
tiene que ser **posterior** al del workflow, o comparará contra una base que todavía no tiene
el gate nuevo.

Rejected: `workflow_dispatch` comparativo — R2.3 hace que siempre ejecute la suite completa, así
que no puede ejercitar el camino corto por diseño.
Rejected: PR de prueba aparte y desechable — evidencia igual de válida, a cambio de un PR extra
de ruido.
