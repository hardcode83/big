# Proposal: worktree-parallel-stack

## Why

Hoy `sdd/project.md` §«Worktree bootstrap» declara la regla **«un stack a la vez»**: un worktree
recién creado no puede levantar el suyo porque `docker-compose.yml` publica 5432, 6379, 8000 y 3000
en el host y el segundo `make up` choca de puertos con el principal. Y no vale reutilizar el stack
del principal, porque `backend` y `frontend` montan el código por bind-mount (`./backend:/app`), así
que sus contenedores sirven **siempre** el árbol desde el que se levantaron: un
`docker compose exec backend uv run pytest` lanzado desde el worktree contra el proyecto del
principal probaría el código del principal, no el del change. El resultado es que dos sesiones
concurrentes —el modo de trabajo que la regla 10 de las reglas compartidas y `EnterWorktree`
promueven— **no pueden correr tests a la vez**.

No es teórico y hoy está pasando: `docker compose ls` da un único proyecto,
`sddlocal-dev-network-hardening`, levantado desde
`.claude/worktrees/sdd+local-dev-network-hardening`, con
`0.0.0.0:3000`, `0.0.0.0:8000`, `127.0.0.1:5432` y `127.0.0.1:6379` tomados — y ese worktree **ya no
existe** (`git worktree list` solo lista el principal). Es decir: el stack sobrevivió a su worktree y
retiene los cuatro puertos sin que nada lo señale.

La hipótesis de partida es que **los tests no necesitan puertos publicados**, porque corren dentro de
la red del stack. Medido en este análisis, se sostiene (ver §«Lo que ya está medido»). Compose ya
aísla contenedores, red y volúmenes por nombre de proyecto —que sale del nombre del directorio, y el
del worktree es distinto—, así que lo único que colisionaba era el bind al host.

**No toca producción**: el CD usa `-f docker-compose.deploy.yml` y nunca el compose base
(`.github/workflows/deploy-dev.yml:207-210`).

## What changes

Después de este change, un worktree secundario levanta su stack completo y corre la suite **sin
publicar puertos en el host**, en paralelo con el stack del worktree principal, que conserva
exactamente la postura de red de hoy. La publicación de puertos deja de estar en el camino común: la
lleva un fichero de compose propio, versionado, que `make up` incluye **solo** en el worktree
principal, detectado por git y sin variables que nadie tenga que cuadrar a mano. La regla «un stack a
la vez» de `sdd/project.md` se sustituye por la operativa real, conservando el aviso de coste (base de
datos vacía, reinstalación de dependencias y gigas de volúmenes por worktree). La postura de red
sigue siendo **verificable** por la guardia que `compose-ports-guard` construirá: este change no
puede dejar los mapeos fuera de su vista.

## Lo que ya está medido (entrada para `/sdd:design`, no volver a derivarlo)

1. **Los tests no dialan ningún puerto publicado.** Barrido de `backend/tests/` y `frontend/` en
   busca de `localhost:{8000,3000,5432,6379}`: **un solo** resultado,
   `backend/tests/integrations/test_beds24_probe.py:97`, que es una URL *lookalike* dentro de un test
   de allowlist de host que afirma `SystemExit` — nunca se conecta. La suite del backend habla con
   `postgres:5432`/`redis:6379` por la red de compose (`environment:` de `docker-compose.yml`).
2. **CI no usa el compose base**: `.github/workflows/backend-tests.yml` levanta *service containers*
   de Actions y apunta a `localhost:5432`/`localhost:6379` (líneas 226-252). Inmune a este change.
3. **CD tampoco**: `deploy-dev.yml` solo pasa `-f docker-compose.deploy.yml`.
4. **Censo de consumidores: tres de los cuatro sospechosos son falsos positivos.**
   - `infra/environments/dev/RUNBOOK.md` §7.4 es depuración de la **VM remota** por túnel SSH contra
     `docker-compose.deploy.yml`; no menciona el compose base.
   - `frontend/README.md:8` documenta `npm run dev` en el host (`http://localhost:3000`), que no pasa
     por compose.
   - `test_beds24_probe.py:97`, ya explicado.
   - **Real, y único**: `backend/app/core/config.py:96-100` cae a `localhost:5432` cuando
     `DATABASE_URL` no viene fijada, para la suite ejecutada en el host. En el worktree principal ese
     camino sigue existiendo; en un worktree secundario no, y ya era inviable allí porque `uv` no está
     instalado en el host (`sdd/project.md:21`).
5. **Un override *sí* puede quitar puertos.** Corrección a la premisa: no es cierto que Compose solo
   concatene arrays. `ports: !reset []` en un fichero de override **elimina** el mapeo — medido con
   Compose v5.1.1: `docker compose -f base.yml -f noports.yml config --format json` deja el servicio
   sin clave `ports`. Esto no cambia el *qué* (un worktree secundario no publica), pero abre una
   segunda vía para el *cómo* que `/sdd:design` debe comparar, y que importa por el punto 7.
6. **La detección de worktree por git funciona, con un matiz.** En un worktree enlazado
   `git rev-parse --git-dir` da `<repo>/.git/worktrees/<nombre>` y `--git-common-dir` da
   `<repo>/.git`; en el principal ambos dan `.git`. La comparación de los dos es exacta; el matiz es
   que en el principal salen **relativos** y en el worktree **absolutos**, así que compararlos
   requiere normalizar. Buscar la subcadena `/worktrees/` funciona pero es más frágil.
7. **Colisión de diseño con `compose-ports-guard`** (abierta, en la frontera). Sus decisiones
   heredadas exigen que el resultado de la guardia sea «función **solo** del repositorio, no del
   entorno» (criterio 2) y que el descubrimiento de ficheros se **delegue** a Compose sin `--file`; su
   censo de vías de elusión ya incluye *(d) un `COMPOSE_FILE` exportado desvía la comprobación* y
   *(f) fijar los ficheros con `--file` desactiva la carga automática del override*. Un fichero de
   puertos seleccionado por `.env` (no versionado) o por `COMPOSE_FILE` haría que la guardia mirase un
   conjunto de ficheros **sin** mapeos y pasase en vacío. R3 existe por esto.
8. **La regla 8 de `steering/security.md` está anclada al fichero por su nombre**: la exención de la
   contraseña de dev en `.env.example` se sostiene explícitamente en que *«`docker-compose.yml`
   publica `postgres` y `redis` solo en `127.0.0.1`»*. Si los mapeos cambian de fichero, esa frase
   queda obsoleta y hay que rehacerla, no seguir citándola (lo dice la propia regla).

## Requirements

### R1 — Dos stacks a la vez, con tests

**Como** desarrollador con una sesión en el worktree principal y otra en un worktree de feature,
**quiero** levantar el stack de ambos, **para** correr la suite de cada uno sin apagar el del otro.

Criterios de aceptación:

1. WHILE el worktree principal tiene su stack levantado, WHEN se ejecuta `make up` en un worktree
   secundario, THE SYSTEM SHALL arrancar todos sus servicios sin fallar por puerto ocupado.
2. WHEN se ejecuta `docker compose exec backend uv run pytest` en el worktree secundario con el stack
   del principal también levantado, THE SYSTEM SHALL correr la suite contra el Postgres y el Redis
   **de su propio proyecto de compose** y terminar con el mismo resultado que tendría en solitario.
3. WHILE los dos stacks están levantados, THE SYSTEM SHALL mantener sus datos separados: la base de
   datos de un proyecto no es visible desde el otro (volúmenes y red por proyecto).
4. IF el árbol de trabajo es un worktree secundario, THEN THE SYSTEM SHALL no publicar **ningún**
   puerto en el host para ese stack, verificable con `docker compose config` desde ese directorio.

### R2 — El worktree principal conserva la postura de red de hoy, sin cambios observables

**Como** responsable de la postura de red del stack local, **quiero** que el principal siga
publicando exactamente lo que publica hoy, **para** que este change no relaje ni endurezca por
accidente lo que `local-dev-network-hardening` estableció.

Criterios de aceptación:

1. WHEN se ejecuta `make up` en el worktree principal, THE SYSTEM SHALL publicar `postgres` y `redis`
   **únicamente** en `127.0.0.1` (`127.0.0.1:5432:5432`, `127.0.0.1:6379:6379`).
2. WHEN se ejecuta `make up` en el worktree principal, THE SYSTEM SHALL publicar `backend:8000` y
   `frontend:3000` en **todas** las interfaces, que es deliberado (mobile-first: la app se abre desde
   un móvil real por la IP de LAN).
3. WHEN se inspecciona el stack del principal con `docker compose config --format json`, THE SYSTEM
   SHALL dar los cuatro mapeos con el mismo `host_ip` y `published` que antes de este change.
4. `worker`, `beat` y `migrate` SHALL seguir sin publicar ningún puerto, en cualquier worktree.

### R3 — La postura sigue siendo verificable por una guardia futura

**Como** autor de `compose-ports-guard`, **quiero** que los mapeos vivan donde una comprobación
reproducible pueda verlos, **para** que la guardia no pase en vacío sobre un stack que sí publica.

Criterios de aceptación:

1. THE SYSTEM SHALL declarar los mapeos de puertos en un fichero **versionado en git**; ningún mapeo
   depende de un fichero ignorado (`.env*`) ni de una variable de entorno del operador.
2. WHERE la comprobación de la postura se ejecuta sobre el repositorio recién clonado (sin `.env`
   local, sin variables exportadas), THE SYSTEM SHALL permitir determinar el conjunto de ficheros de
   compose que reproduce lo que `make up` levanta en el worktree principal.
3. THE SYSTEM SHALL dejar escrito en `sdd/specs/local-environment.md` **cuál** es ese conjunto de
   ficheros y por qué, de forma que `compose-ports-guard` lo herede en vez de volver a derivarlo.
4. IF el mecanismo elegido saca los mapeos de `docker-compose.yml`, THEN THE SYSTEM SHALL rehacer la
   justificación de la exención de la regla 8 de `sdd/steering/security.md`, que hoy cita ese fichero
   por su nombre, y la de `README.md` §«Postura de red del stack local».
5. THE SYSTEM SHALL no introducir un `docker-compose.override.yml` no versionado como portador de los
   mapeos — es la vía de elusión (f) del censo de `compose-ports-guard`.

### R4 — Detección automática, sin configuración manual

**Como** desarrollador que acaba de crear un worktree, **quiero** que `make up` sepa por sí solo si
publica o no, **para** que el bootstrap siga siendo «cero pasos manuales».

Criterios de aceptación:

1. WHEN se ejecuta cualquier target del `Makefile` que hable con compose, THE SYSTEM SHALL determinar
   por sí mismo, consultando git, si el directorio es el worktree principal o uno enlazado, sin que
   el desarrollador edite ficheros ni exporte variables.
2. THE SYSTEM SHALL imprimir en qué modo arranca (publicando puertos / sin publicar), para que un
   stack sin UI alcanzable sea diagnosticable en un segundo.
3. IF git no está disponible o el directorio no es un repositorio, THEN THE SYSTEM SHALL comportarse
   como el worktree principal (publicar) y decirlo: una colisión de puertos falla de forma ruidosa y
   diagnosticable, mientras que no publicar en silencio se lee como una app rota.
4. THE SYSTEM SHALL aplicar la misma detección a todos los targets que operen sobre el stack
   (`up`, `down`, `logs`, `ps`, `sh`, `bootstrap`, `openapi`, `db-clean-test`), para que ninguno
   opere sobre un conjunto de ficheros distinto del que levantó el stack.

### R5 — RETIRADO de este change (2026-08-05, decisión del usuario en `/sdd:review`)

Este requisito pedía un diagnóstico de stacks vivos y huérfanos (`make stacks`). Se **implementó, se
revisó cinco rondas y se retiró**: acumuló ~18 hallazgos con referente —entre ellos una inyección de
comandos real y una suplantación sin metacaracteres— y **tres veces un arreglo introdujo el siguiente**.

El diagnóstico estructural, que es lo que justifica sacarlo y no seguir iterando: el target tiene que
atribuir stacks a partir de **etiquetas de contenedor**, que cualquier contenedor de la máquina puede
poner y que pueden contener cualquier byte —`|`, saltos de línea, controles C1 en UTF-8—, y hacerlo en
shell dentro de un `Makefile`, imprimiendo una tabla. Esa combinación no tiene primitiva segura: cada
ronda reinventaba el tratamiento de delimitadores y reabría la misma clase.

Pasa a la entrada de roadmap **`compose-stacks-diagnostic`**, que hereda el censo completo de vías de
ataque ya demostradas. Nada de lo que este change entrega depende de él: R5 salió de un hallazgo de la
fase `new`, no del enunciado, y lo que desbloquea las sesiones concurrentes son R1-R4.

**Lo que sí queda aquí**, porque es la mitad del valor y no cuesta nada: `sdd/project.md` y `README.md`
dicen que hay que hacer `make down` **antes** de borrar un worktree, y por qué el descuido es fácil
(`git worktree remove` falla si Docker dejó ficheros suyos, así que el caso normal es «worktree
desregistrado, directorio en pie»), y apuntan a `docker compose ls` como diagnóstico de andar por casa.

### R6 — La documentación deja de decir «un stack a la vez»

**Como** cualquiera que abra un worktree mañana, **quiero** leer la operativa real, **para** no
apagar el stack del principal por una regla que ya no aplica.

Criterios de aceptación:

1. THE SYSTEM SHALL reescribir `sdd/project.md` §«Worktree bootstrap» con la operativa nueva,
   eliminando la regla «un stack a la vez» y su secuencia de `make down`/`make up` alternos.
2. THE SYSTEM SHALL conservar en esa sección el coste, que no desaparece: los volúmenes con nombre van
   por proyecto de compose, así que cada worktree arranca con **base de datos vacía**, reinstala
   dependencias la primera vez (lento, no roto), necesita `make bootstrap` para sembrar, y ocupa
   gigas de disco propios.
3. THE SYSTEM SHALL decir explícitamente que en un worktree secundario **no hay UI ni API alcanzables
   desde el navegador del host**, y cuál es la salida si algún día hace falta (ver *Out of scope*).
4. THE SYSTEM SHALL actualizar `sdd/specs/local-environment.md` (§«Postura de red del stack local» y
   §«Makefile como entrypoint único») y `README.md` §«Postura de red del stack local» para que
   describan lo que el compose implementa de verdad — el precedente de la regla 8 es exactamente el
   de una justificación que describía una postura que el compose no implementaba.

## Out of scope

- **Navegar la app desde un worktree secundario** (`make up PORT_OFFSET=10` con los cuatro puertos
  parametrizados). Se añade cuando haga falta, no antes: hoy solo hay un navegador, publicar es cosa
  del principal, y parametrizar obliga a inventar puertos libres y a cuadrar variables que la opción
  «no publicar» no necesita. R6.3 obliga a dejar la salida escrita.
- **Compartir el Postgres y el Redis del principal entre worktrees.** Es la opción más barata en
  disco y en tiempo de arranque, y `backend/tests/db_names.py` (una base por ejecución,
  `<db>_test_<pid>`) ya puso los cimientos sin saberlo. Se descarta **de entrada**, no por coste:
  acopla los worktrees —un `make down` en el principal tumba los tests de todos— y encima el bind a
  loopback que `local-dev-network-hardening` estableció impide alcanzar ese Postgres desde un
  contenedor de otro proyecto por `host.docker.internal`, así que exigiría además una red externa de
  compose compartida. Queda escrita como alternativa viable para quien la retome.
- **La guardia automática de la postura de red**: es `compose-ports-guard`. Este change le fija la
  entrada (R3.3) y no la construye.
- **`docker-compose.deploy.yml`, el CD y la VM dev**: no se tocan (medido: `deploy-dev.yml` nunca
  pasa el compose base).
- **Reducir el coste en disco** de tener volúmenes por worktree, y cualquier forma de compartir
  cachés de dependencias entre proyectos de compose.
- **Hacer viable `pytest` en el host desde un worktree**: ya no lo era (`uv` no está en el host).
- **Parar o limpiar stacks huérfanos automáticamente**, y ahora también **diagnosticarlos**: ver R5,
  retirado a `compose-stacks-diagnostic`.

## Affected specs

- `sdd/specs/local-environment.md` — §«Postura de red del stack local» (qué fichero declara los
  mapeos y cuál es el conjunto de ficheros canónico) y §«Makefile como entrypoint único» (la
  detección de worktree y el modo que imprime).
- `sdd/specs/domain-foundation-core.md` — su línea 39 describe la resolución de `DATABASE_URL` y el
  fallback a `localhost:5432`; **verificar**, probablemente sin cambio, porque el bloque
  `environment:` no se mueve y el fallback sigue vivo en el principal.
- `sdd/specs/backend-ci.md` — **verificar**, se espera sin cambio: la suite de CI usa *service
  containers*, no el compose.
- No son specs pero cambian con este change y R6.4/R3.4 los cubren: `sdd/project.md`
  §«Worktree bootstrap», `sdd/steering/security.md` regla 8, `README.md` §«Postura de red del stack
  local».
