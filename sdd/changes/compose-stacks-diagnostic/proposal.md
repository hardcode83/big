# Proposal: compose-stacks-diagnostic

## Why

Cada worktree levanta ahora su propio stack (`worktree-parallel-stack`, 2026-08-05), y borrar un worktree sin bajarlo deja los contenedores y **volúmenes** vivos sin que nada lo explique. Medido el 2026-08-17: `docker system df` da 7,66 GB de volúmenes locales con 5,15 GB reclaimable (67 %) y 4,69 GB de imágenes reclaimable. El caso habitual no es «directorio borrado» sino **«worktree desregistrado con el directorio en pie»**, porque `git worktree remove --force` falla con `Permission denied` sobre los ficheros que Docker creó por bind-mount.

Lo que hace esto necesario **ahora y no antes** es que el síntoma dejó de avisar. Antes un stack huérfano retenía los puertos del host y te enterabas solo: `make up` fallaba nombrando el puerto. Desde `worktree-parallel-stack` un worktree enlazado **no publica ninguno** (`ports: !reset []`), verificado con dos stacks vivos donde `docker ps` da `5432/tcp` y `3000/tcp` sin prefijo de host. El coste pasó de bloqueante a silencioso, y con un stack por worktree crece más rápido que antes.

Esta entrada se **reencuadró a la baja** el 2026-08-17 por esa misma razón: la mitad de «quién retiene cada puerto» ya no tiene problema que resolver. El análisis completo, el censo de hallazgos que sigue vinculante y la frontera con el `sdd-toolkit` están en `sdd/roadmap/compose-stacks-diagnostic.md` — **leerla antes de `/sdd:design`**.

## What changes

Después de este change existe un comando que, ejecutado desde cualquier worktree del repositorio, lista los proyectos de Compose vivos en la máquina y marca cuáles son **huérfanos**: aquellos cuyo fichero de origen apunta a un worktree que ya no está registrado en git. Cruza `docker compose ls --format json` contra `git worktree list`, ruta contra ruta, **sin leer etiquetas de contenedor y sin imprimir ningún comando de derribo**. Informa; no actúa. Va como script con parser de verdad en `scripts/`, con su test al lado, siguiendo el patrón ya establecido por `check-version-parity.py` — no como shell dentro del `Makefile`, que es la forma que hizo fracasar el intento de 2026-08-05. Además corrige los cinco sitios del árbol que siguen prometiendo o afirmando la retención de puertos.

## Requirements

### R1 — Inventario de stacks vivos con su procedencia

**As a** desarrollador con varios worktrees, **I want** ver de un solo comando qué stacks de Compose hay vivos y desde qué directorio se levantaron, **so that** pueda decidir qué recuperar sin inspeccionar contenedores a mano.

Acceptance criteria:

1. WHEN se invoca el diagnóstico, THE SYSTEM SHALL listar cada proyecto de Compose vivo en la máquina con su nombre, su estado y la ruta del directorio desde el que se levantó, obtenidos de `docker compose ls --format json`.
2. THE SYSTEM SHALL consultar el ámbito de **toda la máquina** y no el del proyecto actual — es decir, sin la definición `COMPOSE`/`COMPOSE_ARGS` del `Makefile`, que está acotada a los ficheros de este directorio y por diseño no ve los stacks ajenos.
3. IF `docker` no está disponible o el demonio no responde, THEN THE SYSTEM SHALL salir con un mensaje que lo diga y un código de salida distinto de cero, sin presentar un inventario vacío como si no hubiera stacks.
4. WHEN el JSON de `docker compose ls` no se puede parsear o no tiene la forma esperada, THE SYSTEM SHALL abortar nombrando el problema en vez de degradar el resultado a «ningún stack».

### R2 — Marca de huérfano derivada de git, no de la existencia en disco

**As a** desarrollador, **I want** que el diagnóstico distinga un stack cuyo worktree sigue vivo de uno cuyo worktree ya no existe, **so that** sepa cuál puedo bajar sin romperle el trabajo a nadie.

Acceptance criteria:

1. WHEN un proyecto vivo tiene su directorio de origen dentro de un worktree **registrado** en `git worktree list`, THE SYSTEM SHALL clasificarlo como vivo y atribuirlo a ese worktree.
2. WHEN un proyecto vivo tiene su directorio de origen bajo el árbol del repositorio pero ese worktree **no** está registrado en `git worktree list`, THE SYSTEM SHALL clasificarlo como **huérfano** — incluso si el directorio existe todavía en disco, que es el caso habitual porque `git worktree remove --force` falla sobre los ficheros de bind-mount.
3. WHERE el directorio de origen de un proyecto queda **fuera** del árbol de este repositorio, THE SYSTEM SHALL clasificarlo como **ajeno** y no como huérfano, nunca proponiendo nada sobre él.
4. IF un proyecto vivo no tiene ruta de origen resoluble, THEN THE SYSTEM SHALL clasificarlo como **indeterminado** y no como huérfano — la ausencia de dato no es evidencia de abandono (hallazgo (j) de la nota: `[ ! -d "" ]` es cierto y marcaba huérfanos falsos).
5. THE SYSTEM SHALL comparar rutas **normalizadas en términos absolutos** antes de decidir la pertenencia al árbol, de forma que un enlace simbólico o un `..` no cambien el veredicto.
6. WHEN la comparación de pertenencia se hace contra la raíz del repositorio, THE SYSTEM SHALL fallar en voz alta si esa raíz sale vacía, en vez de tratar el patrón como coincidencia universal (hallazgo (b): un `REPO_ROOT` vacío convertía el patrón en `/*` y marcaba de huérfano cualquier stack de la máquina).

### R3 — Informa, no actúa, y no filtra secretos

**As a** desarrollador, **I want** que el diagnóstico sea inerte y no me invite a pegar comandos, **so that** leerlo no pueda dañar nada ni exponer credenciales.

Acceptance criteria:

1. THE SYSTEM SHALL limitarse a informar: no ejecuta `down`, `rm`, `prune` ni ninguna operación destructiva, y **no imprime ningún comando de derribo con datos interpolados** que se invite a copiar y pegar. El precedente del árbol es explícito: `specs/seed-data-demo.md:492` enumera los objetos huérfanos y no los borra, y `specs/backend-ci.md:130` advierte de que `make db-clean-test` no distingue una base huérfana de una viva.
2. THE SYSTEM SHALL obtener únicamente los campos que necesita, y NUNCA invocar `docker inspect` sin `--format` ni `docker compose config`, porque la salida por defecto del primero incluye `.Config.Env` y el segundo **resuelve e imprime los valores del `.env`** — medido sobre el stack vivo con `JWT_SECRET_KEY`, `POSTGRES_PASSWORD` y `ENCRYPTION_KEY` presentes.
3. WHERE el diagnóstico imprima un nombre de proyecto o una ruta procedente de Docker, THE SYSTEM SHALL clasificar con el valor **crudo** y sanear **solo para pantalla** mediante **lista blanca** de caracteres imprimibles, nunca con un filtro no inyectivo tipo `tr -cd` (hallazgo (e): mapea `autohostai!` → `autohostai` y hace que un contenedor hostil muestre el nombre real del desarrollador).
4. THE SYSTEM SHALL tratar cada campo por separado y no construir ni parsear líneas con delimitadores compuestos — el `ConfigFiles` de `docker compose ls` llega como lista separada por comas y una ruta puede contener una coma.
5. WHEN el diagnóstico termina, THE SYSTEM SHALL salir con código cero tanto si hay huérfanos como si no: es un informe, no una guardia de CI.

### R4 — Corregir la afirmación caducada sobre retención de puertos

**As a** lector de la documentación, **I want** que ningún documento siga diciendo que un stack huérfano retiene puertos, **so that** no diagnostique el problema equivocado.

Acceptance criteria:

1. WHEN este change se archive, THE SYSTEM SHALL haber corregido los **cinco** sitios que arrastran la afirmación caducada: `sdd/roadmap.md:50` y `sdd/roadmap/compose-stacks-diagnostic.md` (hechos en el reencuadre), más `sdd/project.md:78`, `sdd/specs/local-environment.md:141` y `README.md:93-95`.
2. THE SYSTEM SHALL sustituir la afirmación por la real: un worktree enlazado no publica puertos, así que un stack huérfano retiene **disco** (volúmenes e imágenes) y no puertos; el que publica es solo el worktree principal.
3. WHEN se verifique el cierre, THE SYSTEM SHALL comprobar con un grep tree-wide que no queda redacción de la clase antigua fuera de `sdd/changes/archive/` — teniendo en cuenta que en `local-environment.md` la palabra «puertos» cae en la línea **siguiente** a «retendiendo», así que un grep de una sola línea con ambas palabras **no lo encuentra**.

## Out of scope

- **Bajar stacks, borrar volúmenes o hacer `prune`.** El diagnóstico informa; recuperar el disco lo decide y lo ejecuta una persona. R3.1 lo prohíbe explícitamente.
- **Prevenir el huérfano en origen** — que el ciclo de vida del worktree baje el stack antes de soltarlo (hoy `retire` falla con el stack vivo y su «nothing was changed» miente). Eso es del **`sdd-toolkit`**, no de este repo, y el reparto correcto que dicta la regla 9 es que el toolkit no aprenda Docker sino que invoque un comando de teardown declarado en `sdd/project.md`. Entrada futura del toolkit.
- **Atribución por etiquetas de contenedor** (`com.docker.compose.project.working_dir` y compañía). Es la forma que hizo fracasar el intento de 2026-08-05 con ~18 hallazgos en cinco rondas; el cruce por ruta contra `git worktree list` la hace innecesaria. Si un diseño la reintroduce, hereda el censo entero de la nota.
- **Guardia de puertos / postura de red del compose local.** Es `compose-ports-guard`, entrada propia y hermana, con su propio historial de ~19 hallazgos.
- **`PORT_OFFSET`** para navegar la app desde un worktree. Ya está declarado fuera de alcance en `specs/local-environment.md:135-136`: «se añadirá cuando haga falta, no antes».
- **Integrarlo en CI.** Es diagnóstico local de conveniencia; R3.5 fija salida cero precisamente para que nadie lo convierta en gate sin decidirlo.

## Affected specs

- `sdd/specs/local-environment.md` — modificar: nueva sub-sección para el diagnóstico, y corregir la afirmación de retención de puertos en el bullet «Stacks huérfanos» (línea 141). Ojo a la R de línea 155, que declara **«los nueve targets que hablan con Compose»** compartiendo una única definición del comando: si el diagnóstico se expone como target del `Makefile`, es deliberadamente el **primero que no** la usa, porque su ámbito es la máquina y no este proyecto (R1.2) — la spec tiene que decirlo en vez de dejar el número desactualizado.
- `sdd/project.md` — modificar: §«Worktree bootstrap», bullet «Stacks huérfanos» (línea 78), que promete un diagnóstico incluyendo «quién retiene cada puerto».
- `README.md` — modificar: §«Postura de red del stack local» / líneas 93-95, que enmarcan el diagnóstico como respuesta a un choque de puertos.
