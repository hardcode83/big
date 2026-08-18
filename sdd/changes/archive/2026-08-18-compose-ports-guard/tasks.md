# Tasks: compose-ports-guard

Referencias: `design.md` (D1-D12) y `proposal.md` (R1-R6). El censo de vías de elusión son
**nueve**: (a)-(h) de `sdd/roadmap/compose-ports-guard.md` más la (i) que midió D2.

Obligación de método que gobierna todo el plan (R6.3, y regla 13(c) de `steering/security.md` como
referente): **ninguna tarea de la guardia se da por hecha sin su caso en rojo**. Esta misma guardia
pasó verde cinco veces siendo eludible, así que un test que solo comprueba el verde no cierra una
tarea.

## 1. La guardia: modelo y decisión, sobre funciones puras

Esta sección no invoca a Docker: son funciones puras sobre modelos JSON escritos en el propio test,
que es lo que las hace baratas de escribir primero (`steering/testing.md`, TDD donde el invariante
es real). Al terminar la sección el script todavía no se puede ejecutar, y no pasa nada: nadie lo
invoca aún.

- [x] 1.1 Esqueleto de `scripts/compose-ports.py`: docstring de cabecera que escribe la regla de D1
      (`config` **solo** con `--no-interpolate --no-env-resolution`, con el por qué medido) y la lista
      negra heredada (`docker inspect` sin `--format`, ningún volcado de salida ajena). Constantes:
      `CONFIG_BASE`, `EXPECTED_SERVICES` (los 7 servicios), `EXEMPT` (`{("backend","8000"),
      ("frontend","3000")}`), `SAFE_NETWORK_MODES` (`{None,"bridge","none"}`), y `GuardError`.
      Sin lógica todavía. [R1.1]
- [x] 1.2 `violations(model)` con las **seis reglas de decisión en el orden de D1/Data & interfaces**
      — `scripts/compose-ports.py` + `scripts/test_compose_ports.py`. Un caso en rojo por regla, y
      entre ellos las vías del censo: **(b)** `network_mode: host` sin clave `ports`, **(c)** puerto
      extra en un servicio exento, **(i)** entrada de `ports` que es cadena y no objeto. Más: objeto
      sin `published` (R5.1, también en servicio exento), `host_ip` **ausente** y `host_ip: null` y
      `"0.0.0.0"` y `"::1"`, rango `"8000-8010"`, y el mismo puerto en un servicio no exento (R3.3).
      Los casos van enumerados en una **tupla o lista literal** para `parametrize`, nunca iterando un
      `set`/`frozenset`: el id del test tiene que ser estable entre workers (`steering/testing.md`).
      [R2.1, R2.2, R3.1, R3.2, R3.3, R5.1, R5.2, R6.3]
- [x] 1.3 `assert_inventory(model, services_listed, profiles_listed)`: las **dos igualdades** de D4 —
      servicios del JSON == `EXPECTED_SERVICES` == lo que devolvió `--services`; unión de los
      `profiles` de los servicios == lo enumerado por `--profiles`. Casos en rojo: **(a)** servicio
      bajo profile no activo que no llega al modelo, **(h)** `config` con éxito devolviendo `{}` y
      devolviendo `{"services":{}}`, un servicio nuevo no declarado en `EXPECTED_SERVICES`, uno
      renombrado, y una enumeración de profiles con pérdida (un nombre partido en dos) que el JSON
      desmiente. [R4.3, R4.4, R6.3]
- [x] 1.4 Salida: `escape()` inyectivo y `render()` con una etiqueta y un valor por línea, un bloque
      por hallazgo, orden determinista — el criterio de `compose-stacks.py`, y por su mismo motivo
      (nombres de servicio y de profile son dato ajeno al formato). El verde **nombra y cuenta** lo
      inspeccionado: servicios, mapeos y profiles. Tests: el verde dice «vio esto» y no está vacío;
      un nombre de servicio con caracteres de control no puede falsificar un bloque ni hacerse pasar
      por otro servicio. [R2.3]

## 2. La cadena: cómo se invoca a Compose

Aquí viven cuatro de las nueve vías, porque no están en la lógica sino en **cómo se construyen el
`argv` y el entorno**. Por eso se prueban con un `docker` de mentira en el `PATH` del test y no
mockeando `subprocess.run`, que probaría el mock (D12).

- [x] 2.1 `capture(command)`: `subprocess.run` con **lista de argumentos** y nunca por shell,
      `env` construido desde cero por **lista blanca** (`{"PATH": ...}`, D5), estado de salida
      comprobado **aparte** del contenido, sin `2>/dev/null` y sin pipes. En el fallo: nombra el
      paso y el código, relata **solo la primera línea de `stderr`** saneada y acotada a 200
      caracteres, y **nunca** `stdout` (R1.7). Casos en rojo con el `docker` de mentira: **(d)**
      `COMPOSE_FILE` exportado en el entorno del test no llega al hijo, **(e)** un comando que
      escribe en `stdout` y sale con código distinto de cero es rojo (no se traga el fallo),
      **(f)** el `argv` no contiene `--file` en ninguna invocación, **(g)** el `argv` lleva un
      `--profile` por nombre y ningún valor unido por comas, y **bandera desconocida** → rojo
      nombrando el paso, con la pista de la versión mínima (D6). [R1.7, R4.2, R6.1, R6.2, R6.3]
- [x] 2.2 Las tres invocaciones encadenadas y `main()`: `config --profiles` → `--profile` repetido +
      `config --services` → `--profile` repetido + `config --format json`, todas desde `CONFIG_BASE`
      y por tanto con las dos banderas de D1. Dos regímenes de salida que no se mezclan: **0** solo
      si `assert_inventory` confirma y `violations` está vacío; **distinto de cero** en cualquier
      otro caso, incluido JSON no parseable. Test de que un `GuardError` en cualquier eslabón sale
      en rojo y jamás en verde. [R1.5, R4.1, R4.3, R6.1]
- [x] 2.3 Test espejo de la lista negra sobre el **propio código** del script: en el cuerpo (docstring
      excluido) no aparece ninguna invocación de `config` que no venga de `CONFIG_BASE`, ni
      `docker inspect` sin `--format`, ni `shell=True`. Es el mecanismo que ya protege a
      `compose-stacks.py` (`test_the_command_blacklist_of_d2_has_not_been_reintroduced`, acotado a su
      propio fichero, así que no hay conflicto). [R1.7]
- [x] 2.4 Test de contrato **contra Docker de verdad**, saltado si no hay `docker` en el `PATH`: los
      4 mapeos del repositorio siguen saliendo con la forma que midió `design.md` (`published` como
      **cadena**, `host_ip` **ausente** cuando no se especifica, mapeo interpolado sin normalizar).
      Es lo que avisará el día que Compose cambie la normalización. No asierta el veredicto, asierta
      la **forma**. [R4.1]

## 3. Entrypoint y CI

- [x] 3.1 `Makefile`: target `check-compose-ports` que invoca `python3 scripts/compose-ports.py`,
      añadido a `.PHONY`, **fuera de `$(COMPOSE)`** — con el comentario que explica por qué no es un
      olvido: pasar por `$(COMPOSE)` cargaría `docker-compose.worktree.yml` en un worktree enlazado,
      la guardia vería cero claves `ports` y daría **verde en vacío** (D10). Comprobar que
      `make check-compose-ports` da el mismo veredicto en este worktree que un `docker compose`
      desnudo. [R1.1]
- [x] 3.2 `.github/workflows/compose-ports.yml`: `name: compose-ports`, **un solo job** llamado
      igual (el check run toma el nombre del job), `on: pull_request: {} / push: branches: [main] /
      workflow_dispatch: {}`, **sin `paths:`**, `concurrency` con `cancel-in-progress`,
      `permissions: contents: read`, `timeout-minutes: 10`. Pasos: `actions/checkout` pinneado por
      SHA (el mismo de `api-contract.yml`) → `astral-sh/setup-uv` pinneado por SHA →
      `make check-compose-ports` → `uv run --no-project --with 'pytest==9.1.1' python -m pytest
      scripts/ -q`. **Sin `.env`, sin secrets, sin servicios** — y eso es verificable leyendo el
      fichero, que es el punto de R1.6. Fuera de `backend/tests/` y sin tocar `backend-tests.yml`
      (R1.4). [R1.2, R1.3, R1.4, R1.6, R6.4]

## 4. Documentación y cambio normativo

La prohibición de `docker compose config` está escrita en **tres sitios a propósito**; tocar uno solo
deja el arreglo a medias, así que las tareas 4.1 y 4.2 se cierran juntas o ninguna.

- [x] 4.1 `sdd/specs/local-environment.md`, **seis** sitios — los cuatro planificados más dos que
      aparecieron al implementar, ambos afirmaciones caducadas que el diseño no había censado:
      **(5)** el criterio EARS «WHERE se inspeccione la postura con `docker compose config`, THE
      SYSTEM SHALL exigir un `.env` presente **y completo**», que D1 dejó sin sujeto; y **(6)** el
      suelo «Docker Compose ≥ 2.24», que sube a 2.35.0 por la tarea 5.5 y que además tenía copia
      propia en `README.md`. Un séptimo punto de la misma sección —«Fuera del alcance de cualquiera
      de las dos: `network_mode: host`»— dejó de ser cierto porque D8 lo cubre, y se corrige con el
      bullet que lo contiene. Los cuatro planificados: (1) §«Postura de red del stack local», el
      bullet «Esta postura no tiene comprobación automática todavía» pasa a describir la guardia;
      (2) sección propia al lado de §«Diagnóstico de stacks de Compose», que incluye por qué **no
      duplica ni contradice** la comprobación de `make up` —aquélla asierta la ausencia de `ports`
      en un stack concreto, ésta la postura del repositorio— y las limitaciones conocidas (`::1` da
      rojo; un mapeo interpolado da rojo); (3) §«Diagnóstico», la prohibición se acota **por forma**
      (sin `--no-interpolate --no-env-resolution`) y no por sujeto; (4) §«Makefile como entrypoint
      único», la frase de los **nueve** targets se reformula: los host-side pasan de dos a tres, con
      el motivo propio de éste. [R6.5, y el cambio normativo de D1]
- [x] 4.2 Los otros dos sitios de la misma prohibición, a la forma acotada: docstring de
      `scripts/compose-stacks.py` y el comentario del target `compose-stacks` en el `Makefile`.
      Verificar después que `python3 -m pytest scripts/test_compose_stacks.py` sigue verde: su test
      de lista negra lee ese docstring. [D1]
- [x] 4.3 `sdd/steering/security.md`, regla 8, párrafo de la exención de `POSTGRES_PASSWORD`: «Hoy no
      hay comprobación automática de esa postura … hasta entonces esto depende de la revisión del
      diff» pasa a citar la guardia como lo que sostiene la exención. [R1 en su conjunto]
- [x] 4.4 `README.md`, §«Postura de red del stack local»: misma afirmación caducada, misma
      corrección, y nombrar `make check-compose-ports` en la sección de comandos — el README describe
      el sistema actual (`steering/documentation.md`). Sin `.env.example` que tocar: la guardia no
      añade ninguna variable de entorno (D1). [R1.1]

## 5. Verification

- [x] 5.1 Suite de `scripts/` en verde: `python3 -m pytest scripts/` (el comando local que la spec ya
      documenta), y comprobar que los **nueve** casos del censo (a)-(i) están presentes y que cada
      uno **falla** si se neutraliza la regla que lo cubre. Un caso que pasa igual con la regla
      quitada no prueba nada.
- [x] 5.2 La guardia en verde sobre el repositorio real: `make check-compose-ports` sale con código 0
      y nombra **7 servicios, 4 mapeos, 0 profiles** — las cifras que midió el diseño.
- [x] 5.3 La guardia en **rojo de verdad**, no simulado: quitar temporalmente el prefijo `127.0.0.1:`
      del mapeo de `postgres` en `docker-compose.yml`, comprobar que sale en rojo nombrando
      `postgres` y el mapeo, y **revertir el fichero**. Repetir con un `profiles:` añadido a un
      servicio (que la aserción de profiles lo vea) y con un servicio nuevo sin declarar en
      `EXPECTED_SERVICES`. Confirmar con `git diff` que el árbol queda limpio al terminar.
- [x] 5.4 Sin `.env`: confirmar que la guardia funciona en un clon limpio —este worktree no tiene
      `.env`— y que **no aparece ningún valor del `.env`** en su salida ni en la de un fallo. Es R1.5
      y R1.6 verificados por ausencia, que es como quedaron redactados.
- [x] 5.5 Suelo de versión de Compose. **Respuesta: v2.35.0**, y por tanto posterior a 2.24, así que
      el suelo sube. `--no-env-resolution` la introdujo el PR 12665 de `docker/compose` (mergeado el
      2025-03-24, primera release **v2.35.0** el 2025-04-10); comprobado leyendo
      `cmd/compose/config.go` en las dos tags: en v2.35.0 la bandera está declarada y en v2.34.0 no.
      Corregido en `specs/local-environment.md` **y en `README.md`**, que llevaba su propia copia de
      la cifra y que ni el diseño ni esta tarea habían censado. La cifra queda además en
      `MIN_COMPOSE` del script, que es lo que se imprime en la pista del fallo por bandera
      desconocida (D6).
- [x] 5.6 Ninguna copia de la redacción caducada sobrevive en el árbol:
      `grep -rniE 'no tiene (todavía )?comprobación automática|no hay comprobación automática|solo lo atrapa la revisión del diff' --include='*.md' .`
      Los únicos aciertos aceptables están bajo `sdd/changes/archive/`, que es registro histórico y no
      se reescribe. Corregir una afirmación en un fichero y dejarla viva en otros dos es el fallo que
      esta tarea existe para evitar.
- [x] 5.7 Sin regresión en lo que ya había: `python3 -m pytest scripts/` cubre también
      `test_compose_stacks.py` y `test_check_version_parity.py` (4.2 toca el docstring que uno de
      ellos lee), y `backend-tests.yml` no se ha modificado, así que la suite del backend sigue
      hermética a `backend/**` (`specs/backend-ci.md`). No hay que levantar el stack: nada de este
      change entra en un contenedor.
- [x] 5.8 Revisión del workflow sin poder ejecutarlo en local: comprobar a mano que no lleva `paths:`,
      que el job se llama igual que el workflow, que las dos acciones van pinneadas por SHA y que no
      referencia ningún secret. El primer Pull Request del change es quien lo ejecuta de verdad — y
      es también la primera vez que un workflow de este repositorio recoge `scripts/test_*.py`, así
      que ese check hay que mirarlo en el PR y no darlo por bueno.
