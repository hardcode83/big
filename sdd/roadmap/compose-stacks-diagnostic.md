# compose-stacks-diagnostic

[INFRA] **saber qué stacks de Compose hay vivos y cuáles son huérfanos** —su worktree ya no existe—, para recuperar el disco que retienen en silencio. Separada de `worktree-parallel-stack` el 2026-08-05, en su `/sdd:review` y por decisión del usuario, **después de implementarla entera y retirarla**.

## Reencuadre del 2026-08-17 — la premisa original caducó a medias

La entrada pedía cuatro cosas: *qué stacks hay vivos · desde qué directorio · cuáles son huérfanos · **quién retiene cada puerto***. Medido en el `/sdd:new` del 2026-08-17, **la cuarta ya no tiene problema que resolver y la primera y la segunda las contesta Docker**:

1. **La mitad de puertos está disuelta.** `worktree-parallel-stack` entregó `docker-compose.worktree.yml` con `ports: !reset []`, así que **un worktree enlazado no publica ninguno**. Medido con dos stacks vivos: `docker ps` da `5432/tcp`, `3000/tcp`, `8000/tcp` — sin prefijo `0.0.0.0:` ni `127.0.0.1:`. Y la motivación original de esta entrada era exactamente el caso contrario, el `sddlocal-dev-network-hardening` que retenía 3000/8000/5432/6379 con su worktree ya borrado: **ese caso no puede reproducirse en un worktree**. Solo el principal publica, y ahí no hay ambigüedad sobre de quién es el stack.
2. **`docker compose ls -a --format json` da nombre, estado y la ruta absoluta de los ficheros de origen**, ya parseable. La redacción anterior lo llamaba «el sustituto, sin marcas ni atribución», pero con `--format json` el delta que falta es **solo la marca de huérfano**, no la tabla.
3. **La consecuencia cambió de bloqueante a coste silencioso.** Antes te enterabas solo: puerto ocupado, `make up` falla. Ahora un stack huérfano no molesta a nadie, solo acumula. Medido: `docker system df` con 7,66 GB de volúmenes (5,15 GB reclaimable, 67 %) y 4,69 GB de imágenes reclaimable. Con un stack por worktree eso crece **más** rápido que antes, no menos — la entrada sigue valiendo, pero por el disco, no por los puertos.
4. **Cero huérfanos en el momento de medir**: los dos stacks vivos correspondían a los dos worktrees vivos. El diagnóstico es preventivo, no reactivo a una incidencia abierta.

## Lo que el reencuadre le hace al modelo de amenaza — leer antes de rediseñar

El censo de abajo se acumuló contra una forma concreta: **atribuir stacks leyendo etiquetas de contenedor** (`com.docker.compose.project`, `.project.working_dir` — que **cualquier** contenedor de la máquina puede poner con `docker run --label`, que Docker no escapa y que admiten cualquier byte, incluidos `|`, saltos de línea y C1 en UTF-8) **en shell, dentro de un `Makefile`, para imprimir una tabla**. Esa combinación no tenía primitiva segura: cada ronda reinventaba el tratamiento de delimitadores y reabría la misma clase.

**La forma reencuadrada no lee etiquetas.** Cruza el `ConfigFiles` que devuelve `docker compose ls --format json` contra el conjunto de worktrees vivos que da `git worktree list` — ruta contra ruta, sin tabla que armar y sin comando que sugerir. Eso **elimina de raíz** (a) la inyección por interpolar `$(CURDIR)`/`$(REPO_ROOT)` como texto de make, (b) el `REPO_ROOT` vacío que convertía `case "$dir" in "$REPO_ROOT"/*)` en `/*`, (c) la trampa de copiar-y-pegar del `docker compose -p <nombre> down` interpolado, (d) la fila fabricada por un salto de línea, (f) la suplantación por `head -1` con `sort -u` escondiendo el desacuerdo, e (i) el corte por ancho de terminal. La nota original ya lo anticipaba: *«esto no debería ser shell en un Makefile; un script con un parser de verdad elimina de golpe (c), (d) y (i)»* — el reencuadre extiende esa conclusión al resto.

**Lo que sigue vinculante, y no depende de la forma:**

- **(k) La fuga de secretos por la herramienta, no por la etiqueta.** La salida **por defecto** de `docker inspect` (sin `--format`) incluye `.Config.Env`; medido sobre el stack vivo con `JWT_SECRET_KEY`, `POSTGRES_PASSWORD` y `ENCRYPTION_KEY`. Y lo mismo vale para `docker compose config --format json`, que **resuelve e imprime los valores del `.env`**. Nadie debe «mejorar» el diagnóstico volcando salida completa. Esto es portante, no cosmético.
- **(e) Saneado no inyectivo** y **(g) sanear antes de clasificar**: si algún día se imprime un nombre de proyecto, se clasifica con el valor **crudo** y el saneado de pantalla es **lista blanca** de imprimibles — nunca `tr -cd`, que mapea `autohostai!` → `autohostai` y hace que un contenedor hostil muestre el nombre real del desarrollador.
- **Informa, no aconseja**: ningún comando por fila con datos interpolados. Hay dos precedentes en el propio árbol que lo respaldan: `specs/seed-data-demo.md:492` (*«no borra los objetos huérfanos que un fallo deje en el bucket, sólo los enumera»*) y el aviso de `specs/backend-ci.md:130` (*«`make db-clean-test` **no distingue** una base huérfana de una viva»*). Un derribo automático repetiría ese error con contenedores.
- **Nada de delimitadores compuestos**: un campo por invocación. Aunque el cruce sea por ruta, el `ConfigFiles` del JSON viene como lista separada por comas y una ruta puede contener una coma.

**El caso que el diseño no debe olvidar**: el fallo habitual no es «directorio borrado» sino **«worktree desregistrado con su directorio en pie»**, porque `git worktree remove --force` **falla con `Permission denied`** sobre los ficheros que Docker creó por bind-mount (medido al verificar `worktree-parallel-stack`). Así que existir en disco **no** implica estar registrado: la fuente de verdad es `git worktree list`, no `[ -d ... ]`. Y su simétrico, (j): un proyecto sin ruta de origen resoluble no es huérfano por defecto — `[ ! -d "" ]` es cierto y eso marcaba huérfanos falsos.

## Frontera con el toolkit SDD — decidida el 2026-08-17

Esta entrada **detecta**; no previene. Prevenir es que el ciclo de vida del worktree baje el stack antes de soltarlo (hoy `retire` falla con el stack vivo y su «nothing was changed» miente), y eso **es del `sdd-toolkit`, no de este repo**. El reparto correcto lo dicta la regla 9 de las reglas compartidas —build/test/lint vienen del `sdd/project.md` del proyecto consumidor, nunca se infieren del toolkit—: el toolkit no debe aprender Docker, debe **invocar un comando de teardown declarado** por el proyecto (`sdd/project.md` ya nombra `make down` en prosa). Entrada futura del toolkit, no de aquí.

Que esta mitad viva en AutoHostAI está decidido por lo que necesita: `git worktree list` (git puro) y `docker compose ls` (Docker). **Ninguna es estado del toolkit** — no hace falta leer el registro de bindings de `sdd_session.py`, así que no hay acoplamiento que justifique cruzar de repo. Y todo lo diagnosticado vive aquí: `docker-compose.yml`, `docker-compose.worktree.yml`, el `Makefile`, el prefijo `sdd` del nombre de proyecto.

## Redacción caducada a corregir (censo tree-wide, 2026-08-17)

Cinco sitios afirman todavía que un stack huérfano «retiene puertos» o prometen un diagnóstico que incluye «quién retiene cada puerto». Cerrar esta entrada exige corregirlos todos, no solo el que se toque:

1. `sdd/roadmap.md:50` — la propia línea de la entrada *(corregido en el reencuadre)*
2. `sdd/roadmap/compose-stacks-diagnostic.md` — esta nota *(corregida)*
3. `sdd/project.md:78` — «un diagnóstico con marcas (…, quién retiene cada puerto)»
4. `sdd/specs/local-environment.md:141` — «deja los contenedores vivos retendiendo puertos»
5. `README.md:93-95` — «Si algo choca de puertos, `docker compose ls` dice…»

Ojo al grep: en `local-environment.md` la palabra «puertos» cae en la **línea siguiente** a «retendiendo», así que un `grep` de una línea con las dos palabras **no lo encuentra**.

**Prioridad baja**: sigue siendo diagnóstico de conveniencia y no desbloquea nada — `worktree-parallel-stack` entregó los stacks en paralelo sin él (no está en el plan original, separada de `worktree-parallel-stack` el 2026-08-05; reencuadrada a la baja el 2026-08-17).
