# Design: worktree-parallel-stack

## Context

`docker-compose.yml` (raíz, según `steering/architecture.md` línea 15: sin `/docker`, compose y
`Makefile` en la raíz) declara siete servicios y **cuatro** mapeos de puertos, verificados con
`docker compose config --format json` sobre el fichero real: `postgres` y `redis` con
`host_ip=127.0.0.1`, `backend:8000` y `frontend:3000` con `host_ip=null` —que es cómo Compose
representa «todas las interfaces», dato que el censo de `compose-ports-guard` ya avisa de no
redondear a `"0.0.0.0"`—. El `Makefile` tiene ocho targets que hablan con Compose y **todos** lo
invocan desnudo, sin `-f`: `up`, `down`, `logs`, `ps`, `sh`, `bootstrap`, `openapi`, `db-clean-test`. Ningún
workflow de `.github/workflows/` invoca `make` (comprobado), así que el `Makefile` es exclusivamente
herramienta local: CI usa *service containers* y CD pasa `-f docker-compose.deploy.yml`.

El nombre de proyecto de Compose sale del nombre del directorio (medido: `autohostai` en el
principal, `sddlocal-dev-network-hardening` en el worktree), y con él van contenedores, red y
volúmenes. Lo único compartido entre dos stacks es el **bind al host**, y por eso es lo único que
colisiona. Los worktrees de SDD viven **dentro** del árbol del principal
(`.claude/worktrees/sdd+<feature>/`), excluidos por `**/.claude/worktrees/` en `.git/info/exclude`.

## Decisions

### D1 — Los mapeos se quedan en `docker-compose.yml`; el worktree los retira con `ports: !reset []`

**Chosen:** un fichero versionado nuevo, `docker-compose.worktree.yml`, que solo contiene
`ports: !reset []` para los cuatro servicios que publican, y que el `Makefile` añade con `-f`
**únicamente cuando detecta un worktree enlazado**. En el principal el `Makefile` sigue invocando
`docker compose` desnudo: **cero cambios** en su camino, en el fichero base y en lo que Compose
descubre por sí solo.

Medido contra los ficheros reales de este repo, no en un ejemplo de juguete
(Compose v5.1.1, `config --format json`): base sola → 4 mapeos con sus `host_ip` intactos; base +
overlay → **ningún** servicio con `ports`, mismo nombre de proyecto (`autohostai`) y mismos contextos
de build. `!reset` es del Compose Spec desde v2.24 (enero 2024).

Por qué esta y no la de la propuesta —sacar los mapeos a `docker-compose.ports.yml` que solo incluya
el principal—, que era la recomendación de partida y se descarta con tres razones concretas, no por
gusto:

1. **Rompe la vista de `compose-ports-guard`.** Su decisión heredada es delegar el descubrimiento de
   ficheros a Compose **sin `--file`**, para que la vista de la guardia no pueda ser más estrecha que
   la de `make up`. Si los mapeos salen del fichero que Compose descubre solo, la guardia bare ve
   **cero puertos** y pasa en vacío — exactamente el modo de fallo (h) de su censo, por otra puerta.
   Arreglarlo obliga a rediseñar la guardia (enumerar todos los composes del repo), y su entrada dice
   que su análisis es lo más valioso que arrastra tras cinco rondas en rojo.
2. **Incumple R2.3 y R3.2 literalmente.** «`docker compose config` en el principal da los cuatro
   mapeos» dejaría de ser cierto sin exportar `COMPOSE_FILE`, y exportarlo es la vía de elusión (d)
   del mismo censo, además de hacer el resultado función del entorno (criterio 2 de la guardia).
3. **Deja la regla 8 de `steering/security.md` sin ancla.** Su exención cita
   *«`docker-compose.yml` publica `postgres` y `redis` solo en `127.0.0.1`»* **por el nombre del
   fichero**, y la propia regla obliga a rehacer la justificación si el mapeo cambia. Con D1 la frase
   sigue siendo cierta y no hay que reescribir una norma de seguridad para arreglar una molestia de
   tooling. **R3.4 no se dispara.**

Y un cuarto motivo, menor pero real: hay cinco sitios que enseñan `docker compose` desnudo
(`README.md:99,189,207`, `docs/channex-staging.md:46,68`). Con D1 esos comandos siguen significando
en el principal exactamente lo que significan hoy.

Rejected: `docker-compose.ports.yml` incluido solo en el principal — los tres motivos de arriba.
Rejected: mover los mapeos a un `docker-compose.override.yml` **versionado** (Compose lo carga solo,
así que la guardia seguiría viéndolos y el worktree lo suprimiría con un único `-f`) — es la variante
de la propuesta que sí sobrevive a la guardia, pero rompe la convención de que `override.yml` es el
fichero **personal y no versionado** de cada desarrollador, le quita ese hueco a quien quiera un
retoque local, y aun así obliga a reescribir la regla 8.
Rejected: parametrizar los cuatro puertos con `PORT_OFFSET` — fuera de alcance por decisión de la
propuesta; obliga a inventar puertos libres, y «no publicar» no.
Rejected: que el worktree reutilice el Postgres/Redis del principal — descartado en la propuesta
(acopla los worktrees; y el bind a loopback impide alcanzarlo desde otro proyecto de compose).

### D2 — La detección es la desigualdad `--git-dir` ≠ `--git-common-dir`, en rutas absolutas

**Chosen:** `git rev-parse --path-format=absolute --git-dir` frente a
`--path-format=absolute --git-common-dir`. En el principal ambas dan el mismo `<repo>/.git`; en un
worktree enlazado la primera da `<repo>/.git/worktrees/<nombre>`. Medido en los tres escenarios que
importan: principal, worktree fuera del repo, y worktree **anidado** en
`.claude/worktrees/` (que es dónde los pone SDD). `--path-format` existe desde git 2.31 (2021); aquí
corre 2.52.

La comparación se hace **en shell dentro de `$(shell …)`**, no con `$(filter …)` de make: `filter`
parte por espacios y una ruta con espacios daría un falso «principal».

Rejected: buscar la subcadena `/worktrees/` en `--git-dir` — funciona (medido) pero es frágil: sin
`--path-format=absolute` la salida en el principal es relativa (`.git`) y con ella absoluta, así que
el test cambia de significado según desde dónde se invoque.
Rejected: una variable de entorno o un fichero marcador en el worktree — R4.1 pide que no haya pasos
manuales, y `EnterWorktree` no los escribiría.

### D3 — Fail-open hacia el comportamiento del principal cuando git no contesta

**Chosen:** si `git rev-parse` falla (no hay git, no es un repositorio, es un tarball), ambas
variables quedan vacías, el test de desigualdad da falso y el `Makefile` se comporta como el
principal: **publica**. Es lo que R4.3 pide y la razón está en el modo de fallo: una colisión de
puertos aborta con el mensaje de Compose nombrando el puerto, mientras que no publicar en silencio se
manifiesta como «la app no carga» y se diagnostica media hora después.

Rejected: fallar duro si git no contesta — convierte un caso benigno (clon sin git) en un stack que
no arranca.
Rejected: fail-closed a «no publicar» — invierte el modo de fallo hacia el silencioso.

### D4 — Un único `$(COMPOSE)` que usan los ocho targets

**Chosen:** el `Makefile` calcula `COMPOSE := docker compose $(COMPOSE_ARGS)` una sola vez (con `:=`,
inmediato, una llamada a git por invocación de make) y **todos** los targets pasan por él, incluidos
`down`, `logs`, `ps`, `sh`, `bootstrap`, `openapi` y `db-clean-test`. R4.4 lo exige para que ningún
target opere sobre un conjunto de ficheros distinto del que levantó el stack.

Esbozo, que es casi todo el cambio del `Makefile`:

```make
# En el principal --git-dir y --git-common-dir apuntan al mismo sitio; en un worktree
# enlazado el primero es <común>/.git/worktrees/<nombre>. Si git no contesta, las dos
# quedan vacías, la desigualdad es falsa y nos comportamos como el principal (D3).
IS_WORKTREE  := $(shell test "$$(git rev-parse --path-format=absolute --git-dir 2>/dev/null)" \
                          != "$$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" \
                        && echo yes)
COMPOSE_ARGS := $(if $(IS_WORKTREE),-f docker-compose.yml -f docker-compose.worktree.yml,)
COMPOSE      := docker compose $(COMPOSE_ARGS)
```

Rejected: tocar solo `up`/`down` — `docker compose exec` resolvería el servicio por el fichero base y
`make openapi` levantaría su contenedor con otra configuración que la del stack vivo.

### D5 — `make up` en un worktree verifica que no publica nada antes de levantar

**Chosen:** en modo worktree, `up` corre `$(COMPOSE) config --format json` y aborta si queda **alguna
clave `ports`** en la configuración resuelta. Medido sobre los ficheros reales: 4 ocurrencias con la
base sola, **0** con el overlay, así que el chequeo no tiene falsos positivos en este repo.

*(La primera versión buscaba `"published"`. Se cambió en la revisión a escala de feature: hay dos
formas legales de `ports:` que no producen esa clave y que Docker publica en un puerto efímero en
todas las interfaces — el detalle y la medición, en la cuarta ronda de D6.)*

Cubre dos cosas de un tiro:

- **R1.4 pasa de «verificable» a verificado** en cada arranque, por ~200 ms.
- Es la mitigación del suelo de versión de `!reset`: un Compose anterior a 2.24 que ignorase el tag
  dejaría los cuatro mapeos en pie y el chequeo lo caza **antes** de intentar el bind, en vez de
  fallar con un «port is already allocated» que se lee como otra cosa.

También cubre el caso «servicio nuevo con puerto que nadie añadió al overlay»: falla nombrando el
problema en vez de colisionar.

**Aviso que hereda `compose-ports-guard`, del panel de seguridad de la sección 1 (2026-08-05)**: la
salida de `docker compose config --format json` **contiene los secretos resueltos** — `JWT_SECRET_KEY`,
`POSTGRES_PASSWORD`, `BOOTSTRAP_*_PASSWORD` y `CHANNEX_API_KEY`, que es una de las tres credenciales
que nombra la regla 8 de `steering/security.md`. Aquí no hay fuga porque el preflight **nunca imprime**
esa salida (la captura en una variable y solo compara). Pero R3.3 entrega este mismo comando a una
guardia que el roadmap dice que correrá como workflow de GitHub Actions, donde stdout **es un log
persistido**: quien la escriba no debe volcar la configuración como diagnóstico.

**Prerrequisito que `compose-ports-guard` hereda, y que hay que decir porque no es obvio (panel de QA,
`/sdd:review`)**: `docker compose config` **no corre sobre un clon recién sacado**. Tres servicios
declaran `env_file: .env`, y además `docker-compose.yml` interpola con `${POSTGRES_DB:?...}`,
`${POSTGRES_PASSWORD:?...}` y `${JWT_SECRET_KEY:?...}`, así que sin `.env` falla con
`required variable POSTGRES_DB is missing a value`; y copiar `.env.example` tal cual **tampoco basta**,
porque su `JWT_SECRET_KEY` va deliberadamente vacía y la genera `make up`. Reproducido. La nota
heredada en el roadmap dice que el requisito es que el fichero exista y «no es cuestión de
interpolación» — es **las dos cosas**. Consecuencia para la guardia: en un workflow tendrá que
bootstrapear un `.env` (o inyectar esas variables) antes de poder inspeccionar la postura, y eso es
parte de su diseño, no un detalle de implementación.

**Y el mismo aviso valía para `docker inspect`**, que el `make stacks` retirado usaba (histórico: el
target ya no existe, pero el dato **no se pierde** — está en el censo de la entrada
`compose-stacks-diagnostic`, que es quien lo volverá a necesitar): su salida **por
defecto** (sin `--format`) incluye `.Config.Env`, medido sobre el stack vivo con tres variables de
clase secreta (`JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `ENCRYPTION_KEY`). El
`--format '{{index .Config.Labels ...}}'` estrecho **es portante**, no cosmético: nadie debe
«mejorar» el diagnóstico volcando la salida completa de `inspect`.

Rejected: confiar en el suelo de versión documentado — la propuesta pide postura verificable, y un
`grep` en el arranque cuesta menos que un párrafo en el README.
Rejected: parsear el JSON con python3 — introduce una dependencia de host que el `Makefile` hoy no
tiene (solo shell, docker, openssl, grep).

### D6 — RETIRADO: `make stacks` sale de este change

**Decisión del usuario en `/sdd:review` (2026-08-05), tras cinco rondas de panel y ~18 hallazgos con
referente sobre este único target, tres de ellos introducidos por el arreglo del anterior.**

Se implementó entero y funcionaba: listaba los proyectos vivos con su directorio, marcaba huérfanos
(`[huérfano]`, `[worktree]`, `[ajeno]`, `[aquí]`, `[?]`), decía quién retenía cada puerto, detectaba
suplantación por discrepancia de `working_dir`, saneaba nombres y rutas, y no ejecutaba nada. Y aun así
se retira, porque el problema no era ninguno de los bugs sino su forma: **atribuir stacks exige leer
etiquetas de contenedor —entrada que cualquier contenedor de la máquina escribe y que puede llevar
cualquier byte, incluidos `|`, saltos de línea y C1 en UTF-8— y hacerlo en shell, dentro de un
`Makefile`, para imprimir una tabla.** Esa combinación no tiene primitiva segura: cada ronda
reinventaba el tratamiento de delimitadores y reabría la misma clase de fallo. El último ejemplo, y el
que cerró la discusión: el bloque de puertos volvió a un flujo delimitado por `|` **para satisfacer una
recomendación del propio panel de seguridad**, y con ello reabrió la fabricación de filas que dos
rondas antes se había cerrado.

Pasa a la entrada de roadmap `compose-stacks-diagnostic` con el censo completo de vías demostradas.
**Consecuencia inmediata y buena**: con el target fuera desaparecen también `REPO_ROOT`,
`AHAI_REPO_ROOT` y `AHAI_INVOKED_FROM` —solo existían para él—, y con ellas **toda la superficie de la
inyección de comandos de la ronda 1** y el canal entorno→compose que el panel señaló en su item 5. El
`Makefile` que queda no interpola ningún dato externo en ninguna receta.

Lo que **sí** se queda, porque es la mitad del valor y no cuesta nada: `sdd/project.md` y `README.md`
dicen que hay que hacer `make down` **antes** de borrar el worktree, explican por qué el descuido es
fácil (`git worktree remove` **falla** si Docker dejó ficheros suyos, así que el caso normal es
«worktree desregistrado, directorio en pie» — medido al verificar la tarea 4.7) y apuntan a
`docker compose ls` como diagnóstico de andar por casa.

Rejected: seguir iterando sobre el target — es lo que la regla de tope de rondas de `/sdd:review`
señala como inútil cuando los hallazgos reaparecen en el mismo sitio.
Rejected: reducirlo a un listado mínimo sin marcas ni atribución — perdería justo lo que lo hacía útil
(saber cuál es huérfano) y aun así exigiría otra ronda de arreglos.

### D7 — Falta del overlay = mensaje propio, no un error de Compose

**Chosen:** en modo worktree, si `docker-compose.worktree.yml` no existe, el `Makefile` aborta
diciendo que ese worktree está en una rama anterior a este change y que la salida es rebasar o
levantar el stack desde el principal. Es un caso garantizado durante la transición: cualquier
worktree creado desde una rama sin este commit lo verá.

Rejected: caer a modo principal si el fichero falta — publicaría puertos y colisionaría, que es
precisamente lo que este change viene a quitar.

### D8 — Verificación: procedimental y por la guardia futura, sin tests nuevos de Python

**Chosen:** este change no toca Python ni TypeScript, así que no añade tests a `backend/tests/`. Lo
verificable se verifica de tres formas, y conviene fijarlo aquí para que `/sdd:tasks` no invente
cobertura donde no hay código: (a) `docker compose config --format json` como aserción sobre los
mapeos, en los dos modos —es la misma fuente que usará `compose-ports-guard`—; (b) el chequeo de D5,
que deja la aserción corriendo en cada arranque; (c) la prueba de aceptación de R1.2, que es
manual y cara: dos stacks arriba a la vez y la suite completa del backend en el worktree
(~6m15s, el coste que ataca la entrada `backend-suite-runtime`).

Rejected: un test de shell con un framework nuevo (bats o similar) — el repo no tiene ninguno y
`compose-ports-guard` va a decidir esa forma para el mismo material; adelantarla aquí crearía dos.

### D9 — Qué dice la documentación, y dónde

**Chosen:** `sdd/project.md` §«Worktree bootstrap» se reescribe: desaparece «un stack a la vez» y su
secuencia de `make down`/`make up` alternos, y entra la operativa real más tres avisos que **no**
desaparecen con este change — base de datos vacía por proyecto, reinstalación de dependencias la
primera vez, gigas de volúmenes por worktree, y `make bootstrap` para sembrar. Se añade explícito que
en un worktree **no hay UI ni API en el navegador del host**, con `PORT_OFFSET` nombrado como la
salida si algún día hace falta. `sdd/specs/local-environment.md` recibe el conjunto de ficheros
canónico (R3.3) en §«Postura de red del stack local» y la detección en §«Makefile como entrypoint
único». `README.md` §«Postura de red del stack local» se actualiza con la misma frase y un aviso de
que los `docker compose` desnudos de los §99/§189/§207 valen en el principal, y en un worktree hay
que ir por `make`.

`steering/security.md` regla 8 **no se toca**: su frase sigue describiendo lo que el compose
implementa. Ese es el criterio que D1 optimiza y conviene que quede escrito, porque el precedente de
esa misma regla fue una justificación que describía una postura que el fichero no implementaba.

Rejected: documentar solo en `project.md` — R6.4 y `steering/documentation.md` obligan a que la spec
y el README describan lo implementado.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Compose | `docker-compose.worktree.yml` (**nuevo**, versionado) | `ports: !reset []` para `postgres`, `redis`, `backend`, `frontend`, con comentario de cabecera explicando qué hace, por qué existe y que **no** se usa en el principal ni en el CD |
| Compose | `docker-compose.yml` | **sin cambios funcionales**; se añade una nota junto a los mapeos apuntando al overlay, para que quien lea los `ports:` sepa que un worktree los retira |
| Orquestación | `Makefile` | detección (D2/D3), `$(COMPOSE)` único en los ocho targets (D4), aviso del modo al arrancar (R4.2), chequeo previo en modo worktree (D5), guarda de fichero ausente (D7). ~~target `stacks` (D6)~~ **retirado** |
| Docs de proyecto | `sdd/project.md` | reescritura de §«Worktree bootstrap» (D9) |
| Docs de repo | `README.md` | §«Postura de red del stack local» + nota sobre `docker compose` desnudo en worktrees |
| Spec | `sdd/specs/local-environment.md` | conjunto de ficheros canónico y detección de worktree (al archivar). ~~target `stacks`~~ **retirado** |
| Sin cambios (verificado) | `docker-compose.deploy.yml`, `.github/workflows/*`, `backend/app/core/config.py`, `infra/environments/dev/RUNBOOK.md`, `frontend/README.md`, `sdd/steering/security.md` | el CD nunca usa el compose base; ningún workflow invoca `make`; el fallback a `localhost:5432` sigue vivo en el principal |

## Data & interfaces

**Ninguna variable de entorno nueva** — y es deliberado, no una omisión: R3.1 prohíbe que la postura
dependa de un fichero ignorado, y `.gitignore` ignora `.env*` en bloque. La selección de ficheros
viaja por la línea de comandos que compone el `Makefile`, así que es función del repositorio. Nada
que añadir a `.env.example`.

Sin cambios de esquema, de API ni de contrato, y **ningún interfaz nuevo**: el único que hubo, el
target `make stacks`, se retiró (D6). Lo que cambia de cara a una persona son dos líneas de salida de
`make up` (el modo, y los dos mensajes de abort).

Suelo de herramientas, ahora explícito: **Docker Compose ≥ 2.24** (por `!reset`, mitigado por D5) y
**git ≥ 2.31** (por `--path-format`). El entorno medido corre Compose v5.1.1 y git 2.52.

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| Un `docker compose up` **desnudo** dentro de un worktree carga solo la base, publica y colisiona | Falla ruidosamente con el puerto nombrado, que es el comportamiento de hoy: no es una regresión. D9 lo documenta; el diagnóstico con marcas **no se entrega aquí** (D6 retirado) y queda en la entrada `compose-stacks-diagnostic` — de momento, `docker compose ls`. Es el precio de D1, y se paga a cambio de que el principal y la guardia no cambien |
| Un servicio futuro añade `ports:` y nadie lo añade al overlay | D5 lo caza en el arranque del worktree nombrando el problema, antes de intentar el bind |
| Compose < 2.24 ignora `!reset` y el worktree publica | D5 aborta antes de levantar; el suelo queda escrito en la spec |
| El overlay no existe (worktree en rama antigua) | D7: mensaje propio con la salida |
| Dos stacks completos = doble de contenedores, RAM y gigas de volúmenes | Es el coste asumido por la propuesta; D9 lo deja escrito donde se lee antes de crear el worktree |
| `**/.claude/worktrees/` vive en `.git/info/exclude`, que es **local a la máquina y no versionado** | Fuera de alcance aquí, pero anotado: en otro clon los worktrees anidados aparecerían como ficheros sin trackear. No afecta a este change (el overlay es un fichero versionado del repo, presente en todo worktree); si molesta, es un change propio |
| El stack huérfano de hoy retiene los cuatro puertos y seguirá reteniéndolos | Este change no lo mata (era R5, retirado; y un target que informa sin actuar era su premisa). La secuencia de verificación empieza por `docker compose -p sddlocal-dev-network-hardening down`, que es una acción del desarrollador, no del `Makefile` |

## Open questions

Las tres se plantearon y se **resolvieron en la puerta de este design (2026-08-05)**, con el usuario.
Se dejan escritas con su resolución porque una de ellas revierte la recomendación de partida y quien
lea esto en seis meses necesita saber que fue deliberado.

**OQ1 — El mecanismo de D1 contradice la recomendación con la que se abrió el change.** La propuesta
fijaba «sacar `ports:` del compose base a un fichero que solo incluya el principal»; el análisis de
diseño encuentra que eso rompe la vista de `compose-ports-guard`, incumple R2.3/R3.2 al pie de la
letra y desancla la regla 8, y que `ports: !reset []` consigue lo mismo dejando el principal y el
fichero base intactos. La tercera vía evaluada fue `docker-compose.override.yml` versionado, que
conserva la idea original («los puertos son cosa del principal, en su propio fichero») y sobrevive a
la guardia, a cambio de romper la convención del override personal.

→ **RESUELTA: se va con D1 (`ports: !reset []`).** Se acepta explícitamente su único coste conocido:
un `docker compose` desnudo dentro de un worktree colisiona, igual que hoy, y por eso en un worktree
se va por `make` (D9 lo documenta).

**OQ2 — ¿`make stacks` entra en este change o se queda fuera?** R5 nace de un hallazgo de la fase
`new` (un stack sobrevivió a su worktree), no del enunciado original. Es pequeño (D6), pero es
diagnóstico y no es lo que desbloquea las sesiones concurrentes.

→ **RESUELTA en su momento: entra en este change** — el stack huérfano de hoy es el disparador real.
**SUPERADA por D6 el 2026-08-05**: se implementó, acumuló ~18 hallazgos en cinco rondas de panel y el
usuario decidió retirarla en `/sdd:review`. La respuesta vigente a esta pregunta es «se queda fuera», y
el motivo está en D6. Se conserva la resolución original porque explica por qué se intentó.

**OQ3 — Nombre del overlay.** `docker-compose.worktree.yml` nombra la situación (y deja hueco a un
futuro `PORT_OFFSET`); `docker-compose.noports.yml` nombra el efecto y se lee mejor desde la
perspectiva de la guardia.

→ **RESUELTA: `docker-compose.worktree.yml`.** Es el nombre que ya usan D1, D4, D7 y la tabla de
áreas; no queda ninguna referencia al alternativo.
