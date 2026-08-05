# Tasks: worktree-parallel-stack

Mecanismo fijado en `design.md` D1 (`ports: !reset []` en un overlay que solo se incluye en worktrees
enlazados). Nada de esto toca Python ni TypeScript, así que **no hay tareas de test de la suite**: la
aserción es `docker compose config --format json`, y D8 explica por qué. Dos notas de método antes de
empezar:

- **`sdd/specs/local-environment.md` NO se toca aquí.** Por convención del proyecto las specs se
  mantienen **al archivar** (`steering/documentation.md`, cabecera). R3.3 se cumple entonces; su
  equivalente ejecutable en este change son el `README.md` y `sdd/project.md` (tareas 3.1-3.3).
- **Antes de la tarea 1.1**, guardar la salida de referencia contra la que se compara R2:
  `docker compose config --format json > /tmp/ports-antes.json` en el worktree principal. Sin ese
  «antes» la tarea 4.1 no puede demostrar «sin cambios observables», solo afirmarlo.

## 1. Overlay y detección — el núcleo del change <!-- panel: PASS 2026-08-05 -->
<!-- Panel: sdd-architect PASS · sdd-security PASS · sdd-qa PASS · sdd-review-cicd PASS ·
     sdd-review-documentation FAIL→PASS (3 hallazgos: 2 aceptados, que crearon las tareas 3.2.1 y
     3.2.2; 1 rechazado y retirado por el propio reviewer — marcar un suelo de versión medido como
     ASSUMPTION diluye un marcador cuyo valor es señalar incertidumbre real).
     Reviewers no lanzados: sdd-review-i18n y sdd-review-tenancy — el diff no tiene strings de UI ni
     queries. Defecto encontrado y corregido durante la sección: el preflight era
     `config | grep -q`, y en un pipe el estado de salida es el del último comando, así que un
     `config` que fallara pasaba en verde (vía de elusión (e) del censo de compose-ports-guard). -->


- [x] 1.1 Crear `docker-compose.worktree.yml` (nuevo, **versionado**) con `ports: !reset []` para `postgres`, `redis`, `backend` y `frontend`, y un comentario de cabecera que diga qué hace, por qué existe, que el principal **no** lo usa y que el CD tampoco (usa `docker-compose.deploy.yml`). Hecho = `docker compose -f docker-compose.yml -f docker-compose.worktree.yml config --format json` no devuelve **ningún** servicio con clave `ports`, y `docker compose -f docker-compose.yml config --format json` sigue devolviendo los cuatro mapeos con sus `host_ip` originales (`127.0.0.1` en los datastores, `null` en `backend`/`frontend`). [R1, R2, R3]
- [x] 1.2 Añadir la detección al `Makefile`: `IS_WORKTREE` por desigualdad de `git rev-parse --path-format=absolute --git-dir` frente a `--git-common-dir`, comparada **en shell** (no con `$(filter)`, que parte por espacios), más `COMPOSE_ARGS` y `COMPOSE := docker compose $(COMPOSE_ARGS)` con `:=`. Hecho = en el principal `COMPOSE_ARGS` queda vacía; en un worktree enlazado lleva los dos `-f`; con `git` inalcanzable queda vacía (fail-open, D3). [R4.1, R4.3]
- [x] 1.3 Cablear los **ocho** targets que hablan con Compose a `$(COMPOSE)`: `up`, `down`, `logs`, `ps`, `sh`, `bootstrap`, `openapi`, `db-clean-test` (este último tiene **dos** invocaciones `docker compose exec`, ojo a no dejar una suelta). Hecho = `grep -c 'docker compose' Makefile` solo encuentra ocurrencias dentro de la definición de `$(COMPOSE)`. [R4.4]
- [x] 1.4 `make up` anuncia el modo en el que arranca (publicando puertos / sin publicar, y en el segundo caso que la UI no será alcanzable desde el host). Hecho = una línea legible en la salida de `make up` en cada uno de los dos modos. [R4.2]
- [x] 1.5 Preflight en modo worktree dentro de `up`: `$(COMPOSE) config --format json` y abortar si queda **algún mapeo de puertos** en la configuración resuelta, con mensaje que nombre el problema (servicio con puerto no cubierto por el overlay, o un Compose < 2.24 que ignoró `!reset`). Hecho = el arranque en worktree aborta si se añade a mano un `ports:` a un servicio, y no aborta en el caso normal. **Corregido en la revisión a escala de feature**: la primera versión buscaba la clave `"published"`, y hay dos formas legales de `ports:` que no la producen y que Docker publica en un puerto efímero en todas las interfaces — pasaban en verde. Ahora se comprueba la ausencia de la clave `ports` (medido: 4 con el base, 0 con el overlay). [R1.4, R3.1]
- [x] 1.6 Guarda de overlay ausente: en modo worktree, si `docker-compose.worktree.yml` no existe, abortar con mensaje propio («este worktree está en una rama anterior a `worktree-parallel-stack`: rebasa, o levanta el stack desde el principal»), no con el error de fichero no encontrado de Compose. Hecho = renombrar temporalmente el overlay reproduce el mensaje propio. [R1.1]
- [x] 1.7 Nota en `docker-compose.yml` junto a los mapeos de `postgres`/`redis` y de `backend`/`frontend`, apuntando al overlay, para que quien lea los `ports:` sepa que un worktree los retira. **Sin cambios funcionales en el fichero.** Hecho = el `config --format json` del principal es byte-idéntico al «antes» guardado en el preámbulo. [R2.1, R2.2, R2.3]

## 2. Diagnóstico de stacks vivos — SECCIÓN RETIRADA

Se implementó (`make stacks`), pasó cinco rondas de panel, acumuló ~18 hallazgos con referente y se
**retiró en `/sdd:review` por decisión del usuario**. Motivo estructural en `design.md` D6 y en R5 del
proposal; pasa a la entrada de roadmap `compose-stacks-diagnostic`. Con el target fuera desaparecen
también las variables que solo existían para él (`REPO_ROOT`, `AHAI_REPO_ROOT`, `AHAI_INVOKED_FROM`) y
con ellas toda la superficie de la inyección de comandos que el panel encontró.

- [x] 2.1 ~~Target `stacks`~~ — implementado y **retirado**; el `Makefile` ya no lo contiene. [R5, retirado]
- [x] 2.2 ~~`make up` sugiere `make stacks` al fallar~~ — implementado y **retirado** con él. [R5, retirado]

## 3. Documentación

- [x] 3.1 Reescribir `sdd/project.md` §«Worktree bootstrap»: fuera la regla «un stack a la vez» y su secuencia de `make down`/`make up` alternos; dentro la operativa real. **Conservar** los tres avisos de coste que no desaparecen (base de datos vacía por proyecto de compose, reinstalación de dependencias la primera vez, gigas de volúmenes propios) y `make bootstrap` para sembrar. Añadir explícito que en un worktree **no hay UI ni API en el navegador del host**, con `PORT_OFFSET` nombrado como la salida futura si hace falta. [R6.1, R6.2, R6.3]
- [x] 3.2 `README.md`: actualizar §«Arrancar en local» (la lista de URLs de las líneas 18-21 —backend, frontend, Postgres, Redis— vale en el principal, no en un worktree) y §«Postura de red del stack local», Exigido además por `steering/documentation.md` línea 17 (secciones Estructura/Arrancar/Tests al día). **Nota tras retirar R5**: el `make stacks` que esta tarea añadió al bloque de comandos se quitó con el target; en su lugar el README apunta a `docker compose ls` y a la entrada `compose-stacks-diagnostic`. [R6.4]
- [x] 3.2.1 `README.md` §«Estructura» (líneas 137-138): añadir `docker-compose.worktree.yml` junto a la entrada de `docker-compose.yml`/`Makefile`, que hoy se nombran uno a uno. Hallazgo del panel de documentación de la sección 1, referente `steering/documentation.md` línea 17. [R6.4]
- [x] 3.2.2 `README.md` línea 7 (§«Arrancar en local», requisitos): hoy dice «Docker + Docker Compose v2, `make`» y eso ya no basta — este change fija **Compose ≥ 2.24** (por el tag `!reset`) y **git ≥ 2.31** (por `--path-format=absolute`). Decir ambos suelos. Importa el de git: por debajo, la detección falla abierta hacia «publicar», así que un worktree chocaría de puertos en vez de arrancar sin ellos. Hallazgo del panel de documentación de la sección 1, referente `steering/documentation.md` línea 16. [R6.4, R4.3]
- [x] 3.3 `README.md` §«Tests»: corregir la **deriva preexistente** —hoy dice `cd backend && uv run pytest`, y `sdd/project.md:21` establece que `uv` no está instalado en el host y que la suite corre en Docker (`docker compose exec backend uv run pytest`)—, y añadir que en un worktree la suite corre igual porque va por la red de compose y no por puertos publicados. No es alcance inventado: es la sección que `documentation.md` línea 17 obliga a repasar y describe justo el camino que este change reencuadra. [R6.4, R1.2]
- [x] 3.4 Verificar documentalmente, y dejar constancia en el mensaje de commit, que **no** hacen falta cambios en: `sdd/steering/security.md` regla 8 (su frase sigue describiendo lo que el compose implementa — es el criterio que D1 optimiza), `.env.example` (cero variables nuevas), `docs/<capability>.md` (esto es herramienta de desarrollo, no capability operativa de las que enumera `documentation.md` línea 18), `docs/diagrams/` (no cambia arquitectura ni modelo de datos) y `backend/openapi.json` (no se toca la API). Hecho = las cinco comprobaciones hechas y ninguna edición en esos ficheros. [R3.4]

## 4. Verificación

Todos los comandos de suite salen de `sdd/project.md` §Commands. La secuencia empieza bajando el
stack huérfano, que hoy retiene los cuatro puertos y es una acción del desarrollador, no del
`Makefile` (era R5, retirado).

- [x] 4.1 **Postura del principal intacta**: `docker compose config --format json` en el principal, comparado con `/tmp/ports-antes.json` del preámbulo → idénticos, cuatro mapeos, `127.0.0.1` en los datastores y `null` en `backend`/`frontend`. [R2.1, R2.2, R2.3]
- [x] 4.2 **Dos stacks a la vez**: `docker compose -p sddlocal-dev-network-hardening down` para liberar los puertos del huérfano → `make up` en el principal → crear un worktree de prueba (`git worktree add`) → `make up` allí → los dos proyectos aparecen `running` en `docker compose ls` simultáneamente, sin error de puerto. [R1.1]
- [x] 4.3 **La suite pasa en el worktree con los dos stacks arriba**: `docker compose exec backend uv run pytest` desde el worktree. Mismo resultado que en solitario. **Evidencia registrada aquí a propósito** (el panel de QA señaló, con razón, que era una afirmación irreproducible y sin rastro en el repositorio): ejecutado el **2026-08-05** desde `.claude/worktrees/probe-run` con el stack del principal levantado y publicando los cuatro puertos, y el del worktree sin publicar ninguno → **`3093 passed, 35 skipped in 236.50s`** (3m56s, por debajo de los 6m15s que cita la entrada `backend-suite-runtime`). No queda log persistido: la reproducción exige levantar los dos stacks otra vez, y al terminar la verificación se bajaron. [R1.2]
- [x] 4.4 **Aislamiento de datos**: con los dos stacks arriba, comprobar que la base de datos de un proyecto no es visible desde el otro (volúmenes y red por proyecto) — p. ej. `make bootstrap` en uno y verificar que el otro sigue sin esos usuarios. [R1.3]
- [x] 4.5 **Cero puertos publicados en el worktree**: `docker compose config --format json` desde el worktree **sin ninguna clave `ports`** (criterio endurecido en la revisión a escala de feature; antes se comprobaba `"published"`, que dos formas legales de mapeo no producen), y `docker ps --format '{{.Names}}\t{{.Ports}}'` sin ningún mapeo de host para los contenedores de ese proyecto (`worker`, `beat` y `migrate` sin puertos en **ambos** modos). [R1.4, R2.4]
- [x] 4.6 **Fail-open comprobado**: invocar `make up` con `git` inalcanzable (p. ej. `PATH` recortado) desde el principal → arranca en modo «publicando» y lo dice, no aborta. [R4.3]
- [x] 4.7 ~~**`make stacks` con un huérfano de verdad**~~ (verificación **retirada** con R5; el hallazgo que produjo —que `git worktree remove --force` FALLA por los ficheros de Docker y deja el worktree desregistrado con su directorio en pie— se conserva en `sdd/project.md` y en design.md D6, porque es el motivo por el que hay que hacer `make down` antes de borrar un worktree) **[original]**: levantar el stack del worktree de prueba, borrar el worktree con `git worktree remove --force`, y comprobar que `make stacks` sigue listándolo y lo marca como huérfano sin fallar por el directorio ausente. [R5, retirado]
- [x] 4.8 **Limpieza**: `make down` en los dos stacks, `git worktree remove` del worktree de prueba, `git worktree list` de vuelta a solo el principal, y `docker compose ls` sin proyectos huérfanos de la verificación.

## Cobertura de requisitos

| Req | Tareas |
|---|---|
| R1 — dos stacks con tests | 1.1, 1.5, 1.6, 3.3, 4.2, 4.3, 4.4, 4.5 |
| R2 — el principal no cambia | 1.1, 1.7, 4.1, 4.5 |
| R3 — postura verificable | 1.1, 1.5, 3.4 (+ spec al archivar, ver preámbulo) |
| R4 — detección automática | 1.2, 1.3, 1.4, 4.6 |
| ~~R5 — diagnóstico de huérfanos~~ | **RETIRADO** en `/sdd:review` → entrada `compose-stacks-diagnostic` |
| R6 — documentación | 3.1, 3.2, 3.3 |
