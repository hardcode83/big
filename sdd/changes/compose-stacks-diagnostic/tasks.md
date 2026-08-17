# Tasks: compose-stacks-diagnostic

Todo el código nuevo vive en `scripts/compose-stacks.py` y `scripts/test_compose_stacks.py`.
Las secciones 1-3 construyen funciones puras con su test al lado; el script no es invocable
hasta la 4, así que el árbol queda consistente sección a sección (no hay target en el
`Makefile` prometiendo algo que aún no existe hasta la 6).

Comando de test medido en esta máquina: `pytest scripts/` (el `pytest` de homebrew, en el
`PATH`). Ojo: `python3 -m pytest` **no** funciona en el host — el `python3` de homebrew no
trae el módulo. Q3 del diseño ya asume que ningún workflow recoge estos tests.

## 1. Parseo de las dos fuentes (funciones puras) <!-- panel: PASS 2026-08-17 -->

<!-- Panel único para las secciones 1-6, lanzado al cerrar la 6: el script no es invocable
     hasta la 4 (así lo dice la cabecera de este fichero), así que un panel por sección
     habría revisado tres veces el mismo fichero a medio escribir. Siete reviewers en
     paralelo: sdd-architect, sdd-security, sdd-qa, sdd-review-documentation,
     sdd-review-cicd, sdd-review-tenancy, sdd-review-i18n. Todos PASS. Único hallazgo (QA,
     severidad baja): un proyecto levantado desde un subdirectorio de un worktree registrado
     sale `huérfano` — es el riesgo ya aceptado en design.md §Risks, y quedó fijado con un
     test que impide «arreglarlo» con la regla de prefijo más largo que D5 rechaza. -->


- [x] 1.1 Crear `scripts/compose-stacks.py` con su docstring de cabecera: nombra la entrada
  `compose-stacks-diagnostic` del roadmap y deja escrita la **lista negra** de D2 —
  prohibidos `docker inspect` sin `--format`, `docker compose config` en cualquier forma,
  `docker ps --format '{{.Labels}}'` y cualquier volcado de salida completa, porque el
  primero incluye `.Config.Env` y el segundo resuelve los valores del `.env`
  (`JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `ENCRYPTION_KEY`). Sin lógica todavía. [R3.2]
- [x] 1.2 `parse_worktrees(text)` en `compose-stacks.py`: parsea `git worktree list --porcelain`
  registro a registro, acepta solo líneas `worktree ` con **ruta absoluta**, guarda
  `branch refs/heads/<x>` para atribuir en pantalla, ignora `HEAD`/`locked`/`prunable`/
  `detached`/desconocidas, y **aborta** ante cualquier registro que no encaje en vez de
  inventar una raíz. Devuelve `(main_root, roots)` con el **primer** registro como
  `main_root`. Test en `scripts/test_compose_stacks.py` (cargando el módulo con
  `importlib.util.spec_from_file_location`, como `test_validate_provenance_contract.py`):
  fixture copiada **literalmente** de la salida real, registro con ruta relativa aborta,
  salida sin registros aborta. [R2.6]
- [x] 1.3 `parse_projects(json_text)` en `compose-stacks.py`: exige lista de objetos y las
  tres claves `Name`/`Status`/`ConfigFiles` en cada uno; cualquier otra forma es error, no
  «ningún stack». Tests con fixture copiada literalmente de `docker compose ls -a --format json`
  medido hoy, más: JSON no parseable, JSON que no es lista, objeto al que le falta una clave,
  y `[]` como inventario vacío legítimo. [R1.1, R1.4]
- [x] 1.4 `project_dir(config_files)` en `compose-stacks.py`: parte por `,`, exige que **todos**
  los fragmentos sean absolutos y devuelve `dirname` del primero; si el campo viene vacío, si
  algún fragmento no es absoluto, o si el primero no lo es, devuelve el motivo de
  ambigüedad en vez de una ruta. Nunca reconstruye probando qué prefijo existe en disco.
  Tests: un fichero, varios ficheros, ruta con coma dentro (→ ambiguo), `ConfigFiles` vacío
  (→ ambiguo). [R3.4]

## 2. Clasificación <!-- panel: PASS 2026-08-17 -->

- [x] 2.1 `classify(project, roots, main_root)` en `compose-stacks.py` con las cuatro reglas de
  D5 **en este orden**: (1) origen ambiguo de 1.4 → `indeterminado` con el motivo; (2)
  igualdad exacta contra `roots` → `vivo`, atribuido a ese worktree y su rama; (3)
  `is_relative_to(main_root)` → `huérfano`; (4) resto → `ajeno`. La existencia en disco se
  adjunta como **dato impreso**, jamás como criterio. Tests: un caso por clase. [R2.1, R2.2, R2.3, R2.4]
- [x] 2.2 Resolver todas las rutas con `Path.resolve()` antes de comparar, en `classify` y en
  ambos parsers. Test: la misma raíz expresada con `..` y vía symlink da el mismo veredicto,
  y un directorio inexistente se resuelve igual (no se toca el disco para decidir). [R2.5]
- [x] 2.3 Test del **anidamiento** en `test_compose_stacks.py`: un proyecto cuyo origen es
  `<principal>/.claude/worktrees/sdd+algo` y que **no** está en `roots` sale `huérfano`, no
  `vivo` atribuido al principal — es el caso que rompe la regla de «prefijo registrado más
  largo» y el que ocurre de verdad en este repositorio. [R2.2]
- [x] 2.4 Test de `main_root` vacío/no absoluto en `test_compose_stacks.py`: aborta en voz alta
  y **no** clasifica nada; es el hallazgo (b) — con `M` vacío la pertenencia se vuelve
  universal y marcaría de huérfano cualquier stack de la máquina. [R2.6]

## 3. Salida <!-- panel: PASS 2026-08-17 -->

- [x] 3.1 `escape(value)` en `compose-stacks.py`: `\\` para la barra invertida y `\xNN`/`\uNNNN`
  para todo carácter con `str.isprintable() == False` (controles C0, C1 incluido `\x9b`, y
  separadores distintos del espacio). Se aplica **solo al imprimir**, nunca antes de
  clasificar. Test de **inyectividad**: dos nombres distintos con caracteres de control dan
  salidas distintas, y `autohostai!` no colapsa en `autohostai`; una ruta con acentos sale
  legible (no `repr()`). [R3.3]
- [x] 3.2 `render(records)` en `compose-stacks.py`: un bloque por proyecto con **una etiqueta y
  un valor por línea** (`clase`, `proyecto`, `estado`, `origen`, y `worktree`/`rama` cuando
  aplica), bloques separados por línea en blanco, orden determinista (huérfanos primero por
  clase, y por nombre dentro de cada clase), recuento por clase al final, y una frase fija
  —sin interpolar nada— recordando que bajar un stack lo decide una persona. **Ningún
  comando de derribo**, ni por proyecto ni al final. Tests: orden estable con entrada
  desordenada, y aserción de que la salida no contiene `down`/`rm`/`prune` ni tabla con
  delimitador. [R3.1, R3.4]

## 4. `main()`, invocación y códigos de salida <!-- panel: PASS 2026-08-17 -->

- [x] 4.1 `main()` en `compose-stacks.py`: invoca **exactamente dos** comandos, una vez cada
  uno, con `subprocess.run` y lista de argumentos (nunca `shell=True`) —
  `git worktree list --porcelain` y `docker compose ls -a --format json` (con `-a`, para que
  entren los proyectos parados, que retienen el mismo disco) — y encadena 1.2→1.4→2.1→3.2 sin
  lógica propia. [R1.2, R3.2]
- [x] 4.2 Régimen de salida de D7 en `main()`: **distinto de cero** cuando no se pudo *obtener*
  el dato — `docker` ausente (`FileNotFoundError`), demonio que no responde o
  `docker compose ls` con estado distinto de cero (se resume su `stderr`), más los fallos de
  parseo de 1.2-1.3; **cero** siempre que el inventario se obtuvo, haya huérfanos o no.
  Tests de los cuatro modos de fallo y del caso verde con y sin huérfanos. [R1.3, R1.4, R3.5]

## 5. Test de contrato contra Docker real <!-- panel: PASS 2026-08-17 -->

- [x] 5.1 En `scripts/test_compose_stacks.py`, test que ejecuta el
  `docker compose ls -a --format json` **de verdad** si hay `docker` en el `PATH` y comprueba
  que `parse_projects` lo acepta; `pytest.skip` si no lo hay. Es lo que avisa el día que
  Docker renombre un campo — los mocks de `subprocess.run` probarían el mock, no el riesgo. [R1.1, R1.4]

## 6. Entrypoint <!-- panel: PASS 2026-08-17 -->

- [x] 6.1 Target `.PHONY` `compose-stacks` en el `Makefile` que ejecuta
  `python3 scripts/compose-stacks.py`, exactamente la forma de `check-version-parity`
  (`Makefile:150-151`), más su nombre en la línea `.PHONY` (línea 30). Comentario encima
  fijando por qué **no** usa `$(COMPOSE)`: el ámbito es la máquina y no este proyecto, y
  pasarlo por `$(COMPOSE)` lo acotaría a los ficheros de este directorio, dejando fuera justo
  los stacks que busca. El comentario repite la prohibición de `docker compose config`. [R1.2, R3.2]

## 7. Documentación (los tres sitios que van en este PR) <!-- panel: PASS 2026-08-17 -->

- [x] 7.1 `README.md`, §«Postura de red del stack local» (líneas 93-95): sustituir «Si algo choca
  de puertos…» por lo real — un worktree enlazado no publica puertos, así que un stack
  huérfano retiene **disco** (volúmenes e imágenes) y no puertos; el que publica es solo el
  worktree principal. Documentar ahí `make compose-stacks` (obligación de
  `steering/documentation.md`: comando de Makefile nuevo → README). [R4.1, R4.2]
- [x] 7.2 `sdd/project.md`, §«Worktree bootstrap», línea 78: quitar «quién retiene cada puerto»
  del bullet «Stacks huérfanos» y decir que retiene disco; mencionar `make compose-stacks`
  como el diagnóstico que ya existe. [R4.1, R4.2]
- [x] 7.3 Dejar constancia en `sdd/changes/compose-stacks-diagnostic/STATE.md` (o donde lo pida
  el flujo) de que el **quinto** sitio de R4.1, `sdd/specs/local-environment.md`, se corrige
  en `/sdd:archive` por propiedad del archivado (D13): líneas 141-148, matiz de la R de la
  línea 155, nueva sub-sección de comportamiento y `scripts/compose-stacks.py` en Key files.
  No tocarla en este PR. [R4.1]

## 8. Verification <!-- panel: PASS 2026-08-17 -->

- [x] 8.1 Suite de `scripts/` en verde: `pytest scripts/` (incluye los 2 tests preexistentes
  de `check-version-parity`; el contrato de 5.1 debe **ejecutarse**, no saltarse, porque hay
  Docker en esta máquina). [R1, R2, R3]
- [x] 8.2 `make -n compose-stacks` imprime el comando esperado y `make compose-stacks` corre de
  verdad: comprobar a ojo que los stacks vivos de los worktrees registrados salen `vivo` con
  su rama, que ninguno sale `huérfano` en falso, y que la salida no contiene ningún comando
  de derribo. [R1.1, R2.1, R3.1]
- [x] 8.3 Comprobar el corte de fuentes: `grep -nE 'inspect|compose config|\.Labels|shell=True'
  scripts/compose-stacks.py` no da ningún acierto de código (solo la lista negra del
  docstring y el comentario). [R3.2]
- [x] 8.4 Verificar salida cero con y sin huérfanos: `make compose-stacks; echo $?` da `0` en
  ambos casos, y distinto de cero con el demonio parado. [R1.3, R3.5]

  Los tres casos se midieron con `make` de verdad el 2026-08-17. **El demonio no se paró**:
  hay dos sesiones vivas con su stack en pie (`sdd+revenue-pricing`,
  `sdd+rule11-ownership-single-source`) y pararlo les habría tumbado el trabajo. En su lugar,
  un `docker` de mentira al frente del `PATH` que reproduce literalmente el error del demonio
  (`Cannot connect to the Docker daemon at unix:///var/run/docker.sock`) → el script sale `1`
  y `make` propaga `2`. El caso «con huérfanos» se midió igual, con un inventario de mentira
  apuntando a un worktree no registrado: `clase: huérfano` y salida `0`.
- [x] 8.5 Grep tree-wide de R4.3 —**del verbo solo**, no del par de palabras, porque en
  `local-environment.md` «retendiendo» cierra la línea y «puertos» abre la siguiente:
  `grep -rniE 'retendiendo|reteniendo|quién retiene|choca de puertos' --include='*.md' .`.
  En este PR los únicos aciertos aceptables son `sdd/changes/compose-stacks-diagnostic/`
  (citan la redacción vieja para corregirla), `sdd/changes/archive/` (registro histórico) y
  `sdd/specs/local-environment.md` (pendiente de archivado por 7.3). El grep sin ese tercer
  acierto se vuelve a correr en `/sdd:archive`. [R4.3]

  Medido el 2026-08-17, el grep da además dos clases de acierto que el censo de R4.1 no
  contaba y que **no** son redacción caducada; quedan escritas aquí para que la re-ejecución
  en `/sdd:archive` no las confunda con un sitio pendiente:
  - `sdd/roadmap/worktree-parallel-stack.md:3` («un stack … reteniendo los cuatro puertos») y
    `sdd/roadmap/compose-stacks-diagnostic.md` (líneas 7, 37, 41-45). Son **registro
    histórico**: la primera describe el disparador de un change ya archivado, cuando los
    worktrees sí publicaban puertos y la frase era cierta; la segunda cita la redacción vieja
    justamente para enumerar los cinco sitios a corregir. Reescribirlas falsearía el registro.
  - `sdd/steering/security.md:179` y `sdd/changes/archive/2026-08-17-messaging-ai/proposal.md:128`
    son **falsos positivos** del patrón: «p-retendiendo» contiene `retendiendo`. No se tocan.
