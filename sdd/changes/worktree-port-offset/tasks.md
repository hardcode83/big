# Tasks: worktree-port-offset

Orden pensado para que el repositorio quede funcionando tras cada sección: las
secciones 1-3 añaden un script host-side que **nadie invoca todavía** (el `Makefile`
sigue intacto, `make up` se comporta exactamente como hoy), la 4 lo cablea, y la 5
demuestra que la guardia de `compose-ports-guard` no se movió.

Regla de método heredada de `compose-ports.py` y vinculante en todas las tareas de
`scripts/compose-offset.py` (design D4): `config` **siempre** con `--no-interpolate
--no-env-resolution` desde una única constante; entorno del hijo por lista blanca;
listas de argumentos, nunca `shell=True`; estado de salida comprobado **aparte** del
contenido y sin pipes; nunca se vuelca `stdout` ajeno.

## 1. Cimiento del script: validación, aritmética y generación del overlay <!-- panel: PASS 2026-08-18 -->

- [x] 1.1 Escribir primero los casos en rojo de validación y aritmética en
  `scripts/test_compose_offset.py` (nuevo): `n` no entero (`-1`, `1.5`, ` 10`, `0x10`,
  `abc`) aborta nombrando **el valor recibido**; `n > 57535` aborta nombrando **qué
  puerto** se sale (el mayor base es 8000); `n` válido produce exactamente
  `{postgres 5432+n, redis 6379+n, backend 8000+n, frontend 3000+n}` con un solo
  sumando para los cuatro. Es TDD por obligación de método: la aritmética
  `offset ⇄ puerto` es la sede única del cálculo. [R1.1, R1.4, R5.1, R5.2]
- [x] 1.2 Crear `scripts/compose-offset.py` (stdlib, `python3` del host) con el
  esqueleto de subcomandos (`generate`, `check`, `announce`, `show`), las constantes
  de invocación endurecida copiadas literalmente de `scripts/compose-ports.py`
  (`COMPOSE`, `CONFIG_BASE`, `clean_env()`, `capture()`, `summarize()`,
  `STDERR_LIMIT`) y la validación + aritmética que pone en verde 1.1. [R1.1, R1.4,
  R5.1, R5.2]
- [x] 1.3 Implementar `generate <n>` en `scripts/compose-offset.py`: escribe
  `.make/docker-compose.offset.yml` con **números literales** (nunca
  `${..._HOST_PORT}`) y `ports: !override [<mapeo>]` para los cuatro servicios, con
  el prefijo de interfaz que le toca a cada uno (`127.0.0.1:` en `postgres`/`redis`,
  sin prefijo en `backend`/`frontend`), creando `.make/` si falta y regenerando el
  fichero byte a byte idéntico para el mismo `n`. Test en
  `scripts/test_compose_offset.py`: contenido esperado para un `n` dado, idempotencia
  del segundo `generate`, y que el fichero **no** contiene ningún `$`. [R1.1, R1.4,
  R2.1, R2.2]
- [x] 1.4 Añadir `.make/` a `.gitignore` (D5) y comprobar con `git status` que el
  overlay generado no aparece como untracked. [R1.1]
- [x] 1.5 Test sobre el propio código en `scripts/test_compose_offset.py` — mismo
  patrón que el de la guardia: que ninguna invocación de `config` del módulo pueda
  construirse sin las dos banderas, que el entorno del hijo se construye por lista
  blanca y que no hay `shell=True` en el fichero. Es el test que evita que una
  «mejora» futura reabra lo que D1 cierra. [R6.3]

## 2. `check <n>`: aserción de la configuración resuelta y sondeo de binds <!-- panel: PASS 2026-08-18 -->

- [x] 2.1 Escribir en rojo los casos de la aserción en
  `scripts/test_compose_offset.py`, sobre modelos JSON de `config` fabricados:
  igualdad **exacta** del conjunto de mapeos publicados (no contención, misma
  disciplina que `assert_inventory`); `!override` que no se aplicó (aparecen los dos
  mapeos, base y desplazado); un servicio extra con clave `ports`;
  `postgres`/`redis` sin `host_ip` o con uno distinto de `127.0.0.1`;
  `backend`/`frontend` **con** `host_ip`. Cada caso da rojo con mensaje que nombra
  servicio y mapeo. [R2.1, R2.2, R2.3, R6.1]
- [x] 2.2 Implementar en `scripts/compose-offset.py` la mitad de configuración de
  `check <n>`: invoca `docker compose -f docker-compose.yml -f
  .make/docker-compose.offset.yml config --no-interpolate --no-env-resolution
  --format json`, comprueba el estado de salida aparte, y asierta las dos mitades —
  el conjunto es exactamente el esperado para `n`, y ningún otro servicio trae clave
  `ports` (`worker`, `beat`, `migrate` incluidos). [R2.1, R2.2, R2.3, R6.1]
- [x] 2.3 Escribir en rojo y luego implementar el sondeo de binds de `check <n>` en
  `scripts/compose-offset.py`: sondea IPv4 y solo IPv4 (`127.0.0.1` para
  `postgres`/`redis`, `0.0.0.0` para `backend`/`frontend`), **sin** `SO_REUSEADDR`
  —falla hacia abortar— y **excluyendo los puertos que ya publica este mismo
  proyecto** (los obtiene la lógica de `show`, tarea 3.2), de modo que `make up`
  siga siendo idempotente sobre un stack ya levantado con el mismo `n`. Un puerto
  ocupado aborta nombrando **puerto y servicio**. Dejar escritos en el propio script
  los dos residuales aceptados: el hueco IPv6 de Q2 y el TOCTOU. [R5.3]

## 3. `announce <n>` y `show` <!-- panel: PASS 2026-08-18 -->

- [x] 3.1 Implementar `announce <n>` en `scripts/compose-offset.py`: imprime el modo
  (worktree enlazado o principal, y que en el principal desplazar **mueve el stack
  que hay**, no crea un segundo) y **enumera los cuatro puertos efectivos**, más la
  línea de Q1 avisando de que para abrirlo desde un móvil hay que usar la IP de LAN
  de esta máquina con `3000+n` — sin calcular la IP. Test del texto en
  `scripts/test_compose_offset.py`: aparecen los cuatro números y no aparece ningún
  valor del entorno. [R4.1]
- [x] 3.2 Implementar `show` en `scripts/compose-offset.py`: lee el stack **vivo** con
  `docker compose ps --format json` (nunca un fichero, nunca `docker inspect` sin
  `--format`) y **deriva** `n` de `published - target` para los cuatro servicios,
  imprimiendo los cuatro mapeos efectivos y el desplazamiento; el stack parado y el
  stack sin puertos publicados son estados normales que se informan, no errores.
  Tests sobre salidas de `ps` fabricadas: stack desplazado, stack sin desplazar,
  stack sin publicar, stack parado, y desplazamientos incoherentes entre servicios
  (se informa, no se inventa un `n`). [R4.2]

## 4. Cableado del `Makefile` <!-- panel: PASS 2026-08-18 -->

- [x] 4.1 En `Makefile`: `PORT_OFFSET ?=` y su normalización con
  `$(filter-out 0,$(strip $(PORT_OFFSET)))`, de modo que vacío y `0` se comporten como
  si no se hubiera pasado sin llamar a nadie. [R3.3]
- [x] 4.2 En `Makefile`: `COMPOSE_ARGS` gana la rama de desplazamiento manteniéndose
  **una sola definición** (tres ramas: desplazamiento → `-f docker-compose.yml -f
  .make/docker-compose.offset.yml`; worktree sin desplazamiento → como hoy; principal
  sin desplazamiento → Compose **desnudo**, sin `-f`). Con desplazamiento
  `docker-compose.worktree.yml` **no** se carga (D3), y la rama no mira
  `IS_WORKTREE`, que es lo que da R1.3. Comentario que prohíba explícitamente meter el
  overlay en el conjunto que Compose descubre por sí solo. [R1.3, R3.1, R3.2, R4.3]
- [x] 4.3 En `Makefile`, receta de `up`: insertar los pasos en el orden exacto de D7 —
  `generate` → aserción de configuración → sondeo → `announce` → `up`—, **todos antes
  de levantar**, y conservar **literal** la aserción de ausencia de `ports` de hoy en
  la rama sin desplazamiento (incluido el `case` sin pipe y el estado de salida
  comprobado aparte). Acotar el guard de «falta `docker-compose.worktree.yml`» a la
  rama sin desplazamiento y darle mensaje propio si el desplazamiento se pide y el
  overlay no puede combinarse — nunca degradar a «publicar lo que salga». [R1.1,
  R4.1, R5.3, R5.4, R6.1, R3.1, R3.2]
- [x] 4.4 En `Makefile`: nuevo target `ports` (`.PHONY`) que invoca
  `python3 scripts/compose-offset.py show`, con el comentario que explique por qué
  deriva del stack vivo y no del fichero generado. [R4.2]
- [x] 4.5 En `Makefile`: comentario en `down`/`logs`/`ps`/`sh` dejando escrito que
  **no** hace falta repetir `PORT_OFFSET` —direccionan el proyecto por nombre, que
  sale del directorio— y que es seguro que `up` y `down` operen sobre conjuntos de
  ficheros distintos porque el segundo no crea contenedores (D6). [R4.3]

## 5. Invariancia de la guardia de puertos <!-- panel: PASS 2026-08-18 -->

- [x] 5.1 Comprobar que `make check-compose-ports` da el **mismo veredicto** con
  `.make/docker-compose.offset.yml` presente en el árbol y con `PORT_OFFSET=10`
  exportado en la shell, y que `scripts/compose-ports.py` y
  `.github/workflows/compose-ports.yml` quedan **sin modificar** (`git diff` vacío en
  esos dos ficheros al cerrar). Es el resultado de D1, no un olvido. [R6.2, R6.3]
- [x] 5.2 Añadir a `scripts/test_compose_offset.py` el caso que fija la frontera: la
  ruta del overlay generado no es `docker-compose.override.yml` ni vive en la raíz, y
  `EXEMPT` de `scripts/compose-ports.py` sigue siendo exactamente
  `{("backend","8000"), ("frontend","3000")}`. Si alguien ensancha la exención o
  renombra el overlay, esto rompe. [R6.2, R6.3]

## 6. Documentación <!-- panel: PASS 2026-08-18 -->

- [x] 6.1 En `docker-compose.worktree.yml`: el comentario de cabecera deja de nombrar
  `PORT_OFFSET` como salida futura y pasa a describirlo como operativo, apuntando a
  que con desplazamiento este overlay **no se carga**. Sin cambios en los mapeos.
  [R1.1, R3.1]
- [x] 6.2 En `README.md`: §«Postura de red del stack local» recoge que la postura se
  conserva desplazada; el párrafo de worktrees (~40-42) deja de afirmar que en un
  worktree no hay nada que abrir en el navegador; §Estructura menciona `.make/` y
  §Arrancar/Comandos documentan `make up PORT_OFFSET=<n>` y `make ports`, incluida la
  advertencia de que un `make up SERVICE=<x>` parcial **sin repetir** el
  desplazamiento recrearía ese servicio sin puertos, y la de `FRONTEND_BASE_URL`
  (Q3): en un stack desplazado el enlace de recuperación de contraseña sigue
  apuntando a `localhost:3000` hasta que se ajuste en el `.env`. [R4.1, R4.3]
- [x] 6.3 Verificar con `grep` que ninguna instrucción de verificación local de
  `sdd/specs/frontend-auth-session.md` ni de `sdd/specs/api-contract.md` asume
  `localhost:3000` / `localhost:8000` literales de forma que el desplazamiento la
  invalide; si alguna lo hace, anotarlo para `/sdd:archive` en vez de tocar las specs
  aquí. [R2.4]

## 7. Verification

- [x] 7.1 Suite de los scripts host-side en verde, con el comando exacto del workflow
  `compose-ports.yml`:
  `uv run --no-project --with 'pytest==9.1.1' python -m pytest scripts/ -q`. Recoge
  `scripts/test_compose_offset.py` sin tocar ningún workflow. [R1, R2, R5, R6]
- [x] 7.2 Suite del backend sin cambios de resultado desde este worktree:
  `docker compose exec backend uv run pytest` — resuelve Postgres y Redis por nombre
  de servicio, así que el desplazamiento no está en ese camino. [R2.4]
- [x] 7.3 `make check-compose-ports` en verde. [R6.1, R6.2, R6.3]
- [x] 7.4 Defecto intacto: `make up` **sin** `PORT_OFFSET` en este worktree arranca sin
  publicar ningún puerto y sigue abortando en rojo si en la configuración resuelta
  queda alguna clave `ports` (comprobar además con `docker compose ps` que no hay
  `published`). Y `make -n up` con `IS_WORKTREE` vacío muestra `docker compose`
  **sin `-f`**, sin llegar a levantar el stack del principal —que puede ser de otra
  sesión—. [R3.1, R3.2]
- [x] 7.5 Desplazamiento de punta a punta en este worktree: `make up PORT_OFFSET=10`
  anuncia los cuatro puertos efectivos, `docker compose ps` los muestra publicados con
  la interfaz correcta (`127.0.0.1` en postgres/redis, todas en backend/frontend), y
  `curl -sS -o /dev/null -w '%{http_code}' http://localhost:3010` y `:8010/health`
  responden desde el host. [R1.1, R1.4, R2.1, R2.2, R4.1]
- [x] 7.6 `make ports` sobre el stack levantado en 7.5 informa `PORT_OFFSET=10` y los
  cuatro mapeos, y sobre el stack parado informa sin fallar. [R4.2]
- [x] 7.7 `make down` y `make logs` **sin** repetir `PORT_OFFSET` operan sobre el mismo
  stack de 7.5 y no sobre otro. [R4.3]
- [x] 7.8 Convivencia real: con el stack de 7.5 vivo, un segundo `make up
  PORT_OFFSET=20` desde otro directorio de trabajo arranca sin fallar por puerto
  ocupado. [R1.2]

  **Ejecutado el 2026-08-18, y la vía de escape que esta tarea ofrecía queda
  descartada por escrito**: el panel demostró que `make up PORT_OFFSET=20` tras un
  `make down` en el *mismo* directorio no puede probar R1.2 ni en principio, porque
  Compose saca el nombre de proyecto del directorio — es el mismo stack recreado, no
  dos conviviendo. El sondeo disjunto tampoco basta: prueba que los puertos no chocan
  en el bind, no que dos proyectos sostengan sus contenedores a la vez. Lo que se hizo
  es lo único que lo prueba: un `git worktree add --detach` **desechable** bajo el
  scratchpad (nunca un worktree ajeno; los otros de esta máquina son de sesiones
  vivas), `make up PORT_OFFSET=20` allí con el stack de 10 arriba, y los cuatro
  endpoints respondiendo 200 **a la vez** — `sddworktree-port-offset` publicando
  5442/6389/8010/3010 y `wt-concurrency` publicando 5452/6399/8020/3020. Después,
  teardown completo del desechable y `git worktree remove`.
- [x] 7.9 Los cuatro rojos de R5, ejecutados: `make up PORT_OFFSET=-1` y
  `PORT_OFFSET=abc` abortan nombrando el valor; `PORT_OFFSET=60000` aborta nombrando
  el puerto fuera de rango; con el stack de 7.5 vivo, `make up PORT_OFFSET=10` es
  idempotente (no aborta por sus propios puertos) mientras un `PORT_OFFSET` que
  solape un puerto ajeno aborta nombrando puerto y servicio **antes** de crear ningún
  contenedor. [R5.1, R5.2, R5.3]
- [x] 7.10 Panel de review de `/sdd:run`/`/sdd:review` en verde, incluidos
  `sdd-review-documentation` y `sdd-review-cicd`. [R6]

---

**Fuera de este checklist a propósito**: las ediciones de `sdd/specs/`, `sdd/project.md` y
`sdd/steering/` que enumera la tabla «Changes by area» del design — esa tabla es la lista, y no se
repite aquí para que no haya dos versiones de ella. `steering/documentation.md` reserva `sdd/specs/`
para el archivado, así que las aplica `/sdd:archive` con el design delante; la tarea 6.3 solo recoge
lo que haya que anotarle.

Dos de esas filas las **añadió el panel de `/sdd:review` el 2026-08-18** y conviene saber que no
son del diseño original: la corrección del suelo de Compose (`!override` pide ≥ 2.24.4, así que las
«dos cosas» que fijan el suelo son tres) y la frase que le falta a la regla 8 de
`steering/security.md` para no leerse como que `check-compose-ports` cubre también el modo
desplazado, que por D1 no puede ver.
