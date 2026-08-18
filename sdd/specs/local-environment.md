# Entorno de desarrollo local

## Purpose

Scaffold de monorepo y stack de desarrollo local para AutoHostAI: estructura de repo por componente, orquestación con Docker Compose y un Makefile como único punto de entrada, construidos para ser compatibles con un futuro despliegue remoto sin rehacer imágenes ni estructura.

## Requirements

### Estructura de monorepo por componente

- El repo contiene `backend/` (FastAPI + Celery) y `frontend/` (Next.js App Router), cada uno con su propio `devops/Dockerfile` junto a su código.
- No existe un directorio `/docker` compartido a nivel de raíz: `docker-compose.yml` y `Makefile` orquestan todos los componentes desde la raíz del repo porque necesitan conocerlos a todos a la vez.
- Un componente nuevo sigue la misma convención (directorio propio + `devops/Dockerfile` propio) sin cambiar el layout raíz.

### Stack local vía Docker Compose

- WHEN se ejecuta `docker compose up` (o `make up`) en la raíz, THE SYSTEM SHALL arrancar los servicios `postgres` (postgres:16), `redis` (redis:7), `migrate` (aplica las migraciones Alembic y termina), `backend`, `worker` (Celery, misma imagen que backend), `beat` (el scheduler de Celery, misma imagen y volumen `.venv` propio) y `frontend`.
- `backend`, `worker` y `beat` esperan `condition: service_completed_successfully` de `migrate` antes de arrancar — el esquema de base de datos existe siempre antes de que la app reciba tráfico, sin paso manual (ver spec `domain-foundation-core` para el contenido del esquema).
- WHILE los contenedores `backend`/`frontend` corren en el target `dev`, THE SYSTEM SHALL reflejar cambios de código sin reconstruir la imagen (bind mount del código + volumen nombrado propio por servicio para `.venv`/`node_modules`, para evitar que el bind mount los pise).
- WHEN arranca (o se reinicia) el contenedor `frontend` en target `dev` y el `package-lock.json` difiere de lo instalado en su volumen `node_modules`, THE SYSTEM SHALL instalar las dependencias del lockfile (`npm ci`) antes de ejecutar `next dev` — vía el entrypoint `frontend/devops/docker-entrypoint.sh`, que compara el hash del lockfile con el que guarda en un fichero .lock-hash **dentro del volumen** de node_modules — creado en tiempo de ejecución dentro del contenedor, así que no existe en el árbol del repositorio. Añadir o actualizar dependencias del frontend no requiere `npm install` manual ni reconstruir la imagen; evita el `Module not found` clásico por volumen nombrado desactualizado. `node_modules` permanece en `/app` (lo exige el root de compilación de Turbopack).
- WHILE el `package-lock.json` del frontend no cambie entre arranques, THE SYSTEM SHALL NOT reinstalar `node_modules` (arranque rápido), determinándolo por comparación de hash del lockfile.
- IF el `package-lock.json` falta o no es legible en el contenedor `frontend`, THEN THE SYSTEM SHALL abortar el arranque con un error explícito en vez de continuar con dependencias inconsistentes.
- Las dependencias del frontend se instalan siempre con `npm ci` (reproducible a partir del lockfile), tanto al construir la imagen como en la sincronización automática de dev; una desincronización entre `package.json` y `package-lock.json` falla de forma explícita (comportamiento de `npm ci`).
- `backend` y `worker` NUNCA comparten el volumen de `.venv` entre sí (aunque comparten imagen) — hacerlo produce una condición de carrera al arrancar ambos a la vez.
- `postgres` y `redis` declaran `healthcheck`; `backend`/`worker` esperan `condition: service_healthy` de ambos antes de arrancar. `frontend` espera solo a que `backend` haya iniciado (`condition: service_started`).
- IF falta `POSTGRES_DB`, `POSTGRES_USER` o `POSTGRES_PASSWORD` en `.env`, THEN THE SYSTEM SHALL fallar el arranque de `docker compose up` con un mensaje explícito (`${VAR:?mensaje}`) en vez de arrancar mal configurado — defensa en profundidad para quien use `docker compose` directo sin pasar por `make up`.
- IF falta `JWT_SECRET_KEY`, THEN THE SYSTEM SHALL fallar igual, y en los **tres** servicios que importan la configuración al arrancar: `backend`, `worker` y `migrate`. Omitirla en cualquiera de ellos convertiría un despliegue en un fallo de arranque en cadena, porque `backend` y `worker` dependen de que `migrate` termine con éxito.
- `REDIS_URL` (backend/worker), `BACKEND_INTERNAL_URL` (frontend) y `DATABASE_URL` (backend/worker/migrate) están fijados directamente en `docker-compose.yml` vía `environment:` — no vienen de `.env`, porque su valor lo determina la topología de la red de compose, no algo que un desarrollador deba decidir.

### Postura de red del stack local

Los cuatro mapeos que describe esta sección son los del **worktree principal**. Un worktree enlazado
de git levanta su stack **sin publicar ninguno**: ver §«Stacks en paralelo por worktree».

- THE SYSTEM SHALL publicar `postgres` y `redis` **únicamente en la interfaz de loopback**
  (`127.0.0.1:5432:5432` y `127.0.0.1:6379:6379` en `docker-compose.yml`), de forma que no sean
  alcanzables desde otros equipos de la red a la que esté conectada la máquina.
- WHERE un mapeo se declara sin prefijo de interfaz, Docker publica en `0.0.0.0`; el prefijo
  `127.0.0.1:` es lo único que distingue una cosa de la otra. Acotar a loopback **elimina también
  el binding IPv6**: los servicios acotados no exponen `::`, y los que publican en todas las
  interfaces sí.
- **Por qué no es higiene.** Ese Redis guarda los contadores del límite de intentos de login
  (`login:ip:*`, `login:fail:*`, `login:lock:*`, ver `backend/app/auth/infrastructure/throttle.py`
  y la spec `auth-tenancy`), y corre **sin `requirepass`**. Quien alcance el puerto puede borrarlos
  entre intentos, con lo que el límite de 10 intentos/min por IP y el bloqueo tras 10 fallos que
  exige la regla 7 de `steering/security.md` no se disparan nunca. **La defensa de esos contadores
  en dev local es este bind, no la autenticación de Redis.**
- IF alguna vez se necesita exponer `redis` fuera de loopback, THEN THE SYSTEM SHALL exigir que se
  resuelva antes su autenticación.
- THE SYSTEM SHALL publicar `backend` (`8000`) y `frontend` (`3000`) en **todas** las interfaces, y
  es deliberado: el proyecto es mobile-first y abrir la app desde un móvil real por la IP de LAN es
  cómo se comprueba el diseño en un viewport de verdad. Acotarlos a loopback eliminaría esa vía.
  `worker`, `beat` y `migrate` no publican ningún puerto.
- Consecuencia que conviene no leer de más: **el stack local no es «inalcanzable desde la red»**.
  La UI y la API sí lo son para quien comparta red; lo que no lo es es el acceso directo al
  datastore. Y lo que se cierra es la explotación **desde la red**: con Redis sin `requirepass`,
  otro proceso de la propia máquina sigue pudiendo tocar esos contadores — residual aceptado
  porque es una máquina de desarrollo con datos de prueba.
- WHILE el stack está levantado, THE SYSTEM SHALL seguir permitiendo que los contenedores alcancen
  Postgres y Redis **por nombre de servicio** a través de la red de compose (`postgres:5432`,
  `redis:6379`): el bind acota la publicación en el *host*, no la red interna. En el principal
  `localhost:5432` / `localhost:6379` siguen sirviendo desde el host, incluida la suite ejecutada
  fuera de Docker, que cae a ese valor por defecto (ver spec `domain-foundation-core`); en un worktree
  enlazado no, porque allí no se publica nada — y no hace falta, porque la suite corre dentro del
  contenedor y va por la red de compose.
- El camino `/api/` del frontend existe en local con la **misma forma** que en el desplegado, de
  modo que la aplicación use siempre la misma URL relativa. La **confianza en cabeceras de proxy
  no**: el `backend` local arranca con `--forwarded-allow-ips 127.0.0.1`, y el motivo es
  exactamente el mapeo `8000:8000` en todas las interfaces que esta misma sección justifica —
  con el puerto abierto a la LAN, la cabecera la suministra quien llama. Consecuencia aceptada
  en local: el límite por IP degrada a un contador único (spec `auth-tenancy`
  §Identificación del cliente).
- **Esta postura no tiene comprobación automática todavía.** Si alguien publica un puerto sin el
  prefijo, hoy solo lo atrapa la revisión del diff. La guardia que lo comprobaría en cada PR es la
  entrada `compose-ports-guard` del roadmap, separada del change que estableció esta postura
  porque construirla bien resultó tener más fondo del que aparenta — su enunciado lleva el censo de
  vías de elusión ya demostradas.
- **Conjunto de ficheros canónico, que es lo que esa guardia tiene que mirar**: en el worktree
  principal, `docker-compose.yml` **a secas** — el `Makefile` lo invoca sin `-f`, así que lo que
  Compose descubre por sí solo *es* la postura real y una comprobación desnuda no puede quedarse
  corta. En un worktree enlazado, `docker-compose.yml` **+** `docker-compose.worktree.yml`, en ese
  orden. Los mapeos siguen declarados en el fichero base a propósito: sacarlos a un fichero aparte
  habría dejado la vista desnuda sin puertos y la guardia pasando en vacío.
- WHERE se inspeccione la postura con `docker compose config`, THE SYSTEM SHALL exigir un `.env`
  presente **y completo**: tres servicios declaran `env_file: .env` y el compose interpola
  `${POSTGRES_DB:?...}`, `${POSTGRES_PASSWORD:?...}` y `${JWT_SECRET_KEY:?...}`, así que en un clon
  limpio falla — y copiar `.env.example` **no basta**, porque su `JWT_SECRET_KEY` va vacía a propósito
  y la genera `make up`. Es requisito de existencia *y* de interpolación.
- **Qué NO detecta una comprobación que busque un puerto de host publicado**: hay formas legales de
  `ports:` que no declaran ninguno —la corta con solo el puerto del contenedor (`ports: ["5432"]`) y
  la larga sin `published` (`{target: 6379, mode: ingress}`)— y Docker las publica en un puerto
  **efímero y en todas las interfaces**. La aserción fiable es sobre la **presencia de la clave
  `ports`**, no sobre `published` ni `host_ip`. Fuera del alcance de cualquiera de las dos:
  `network_mode: host`, que publica sin declarar mapeo alguno y que hoy ningún servicio usa.

### Stacks en paralelo por worktree

- WHEN se ejecuta cualquier target del `Makefile` que hable con Compose, THE SYSTEM SHALL determinar
  por sí mismo si el directorio es el worktree principal o uno enlazado, comparando
  `git rev-parse --path-format=absolute --git-dir` con `--git-common-dir`: en el principal apuntan al
  mismo `.git`; en un worktree enlazado el primero es `<común>/.git/worktrees/<nombre>`. Sin variables
  de entorno, ficheros marcadores ni pasos manuales.
- WHERE el directorio es un worktree enlazado, THE SYSTEM SHALL añadir
  `docker-compose.worktree.yml`, que retira los cuatro mapeos con `ports: !reset []` — la fusión de
  Compose concatena arrays, así que un override no puede quitar puertos por la vía normal.
- WHERE el directorio es el worktree principal, THE SYSTEM SHALL invocar `docker compose` **sin
  `-f`**, de forma que su comportamiento y la vista que Compose descubre por sí solo sean los mismos
  que antes de que existiera el soporte de worktrees.
- WHILE el worktree principal tiene su stack levantado, WHEN se ejecuta `make up` en un worktree
  enlazado, THE SYSTEM SHALL arrancar todos sus servicios sin fallar por puerto ocupado. Compose ya
  aísla contenedores, red y volúmenes por nombre de proyecto —que sale del nombre del directorio—, así
  que la publicación en el host era lo único que colisionaba.
- WHILE dos stacks están levantados, THE SYSTEM SHALL mantener sus datos separados: los volúmenes con
  nombre van por proyecto, así que la base de datos de uno no es visible desde el otro.
- WHEN se ejecuta la suite del backend dentro del contenedor desde un worktree enlazado, THE SYSTEM
  SHALL resolver Postgres y Redis por nombre de servicio a través de la red de compose y dar el mismo
  resultado que en solitario: los puertos publicados nunca estuvieron en ese camino.
- WHEN `make up` arranca, THE SYSTEM SHALL anunciar en qué modo lo hace (publicando puertos, o sin
  publicarlos y por tanto sin UI ni API alcanzables desde el navegador del host).
- IF el modo es worktree, THEN THE SYSTEM SHALL comprobar **antes de levantar** que la configuración
  resuelta no contiene ninguna clave `ports`, y abortar en rojo si la hay — cubre a la vez un servicio
  con puerto que nadie añadió al overlay y un Compose anterior a 2.24 que ignore `!reset`. El estado
  de salida de `config` se comprueba aparte del contenido: un `config` que falle aborta con mensaje
  propio en vez de degradar la comprobación a verde.
- IF el modo es worktree y `docker-compose.worktree.yml` no existe, THEN THE SYSTEM SHALL abortar con
  un mensaje que diga que esa rama es anterior al soporte de stacks en paralelo, en vez del error de
  fichero no encontrado de Compose.
- IF git no está disponible o el directorio no es un repositorio, THEN THE SYSTEM SHALL comportarse
  como el worktree principal —publicar— y decirlo. Es deliberado: una colisión de puertos aborta
  nombrando el puerto, mientras que no publicar en silencio se manifiesta como «la app no carga».
- THE SYSTEM SHALL requerir **Docker Compose ≥ 2.24** (por el tag `!reset`) y **git ≥ 2.31** (por
  `--path-format`). Por debajo del suelo de git la detección falla hacia publicar, así que un worktree
  chocaría de puertos en vez de arrancar sin ellos.
- **Lo que un worktree enlazado no tiene**: nada alcanzable desde el navegador del host, ni un cliente
  gráfico contra `localhost:5432`. Si alguna vez hace falta, la salida es parametrizar los cuatro
  puertos con un desplazamiento (`PORT_OFFSET`), no volver a publicarlos sin más.
- **Coste, que no desaparece**: los volúmenes van por proyecto, así que el stack de un worktree
  arranca con base de datos **vacía**, reinstala dependencias la primera vez y ocupa sus propios gigas.
  Se siembra con `make bootstrap`, y con `make seed-demo` detrás si se quiere un stack recorrible
  en vez de un dashboard vacío (ver spec `seed-data-demo`).
- **Stacks huérfanos**: borrar un worktree sin bajar su stack deja sus contenedores y volúmenes vivos,
  y lo que retiene un huérfano es **disco** —volúmenes e imágenes—, **no puertos**: un worktree
  enlazado no publica ninguno, así que solo el stack del principal puede chocar de puertos y el coste
  de un huérfano es silencioso, sin síntoma que avise. Y el caso habitual no es «directorio borrado»
  sino «worktree desregistrado con el directorio en pie», porque `git worktree remove --force`
  **falla** sobre los ficheros que Docker creó por bind-mount. Por eso: `make down` antes de borrar el
  worktree, y `make compose-stacks` para verlo a posteriori (§«Diagnóstico de stacks de Compose»).

### Diagnóstico de stacks de Compose

`make compose-stacks` ejecuta `python3 scripts/compose-stacks.py`, que lista los proyectos de Compose
de la máquina y marca cuáles quedaron huérfanos. Informa; no actúa.

- THE SYSTEM SHALL listar cada proyecto de Compose de la máquina —incluidos los **parados**, vía
  `docker compose ls -a --format json`— con su nombre, su estado y el directorio desde el que se
  levantó. Los parados entran porque un huérfano parado retiene exactamente el mismo disco que uno
  corriendo, que es la motivación entera del diagnóstico.
- THE SYSTEM SHALL consultar el ámbito de **toda la máquina**, y por eso este target es
  deliberadamente el segundo que **no** pasa por `$(COMPOSE)`: acotarlo a los ficheros de este
  directorio dejaría fuera justo los stacks ajenos que busca.
- THE SYSTEM SHALL derivar el directorio de origen del **primer** fichero de `ConfigFiles`, que es el
  que Compose toma como directorio del proyecto cuando nadie pasa `--project-directory` — y el
  `Makefile` nunca lo pasa.
- THE SYSTEM SHALL clasificar cada proyecto con cuatro reglas **en este orden**, comparando rutas
  resueltas (`Path.resolve()`, que normaliza `..` y enlaces simbólicos aunque el directorio ya no
  exista):
  1. `ConfigFiles` vacío, con algún fragmento no absoluto o con un byte NUL → **`indeterminado`**,
     nombrando el motivo. El campo llega unido por comas y una ruta puede contener una coma: la
     ambigüedad se **detecta** exigiendo que todos los fragmentos sean absolutos, nunca se adivina.
     Ausencia de dato no es evidencia de abandono.
  2. El directorio de origen **coincide exactamente** con una raíz registrada en
     `git worktree list --porcelain` → **`vivo`**, atribuido a ese worktree y a su rama.
  3. El directorio de origen cuelga del árbol del worktree **principal** → **`huérfano`**.
  4. El resto → **`ajeno`**, sin proponer nada sobre él.
- THE SYSTEM SHALL aplicar la igualdad exacta **antes** que la pertenencia al árbol, porque los
  worktrees de este repositorio viven **dentro** del principal (`<principal>/.claude/worktrees/…`):
  una regla de «prefijo registrado más largo» atribuiría un worktree desregistrado al principal y lo
  daría por vivo. Funciona porque cada proyecto tiene su fichero de compose en la **raíz** de su
  worktree — la regla asume un proyecto por raíz, condición a revisar si algún día se añade uno
  anidado (hoy se marcaría como huérfano; el informe imprime la ruta, así que se ve de un vistazo).
- THE SYSTEM SHALL decidir «huérfano» por lo que dice `git worktree list` y **nunca** por lo que haya
  en disco: la existencia del directorio se imprime como dato, no se usa como criterio, precisamente
  porque el caso habitual es «worktree desregistrado con el directorio en pie».
- THE SYSTEM SHALL tomar como raíz del repositorio el **primer** registro de
  `git worktree list --porcelain` —git documenta que el principal va primero—, de forma que el
  veredicto es el mismo se lance desde el worktree que se lance.
- IF `docker` o `git` faltan del `PATH`, el demonio no responde, un comando sale con código distinto
  de cero, el JSON no es una lista de objetos con las tres claves `Name`/`Status`/`ConfigFiles`,
  `git worktree list` no devuelve registros, alguna de sus rutas no es absoluta, o el repositorio es
  `bare`, THEN THE SYSTEM SHALL abortar nombrando el problema y salir con código **1** — nunca
  presentar un inventario vacío como si no hubiera stacks. Una lista vacía con código cero es un
  inventario vacío legítimo, y se distingue del fallo por el **código de salida**, no por la forma de
  la salida.
- WHEN el inventario se obtuvo, THE SYSTEM SHALL salir con código **cero** haya huérfanos o no: es un
  informe, no una guardia de CI. Un código distinto de cero por hallazgo invitaría a ponerlo en CI,
  que está fuera de alcance por decisión explícita.
- THE SYSTEM SHALL limitarse a informar: no ejecuta `down`, `rm` ni `prune`, y **no imprime ningún
  comando de derribo con datos interpolados**; cierra con una frase fija recordando que qué stack se
  baja lo decide y lo ejecuta una persona. Mismo precedente que `specs/seed-data-demo.md` —enumera
  los objetos huérfanos y no los borra— y `specs/backend-ci.md`, que avisa de que `make db-clean-test`
  no distingue una base huérfana de una viva.
- THE SYSTEM SHALL usar **exactamente dos fuentes**, una invocación cada una, con lista de argumentos
  y nunca por shell: `git worktree list --porcelain` y `docker compose ls -a --format json`. Quedan
  **prohibidos** `docker compose config` en cualquier forma y `docker inspect` sin `--format`: el
  primero resuelve e imprime los valores del `.env` y la salida por defecto del segundo incluye
  `.Config.Env` — medido sobre el stack vivo, con `JWT_SECRET_KEY`, `POSTGRES_PASSWORD` y
  `ENCRYPTION_KEY` dentro (regla 8 de `steering/security.md`). La prohibición está escrita en tres
  sitios —docstring del script, comentario del `Makefile` y aquí— porque es portante, no cosmética.
- THE SYSTEM SHALL atribuir cruzando **rutas**, nunca etiquetas de contenedor
  (`com.docker.compose.project.working_dir` y compañía): cualquier contenedor de la máquina las pone
  con `docker run --label` y admiten cualquier byte. Atribuir por etiquetas es lo que hizo fracasar el
  intento de 2026-08-05; el cruce por ruta las hace innecesarias.
- THE SYSTEM SHALL clasificar con el valor **crudo** que devuelven Docker y git, y sanear **solo al
  imprimir** con un escape **inyectivo**: `\\` para la barra invertida y `\xNN`/`\uNNNN`/`\UNNNNNNNN`
  —de longitud fija, que es lo que mantiene la inyectividad— para todo carácter no imprimible
  (controles C0, C1 incluido `\x9b`, y separadores distintos del espacio). Un filtro que **borre**
  caracteres no vale: mapea `autohostai!` → `autohostai`, y con eso un contenedor hostil consigue que
  el informe lo muestre como si fuera otro proyecto. Sanear antes de clasificar tampoco: cambiaría el
  veredicto.
- THE SYSTEM SHALL imprimir **una etiqueta y un valor por línea**, un bloque por proyecto y en orden
  determinista —huérfanos primero, luego indeterminados, vivos y ajenos, y por nombre dentro de cada
  clase—, cerrando con el recuento por clase. Sin tabla y sin delimitador compuesto: con un campo por
  línea no hay separador que un nombre hostil pueda falsificar para fabricar una fila, ni ancho de
  terminal que corte.
- **Limitación conocida**: un worktree creado fuera del árbol del repositorio (`git worktree add
  ~/tmp/foo`) sale como `ajeno` aunque sea nuestro, incluso desregistrado. Es lo que pide la regla 4
  literalmente, y hoy es hipotético porque todos los worktrees los crea la misma herramienta bajo
  `.claude/worktrees/`.
- **Lo que el informe no dice: cuánto disco retiene cada huérfano.** Medirlo por proyecto obliga a
  filtrar volúmenes por `label=com.docker.compose.project=<nombre>`, es decir a **leer etiquetas** —
  justo lo que la atribución por ruta evita. Descartado a sabiendas el 2026-08-17; si se quiere, es
  entrada propia del roadmap que decida antes cómo se lee una etiqueta sin confiar en ella.
- El script vive en `scripts/compose-stacks.py` con `scripts/test_compose_stacks.py` al lado —el
  patrón de `check-version-parity.py`, cargado por `importlib` porque el nombre kebab-case no es
  importable— y **ningún workflow lo recoge**: el `pytest` de `backend-tests.yml` corre con
  `working-directory: backend`. Se ejecuta en local con `python3 -m pytest scripts/`. Su test de
  contrato invoca el `docker compose ls -a --format json` real cuando hay `docker` en el `PATH`, y es
  lo que avisará el día que Docker renombre un campo.
- **La redacción caducada de «un stack huérfano retiene puertos» no vuelve**: se verifica con
  `grep -rniE 'retendiendo|reteniendo|quién retiene|choca de puertos' --include='*.md' .`, del
  **verbo solo** y no del par de palabras, porque en la redacción vieja «retendiendo» cerraba una
  línea y «puertos» abría la siguiente — un grep de una sola línea con ambas no lo encontraba. Los
  únicos aciertos aceptables están bajo `sdd/changes/archive/`, que es registro histórico y no se
  reescribe.

### Makefile como entrypoint único

- WHEN se ejecuta `make up` y no existe `.env`, THE SYSTEM SHALL crearlo automáticamente copiando `.env.example` antes de levantar el stack — cero pasos manuales para arrancar por primera vez.
- WHEN se ejecuta `make up` y falta `JWT_SECRET_KEY` en `.env` (o está vacía), THE SYSTEM SHALL generarla con `openssl rand -hex 32` bajo `umask 077`, escribirla en el `.env` local y dejar el fichero en `600`, de forma idempotente y también sobre un `.env` preexistente. Es la forma de cumplir a la vez la regla 8 de `steering/security.md` —la clave de firma nunca lleva valor por defecto en el repositorio— y el arranque sin pasos manuales: el valor se genera en la máquina del desarrollador (ver spec `auth-tenancy`).
- WHEN se ejecuta `make up`, `make down`, `make logs`, `make ps` o `make sh`, THE SYSTEM SHALL delegar en el comando `docker compose` equivalente.
- THE SYSTEM SHALL hacer que **los nueve targets que invocan `docker compose` desde el `Makefile`** (`up`, `down`, `logs`, `ps`, `sh`, `bootstrap`, `seed-demo`, `openapi`, `db-clean-test`) pasen por una única definición del comando, para que ninguno opere sobre un conjunto de ficheros distinto del que levantó el stack (ver §«Stacks en paralelo por worktree»). Siguen siendo nueve: los dos targets que delegan en un script host-side —`check-version-parity` y `compose-stacks`— no invocan `docker compose` desde el `Makefile` y por tanto no entran en la cuenta. En `compose-stacks` quedar fuera de `$(COMPOSE)` es **deliberado y no un olvido que arreglar**: su ámbito es la máquina y no este proyecto, así que pasarlo por la definición común lo acotaría a los ficheros de este directorio y dejaría fuera justo los stacks que busca (ver §«Diagnóstico de stacks de Compose»).
- WHERE se invoque `docker compose` **desnudo** en lugar de por el `Makefile`, THE SYSTEM SHALL comportarse igual en el worktree principal —ahí `make` tampoco pasa `-f`— y **distinto** en un worktree enlazado, donde el comando desnudo carga solo el fichero base. Los que **no crean** contenedores (`exec`, `logs`, `ps`, `down`) funcionan igual en los dos sitios; los que crean o **recrean** (`up`, y `run` cuando arrastra dependencias) publicarían los cuatro puertos. Medido, porque la intuición dice lo contrario: tener las dependencias ya levantadas **no** protege — Compose recrea la que tenga un hash de configuración distinto, así que un `run` desnudo en un worktree las recrea publicando. Desde un worktree: `make`, o `--no-deps` cuando el comando no necesita la base de datos (por eso `make openapi` lo lleva).
- `make bootstrap` crea el tenant y los usuarios iniciales ejecutando `python -m app.cli.bootstrap` dentro del contenedor `backend` — deliberadamente **no** forma parte de `make up`, porque necesita valores que elige una persona (ver spec `auth-tenancy`). Usa `python -m` y no `uv run` para que el mismo comando valga contra la imagen `prod`, que no lleva `uv`.
- `make seed-demo` llena el tenant que `bootstrap` dejó con el dataset de demo de PRD §27 ejecutando `python -m app.cli.seed_demo` dentro del contenedor `backend` — igual que `bootstrap`, **no** forma parte de `make up` porque necesita valores que elige una persona, y **exige que el tenant ya exista**: sin él sale con error nombrando `make bootstrap` y sin escribir nada (ver spec `seed-data-demo`).
- `make db-clean-test` borra las bases de datos de test huérfanas que deje una ejecución de pytest interrumpida, sin tocar la de desarrollo (ver spec `backend-ci`).
- WHERE se pasa `SERVICE=<nombre>` a cualquiera de esos targets, THE SYSTEM SHALL limitar la operación a ese servicio — Compose arranca automáticamente sus dependencias declaradas (p.ej. `SERVICE=backend` trae `postgres`+`redis`; `SERVICE=frontend` trae además `backend`).
- `make sh` sin `SERVICE=` abre shell en `backend` por defecto.

### Compatibilidad con despliegue remoto

- Backend lee su configuración exclusivamente vía `Settings(BaseSettings)` (`backend/app/core/config.py`), nunca hardcodeada ni dispersa en `os.getenv`. Frontend lee la suya vía `process.env`.
- Cada `devops/Dockerfile` es multi-stage con targets `dev` (deps de desarrollo, pensado para bind mount) y `prod` (imagen lean, sin deps dev, sin bind mount, ejecutable con el mismo comando fuera de docker-compose).
- `.env.example` (gitignored el propio `.env`, no `.env.example`) trae valores por defecto funcionales para config local sin sensibilidad real (`POSTGRES_*`, `NEXT_PUBLIC_APP_ENV`) — no son secretos, y lo que lo hace aceptable es que `postgres` está publicado **solo en loopback** (ver §Postura de red del stack local), así que ese valor por defecto únicamente es alcanzable desde la propia máquina. La justificación anterior decía «un Postgres solo alcanzable dentro de la red de compose», que era falso mientras el mapeo fue `5432:5432`: sin prefijo de interfaz Docker publica en `0.0.0.0`. Si el mapeo vuelve a publicar fuera de loopback, este default deja de estar justificado (misma condición que la exención de la regla 8 de `steering/security.md`). Los secretos reales siguen la regla de "solo nombre, nunca valor" de `security.md` #8: `JWT_SECRET_KEY` ya está declarada así (nombre, sin valor, generada por `make up`), igual que `CHANNEX_API_KEY` (adapter de validación de Channex, `specs/pms-channex-staging.md`), y las credenciales futuras de WhatsApp/SES.Hospedajes y `ENCRYPTION_KEY` harán lo mismo. `CHANNEX_BASE_URL` es la excepción deliberada: **lleva valor**, comentado como los demás overrides opcionales, porque no es un secreto y ese default apuntando a staging es lo que impide que un descuido de configuración escriba en una cuenta de proveedor viva.
- `.gitignore` excluye `.env*` con excepciones explícitas para `.env.example` y `.env.deploy.example` — un `.env.local` o `.env.deploy` con valores reales no puede colarse por olvido.

### Esqueleto ejecutable mínimo

- El backend expone `GET /health` → `200 {"status": "ok"}`.
- El frontend renderiza dinámicamente (sin cachear el resultado en build time) una página raíz que hace fetch a `${BACKEND_INTERNAL_URL}/health` y muestra `backend: ok` o `backend: ko` según la respuesta.
- El worker ejecuta las ocho tareas periódicas que `celery-jobs` registra en `backend/app/worker.py` —las cuatro nombradas por PRD §8.3 más las cuatro que no lo están: `dispatch_notifications`, `provision_access_records`, `process_webhook_events` y `classify_incidents`—, con broker/backend en `REDIS_URL`; `beat` es quien las dispara (ver `specs/celery-jobs.md`). El fichero de estado de `beat` aparece como `backend/celerybeat-schedule` en el árbol de trabajo —el bind mount de `./backend` lo hace persistente en el host, no efímero— y está en `.gitignore`.

### Inicialización de git

- El repo tiene un `.git` inicializado en la rama `main`.
- `.gitignore` excluye `.env`, `node_modules/`, `__pycache__/`, `.venv/`, `.next/`, `dist/`, `build/` y artefactos de editor/OS — ninguno de ellos está trackeado.

## Key files

- Raíz: `docker-compose.yml`, `docker-compose.worktree.yml`, `Makefile`, `.env.example`, `.gitignore`, `README.md`.
- Herramienta host-side (fuera de `$(COMPOSE)`, ejecutada con el `python3` del host y sin dependencias): `scripts/compose-stacks.py` + `scripts/test_compose_stacks.py` (diagnóstico de stacks huérfanos, `make compose-stacks`); `scripts/check-version-parity.py` + `scripts/test_check_version_parity.py`.
- Backend: `backend/devops/Dockerfile`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/worker.py`, `backend/pyproject.toml` + `backend/uv.lock`, `backend/tests/test_health.py`.
- Frontend: `frontend/devops/Dockerfile`, `frontend/devops/docker-entrypoint.sh` (sincroniza `node_modules` con el lockfile en dev), `frontend/devops/test-entrypoint.sh` (test del entrypoint, `npm run test:entrypoint`), `frontend/app/(workspace)/page.tsx` (redirige `/` a `/dashboard`), `frontend/app/layout.tsx`, `frontend/next.config.ts`, `frontend/app/route-wiring.test.tsx` (verifica el wiring de la ruta raíz).
