# Design: worktree-port-offset

## Context

`Makefile` decide por sí solo con qué ficheros habla Compose: detecta worktree enlazado
comparando `git rev-parse --git-dir` con `--git-common-dir` (`IS_WORKTREE`) y construye una
**única** definición del comando (`COMPOSE_ARGS` → `COMPOSE`) que usan los nueve targets que
invocan `docker compose` desde el `Makefile`. En el principal invoca Compose **desnudo**; en un
worktree enlazado añade `docker-compose.worktree.yml`, que retira los cuatro mapeos con
`ports: !reset []`, y antes de levantar comprueba con `config --no-interpolate
--no-env-resolution --format json` que **no queda ninguna clave `ports`**.

Los cuatro mapeos viven declarados en `docker-compose.yml` a propósito
(`127.0.0.1:5432:5432`, `127.0.0.1:6379:6379`, `8000:8000`, `3000:3000`), porque esa declaración
*es* la postura de red del proyecto. Desde `compose-ports-guard` (2026-08-18) esa postura la
comprueba `scripts/compose-ports.py` (`make check-compose-ports` + workflow `compose-ports`), que
invoca Compose **desnudo**, con el entorno del hijo construido **por lista blanca (`PATH` y nada
más)**, y exime exactamente dos pares literales servicio+puerto: `("backend","8000")` y
`("frontend","3000")`. Esa guardia es lo que hoy sostiene la exención de la regla 8 de
`steering/security.md` para `POSTGRES_PASSWORD`.

`sdd/specs/local-environment.md:354` dejó escrita la consecuencia para este change: *«un
desplazamiento escrito como `"127.0.0.1:${PORT_OFFSET}..."` daría rojo, y aquel change tendrá que
generar mapeos literales o reabrir esta regla a sabiendas»*. Este diseño toma la primera vía —
mapeos literales — y añade el dato que aquella frase no tenía: **hay un tercer eje**, el conjunto
de ficheros que la guardia carga. Un overlay que Compose nunca descubre por sí solo no entra en su
vista, así que el desplazamiento no la toca en absoluto.

## Tres medidas tomadas antes de decidir

Con Compose 5.1.1, en este worktree, con `--no-interpolate --no-env-resolution` (rc=0 las tres):

1. **`ports: !override` sustituye, no concatena.** Con `-f docker-compose.yml -f <overlay>` y
   `ports: !override ["127.0.0.1:5442:5432"]`, `postgres` sale con **una** entrada, no dos, y
   **normalizada**: `{"host_ip":"127.0.0.1","mode":"ingress","protocol":"tcp","published":"5442","target":5432}`.
   Los de `backend`/`frontend` salen **sin `host_ip`**, que es exactamente la forma que la guardia
   ya sabe leer.
2. **`base + overlay-de-desplazamiento` y `base + worktree` difieren SOLO en `ports`.** Comparadas
   clave a clave las dos configuraciones resueltas, la única diferencia son los cuatro `ports`. El
   `volumes` extra que `docker-compose.worktree.yml` añade a `backend`
   (`./.github/workflows/deploy-dev.yml:...:ro`) **ya está en el fichero base**, así que no cargar
   ese overlay cuando hay desplazamiento **no pierde nada**. Medido, no razonado.
3. **La ubicación del overlay no cambia el nombre de proyecto.** El overlay de la medida 1 vivía
   **fuera** del repositorio y la clave `name` del modelo salió idéntica: el directorio de proyecto
   lo fija el **primer** `-f`. Y con `!reset []` la clave `"ports"` está **ausente** (0
   coincidencias en el JSON), no presente con valor nulo — la aserción actual de `make up` sigue
   siendo la correcta.

## Decisions

### D1 — El desplazamiento vive en un overlay que Compose no descubre por sí solo; el fichero base no se toca

**Chosen:** los cuatro mapeos siguen declarados literalmente en `docker-compose.yml` y el
desplazamiento llega por un overlay cargado **solo con `-f` explícito**
(`.make/docker-compose.offset.yml`, ver D5). Es la decisión de cabecera y de ella cuelga todo R6:
la guardia delega el descubrimiento en Compose y sanea el entorno del hijo por lista blanca, así
que **no puede ver** un fichero que solo se carga con `-f` — ni siquiera con `COMPOSE_FILE`
exportado, que su `clean_env()` elimina. Consecuencia: `EXEMPT` no se toca, los dos pares literales
`backend:8000`/`frontend:3000` siguen describiendo lo que la guardia mira, y su veredicto sigue
siendo función **solo del repositorio** (R6.2, R6.3).

Rejected: parametrizar `ports` en `docker-compose.yml` con `${..._HOST_PORT:-5432}` — con
`--no-interpolate` el mapeo llega como cadena cruda, la guardia lo marca `mapeo-no-normalizado` y
el veredicto pasa a depender del entorno; es la limitación deliberada de `local-environment.md:352`.

Rejected: ensanchar `EXEMPT` a «cualquier `published` cuyo `target` sea 8000/3000» — convertiría la
exención de par literal en exención por servicio, que es la vía (c) del censo de elusión.

### D2 — El overlay se **genera** con números literales, no se commitea con interpolación

**Chosen:** un script genera el overlay con los cuatro puertos ya calculados. Lo pide R6.1 por su
propia redacción: la comprobación previa debe asertar que *«cada mapeo publicado es el esperado
para ese desplazamiento»*, y eso es una aserción **numérica**; con `--no-interpolate` un
`${POSTGRES_HOST_PORT}` es opaco y solo permitiría comparar plantillas. Con literales, la medida 1
demuestra que Compose normaliza a `{host_ip, published, target}` y la comprobación compara el
conjunto exacto — el mismo dato y la misma forma que usa la guardia. Además cierra dos trampas de
paso: ningún `ports` del repositorio queda dependiendo del entorno, y un `POSTGRES_HOST_PORT` en el
`.env` de alguien no puede desplazar nada.

Rejected: `docker-compose.offset.yml` commiteado con `${..._HOST_PORT:?}` y la aritmética en el
`Makefile` — más legible en el diff, pero deja R6.1 en «la plantilla es la esperada» en vez de «el
puerto es el esperado», y siembra en el repositorio un fichero que la guardia tendría que rechazar
si algún día lo viera.

### D3 — `!override` y no `!reset` + lista, y con desplazamiento `docker-compose.worktree.yml` no se carga

**Chosen:** el overlay generado usa `ports: !override [<mapeo>]`, que **sustituye** la lista del
base (medida 1). Con eso el mismo fichero vale igual en el principal y en un worktree enlazado, sin
depender del orden de `-f` ni de que alguien haya reseteado antes, y el overlay de worktree **queda
fuera** de la invocación cuando hay desplazamiento. La medida 2 es lo que hace esto seguro: sus dos
configuraciones difieren solo en `ports`.

Rejected: `-f base -f worktree -f offset` con `!reset []` y luego una lista que concatena sobre el
vacío — funciona, pero obliga a cargar «el overlay de worktree» también en el worktree principal
para poder desplazarlo ahí (R1.3), que es exactamente el tipo de invocación que no se lee.

### D4 — Un solo script host-side valida, calcula, genera, comprueba y anuncia

**Chosen:** `scripts/compose-offset.py` (stdlib, ejecutado con el `python3` del host, como los otros
tres) con subcomandos, y `scripts/test_compose_offset.py` al lado. Una sola sede para la aritmética
`offset ⇄ puerto` evita que el `Makefile` y el script deriven el mismo número por su cuenta, que es
la clase de deriva que este repositorio persigue. **Hereda literalmente la lista negra de
`compose-ports.py`**, y esto es vinculante: `config` **siempre** con `--no-interpolate
--no-env-resolution` desde una única constante; entorno del hijo por lista blanca; listas de
argumentos, nunca `shell=True`; estado de salida comprobado **aparte** del contenido y sin pipes; y
**nunca** se vuelca `stdout` ajeno (de `stderr`, solo su primera línea saneada y acotada).

Subcomandos previstos:

| subcomando | qué hace | requisitos |
|---|---|---|
| `generate <n>` | valida `n`, calcula los cuatro puertos, escribe el overlay | R1.1, R1.4, R5.1, R5.2 |
| `check <n>` | asierta la configuración resuelta y sondea los cuatro binds | R5.3, R6.1 |
| `announce <n>` | imprime modo y los cuatro puertos efectivos | R4.1 |
| `show` | lee el stack **vivo** y deriva su desplazamiento | R4.2 |

Rejected: resolverlo con aritmética de shell dentro del `Makefile` — la validación de R5 (entero no
negativo, rango, puerto ocupado, mensaje que nombra el valor recibido) en recetas de `make` es
justamente el estilo que `compose-ports-guard` desmontó, y no habría dónde colgarle una suite.

Rejected: un cuarto script separado para `show` — la conversión puerto↔desplazamiento es la misma
aritmética; separarla la duplica.

### D5 — El overlay generado vive en `.make/docker-compose.offset.yml`, gitignorado y regenerado siempre

**Chosen:** ruta **estable** dentro del repositorio y en un subdirectorio, por dos razones. (a) Es
conocida en tiempo de parseo, así que `COMPOSE_ARGS` sigue siendo **una sola definición** y el
criterio de los nueve targets de `local-environment.md` §«Makefile como entrypoint único` sobrevive
intacto; con `$(shell mktemp)` habría que construir la invocación dentro de la receta, es decir una
segunda definición. (b) Al estar en `.make/` y no llamarse `docker-compose.override.yml`, Compose no
lo descubre nunca (D1). Se **regenera en cada invocación** con desplazamiento: es función pura de
`n`, así que no hay estado que quede viejo, y el contenido byte a byte idéntico mantiene el hash de
configuración de Compose (un segundo `make up SERVICE=frontend` con el mismo `n` no recrea nada).
`.gitignore` gana `.make/`.

Rejected: fichero temporal borrado tras `up` — pierde (a), y con él el criterio de la única
definición.

Rejected: la raíz del repositorio — un `docker-compose.*.yml` más en la raíz invita a confundirlo
con los tres versionados, y la raíz es donde vive el conjunto canónico que la guardia mira.

### D6 — Solo `up` necesita el número; los demás targets hablan con el proyecto por nombre

**Chosen:** `COMPOSE_ARGS` se hace consciente del desplazamiento (una definición, tres ramas), pero
**no hace falta repetir el número**: `down`, `logs`, `ps` y `sh` direccionan el proyecto por su
nombre —que sale del directorio y es distinto por worktree—, no por sus puertos, así que funcionan
igual con `PORT_OFFSET` y sin él, y nunca acaban hablando con otro stack (R4.3). El único que
necesita el número es `up`, porque es el que **crea** los mapeos. `bootstrap`, `seed-demo`,
`db-clean-test` y `sh` usan `exec` (no crean nada) y `openapi` usa `run --rm --no-deps`, que
además **no publica puertos** salvo con `--service-ports`: ninguno puede chocar.

Consecuencia que hay que escribir en la spec porque contradice la lectura literal del criterio
vigente: con desplazamiento, un `up` al que se le pasó `PORT_OFFSET` y un `down` posterior al que no
operan sobre **conjuntos de ficheros distintos**, y es seguro precisamente porque el segundo no crea
contenedores. El criterio de los nueve targets sigue garantizando lo que garantizaba (una única
definición); lo que gana es esa frase.

Rejected: persistir el desplazamiento vigente en un fichero de estado para que los demás targets lo
lean — estado derivado en un segundo sitio, y `show` ya lo obtiene del stack vivo, que es la fuente
real.

### D7 — Orden de la comprobación previa: validar → calcular → generar → asertar la configuración → sondear → anunciar → levantar

**Chosen:** ese orden exacto, y todo antes de `up`. La aserción de configuración es la variante con
desplazamiento de la que ya existe (R6.1), y tiene **dos mitades**: el conjunto de mapeos publicados
es **exactamente** `{postgres 127.0.0.1:5432+n→5432, redis 127.0.0.1:6379+n→6379, backend
*:8000+n→8000, frontend *:3000+n→3000}` —igualdad, no contención, la misma disciplina que
`assert_inventory`—, y **ningún otro servicio trae clave `ports`** (R2.3). Un servicio nuevo con
mapeo, o un `!override` que no se aplicó, salen en rojo. Sin desplazamiento la comprobación es la de
hoy, palabra por palabra: en worktree, ausencia de la clave `ports`; en el principal, nada.

El sondeo de binds va **después** de la aserción y **antes** de levantar (R5.3): un puerto ocupado
aborta nombrando puerto y servicio, en vez de dejar que Compose falle a medio levantar. Se sondea en
la interfaz que le toca a cada uno —`127.0.0.1` para `postgres`/`redis`, `0.0.0.0` para
`backend`/`frontend`—, **solo en IPv4** (Q2, decidido en contra de la recomendación de este design;
el residual está escrito allí), y se **excluyen los puertos que ya publica este mismo proyecto**,
para que `make up` siga siendo idempotente sobre un stack ya levantado con el mismo desplazamiento
(los obtiene `show`).

Rejected: sondear después de levantar, o dejar que el error lo dé Compose — es el síntoma ilegible
que R5.3 existe para evitar.

Rejected: asertar los números con interpolación activada — prohibido por la regla de las dos
banderas; ahí está el motivo de D2.

### D8 — `make ports` lee el stack vivo y **deriva** el desplazamiento

**Chosen:** `make ports` invoca `compose-offset.py show`, que lee los mapeos publicados del proyecto
con `docker compose ps --format json` y deriva `n` de `published - target` para los cuatro
servicios, imprimiendo los cuatro mapeos efectivos y el desplazamiento (R4.2). Derivar del stack
vivo, y no de un fichero, es lo que hace que la respuesta sea verdad incluso si alguien levantó con
otro número. `--format json` es obligatorio por la misma lista negra que prohíbe `docker inspect`
sin `--format`; su salida no contiene entorno.

Rejected: leer `.make/docker-compose.offset.yml` — describe la última **intención**, no lo que está
corriendo, y en el principal sin desplazamiento no existe.

Rejected: `docker compose port <svc> <target>` cuatro veces — cuatro invocaciones en vez de una, y
sale con error cuando el servicio no corre, que aquí es un estado normal que hay que contar.

### D9 — La validación nombra el valor recibido y el puerto culpable

**Chosen:** `n` es aceptado solo si encaja la clase `[0-9]+` **entera** (entero no negativo; sin
signo, sin espacios, sin hexadecimal) y si los cuatro puertos caen en rango, es decir `n ≤ 57535`
porque el mayor de los cuatro bases es 8000 (R5.1, R5.2). Los mensajes nombran el valor recibido y,
en el caso del rango, **qué puerto** se sale. `PORT_OFFSET` vacío o `0` se comporta como si no se
hubiera pasado (R3.3), y lo resuelve el `Makefile` sin llamar a nadie.

**Corregido durante `/sdd:run` (2026-08-18), con las tres cosas medidas y no razonadas.** La
redacción anterior de esta decisión —`^[0-9]+$` en el script, y `$(filter-out 0,$(strip …))` como
única normalización en el `Makefile`— tenía tres agujeros que encontró el panel de review:

1. **`^[0-9]+$` con `re.match` acepta un salto de línea final**, porque en Python `$` encaja también
   antes de un `\n` final. Se usa `re.fullmatch` sobre `[0-9]+`.
2. **`$(filter-out 0,…)` compara por palabra, no por valor.** Un `PORT_OFFSET=00` no era filtrado y
   tomaba la rama del desplazamiento, generando un overlay que publica los puertos **sin desplazar**
   — la colisión exacta que este change existe para evitar, a partir de un dedazo. Y un
   `PORT_OFFSET='1 0'` perdía la palabra `0` y llegaba al validador como `1`, así que el valor que
   R5.1 promete nombrar nunca llegaba a nadie. La normalización pasa a ser «no le queda nada al
   quitarle los ceros».
3. **`make` interpola la variable en el TEXTO de la receta**, así que entrecomillarla no contiene un
   valor con una comilla dentro: la cierra, y lo que venga detrás se ejecuta. Medido con
   `PORT_OFFSET='1"; echo PWNED; "'`. Por eso el `Makefile` gana una **puerta de clase de caracteres
   en tiempo de parseo** (`subst` puro, sin pasar por ningún shell), que rechaza el valor antes de
   que llegue a ninguna receta. Es lo que manda el propio comentario de cabecera del `Makefile` para
   un valor que no escribe una persona —*«hay que entrecomillarlo y validarlo aquí»*—, y este se
   toma del entorno a propósito (D10). **El orden entre los dos pasos es parte de la decisión**:
   primero se rechaza, después se normaliza; al revés, la normalización convierte un valor
   inservible en uno válido y el rechazo no llega nunca.
4. **Y la puerta se lee con `$(value PORT_OFFSET)`, no con `$(PORT_OFFSET)`.** Una primera versión
   de la puerta seguía siendo eludible y de una forma peor: para `make` una variable de entorno es
   de expansión diferida, así que **nombrarla la expande**, y un `$(shell …)` dentro de su texto se
   ejecuta al evaluar la asignación — que, siendo de nivel superior, corre para **cualquier**
   target, incluido `make check-compose-ports`. `$(value …)` devuelve el texto sin expandir, así que
   la carga llega entera a la comprobación y se rechaza sin haberse ejecutado. Medido con un `touch`
   como carga y observando el fichero, no la salida: la salida pasa por un shell que hace su propia
   sustitución de `$(…)` y miente sobre lo que hizo `make`.

   **Residual declarado, que ningún constructo del `Makefile` puede cerrar**: una definición en la
   **línea de comandos** (`make up 'PORT_OFFSET=$(shell …)'`) la expande `make` al parsear sus
   argumentos, antes de leer el fichero. Ahí sí se ejecuta. Se acepta porque es exactamente el caso
   que la cabecera del `Makefile` ya declara aceptable para `$(SERVICE)` —auto-inyección de quien
   escribe en su propia terminal, sin ganancia de privilegio—, mientras que el canal que aquella
   nota señala como problema real es el no humano (un `.envrc`, un wrapper, un agente, un job de
   CI), y ése es el entorno, que es el que `$(value …)` cierra.

   Efecto colateral aceptado: la puerta corre en todos los targets, así que un `PORT_OFFSET`
   exportado con un valor malo impide también `make down`. El mensaje de error nombra la salida
   (`PORT_OFFSET= make down`) en vez de dejar a nadie atrapado con un stack levantado.

Sigue habiendo **una sola sede para la aritmética**: el `Makefile` decide únicamente la clase de
caracteres y la equivalencia con cero; el rango, el techo de 57535 y el mensaje que nombra el puerto
culpable viven solo en `scripts/compose-offset.py`.

Nota deliberada: dos de los cuatro puertos desplazados nunca pueden chocar **entre sí** (bases
distintas, mismo desplazamiento), pero sí pueden chocar con un puerto **no** desplazado de otro
stack —`PORT_OFFSET=2432` lleva el frontend al 5432 del Postgres del principal—. No hay regla
especial para eso: lo caza el sondeo de D7, que es general.

### D10 — `PORT_OFFSET` es variable de `make`, no variable de entorno de la aplicación

**Chosen:** no entra en `.env.example` ni en `Settings`, y el overlay generado lleva números
literales, así que nada del `.env` puede desplazar el stack. Se dice explícitamente porque la regla
de `steering/documentation.md` («variable de entorno nueva → `.env.example`») no aplica: no la lee
ni la aplicación ni Compose.

Y `make` sí toma sus variables del entorno, así que un `export PORT_OFFSET=10` en la shell de un
worktree desplaza todos sus `make up` sin repetirlo — deliberado y útil. Lo que **no** puede hacer
es mover a la guardia: `check-compose-ports` no pasa por `$(COMPOSE)` y su script construye el
entorno del hijo por lista blanca, así que un `PORT_OFFSET` exportado no cambia su veredicto. Esa es
la demostración de R6.3.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Orquestación local | `Makefile` | `PORT_OFFSET ?=` + normalización (D9); `COMPOSE_ARGS` gana la rama de desplazamiento (D6); `up` gana los pasos generar → asertar → sondear → anunciar (D7); el guard de `docker-compose.worktree.yml` ausente queda acotado a la rama sin desplazamiento (R5.4); nuevo target `ports` (D8). La aserción actual de ausencia de `ports` se conserva **literal** en la rama sin desplazamiento (R3.1) |
| Herramienta host-side | `scripts/compose-offset.py` **(nuevo)** | Validación, aritmética, generación del overlay, aserción de la configuración resuelta, sondeo de binds, anuncio y lectura del stack vivo (D4). Hereda la lista negra de `compose-ports.py` |
| Suite | `scripts/test_compose_offset.py` **(nuevo)** | Recogida **sin tocar workflows**: `compose-ports.yml` ya ejecuta `pytest scripts/ -q`. Casos en rojo por obligación de método: offset no entero, fuera de rango, puerto ocupado, overlay que no se aplicó, servicio extra con `ports`, `postgres`/`redis` fuera de `127.0.0.1`, invocación de `config` sin las dos banderas (test sobre el propio código, como el de la guardia) |
| Ignorados | `.gitignore` | `.make/` (D5) |
| Guardia | `scripts/compose-ports.py`, `.github/workflows/compose-ports.yml` | **Sin cambios**, y es un resultado del diseño, no un olvido: D1 deja su vista y su veredicto intactos |
| Compose | `docker-compose.yml`, `docker-compose.worktree.yml`, `docker-compose.deploy.yml` | **Sin cambios** en los mapeos. En `docker-compose.worktree.yml` cambia solo el comentario de cabecera, que hoy nombra `PORT_OFFSET` como salida futura |
| Especificación | `sdd/specs/local-environment.md` | §Postura de red: la postura se conserva desplazada. §Stacks en paralelo: el bullet 134-136 pasa de «si alguna vez hace falta» a describir el desplazamiento; el criterio de la comprobación previa gana su variante. §Guardia: el párrafo de la limitación por interpolación (`:352-355`) registra que el change tomó la vía de los mapeos literales **y** el tercer eje de D1. §Makefile: `ports`, el parámetro, y la frase de D6 |
| Especificación | `sdd/specs/domain-foundation-core.md:39` | Matiz: el `localhost:5432` del host ya no es exclusivo del principal — un worktree desplazado publica `5432+n` |
| Documentación | `sdd/project.md:72`, `README.md` (~40-42, §Postura de red, §Estructura) | «Lo que no tendrás en un worktree: navegador» pasa a operativa; `.make/` y `make ports` en la estructura y los comandos |
| Documentación | `sdd/project.md`, `sdd/specs/local-environment.md` (§suelo de versiones) | **Añadido en review (2026-08-18)**: el suelo de Compose lo fijan ahora **tres** tags/banderas y no dos — `!override` (el del overlay generado) pide **≥ 2.24.4**. Sigue mandando 2.35.0, así que el suelo efectivo no se mueve; lo que se corrige es la frase que dice «dos cosas». `README.md` ya va corregido aquí |
| Steering | `sdd/steering/security.md` (regla 8) | **Añadido en review (2026-08-18)**: la regla nombra `make check-compose-ports` como *la* guardia de la postura, pero por D1/R6.3 esa guardia **no puede ver** el modo desplazado. Ahí la postura la sostienen la tabla `SERVICES` de `scripts/compose-offset.py` y sus tests, que el **mismo** workflow recoge. Falta una frase que lo nombre para que nadie lea la regla como cobertura total. No es exposición: verificado que el workflow va en rojo igual |

Sin `docs/<capability>.md` y sin diagrama, por decisión: esto es tooling del monorepo y no una
capability de usuario —`compose-ports-guard` no creó página por lo mismo—, y un diagrama de «cuatro
puertos con un sumando» diría menos que la tabla de arriba.

## Data & interfaces

**Ningún cambio de esquema, de API ni de contrato.** `BACKEND_INTERNAL_URL: http://backend:8000` y
`REDIS_URL: redis://redis:6379/0` no se tocan: el desplazamiento mueve `published`, nunca `target`,
así que la resolución por nombre de servicio dentro de la red de compose es idéntica y el proxy
`/api/` del frontend y la suite del backend no ven el desplazamiento en absoluto (R2.4).

Interfaz nueva, `PORT_OFFSET=<n>` en `make up`, con esta tabla para un desplazamiento `n`:

| servicio | interfaz | puerto de host | puerto de contenedor |
|---|---|---|---|
| `postgres` | `127.0.0.1` | `5432+n` | 5432 |
| `redis` | `127.0.0.1` | `6379+n` | 6379 |
| `backend` | todas | `8000+n` | 8000 |
| `frontend` | todas | `3000+n` | 3000 |

`worker`, `beat` y `migrate` siguen sin publicar nada (R2.3). Sin `PORT_OFFSET`, o con `0`, la tabla
no existe y todo se comporta como hoy (R3).

**Fichero generado** (no versionado): `.make/docker-compose.offset.yml`, solo claves `ports` con
`!override` para esos cuatro servicios.

## Risks & mitigations

- **El sondeo de bind y el bind real de Docker son dos momentos distintos (TOCTOU).** Alguien puede
  ocupar el puerto en la ventana. Mitigación: se acepta; el fallo degrada al error de Compose, que
  nombra el puerto, y el sondeo elimina el caso habitual (el otro stack ya levantado).
- **Un `SO_REUSEADDR` mal elegido convierte el sondeo en mentira.** Sin él, un puerto en `TIME_WAIT`
  se reporta ocupado sin estarlo; con él, un bind puede tener éxito donde Docker fallará.
  Mitigación: sondear **sin** `SO_REUSEADDR` — falla hacia abortar, que es la dirección correcta — y
  dejarlo dicho en el propio script.
- **El sondeo es solo IPv4, así que un puerto ocupado únicamente en `::` lo atraviesa** (Q2, decidido
  a sabiendas). Mitigación: residual aceptado y escrito; el fallo degrada al error de Compose, que
  nombra el puerto. Ensancharlo es una línea el día que aparezca.
- **`make up SERVICE=<x>` parcial sin repetir el desplazamiento recrearía ese servicio sin puertos.**
  Es el único target donde el número importa (D6). Mitigación: documentarlo en README y en la spec;
  la aserción de D7 no lo cubre porque en ese caso no se ejecuta.
- **En el principal, desplazar no crea un segundo stack: mueve el que hay.** El nombre de proyecto es
  el directorio, así que `make up PORT_OFFSET=n` recrea los cuatro servicios en los puertos nuevos —
  que es justo lo que R1.3 pide («apartarse»), pero se lee mal si no está escrito. Mitigación: el
  anuncio de R4.1 lo dice al arrancar.
- **`FRONTEND_BASE_URL` por defecto es `http://localhost:3000`** (`.env.example:85`,
  `specs/auth-account-recovery.md:341`), así que en un stack desplazado el enlace de recuperación de
  contraseña apunta al frontend **de otro** stack. Mitigación: documentarlo; ver Q3, que es la
  decisión de si además se corrige.
- **Un `.make/` viejo de otro `n`.** Mitigación: se regenera en cada invocación con desplazamiento
  (D5), así que no hay ruta por la que se lea uno viejo.
- **La guardia se queda ciega si alguien «mejora» el diseño metiendo el overlay en el conjunto
  descubierto** (renombrarlo a `docker-compose.override.yml`, o añadir un `-f` al target de la
  guardia). Mitigación: es el punto de D1, y va escrito como prohibición en el comentario del
  `Makefile` y en la spec, igual que las otras dos prohibiciones que ya viven ahí.

## Cobertura de requisitos

| Req | Dónde se resuelve |
|---|---|
| R1.1, R1.4 | D2, D4 (`generate`), tabla de Data & interfaces |
| R1.2 | D1 + D3: puertos distintos y nombres de proyecto distintos; el sondeo de D7 lo prueba antes de arrancar |
| R1.3 | D6 (`COMPOSE_ARGS` no mira `IS_WORKTREE` cuando hay desplazamiento) + riesgo «mueve el que hay» |
| R2.1, R2.2 | Tabla de Data & interfaces; asertado por la igualdad de conjuntos de D7 y por la suite de D4 |
| R2.3 | Segunda mitad de la aserción de D7 (ningún otro servicio con `ports`) |
| R2.4 | Data & interfaces: solo se mueve `published` |
| R3.1, R3.2 | D9 (normalización en `make`) + D6: sin desplazamiento, `COMPOSE_ARGS` es exactamente el de hoy, incluido el Compose desnudo en el principal |
| R3.3 | D9 |
| R4.1 | D4 (`announce`), D7 (orden) |
| R4.2 | D8 |
| R4.3 | D6 |
| R5.1, R5.2 | D9 |
| R5.3 | D7 (sondeo, con exclusión del propio proyecto) |
| R5.4 | D3: con desplazamiento el overlay de worktree no se carga, así que no hay combinación que pueda fallar; el guard de fichero ausente queda acotado a la rama sin desplazamiento |
| R6.1 | D7 (las dos variantes, y la de hoy conservada literal) |
| R6.2, R6.3 | D1 y D10 |

## Open questions

Ninguna abierta. Las cuatro que este design planteó se resolvieron con Jose el 2026-08-18, y **una
de ellas en contra de la recomendación**; se listan por su estado final.

**Q1 — El anuncio imprime los cuatro puertos y avisa de que el móvil necesita la IP de LAN, sin
calcularla.** El motivo entero del change es abrir la app desde un móvil real, y para eso
`localhost:3000+n` no sirve; pero resolver la IP (`ipconfig getifaddr en0` / `hostname -I`) es
específico de plataforma y falla de formas que se leen como un bug del stack. Así que el anuncio
enumera los cuatro puertos efectivos (R4.1) y añade una línea diciendo que para el móvil hay que
usar la IP de esta máquina con el puerto `3000+n`.

**Q2 — El sondeo comprueba SOLO IPv4** (`127.0.0.1` para `postgres`/`redis`, `0.0.0.0` para
`backend`/`frontend`). **Decidido en contra de la recomendación de este design**, que proponía
sondear también `::` para los dos que publican en todas las interfaces. Residual aceptado, y va
escrito aquí y en el script para que no se descubra como un bug: un puerto ocupado **solo** en `::`
y libre en `0.0.0.0` pasa el sondeo y falla al levantar, con el error de Compose en vez del mensaje
propio de R5.3. Es un hueco estrecho —requiere un proceso escuchando en IPv6 y no en IPv4 en ese
mismo puerto— y ensancharlo después es una línea, no un rediseño.

**Q3 — `FRONTEND_BASE_URL` se documenta, no se inyecta.** El overlay generado se queda estrictamente
en `ports`, que es lo que mantiene la aserción de D7 y la historia de R2 en una sola cosa. En un
stack desplazado, el enlace de recuperación de contraseña sigue apuntando a `localhost:3000` hasta
que se ajuste `FRONTEND_BASE_URL` en el `.env`; para un móvil de la LAN un `localhost` tampoco
valdría, así que inyectarlo habría resuelto medio caso a cambio de ensanchar el overlay.

**Q4 — El target de consulta se llama `make ports`.** Lo que se consulta es el desplazamiento
vigente y sus cuatro mapeos, no una lista de URLs, y `make check-compose-ports` ya fija «ports» como
el vocabulario de esta área.
