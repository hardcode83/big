# Design: compose-stacks-diagnostic

## Context

El estado local vive en tres ficheros de la raíz: `docker-compose.yml`, `docker-compose.worktree.yml` (que retira los cuatro mapeos con `ports: !reset []`) y el `Makefile`, que decide entre los dos comparando `--git-dir` con `--git-common-dir` y expone `$(COMPOSE)` a los nueve targets que hablan con Compose (`Makefile:21-27`, `sdd/specs/local-environment.md:155`). No hay ningún otro fichero de compose en el árbol: medido, son exactamente esos tres, todos en la raíz.

El patrón para herramienta host-side ya existe y son dos ficheros: `scripts/check-version-parity.py` con `scripts/test_check_version_parity.py` al lado, invocado por `make check-version-parity` (`Makefile:150-151`) — el único target `.PHONY` que **no** usa `$(COMPOSE)`. `scripts/validate-provenance-contract.py` añade la variante `--self-test`, y su test se carga por `importlib.util.spec_from_file_location` porque el fichero es kebab-case y no es importable como módulo.

Lo que este change necesita saber lo dan dos comandos, ambos verificados hoy en esta máquina: `docker compose ls -a --format json` devuelve un array de objetos con exactamente `Name`, `Status` y `ConfigFiles` (este último, **rutas absolutas unidas por comas**), y `git worktree list --porcelain` devuelve registros `worktree <ruta absoluta>` / `HEAD <sha>` / `branch <ref>` con el worktree principal **primero**. Ninguno de los dos es estado del `sdd-toolkit`, que es lo que fija la frontera decidida en `sdd/roadmap/compose-stacks-diagnostic.md`.

El hecho que gobierna la regla de clasificación, y que no estaba escrito en el proposal: **los worktrees de este repositorio viven bajo el árbol del principal** (`<principal>/.claude/worktrees/sdd+<feature>`). Medido: cinco worktrees registrados, cuatro de ellos anidados dentro del primero.

## Decisions

### D1 — Script Python con parser en `scripts/`, no shell en el `Makefile`

**Chosen:** `scripts/compose-stacks.py`, siguiendo `check-version-parity.py`: stdlib (`json`, `subprocess`, `pathlib`, `sys`), sin dependencias nuevas, ejecutable con el `python3` del host. Es lo que elimina de raíz los hallazgos (a), (c), (d) e (i) del censo de 2026-08-05 — no hay interpolación de make, ni fila que fabricar, ni ancho de terminal que respetar.

Rejected: receta de shell en el `Makefile` — es la forma que acumuló ~18 hallazgos en cinco rondas y la nota del roadmap ya concluyó que no tenía primitiva segura. Rejected: función de shell documentada en el README — misma clase de problema, sin test posible.

### D2 — Exactamente dos fuentes, y una lista negra explícita de comandos

**Chosen:** el script invoca **solo** `git worktree list --porcelain` y `docker compose ls -a --format json`, cada uno una vez, con `subprocess.run` y lista de argumentos (nunca `shell=True`). Queda prohibido en el código y en la spec: `docker inspect` sin `--format`, `docker compose config` (en cualquier forma), `docker ps --format '{{.Labels}}'` y cualquier volcado de salida completa. Motivo medido y portante: la salida por defecto de `docker inspect` incluye `.Config.Env` y `docker compose config` **resuelve e imprime los valores del `.env`** — con `JWT_SECRET_KEY`, `POSTGRES_PASSWORD` y `ENCRYPTION_KEY` dentro. Cubre R3.2 y la regla 8 de `steering/security.md`.

Rejected: atribuir por etiquetas de contenedor (`com.docker.compose.project.working_dir`) — cualquier contenedor de la máquina las pone con `docker run --label`, admiten cualquier byte, y el cruce por ruta las hace innecesarias (R2, «out of scope» del proposal).

### D3 — `-a`: el inventario incluye los proyectos parados

**Chosen:** `docker compose ls -a`. Sin `-a` solo salen los que tienen contenedores corriendo, y un stack huérfano **parado** retiene exactamente el mismo disco (volúmenes e imágenes) que uno corriendo — que es la motivación que quedó viva tras el reencuadre. El campo `Status` (p. ej. `exited(1), running(6)`) es lo que distingue los dos casos en pantalla, así que no se pierde información.

Rejected: `docker compose ls` sin `-a` — dejaría fuera justo los huérfanos que llevan más tiempo abandonados.

### D4 — El directorio de origen es `dirname` del **primer** `ConfigFiles`, y la coma se detecta en vez de adivinarse

**Chosen:** Compose define el directorio del proyecto como el del primer fichero de configuración cuando no se pasa `--project-directory` (y el `Makefile` nunca lo pasa), así que ése es el dato correcto. El campo llega unido por comas y una ruta puede contener una coma (R3.4), ambigüedad que está en el lado de Docker y no se puede resolver desde aquí. Se **detecta**: se parte por `,` y se exige que **todos** los fragmentos sean rutas absolutas (empiezan por `/`); si alguno no lo es, el campo es ambiguo y el proyecto se clasifica **`indeterminado`** nombrando el motivo, nunca con un veredicto derivado de una ruta partida por la mitad. Igual si `ConfigFiles` viene vacío, o si el primer fragmento no es absoluto.

Rejected: partir solo por la primera coma — falla igual y en silencio si la coma está en la primera ruta. Rejected: reconstruir probando qué prefijo existe en disco — el caso «directorio borrado» no tiene fichero que comprobar, así que la heurística fallaría precisamente donde importa.

### D5 — Clasificación: igualdad exacta contra las raíces registradas, y **después** pertenencia al árbol

**Chosen:** con `P` = directorio de origen resuelto (`Path.resolve()`, que normaliza `..` y symlinks aunque el directorio ya no exista — R2.5), `R` = conjunto de raíces registradas resueltas, y `M` = raíz del worktree principal resuelta:

| # | Condición | Clase | Qué se imprime |
|---|---|---|---|
| 1 | `ConfigFiles` vacío / ambiguo / no absoluto (D4) | `indeterminado` | el motivo; **nunca** huérfano |
| 2 | `P` ∈ `R` (igualdad exacta) | `vivo` | worktree y rama a los que se atribuye |
| 3 | `P.is_relative_to(M)` | `huérfano` | ruta y si el directorio sigue en disco |
| 4 | resto | `ajeno` | nada más; no se propone nada sobre él |

El orden importa y es lo que resuelve el anidamiento: como los worktrees viven **dentro** del árbol del principal, una regla de «prefijo registrado más largo» atribuiría un worktree desregistrado al principal y lo daría por vivo. La igualdad exacta funciona porque cada proyecto de compose de este repositorio tiene su fichero en la **raíz** de su worktree, así que `dirname` coincide exactamente con la raíz registrada. La regla 3 es la que cubre el caso habitual —«worktree desregistrado con el directorio en pie», porque `git worktree remove --force` falla con `Permission denied` sobre los ficheros de bind-mount— y también el de directorio borrado, sin consultar el disco para decidir: `git worktree list` es la fuente de verdad, `[ -d … ]` no (R2.2). La existencia en disco se imprime como dato, no se usa como criterio. La regla 1 antes que todo lo demás es el simétrico, el hallazgo (j): ausencia de dato no es evidencia de abandono (R2.4).

Rejected: prefijo registrado más largo gana — roto por el anidamiento, según lo medido. Rejected: preguntar a git por cada directorio (`git -C <P> rev-parse --show-toplevel`) — un `subprocess` por proyecto para decidir lo mismo, y falla de formas distintas según por qué el worktree dejó de estar registrado.

### D6 — La raíz del repositorio sale del primer registro de `git worktree list`, y vacía es fatal

**Chosen:** `M` es la ruta del **primer** registro `worktree ` de `git worktree list --porcelain` — git documenta que el principal va primero, y eso hace que el diagnóstico dé el mismo veredicto ejecutado desde cualquier worktree. Si `git` no está, no es un repositorio, sale sin registros, o el primer registro no es una ruta absoluta, o el repositorio es `bare` (no hay árbol contra el que comparar): **se aborta con código distinto de cero** nombrando el problema. Es el hallazgo (b) convertido en aserción: con `M` vacío la pertenencia se vuelve universal y se marcaría de huérfano cualquier stack de la máquina (R2.6).

Rejected: derivar `M` de `git rev-parse --show-toplevel` — devuelve el worktree *actual*, no el principal, así que el veredicto dependería de desde dónde se lanza. Rejected: seguir con `R` vacío tratando todo como ajeno — es la degradación silenciosa que R1.3 prohíbe en su equivalente de Docker.

### D7 — Fallar en voz alta al leer, salir en verde al informar

**Chosen:** dos regímenes de código de salida, y no se mezclan. **Distinto de cero** cuando no se pudo *obtener* el dato: `docker` ausente (`FileNotFoundError`), demonio que no responde o `docker compose ls` con estado distinto de cero (se resume su `stderr`), JSON no parseable, JSON que no es una lista de objetos, u objeto al que le falta alguna de las tres claves `Name`/`Status`/`ConfigFiles` (R1.3, R1.4), más los fallos de git de D6. **Cero** siempre que el inventario se obtuvo, haya huérfanos o no (R3.5) — es un informe, no una guardia; y `[]` con estado cero es legítimamente «no hay stacks», distinguible del fallo por el código de salida y no por la forma de la salida.

Rejected: código distinto de cero al encontrar huérfanos — invita a ponerlo en CI, que está fuera de alcance por decisión explícita.

### D8 — Clasificar con el valor crudo, sanear para pantalla con escape inyectivo

**Chosen:** todas las comparaciones de D4-D6 usan el valor **crudo** que devuelven Docker y git (hallazgo (g): sanear antes de clasificar cambia el veredicto). Solo al imprimir se aplica una función de escape: `\\` para la barra invertida, y `\xNN`/`\uNNNN` para todo carácter con `str.isprintable() == False` — es decir, controles C0, C1 (incluido `\x9b`, el CSI de un byte) y separadores distintos del espacio. El escape es **inyectivo por construcción**, así que dos nombres distintos nunca se ven iguales en pantalla (R3.3).

Rejected: `tr -cd` o cualquier borrado de caracteres — mapea `autohostai!` → `autohostai`, y con eso un contenedor hostil consigue que el informe muestre el nombre real del desarrollador. Rejected: `repr()` de Python — inyectivo, pero también entrecomilla y escapa caracteres no-ASCII legítimos, así que una ruta con acentos se vuelve ilegible.

### D9 — Un campo por línea, ningún comando interpolado

**Chosen:** la salida es un bloque por proyecto —`clase`, `proyecto`, `estado`, `origen`, y `worktree`/`rama` cuando aplica—, una etiqueta y un valor por línea, separados por línea en blanco, ordenados de forma determinista (por clase, huérfanos primero, y por nombre dentro de cada clase). Cierra con un recuento por clase. Con el escape de D8 no queda ningún carácter de control en la salida, y con un campo por línea no hay delimitador compuesto que un nombre hostil pueda falsificar para fabricar una fila (R3.4). **Ningún comando de derribo con datos interpolados**, ni por proyecto ni al final: el precedente del árbol es explícito (`specs/seed-data-demo.md:492` enumera y no borra; `specs/backend-ci.md:130` avisa de que `make db-clean-test` no distingue una base huérfana de una viva). Lo que sí se imprime al final es una frase fija, sin interpolar nada, recordando que bajar un stack es decisión de una persona (R3.1).

Rejected: tabla alineada por columnas — es el hallazgo (i), el corte por ancho de terminal, y además reintroduce el delimitador. Rejected: un `docker compose -p <nombre> down` sugerido por fila — hallazgo (c), la trampa de copiar y pegar.

### D10 — Funciones puras + `main()` fino; test por `importlib`, más un test de contrato contra Docker real

**Chosen:** el módulo separa `parse_worktrees(text)`, `parse_projects(json_text)`, `classify(project, roots, main_root)` y `render(records)` —todas puras, sin `subprocess`— de un `main()` que solo invoca, encadena e imprime. `scripts/test_compose_stacks.py` carga el módulo con `importlib.util.spec_from_file_location`, igual que `test_validate_provenance_contract.py`, porque el nombre kebab-case no es importable. Cubre: las cuatro clases de D5, el anidamiento de D5 (un huérfano bajo `.claude/worktrees/` no se atribuye al principal), la coma ambigua y el `ConfigFiles` vacío de D4, la inyectividad del escape de D8 (dos nombres distintos con controles dan salidas distintas), y los cuatro modos de fallo de D7 con `M` vacío incluido.

Y **un test de contrato contra la realidad**: si hay `docker` en el `PATH`, ejecuta el `docker compose ls -a --format json` de verdad y comprueba que `parse_projects` lo acepta; si no, `pytest.skip`. Es la lección de que una suite verde puede estar de acuerdo consigo misma y no con el escritor real: los fixtures se copian **literalmente** de la salida medida hoy, y este test es lo que avisa el día que Docker renombre un campo.

Rejected: mockear `subprocess.run` — probaría el mock, y el riesgo real de este script es exactamente que la forma de la salida ajena cambie.

### D11 — Se expone como `make compose-stacks`, host-side, deliberadamente fuera de `$(COMPOSE)`

**Chosen:** target `.PHONY` `compose-stacks` que ejecuta `python3 scripts/compose-stacks.py`, exactamente la forma de `check-version-parity` (`Makefile:150-151`). El `Makefile` es el entrypoint único por spec, y así el diagnóstico es descubrible con `make`. Que no use `$(COMPOSE)` **no rompe** la R de `local-environment.md:155`: esa R habla de los targets que invocan `docker compose` desde el `Makefile`, y éste no lo invoca — delega en un script host-side, igual que `check-version-parity`. Siguen siendo nueve. Lo que la spec sí tiene que decir, para que nadie lo «arregle» después, es que el ámbito de este diagnóstico es **la máquina** y no este proyecto (R1.2): pasarlo por `$(COMPOSE)` lo acotaría a los ficheros de este directorio y por diseño dejaría de ver los stacks ajenos, que son justo los que busca.

Rejected: solo el script, sin target — menos descubrible y contra la §«Makefile como entrypoint único». Rejected: target dentro de `$(COMPOSE)` — contradice R1.2.

### D12 — `--porcelain` sin `-z`, con validación estricta de cada registro

**Chosen:** se parsea `git worktree list --porcelain` línea a línea, aceptando solo registros cuya línea `worktree ` lleva una ruta absoluta; cualquier registro que no encaje **aborta** en vez de producir una raíz inventada (que por D6 marcaría huérfanos falsos). Se ignoran las líneas `HEAD`, `locked`, `prunable`, `detached` y las desconocidas, y `branch refs/heads/<x>` se guarda solo para atribuir en pantalla.

Rejected: `--porcelain -z`, que resolvería de verdad las rutas con salto de línea — exige **git ≥ 2.36** y el suelo declarado del proyecto es 2.31 (`local-environment.md:131`). Subir un suelo global que afecta a `make up` por un diagnóstico de conveniencia no sale a cuenta; abortar en voz alta cubre el mismo caso sin mover el suelo.

### D13 — R4: dónde se corrige cada sitio y con qué grep se verifica

**Chosen:** los cinco sitios no se tocan todos en el mismo commit, porque `sdd/specs/` es propiedad del archivado (`steering/documentation.md`). Reparto:

| Sitio | Cuándo | Qué |
|---|---|---|
| `sdd/roadmap.md:50` | hecho | corregido en el reencuadre |
| `sdd/roadmap/compose-stacks-diagnostic.md` | hecho | corregido en el reencuadre |
| `sdd/project.md:78` | PR de la feature | quitar «quién retiene cada puerto»; decir que retiene **disco** |
| `README.md:93-95` | PR de la feature | reencuadrar de «si algo choca de puertos» a disco, y documentar `make compose-stacks` |
| `sdd/specs/local-environment.md` | `/sdd:archive` | líneas 141-148 (retención), matiz de la R de línea 155 (D11), nueva sub-sección de comportamiento, `scripts/compose-stacks.py` en Key files |

La verificación de R4.3 es un grep del **verbo solo**, no del par de palabras: en `local-environment.md:141` «retendiendo» cierra la línea y «puertos» abre la siguiente, así que un grep de una línea con ambas no lo encuentra. Concretamente `grep -rniE 'retendiendo|reteniendo|quién retiene|choca de puertos' --include='*.md' .`, cuyos únicos aciertos aceptables son los documentos de este propio change (`sdd/changes/compose-stacks-diagnostic/`, que citan la redacción vieja para corregirla) y `sdd/changes/archive/` (registro histórico, no se reescribe). Se corre al archivar, que es el primer momento en que los cinco están corregidos.

Rejected: corregir la spec en el PR de la feature — rompe la propiedad del archivado y deja el spec describiendo comportamiento no mergeado.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Diagnóstico | `scripts/compose-stacks.py` **(nuevo)** | El script entero: D1-D10. Docstring que nombra la entrada `compose-stacks-diagnostic` del roadmap y la lista negra de D2 |
| Test | `scripts/test_compose_stacks.py` **(nuevo)** | Cobertura de D10, fixtures copiados literalmente de la salida medida + test de contrato con skip si no hay `docker` |
| Entrypoint | `Makefile` | Target `compose-stacks` + su entrada en `.PHONY` (línea 30). Comentario que fija por qué no usa `$(COMPOSE)` (D11) |
| Docs raíz | `README.md` | §«Postura de red del stack local», líneas 93-95: corrección de R4 + `make compose-stacks` documentado (obligación de `steering/documentation.md`: comando de Makefile nuevo → README) |
| Steering | `sdd/project.md` | §«Worktree bootstrap», línea 78: corrección de R4 |
| Spec (al archivar) | `sdd/specs/local-environment.md` | D13 |

Requisitos sin implicación de diseño, declarados para que no falte ninguno: **R1.1** es la salida de D9 alimentada por D2/D3; **R2.1** es la fila 2 de la tabla de D5. Todo lo demás está mapeado en las decisiones.

## Data & interfaces

Sin esquema, sin API, sin eventos, sin variables de entorno nuevas (por tanto sin tocar `.env.example`). Interfaces consumidas, ambas de terceros y ambas verificadas hoy en esta máquina:

- `docker compose ls -a --format json` → array de objetos con `Name` (str), `Status` (str) y `ConfigFiles` (str, rutas absolutas unidas por comas). Docker Compose 5.1.1.
- `git worktree list --porcelain` → registros separados por línea en blanco, `worktree <ruta absoluta>` primero y el worktree principal primero de todos; `HEAD`, `branch`, `locked` opcionales. git 2.52.0, suelo declarado 2.31.

Interfaz propia expuesta: `make compose-stacks`, sin argumentos, sin variables, salida de texto para persona (no es contrato de máquina y no debe convertirse en uno).

## Risks & mitigations

- **Falso huérfano por un proyecto de compose en un subdirectorio del árbol.** La fila 3 de D5 marcaría huérfano un stack levantado desde, digamos, `<worktree>/infra/`. Hoy no puede ocurrir: los únicos ficheros de compose del árbol son los tres de la raíz, medido. Mitigación: el informe imprime la ruta de origen, así que el falso positivo es legible de un vistazo; y la spec deja escrito que la regla asume un proyecto por raíz de worktree, condición a revisar si algún día se añade uno anidado.
- **Un worktree creado fuera del árbol del repositorio** (`git worktree add ~/tmp/foo`) sale como `ajeno` y nunca se marca, aunque sea nuestro. Es lo que R2.3 pide literalmente; hoy es hipotético porque todos los worktrees los crea la misma herramienta bajo `.claude/worktrees/`. Ver pregunta abierta Q1.
- **Docker renombra o reordena los campos del JSON.** Mitigación doble: D7 aborta si falta cualquiera de las tres claves en vez de informar de menos, y el test de contrato de D10 lo caza contra la salida real en cuanto alguien corre la suite con Docker delante.
- **Que alguien «mejore» el diagnóstico volcando salida completa** de `docker inspect` o `docker compose config` y filtre `JWT_SECRET_KEY`/`ENCRYPTION_KEY`/`POSTGRES_PASSWORD`. Mitigación: la prohibición va en el docstring del script, en la spec y en el comentario del `Makefile` — tres sitios, porque este hallazgo (k) es portante y no cosmético.
- **La redacción caducada vuelve** en un documento nuevo. Mitigación: el grep exacto de D13 queda escrito en la spec, con su aviso de que el par de palabras cae en líneas distintas.
- **El test no lo ejecuta CI** (medido: el `pytest` de `backend-tests.yml` corre con `working-directory: backend`, así que `scripts/test_*.py` no se recoge). Ver Q3.

## Open questions

Ninguna abierta. Las tres que este diseño planteó se decidieron en el gate del 2026-08-17 y quedan aquí como decisiones, no como preguntas:

**Q1 — Alcance de la marca de huérfano: solo el árbol del repositorio.** D5 se queda como está, con la fila 3 literal de R2.3: fuera del árbol del principal → `ajeno`. Se **rechazó** añadir la señal positiva del fichero `.git` (comprobar que su `gitdir:` apunta bajo el directorio git común de este repositorio, ~15 líneas), que habría cubierto un worktree desregistrado creado fuera del árbol: todos los worktrees los crea la misma herramienta bajo `.claude/worktrees/`, así que esa cobertura es hipotética, y la señal iría más allá del texto del requisito. Queda como limitación conocida en Risks.

**Q2 — El informe no dice cuánto disco retiene cada huérfano.** Sería el dato más útil dada la motivación del reencuadre (7,66 GB de volúmenes, 67 % reclaimable), pero medir volúmenes por proyecto obliga a filtrar por `label=com.docker.compose.project=<nombre>`, es decir a **leer etiquetas** — que el proposal excluye y es de donde salió el censo de ~18 hallazgos. Si se quiere, entrada propia que decida antes cómo se lee una etiqueta sin confiar en ella.

**Q3 — El test se ejecuta solo en local**, con `python3 -m pytest scripts/`, que es el patrón que nombra el proposal y respeta el «integrarlo en CI» declarado fuera de alcance. Consecuencia asumida a sabiendas, y por eso está en Risks: como `test_check_version_parity.py`, este test **no lo recoge ningún workflow** (medido: el `pytest` de `backend-tests.yml` corre con `working-directory: backend`). Se rechazaron las dos alternativas que lo habrían cubierto: un `--self-test` con asserts de stdlib invocado en `frontend-tests.yml` (duplica superficie de test) e instalar pytest en el runner para recoger `scripts/` (toca CI, fuera de alcance).
