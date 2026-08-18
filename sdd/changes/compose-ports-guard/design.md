# Design: compose-ports-guard

## Context

`docker-compose.yml` declara hoy **7 servicios** (`postgres`, `redis`, `migrate`, `backend`,
`worker`, `beat`, `frontend`), **4 mapeos de puertos** (`127.0.0.1:5432:5432`,
`127.0.0.1:6379:6379`, `8000:8000`, `3000:3000`) y **0 profiles** — medido en este worktree con
Compose 5.1.1. `docker-compose.worktree.yml` los retira con `ports: !reset []` y lo carga **solo**
el `Makefile` cuando detecta un worktree enlazado (`COMPOSE_ARGS`), así que un `docker compose`
desnudo ve siempre el fichero base.

El patrón que esta guardia tiene que seguir ya existe y está maduro: `scripts/compose-stacks.py`
(Python de la stdlib, funciones puras + un `main()` que encadena, `capture()` que comprueba el
estado de salida aparte del contenido, `escape()` inyectivo para imprimir, lista negra de comandos
en el docstring **y** verificada por su propia suite) con `scripts/test_compose_stacks.py` al lado,
cargado por `importlib` porque el nombre kebab-case no es importable. El workflow a copiar es
`.github/workflows/api-contract.yml`: un job, sin `paths:`, `concurrency`, `permissions:
contents: read`, acciones pinneadas por SHA.

La comprobación que `make up` ya hace en modo worktree (`Makefile`, receta de `up`) es el otro
antecedente vivo: asierta la **ausencia** de la clave `ports` antes de levantar, comprueba el
estado de salida de `config` aparte del contenido, y nunca degrada a verde. Esta guardia es su
complemento con sujeto distinto (la postura del repositorio en CI, no un stack concreto).

Todas las cifras y comportamientos de Compose que este documento afirma están **medidos en esta
máquina** contra ficheros de prueba sintéticos, no heredados de la entrada de roadmap.

## Decisions

### D1 — La fuente es `docker compose config --no-interpolate --no-env-resolution --format json`

**Chosen:** invocar `config` con **las dos banderas**, y no `config` a secas. Medido: con las dos
banderas, en un clon **sin `.env`**, `config` sale con **código 0**, normaliza igual los mapeos de
puertos, y su salida **no contiene ningún valor del `.env`** (las variables quedan literales:
`JWT_SECRET_KEY: "${JWT_SECRET_KEY:?Falta JWT_SECRET_KEY en .env (make up la genera)}"`). Sin
ellas, y con un `.env` presente, `config --format json` **inlina el fichero entero** en
`environment` — medido con un `.env` de prueba: un `SUPER_SECRET` que no aparece en ninguna parte
del compose salió en la salida. Eso es exactamente lo que prohíbe `specs/local-environment.md`.

Esto es la decisión de cabecera porque **cambia tres premisas del proposal**:

- **R1.5 y R1.6 dejan de tener sujeto.** No hay `.env` que bootstrapear en el workflow, ni valores
  efímeros que generar, ni ningún secreto —real o de usar y tirar— dentro del job. El requisito se
  cumple por no existir el problema, no por gestionarlo bien.
- **R1.7 pasa de disciplina a construcción.** La obligación de no volcar nunca la salida sigue
  escrita (defensa en profundidad, y sigue siendo lo correcto), pero ya no carga con todo el peso:
  la salida **medida** no tiene nada sensible dentro.
- **El criterio 2 de la entrada de roadmap** —«su resultado es función **solo** del repositorio, no
  del entorno de quien la ejecuta»— pasa de aspiración a propiedad estructural. Con interpolación
  activada, un `BIND=0.0.0.0` en el `.env` de alguien daría rojo en su máquina y verde en CI: el
  veredicto sería función del entorno. Con `--no-interpolate` el veredicto se calcula sobre el
  texto del repositorio y nada más.

Rejected: `config` con un `.env` efímero bootstrapeado en el workflow (la vía del proposal) — pone
secretos resueltos en un log persistido y hace el veredicto función del `.env`.
Rejected: parsear el YAML a pelo — Compose es quien normaliza las cuatro formas de escribir un
mapeo, y la stdlib no trae parser de YAML (R4.1 y R1.1 lo cierran).
Rejected: `--no-interpolate` a secas (medido: también basta hoy, y tampoco inlinó el `env_file`) —
la bandera documentada para eso es `--no-env-resolution`, y depender de un acoplamiento no
documentado entre las dos es la clase de suposición que este historial ya castigó cinco veces.

### D2 — Un mapeo de puertos construido con interpolación es una infracción

**Chosen:** una entrada de `ports` que **no sea un objeto** es infracción, y se nombra tal cual.
Medido, y es una **vía que el censo no tenía**: con `--no-interpolate`, un mapeo que contiene
`${...}` **no se normaliza** — sale como cadena cruda (`"${BIND}:5432:5432"`,
`"127.0.0.1:${PGPORT}:5432"`, `"${WHOLE_MAPPING}"`), no como `{host_ip, published, target}`. Una
guardia que asuma objeto y haga `entry.get("host_ip")` revienta con `AttributeError` sobre una
cadena; una que lo envuelva en `try/except` lo deja pasar en verde.

Tratarlo como infracción no es una limitación que se acepta: **es el mecanismo que hace verdadero
el criterio 2**. Un mapeo cuyo valor sale del entorno no es una postura del repositorio, así que
la guardia no puede aprobarlo sin dejar de ser función solo del repositorio. La llamamos vía **(i)**
del censo y lleva su propio caso en rojo.

Consecuencia declarada para el change hermano `worktree-port-offset`: un desplazamiento escrito
como `"127.0.0.1:${PORT_OFFSET}..."` daría **rojo** con esta guardia. Aquel change tendrá que
decidir entre generar mapeos literales o reabrir esta regla a sabiendas — que es exactamente la
relación que el proposal anticipa, ahora con el mecanismo concreto nombrado.

Rejected: interpolar solo la clave `ports` — no existe forma de interpolar selectivamente.
Rejected: aceptar la cadena y parsear el prefijo a mano — el prefijo literal `127.0.0.1:` sería
aprobable, pero cualquier otra forma exigiría reimplementar el parser de mapeos de Compose.

### D3 — Los profiles se enumeran por línea y se activan por `argv` repetido

**Chosen:** dos invocaciones. `config --profiles` enumera **todos** los profiles declarados, activos
o no, uno por línea (medido: lista `tools` y también `a,b`). Después, `docker compose --profile <p1>
--profile <p2> … config …`, un `--profile` por nombre, porque la bandera es `stringArray` y viaja por
`argv` **sin separador**: no hay representación con pérdida y la vía (g) desaparece del camino.

Medido, y es la demostración de (g) y de su arreglo sobre el mismo fichero: con
`--profile "a,b" --profile tools` salen **6** servicios (los 6 declarados, incluido el que cuelga del
profile con coma); con `COMPOSE_PROFILES="a,b,tools"` salen **5** — el servicio bajo el profile `a,b`
desaparece en silencio.

Rejected: `COMPOSE_PROFILES` unido por comas — es el viaje con pérdida que la vía (g) explota.
Rejected: no evaluar los profiles porque hoy el repositorio no declara ninguno (medido: 0) — R4.3 lo
exige, y una guardia que solo funciona mientras nadie use profiles es la clase de verde que este
historial ya vio cinco veces.

**Corrección medida en `/sdd:run` (2026-08-18), y afecta a la premisa, no a la decisión.** R4.3 y
esta decisión dan por hecho que «un servicio bajo un profile no activo es invisible para
`docker compose config`». Eso es cierto de `config` **a secas** —medido: 2 de 4 servicios—, pero
**`--no-interpolate` por sí solo hace visibles los servicios con profile** en `config`, `--services`
y `--profiles`, sin ninguna bandera `--profile` (medido: 4 de 4). El motivo está en el código de
Compose: con `--no-interpolate`, `runServices` no construye un proyecto resuelto sino que renderiza
el modelo crudo (`cmd/compose/config.go`, idéntico en v5.1.1 y v5.5.0), y el modelo crudo no tiene
filtrado por profile.

Es decir: las banderas de D1 ya cierran la vía (a) por sí mismas. **La decisión no cambia** —seguir
activando los profiles por `--profile` repetido es estrictamente más seguro y no depende de un
acoplamiento no documentado entre las dos banderas, que es justo lo que D1 rechaza en su último
«Rejected»—, pero la premisa que la justificaba era más débil de lo que este documento afirmaba, y
queda escrita para que nadie la vuelva a derivar.

### D4 — La aserción positiva son dos igualdades, y la de profiles audita a la enumeración

**Chosen:** antes de emitir verde, la guardia afirma dos cosas y falla si no puede confirmar
cualquiera de ellas (R4.4):

1. **Servicios**: el conjunto de servicios del JSON es **exactamente igual** al inventario que la
   guardia declara en su propio código (`EXPECTED_SERVICES = {postgres, redis, migrate, backend,
   worker, beat, frontend}`), y además igual al que devuelve `config --services` con los mismos
   profiles activados.
2. **Profiles**: la unión de los `profiles` que traen los servicios del JSON es **igual** al conjunto
   que devolvió `config --profiles`.

La segunda es la que cierra la clase entera del problema, y conviene ver por qué: el JSON es una
representación **sin pérdida** (lo decodifica `json.loads`) y la enumeración por líneas es **con
pérdida** (un nombre con salto de línea se parte en dos). Al exigir que coincidan, **la fuente sin
pérdida audita a la fuente con pérdida**. Un profile que la enumeración no supo leer no llega a
activarse, su servicio no aparece en el JSON, la unión no coincide con la enumeración y la guardia
falla. Eso es la inversión que pide el diagnóstico estructural del roadmap: una sola aserción
positiva en lugar de tres guardas negativas, y cubre (e), (g) y (h) a la vez — un `config` que
salga con **éxito** devolviendo `{}` da conjunto de servicios vacío ≠ inventario declarado, y es
rojo.

El inventario declarado en el código es lo único que ata el modelo inspeccionado a **este**
repositorio, y por eso va por **igualdad** y no por contención: un servicio nuevo deja la guardia en
rojo hasta que alguien lo añada a la lista, y ese momento es precisamente cuando hay que decidir
qué publica. Es la misma disciplina que `docker-compose.worktree.yml` ya impone y que el propio
compose documenta («Ojo si añades un servicio con `ports:` al fichero base: añádelo también aquí»).

**Corrección medida en `/sdd:run` (2026-08-18): de las dos igualdades, la primera tiene media pata
menos de la que este documento le atribuía, y la segunda las tiene todas.** El párrafo de arriba
presenta la comparación JSON ↔ `config --services` como si fueran dos fuentes independientes que se
auditan. Medido en el código de Compose: con `--no-interpolate`, tanto `--format json` como
`--services` derivan del **mismo** `ToModel` (`cmd/compose/config.go`, `runConfig` y `runServices`,
idéntico en v5.1.1 y v5.5.0), así que esa igualdad compara el modelo consigo mismo y **no puede
discrepar** en las versiones medidas.

Lo que sí hace trabajo real, y basta:

- La igualdad contra `EXPECTED_SERVICES`, que es **genuinamente independiente** porque vive en el
  código de la guardia y no en la salida de Compose. Es la que atrapa el servicio nuevo, el
  renombrado y el `{}`.
- La igualdad de **profiles**, que es la que este documento ya llamaba portante — y con razón:
  `config --profiles` **no** tiene atajo para `--no-interpolate`, va por el cargador completo
  (`runProfiles` → `ToProject` → `AllServices()`), así que es un camino de verdad distinto del JSON.

La comparación contra `--services` **se conserva**: no cuesta nada y sería lo que avise el día que
Compose vuelva a separar los dos caminos. Lo que se corrige es la afirmación de que hoy audita algo.

Rejected: solo contención (`⊇`), como dice literalmente R4.4 — deja entrar un servicio nuevo sin que
nadie mire su postura, que es el descuido que esta guardia existe para atrapar. La igualdad quedó
confirmada en el gate (Q1).
Rejected: derivar el inventario del fichero con un escáner de YAML propio — segundo parser, sin
dependencias disponibles, y frágil justo donde tiene que ser fiable.
Rejected: asertar solo «al menos un servicio» o un recuento — un renombrado pasaría el recuento.

### D5 — El entorno del hijo se construye por lista blanca, no desinfectando por lista negra

**Chosen:** las invocaciones a Compose se lanzan con `env={"PATH": os.environ["PATH"]}` — un
diccionario construido desde cero, no `os.environ` menos unas claves. Medido: con solo `PATH`,
`config --services` devuelve los 7 servicios y código 0.

El argumento es de dirección de fallo: **una lista blanca demasiado estrecha falla en rojo** (Compose
no arranca o no encuentra algo, y la guardia lo nombra), mientras que **una lista negra demasiada
estrecha falla en verde** — es la vía (d), y se repite con cada variable nueva que Docker añada
(`COMPOSE_FILE`, `COMPOSE_PATH_SEPARATOR`, `COMPOSE_PROFILES`, `COMPOSE_ENV_FILES`, y la siguiente,
que no conocemos). Enumerar lo que se conserva es afirmar en positivo; enumerar lo que se quita es
volver a razonar en negativo.

Rejected: `os.environ.copy()` quitando `COMPOSE_*` — lista negra, vía (d) reabierta en cuanto Docker
añada una variable.
Rejected: pasar `--file docker-compose.yml` para no depender del entorno — es la vía (f): `--file`
**desactiva** la carga automática del override y una lista escrita a mano se queda corta.

### D6 — No hay comparación de versión de Compose: una bandera desconocida ya falla en rojo

**Chosen:** ninguna lógica de versión. Un Compose que no conozca `--no-env-resolution` sale con
código distinto de cero y `unknown flag`, y eso ya es el camino de fallo de D7: rojo nombrando el
paso. El mensaje de ese fallo incluye la pista («si dice `unknown flag`, tu Docker Compose es
anterior al mínimo del proyecto»), que es todo lo que aporta una comparación de versiones sin
inventarse una tabla de qué bandera llegó en qué release.

R6.1 nombra «Compose por debajo de la versión mínima» entre los fallos que hay que atrapar: se
atrapa, solo que por el estado de salida y no por una cadena de versión parseada.

Rejected: parsear `docker compose version --short` y comparar — código nuevo, tabla de versiones
que mantener, y un parseo que puede fallar (y entonces hay que decidir qué hacer, que es una guarda
negativa más).

### D7 — Cada invocación comprueba su estado de salida aparte, y el fallo relata solo la primera línea de `stderr`

**Chosen:** una sola función `capture()` —copiada en espíritu de `compose-stacks.py`— con
`subprocess.run(cmd, capture_output=True, text=True, env=CLEAN_ENV)`, lista de argumentos y **nunca**
por shell, sin `2>/dev/null` y sin pipes: el estado de salida se comprueba **antes** de mirar el
contenido (R6.2). En el fallo, el mensaje nombra el paso, el código de salida, y **la primera línea
de `stderr`** saneada con el `escape()` inyectivo y acotada a 200 caracteres, igual que
`compose-stacks.py`.

Relatar esa línea es seguro **por D1 y no por confianza**: sin interpolación no hay error de
interpolación que pueda citar un valor, y sin resolución de `env_file` no hay valores del `.env` en
juego. `stdout` no se relata **nunca**, ni entero ni en fragmentos (R1.7).

La vía (e) merece la demostración que este documento puede dar de sí misma: al comprobar cosas
para escribirlo, `docker compose config --services 2>&1 | tail -2` imprimió el error de
interpolación y devolvió **`rc=0`**, porque en un pipe el estado de salida es el del último comando.
Esa es la vía, viva, medida hoy.

Rejected: no relatar nada de `stderr` — un rojo en CI que no se puede diagnosticar invita a
rerunear a ciegas, y con D1 el motivo para callarlo ya no existe.
Rejected: relatar `stderr` entero — el precedente del repositorio es la primera línea acotada, y un
volcado ajeno es exactamente lo que la lista negra de `compose-stacks.py` prohíbe.

### D8 — `network_mode` va por lista blanca de valores conocidos

**Chosen:** un servicio es conforme solo si su `network_mode` está **ausente** o es `bridge` o
`none`. Cualquier otro valor es infracción nombrando el servicio y el valor. `host` publica todo
**sin generar ninguna entrada `ports`** (medido: el servicio con `network_mode: host` sale sin clave
`ports`), así que un bucle sobre `ports` lo trata como conforme — vía (b).

Lista blanca y no `!= "host"` por el mismo argumento de D5: hoy ningún servicio del repositorio usa
`network_mode`, así que el coste de la lista blanca es cero y la próxima forma de compartir el
espacio de red del host llega en rojo en vez de en verde.

Rejected: comprobar solo `network_mode == "host"` — cierra la vía conocida y deja abierta la
siguiente.

### D9 — La exención es un conjunto de pares literales, y ampliarla es un cambio de datos

**Chosen:** `EXEMPT = frozenset({("backend", "8000"), ("frontend", "3000")})`, y la decisión por
mapeo es una pertenencia a ese conjunto. `published` llega como **cadena** en el JSON (medido:
`'8000'`, no `8000`), así que la comparación es de cadenas y un rango (`"8000-8010"`) nunca
pertenece al conjunto: cae por el camino normal y es rojo, sin código propio.

Eso satisface R3 completo por construcción: la unidad de decisión **es** el par, así que un puerto
extra en un servicio exento (R3.2) y el mismo puerto en un servicio no exento (R3.3) son rojo sin
ninguna regla adicional.

Y satisface lo que el proposal pide para el change hermano: la estructura es «una decisión por par»,
así que admitir un desplazamiento después es sustituir el conjunto por una tabla o un predicado
sobre `(servicio, puerto)` — un cambio en el dato, no en la forma de recorrer el modelo.

Rejected: eximir por servicio — vía (c) del censo, explícitamente prohibida por R3.1.
Rejected: eximir por puerto — R3.3.

### D10 — Vive fuera de `$(COMPOSE)`, y eso es lo que impide que pase en vacío

**Chosen:** `make check-compose-ports` invoca `python3 scripts/compose-ports.py` directamente, como
`check-version-parity` y `compose-stacks`, **sin pasar por `$(COMPOSE)`**. No es una omisión: en un
worktree enlazado `$(COMPOSE)` añade `docker-compose.worktree.yml`, que retira los cuatro mapeos, así
que la guardia vería **cero claves `ports`** y daría verde sin haber comprobado nada — la «guardia
pasando en vacío» de la que avisa `specs/local-environment.md`. Invocando Compose desnudo, la
guardia da el mismo veredicto en el worktree principal, en un worktree enlazado y en CI, que es lo
que pide el criterio 2.

Consecuencia para `specs/local-environment.md:251` (la cuenta de «los nueve targets que invocan
`docker compose` desde el `Makefile`»): este target **no** invoca `docker compose` desde el
`Makefile` —lo invoca su script, desde Python, con entorno propio y deliberadamente desnudo—, así que
la cuenta sigue en **nueve** y lo que cambia es la frase que enumera los host-side: pasan de dos
(`check-version-parity`, `compose-stacks`) a **tres**, y el motivo por el que este queda fuera se
escribe junto al de `compose-stacks`, porque no es el mismo motivo (confirmado en el gate, Q3).

Rejected: una receta de shell en el `Makefile` — R1.1 lo prohíbe por precedente medido (~18 hallazgos
en cinco rondas).
Rejected: pasar por `$(COMPOSE)` «por coherencia» — daría verde en vacío en cualquier worktree.

### D11 — Un workflow propio, un job, sin `paths:`

**Chosen:** `.github/workflows/compose-ports.yml`, `name: compose-ports`, un único job llamado
también `compose-ports` (el check run toma el nombre del **job**, R1.2), copiando la forma de
`api-contract.yml`: `on: pull_request: {} / push: branches: [main] / workflow_dispatch: {}`,
`concurrency` con `cancel-in-progress`, `permissions: contents: read`, `timeout-minutes: 10`,
`actions/checkout` pinneado por SHA. **Sin `paths:`** (R1.3, prohibido por `specs/backend-ci.md:27`).

Pasos: checkout → `astral-sh/setup-uv` (pinneado por SHA, el mismo que `api-contract.yml`) →
`make check-compose-ports` → `uv run --no-project --with 'pytest==9.1.1' python -m pytest scripts/ -q`.
Nada más: sin `setup-python` (la guardia es stdlib y `uv` provee el intérprete de las pruebas), sin
`.env`, sin secrets, sin servicios. El runner de `ubuntu-latest` ya trae Docker con el plugin
`compose`, y `config` **no habla con el daemon**.

Y queda **fuera de `backend/tests/`** (R1.4): `backend-tests.yml:137` decide el área con
`case "$f" in backend/* | ...)`, así que un PR que solo toque `docker-compose.yml` no ejecutaría esa
suite — justo el PR donde la guardia tiene que hablar.

Rejected: un paso dentro de `backend-tests.yml` — R1.4, y además el patrón de tres jobs no se paga
en una comprobación de segundos (R1.2).

### D12 — La suite demuestra la guardia en rojo, una vía por caso, y se vigila a sí misma

**Chosen:** `scripts/test_compose_ports.py`, cargado por `importlib` como
`scripts/test_compose_stacks.py`, con **un caso en rojo por vía** del censo: (a) servicio bajo
profile no activo, (b) `network_mode: host`, (c) exención por servicio en vez de por par, (d)
`COMPOSE_FILE` exportado, (e) fallo de enumeración que se traga, (f) `--file` que pierde el
override, (g) profile con coma, (h) `config` con éxito devolviendo `{}`, más la nueva **(i)** mapeo
interpolado de D2. Los casos que no dependen de Docker se prueban sobre las funciones puras con
modelos JSON en el propio fichero; los que dependen de cómo se invoca a Compose (d, e, f, g) se
prueban con un `docker` de mentira en el `PATH` del test.

Y dos tests de contrato que no prueban lógica sino que la guardia no se desarme:

- **Espejo de la lista negra**: el código de `compose-ports.py` nunca invoca `config` sin las dos
  banderas de D1. Se consigue con una única constante (`CONFIG_BASE`) y un test que asierta que en
  el cuerpo del script no aparece ninguna otra invocación de `config` — el mismo mecanismo que
  `test_the_command_blacklist_of_d2_has_not_been_reintroduced` ya usa para `compose-stacks.py`, que
  está acotado a **su** fichero y por tanto no entra en conflicto con este script nuevo.
- **Contra Docker de verdad**, cuando hay `docker` en el `PATH`: que los cuatro mapeos del
  repositorio siguen saliendo con la forma que este documento midió. Es lo que avisará el día que
  Compose renombre un campo o cambie la normalización — el mismo test de contrato que
  `test_compose_stacks.py` ya tiene.

La suite corre **en el mismo workflow** (R6.4). Hoy ningún workflow recoge `scripts/test_*.py`
(`backend-tests.yml` invoca pytest con `working-directory: backend`), así que este change es el
primero que las lleva a CI. El mecanismo, decidido en el gate (Q4): `astral-sh/setup-uv` +
`uv run --no-project --with 'pytest==9.1.1' python -m pytest scripts/ -q` — el `pytest` queda
pinneado y alineado con `backend/pyproject.toml`, y `--no-project` evita sincronizar el árbol de
dependencias del backend para probar un script de la stdlib. En local sigue siendo
`python3 -m pytest scripts/`, como ya documenta la spec para `compose-stacks`.

Rejected: probar solo el verde sobre el compose real — es literalmente lo que pasó cinco veces.
Rejected: mockear `subprocess.run` para las vías (d)-(g) — probaría el mock; un `docker` de mentira
en el `PATH` prueba la construcción real del `argv` y del entorno, que es donde viven esas vías.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Guardia | `scripts/compose-ports.py` | **Nuevo**. Stdlib, sin dependencias. Funciones puras (`parse_model`, `assert_inventory`, `violations`, `render`) + `capture()` + `main()`. Constantes: `CONFIG_BASE`, `EXPECTED_SERVICES`, `EXEMPT`, `SAFE_NETWORK_MODES`. Docstring de cabecera con la regla de D1 escrita. |
| Pruebas | `scripts/test_compose_ports.py` | **Nuevo**. Un caso en rojo por vía (a)-(i), los dos tests de contrato de D12. |
| Entrypoint | `Makefile` | Target `check-compose-ports` + entrada en `.PHONY`, fuera de `$(COMPOSE)`, con el comentario que explica **por qué** queda fuera (D10). |
| CI | `.github/workflows/compose-ports.yml` | **Nuevo**. Un job, sin `paths:`, patrón `api-contract.yml`. |
| Spec | `sdd/specs/local-environment.md` | **6 sitios** (el diseño planificó 4; los otros dos aparecieron al implementar, ver nota abajo): (1) §Postura de red, el bullet «no tiene comprobación automática todavía» pasa a describir la guardia; (2) sección propia junto a §Diagnóstico de stacks de Compose; (3) §Diagnóstico, la prohibición de `docker compose config` se **acota a su forma peligrosa** (ver Data & interfaces); (4) §Makefile, la frase de los nueve targets (D10, Q3); (5) el criterio EARS que exigía un `.env` presente y completo para inspeccionar la postura, que D1 dejó sin sujeto; (6) el suelo de versión de Compose, que sube de 2.24 a 2.35.0. |
| Prohibición, otros dos sitios | `scripts/compose-stacks.py` (docstring), `Makefile` (comentario de `compose-stacks`) | La prohibición está escrita en tres sitios a propósito: los tres pasan a la forma acotada, o el arreglo queda a medias. |
| Steering | `sdd/steering/security.md` | Regla 8, párrafo de la exención de `POSTGRES_PASSWORD`: «Hoy no hay comprobación automática…» pasa a citar la guardia como lo que sostiene la exención. |
| README | `README.md` | §Postura de red del stack local: misma afirmación, misma corrección. |
| No se modifica | `sdd/specs/backend-ci.md` | Se cita (prohibición de `paths:`, suite del backend hermética a `backend/**`). Verificar al cerrar que el workflow nuevo no la contradice. |

## Data & interfaces

**Nada de esquema, nada de API, ninguna variable de entorno nueva** — y esto último es
consecuencia de D1: la guardia no lee configuración, así que no añade nada a `.env.example`.

**Contrato de la guardia** (es su interfaz real):

- `python3 scripts/compose-ports.py`, sin argumentos, sin banderas. Se ejecuta desde la raíz del
  repositorio.
- **Código 0**: ninguna infracción. `stdout` dice cuántos servicios, cuántos mapeos y cuántos
  profiles ha inspeccionado, y los nombra (R2.3) — «vio esto», no «no vio nada».
- **Código distinto de cero**: infracción o fallo de la cadena. `stdout`/`stderr` nombran servicio y
  mapeo infractor (R2.1) o el paso que falló (R6.1). **Nunca** la salida de `config`.
- Formato de la salida: una etiqueta y un valor por línea, un bloque por hallazgo, orden
  determinista, escape inyectivo — el mismo criterio de `compose-stacks.py`, y por el mismo motivo
  (nombres de servicio y de profile son datos ajenos al formato).

**Regla que sustituye a la prohibición actual** (el cambio normativo de este change, y va escrito en
los tres sitios donde hoy vive la prohibición):

> Prohibido `docker compose config` **sin `--no-interpolate --no-env-resolution`**. Con las dos
> banderas la salida no contiene ningún valor del `.env` (medido); sin ellas inlina el fichero
> entero. `docker inspect` sin `--format` sigue prohibido sin excepción.

Es mejor que la prohibición que sustituye por una razón concreta: hoy dice «en cualquier forma» y
habría obligado a exceptuar **este script** por promesa de buena conducta. La forma acotada es
**mecánica y verificable** —una lista de banderas, comprobada por un test sobre el propio código— en
vez de una excepción nominal que el siguiente script pediría también.

**Decisión por mapeo** (el núcleo, en orden):

1. `network_mode` no está en `{ausente, bridge, none}` → infracción (D8).
2. `ports` ausente → conforme.
3. Entrada de `ports` que no es objeto → infracción (D2, vía (i)).
4. Objeto sin `published` → infracción **siempre**, incluso en un servicio exento: sin puerto de host
   no hay par que identificar, y Docker publica en un puerto efímero en todas las interfaces (R5.1).
5. `(servicio, published)` ∈ `EXEMPT` → conforme (R3.1).
6. `host_ip == "127.0.0.1"` → conforme; cualquier otra cosa —ausente, `null`, `"0.0.0.0"`, `"::1"`,
   un literal interpolado— → infracción.

Dato medido que corrige a la entrada de roadmap: con Compose 5.1.1 un `host_ip` sin especificar sale
con la clave **ausente**, no como `null`. La comparación por igualdad con `"127.0.0.1"` cubre las
dos formas y no depende de cuál sea.

## Risks & mitigations

- **La postura pasa a ser «ningún mapeo interpolado», y eso es más estricto que lo que hay escrito
  hoy.** Es deliberado (D2) y es lo que sostiene el criterio 2, pero acota a `worktree-port-offset`
  antes de que se diseñe. Mitigación: queda escrito aquí y en la sección de relación del proposal, no
  se descubre allí.
- **`::1` (loopback IPv6) daría rojo.** Es loopback y por tanto seguro, pero no es la postura escrita.
  Fallar en rojo y dejar que una persona ensanche la regla a sabiendas es la dirección correcta;
  queda anotado como limitación conocida en la spec.
- **El inventario declarado de D4 hay que mantenerlo.** Un servicio nuevo deja la guardia en rojo
  hasta que se añada. Mitigación: es la misma disciplina que `docker-compose.worktree.yml` ya exige,
  el mensaje de fallo dice exactamente qué línea añadir, y el rojo llega en el PR que añade el
  servicio — que es cuando hay que decidir su postura.
- **Las banderas de D1 son un contrato con Compose.** Si una desaparece o cambia de semántica, la
  guardia falla en rojo (bandera desconocida, D6) o —el caso malo— sigue funcionando resolviendo el
  `.env`. Mitigación: el test de contrato contra Docker de verdad (D12) comprueba la forma de la
  salida, y el test espejo comprueba que las banderas no se han caído del código.
- **Compose por debajo del mínimo del proyecto.** Cubierto por D6: `unknown flag` es código distinto
  de cero y por tanto rojo con mensaje propio. **Confirmado en `/sdd:run` (2026-08-18), y el suelo
  sube**: `--no-env-resolution` la introdujo el PR 12665 de `docker/compose`, mergeado el 2025-03-24
  y publicado por primera vez en **v2.35.0** (2025-04-10); comprobado que en v2.35.0 la bandera está
  y en v2.34.0 no. Es **posterior** a 2.24, así que el suelo documentado sube de 2.24 a **2.35.0**,
  en `specs/local-environment.md` y también en `README.md`, que llevaba su propia copia de la cifra
  (el diseño solo nombraba la spec). Cambio de spec, no de código, como este riesgo anticipaba.
- **No duplica ni contradice la comprobación de `make up`** (R6.5): aquélla asierta la **ausencia** de
  `ports` en la configuración con overlay antes de levantar **un stack**; ésta asierta la **postura
  del repositorio** sobre la configuración desnuda. Sujetos distintos, ficheros distintos, momentos
  distintos. Queda escrito en la sección nueva de la spec para que nadie las funda después.
- **No se genera diagrama**: el flujo es una tubería lineal de tres invocaciones y dos aserciones, y
  la decisión por mapeo son seis reglas en orden que la tabla de arriba ya expresa mejor que una
  imagen.

## Open questions

**Ninguna abierta.** Las cuatro que este diseño planteó quedaron resueltas en su gate el
2026-08-18, y se dejan escritas con su motivo porque cada una es una decisión que no hay que volver
a derivar:

**Q1 — Igualdad o contención en el inventario declarado (D4).** → **Igualdad estricta.** R4.4 pide
literalmente *contención*, y aquí se cumple de la forma más fuerte: un servicio nuevo deja la
guardia en rojo hasta que se añada a `EXPECTED_SERVICES`, lo que fuerza a decidir su postura de
puertos en el PR que lo introduce. Coste aceptado: una línea que mantener y un rojo que explicar la
primera vez.

**Q2 — R1.5 y R1.6 quedan sin sujeto (D1).** → **Se reescriben en el proposal**, con el hallazgo
medido dentro. Un criterio que nadie puede verificar porque su sujeto no existe es exactamente la
clase de verde vacío que este change combate, y dejarlos en pie obligaría a `/sdd:review` a
certificar dos criterios inverificables.

**Q3 — La cuenta de `specs/local-environment.md:251`.** → **Sigue en nueve, y la frase de los
host-side se reformula** (de dos a tres, con el motivo propio de este target). La cuenta mide
targets que invocan `docker compose` **desde el `Makefile`** y garantiza que todos pasen por una
única definición; éste lo invoca su script desde Python, con entorno propio y deliberadamente
desnudo, que es lo contrario de lo que la cuenta garantiza. Meterlo dentro la haría medir dos cosas
distintas.

**Q4 — Cómo corre la suite de `scripts/` en CI (D12, R6.4).** → **`astral-sh/setup-uv` pinneado por
SHA + `uv run --no-project --with 'pytest==9.1.1' python -m pytest scripts/ -q`.** Es el gestor de
Python que el repositorio ya usa en CI (`api-contract.yml`, `backend-tests.yml`, misma acción y
mismo SHA), la versión queda **fijada** y alineada con el pin de `backend/pyproject.toml`
(`pytest>=9.1.1`), y `--no-project` evita sincronizar el árbol de dependencias del backend para
probar un script de la stdlib. Rechazadas: `setup-python` + `pip install` (introduce una acción y un
gestor que el repositorio no usa para Python); `unittest` de la stdlib (cero dependencias, pero se
aparta del idioma de `scripts/test_compose_stacks.py` que R6.3 manda seguir).
