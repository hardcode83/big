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

Y **la postura se conserva desplazada**. Con `make up PORT_OFFSET=<n>` cambia el **puerto de host** de
los cuatro mapeos, nunca la interfaz ni el puerto de destino: `postgres` y `redis` siguen acotados a
`127.0.0.1` —ese bind es la única defensa de los contadores del throttle, ver abajo— y `backend` y
`frontend` siguen en **todas** las interfaces, que es lo que permite abrir la app desde un móvil de la
LAN y el motivo entero de que el desplazamiento exista. Ningún servicio que hoy no publique empieza a
publicar: `worker`, `beat` y `migrate` siguen sin mapeos. La **sede única** de esa aritmética es la
tabla `SERVICES` de `scripts/compose-offset.py`, con su suite al lado — ni el `Makefile` ni ningún otro
sitio vuelven a sumar puertos.

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
- **Esta postura se comprueba sola, en local y en cada Pull Request**, con
  `make check-compose-ports` y el workflow `compose-ports` (ver §«Guardia de la postura de red»).
  Un mapeo al que se le caiga el prefijo `127.0.0.1:` sale en rojo nombrando servicio y mapeo, en
  vez de depender de que alguien lo vea en el diff. Lo añadió el change `compose-ports-guard`,
  separado del que estableció esta postura porque construir la guardia bien resultó tener más
  fondo del que aparenta: su entrada de roadmap lleva el censo de vías de elusión ya demostradas.
- **Conjunto de ficheros canónico, que es lo que esa guardia tiene que mirar**: en el worktree
  principal, `docker-compose.yml` **a secas** — el `Makefile` lo invoca sin `-f`, así que lo que
  Compose descubre por sí solo *es* la postura real y una comprobación desnuda no puede quedarse
  corta. En un worktree enlazado, `docker-compose.yml` **+** `docker-compose.worktree.yml`, en ese
  orden. Los mapeos siguen declarados en el fichero base a propósito: sacarlos a un fichero aparte
  habría dejado la vista desnuda sin puertos y la guardia pasando en vacío.
- WHERE se inspeccione la postura con `docker compose config`, THE SYSTEM SHALL invocarlo con
  `--no-interpolate --no-env-resolution`, y entonces **no hace falta `.env` de ninguna clase**:
  medido, sale con código 0 en un clon limpio y normaliza igual los mapeos de puertos. Redacciones
  anteriores de este criterio exigían un `.env` presente **y completo**, razonando que tres
  servicios declaran `env_file: .env` y que el compose interpola `${POSTGRES_DB:?...}`,
  `${POSTGRES_PASSWORD:?...}` y `${JWT_SECRET_KEY:?...}`. Eso es cierto de `config` **a secas** —y
  sigue siendo el motivo por el que `make up` crea el fichero—, pero no de esta invocación. La
  diferencia no es cosmética: con interpolación activada, un `BIND=0.0.0.0` en el `.env` de alguien
  daría rojo en su máquina y verde en CI, y el veredicto sería función del entorno en vez de del
  repositorio.
- **Qué NO detecta una comprobación que busque un puerto de host publicado**: hay formas legales de
  `ports:` que no declaran ninguno —la corta con solo el puerto del contenedor (`ports: ["5432"]`) y
  la larga sin `published` (`{target: 6379, mode: ingress}`)— y Docker las publica en un puerto
  **efímero y en todas las interfaces**. La aserción fiable es sobre la **presencia de la clave
  `ports`**, no sobre `published` ni sobre `host_ip`. Y `network_mode: host` no lo detecta ninguna
  de las dos, porque publica **sin generar ninguna entrada `ports`**: quien lo cubre es la guardia,
  con una lista blanca de `network_mode` (ver §«Guardia de la postura de red»).

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
- WHEN `make up` arranca, THE SYSTEM SHALL anunciar en qué modo lo hace: publicando puertos; sin
  publicarlos y por tanto sin UI ni API alcanzables desde el navegador del host; o **desplazado**, y en
  ese caso enumerando los **cuatro puertos efectivos** con su interfaz y añadiendo cómo abrirlo desde
  un móvil de la LAN. La IP de la máquina **no** se calcula en el anuncio, a propósito: resolverla es
  específico de plataforma y falla de formas que se leen como un fallo del stack.
- IF el modo es worktree **y no se pidió desplazamiento**, THEN THE SYSTEM SHALL comprobar **antes de
  levantar** que la configuración resuelta no contiene ninguna clave `ports`, y abortar en rojo si la
  hay — cubre a la vez un servicio con puerto que nadie añadió al overlay y un Compose anterior a 2.24
  que ignore `!reset`. El estado de salida de `config` se comprueba aparte del contenido: un `config`
  que falle aborta con mensaje propio en vez de degradar la comprobación a verde.
- WHERE se pidió desplazamiento, THE SYSTEM SHALL sustituir esa aserción de **ausencia** por una de
  **igualdad numérica**: cada mapeo de la configuración resuelta es exactamente el esperado para ese
  desplazamiento, con su prefijo de interfaz, y ningún otro servicio publica nada. Las dos mitades
  hacen falta —la primera caza el overlay que no llegó a aplicarse, la segunda un servicio que publique
  por su cuenta— y la aserción es **numérica** porque los mapeos generados son literales.
- IF el modo es worktree, no se pidió desplazamiento y `docker-compose.worktree.yml` no existe, THEN
  THE SYSTEM SHALL abortar con un mensaje que diga que esa rama es anterior al soporte de stacks en
  paralelo, en vez del error de fichero no encontrado de Compose.
- IF git no está disponible o el directorio no es un repositorio, THEN THE SYSTEM SHALL comportarse
  como el worktree principal —publicar— y decirlo. Es deliberado: una colisión de puertos aborta
  nombrando el puerto, mientras que no publicar en silencio se manifiesta como «la app no carga».
- THE SYSTEM SHALL requerir **Docker Compose ≥ 2.35.0** y **git ≥ 2.31** (por `--path-format`). Por
  debajo del suelo de git la detección falla hacia publicar, así que un worktree chocaría de puertos
  en vez de arrancar sin ellos.

  El suelo de Compose lo fijan **tres** cosas, y manda la mayor. El tag `!reset` de
  `docker-compose.worktree.yml` pide ≥ **2.24**; el tag `!override` del overlay que genera
  `make up PORT_OFFSET=<n>` pide ≥ **2.24.4**; la bandera `--no-env-resolution` que usa la guardia
  de puertos pide ≥ **2.35.0**, y ese es el suelo efectivo. La segunda cifra está **medida** y no
  estimada: la bandera la introdujo el PR 12665 de `docker/compose`, mergeado el 2025-03-24 y
  publicado por primera vez en **v2.35.0** (2025-04-10); en v2.34.0 no existe. Hasta el change
  `compose-ports-guard` aquí ponía 2.24, que era el suelo correcto de entonces y se quedó corto al
  añadir la guardia. Por debajo del suelo, la guardia sale en **rojo** nombrando el paso y avisando
  de `unknown flag` — no en verde (ver §«Guardia de la postura de red»).
- **Lo que un worktree enlazado no publica por defecto**: nada alcanzable desde el navegador del host,
  ni un cliente gráfico contra `localhost:5432`. La salida existe, es explícita y está descrita justo
  abajo —desplazar los cuatro puertos—; el **defecto sigue siendo no publicar**, porque lo que se añadió
  es una salida bajo petición, no la vuelta atrás de la decisión de 2026-08-05.
- WHEN se ejecuta `make up PORT_OFFSET=<n>`, THE SYSTEM SHALL publicar los cuatro puertos desplazados
  por `<n>` —`postgres 5432+n`, `redis 6379+n`, `backend 8000+n`, `frontend 3000+n`—, un **único
  sumando para los cuatro** y no uno por servicio, de modo que un solo número describa el stack entero.
- THE SYSTEM SHALL aceptar el desplazamiento **también en el worktree principal**, para que el principal
  pueda apartarse en vez de obligar a bajarlo. WHERE hay desplazamiento, la elección de ficheros deja de
  mirar si el directorio es principal o enlazado: los dos cargan la base más el overlay desplazado, y
  `docker-compose.worktree.yml` **no** se añade.

  Consecuencia que se lee mal si no está escrita: en el principal, desplazar **no crea un segundo
  stack, mueve el que hay**. El nombre de proyecto sale del directorio, así que `make up PORT_OFFSET=<n>`
  recrea los cuatro servicios en los puertos nuevos. Es exactamente el «apartarse» que se pidió, no un
  fallo; y el anuncio de arranque lo dice.
- WHILE dos stacks están levantados con desplazamientos distintos, THE SYSTEM SHALL arrancar ambos sin
  fallar por puerto ocupado.
- THE SYSTEM SHALL escribir el desplazamiento en un overlay **generado** —`.make/docker-compose.offset.yml`,
  gitignorado y regenerado en cada invocación con desplazamiento—, con `!override` y **números
  literales**, cargado solo con un `-f` explícito.

  Las tres propiedades son deliberadas y cada una cierra una vía distinta. **Fuera de la raíz y sin
  llamarse `docker-compose.override.yml`**, para que Compose no lo descubra por sí solo y la guardia de
  la postura —que invoca Compose desnudo— no pueda verlo: su veredicto sigue siendo función **solo del
  repositorio** (ver §«Guardia de la postura de red»). **Números literales y no `${...}`**, porque con
  `--no-interpolate` un mapeo interpolado llega como cadena cruda y la aserción previa a levantar tiene
  que ser numérica; de paso, ningún `ports` del repositorio queda dependiendo del entorno. **Regenerado
  siempre**, para que no exista ruta por la que se lea el `<n>` de una invocación anterior.

  THE SYSTEM SHALL mantener **prohibido** renombrar ese overlay, moverlo a la raíz o añadir un `-f` al
  target de la guardia: cualquiera de las tres la deja ciega. Es la misma familia de prohibiciones que
  ya viven en §«Diagnóstico de stacks de Compose».
- **La postura de red se conserva desplazada** —interfaces y servicios que no publican, intactos—: ver
  §«Postura de red del stack local».
- WHEN `make up` arranca con desplazamiento, THE SYSTEM SHALL ejecutar, **todo antes de levantar y en
  este orden**: generar el overlay → asertar la configuración resuelta → sondear los binds del host →
  anunciar. El orden no es indiferente: sondear antes de asertar diría «el puerto está libre» sobre una
  configuración que quizá no publica lo que creemos, y sondear **después** de levantar es justamente el
  síntoma ilegible que esto existe para evitar —Compose fallando a medio arrancar con `port is already
  allocated` y contenedores a medias— en vez de un error que nombra puerto y servicio.
- IF `PORT_OFFSET` no es un entero no negativo, THEN THE SYSTEM SHALL abortar antes de levantar nada,
  nombrando el valor recibido. El rechazo va **antes** de cualquier normalización: al revés, normalizar
  podía convertir un valor inservible en uno válido y el rechazo no llegaba nunca. Se rechazan por igual
  un valor con espacios y un `10` con salto de línea final.
- IF `PORT_OFFSET` vale `0` o está vacío, THEN THE SYSTEM SHALL comportarse como si no se hubiera
  pasado. Un valor de **solo espacios** no equivale a vacío y aborta nombrándolo, con un mensaje que
  dice cómo salir: dos capas que se contradijeran sobre el mismo valor es lo que se evita.
- IF algún puerto desplazado supera `65535`, THEN THE SYSTEM SHALL abortar nombrando cuál.
- IF algún puerto desplazado ya está ocupado en el host, THEN THE SYSTEM SHALL abortar **antes** de
  arrancar, nombrando puerto y servicio, excluyendo del sondeo los puertos que ya publica el propio
  stack. Cubre también el choque contra un puerto **no** desplazado de otro stack —`PORT_OFFSET=2432`
  lleva el frontend al `5432` del Postgres del principal—, porque el sondeo es general y no una regla
  especial. Va **sin `SO_REUSEADDR`** (falla hacia abortar, que es la dirección correcta) y es **solo
  IPv4**: un puerto ocupado únicamente en `::` lo atraviesa y degrada al error de Compose, que también
  nombra el puerto. Residual aceptado y escrito.
- IF el overlay desplazado no pudo combinarse con la base, THEN THE SYSTEM SHALL abortar con mensaje
  propio: si `!override` no se aplicó, la configuración resuelta trae los dos mapeos y la aserción de
  igualdad sale en rojo. **Nunca** se degrada a «publicar lo que salga».
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
  **prohibidos** `docker compose config` **sin `--no-interpolate --no-env-resolution`** y
  `docker inspect` sin `--format`: el primero, en su forma desnuda, resuelve e imprime los valores
  del `.env` y la salida por defecto del segundo incluye `.Config.Env` — medido sobre el stack vivo,
  con `JWT_SECRET_KEY`, `POSTGRES_PASSWORD` y `ENCRYPTION_KEY` dentro (regla 8 de
  `steering/security.md`). La prohibición está escrita en tres sitios —docstring del script,
  comentario del `Makefile` y aquí— porque es portante, no cosmética.

  **La primera mitad se acotó por forma en `compose-ports-guard` (2026-08-18), y el cómo importa.**
  Antes decía «`docker compose config` en cualquier forma», y la guardia de puertos —para la que
  `config` es la única fuente correcta— habría necesitado exceptuarse **por sujeto**: «prohibido
  salvo para este script», que es una excepción nominal que el siguiente script pediría también. La
  forma acotada es **mecánica y verificable**: es una lista de banderas, y con las dos la salida no
  contiene ningún valor del `.env` (medido — sin ellas inlina el fichero entero en `environment`,
  incluidas variables que el compose no menciona). `scripts/test_compose_ports.py` la comprueba
  sobre el propio código del script, por AST y no por `grep`. `docker inspect` sin `--format` sigue
  prohibido **sin excepción**: ahí no hay bandera que acote nada.
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

### Guardia de la postura de red

`make check-compose-ports` ejecuta `python3 scripts/compose-ports.py`, que comprueba que ningún
servicio del compose local publique un puerto en el host fuera de `127.0.0.1`. Corre también en cada
Pull Request (`.github/workflows/compose-ports.yml`). A diferencia del diagnóstico de stacks, **esto
sí es una guardia de CI**: sale con código distinto de cero cuando hay hallazgo.

**Estado del check.** WHILE el repositorio no disponga de protección de rama compatible, THE SYSTEM
SHALL ejecutar y reportar `compose-ports` **sin** configurarlo como check obligatorio para fusionar
— igual que `api-contract` y `frontend-tests`, y por el mismo motivo de plan de GitHub
(`specs/backend-ci.md` §Estado, `docs/adr/0002-github-org-hosting.md`). Conviene decirlo aquí porque
la regla 8 de `steering/security.md` apoya en esta guardia la exención de `POSTGRES_PASSWORD`: lo que
la sostiene es un rojo **visible** en cada Pull Request, no una puerta que impida fusionar. El día
que haya protección de rama, éste es de los checks que deben pasar a obligatorios.

- THE SYSTEM SHALL tomar su dato de `docker compose config --no-interpolate --no-env-resolution
  --format json` y **no** del YAML a pelo, porque Compose es quien normaliza las cuatro formas de
  escribir un mapeo. Las dos banderas son obligatorias y viven en una única constante del script;
  ver §«Diagnóstico de stacks de Compose» para la prohibición que acotan.
- THE SYSTEM SHALL **delegar en Compose el descubrimiento de ficheros** —invocarlo sin `--file`— y
  construir el entorno del hijo **desde cero por lista blanca** (`PATH` y nada más), de modo que ni
  un `COMPOSE_FILE` exportado en el shell ni un `compose.yaml` que sustituya a `docker-compose.yml`
  desvíen la comprobación. Lista blanca y no desinfección por lista negra: una lista blanca
  demasiado estrecha falla en **rojo**, una lista negra demasiado estrecha falla en **verde** y se
  reabre con cada variable nueva que Docker añada.
- THE SYSTEM SHALL decidir cada mapeo con **seis reglas en este orden**: (1) `network_mode` fuera de
  `{ausente, bridge, none}` → infracción; (2) `ports` ausente → conforme; (3) entrada de `ports` que
  no es objeto → infracción; (4) objeto sin `published` → infracción **siempre**, incluso en un
  servicio exento; (5) `(servicio, published)` en la exención → conforme; (6) `host_ip` igual a
  `127.0.0.1` → conforme, cualquier otra cosa → infracción. El orden es normativo: intercambiar (4)
  y (5) eximiría en silencio un mapeo sin puerto de host.
- THE SYSTEM SHALL eximir exactamente **dos pares servicio+puerto** —`backend:8000` y
  `frontend:3000`—, nunca servicios enteros ni puertos sueltos: un puerto extra en un servicio
  exento y el mismo puerto en un servicio no exento son infracción.
- THE SYSTEM SHALL evaluar los servicios declarados bajo `profiles:` **estén o no activos**,
  enumerándolos con `config --profiles` y activándolos con un `--profile` **por nombre**, nunca
  unidos por comas: la bandera viaja por `argv` sin separador, mientras que unir los nombres pierde
  el que lleve una coma dentro, que es un carácter legítimo del dato.
- THE SYSTEM SHALL **afirmar en positivo** antes de dar verde, con dos igualdades, y fallar si no
  puede confirmar cualquiera de ellas: el conjunto de servicios del modelo es exactamente el
  inventario que el script declara (`EXPECTED_SERVICES`) y exactamente el que devuelve
  `config --services`; y la unión de los `profiles` del modelo es igual a lo que enumeró
  `config --profiles`. Es una aserción positiva en lugar de varias guardas negativas, y con ella un
  `config` que salga con **éxito** devolviendo `{}` da conjunto vacío ≠ inventario, y es rojo.
- THE SYSTEM SHALL comparar el inventario por **igualdad** y no por contención: un servicio nuevo
  deja la guardia en rojo hasta que alguien lo añada a `EXPECTED_SERVICES`, y ese momento —el Pull
  Request que lo introduce— es precisamente cuando hay que decidir qué publica. El mensaje de fallo
  dice qué añadir y dónde. Es la misma disciplina que `docker-compose.worktree.yml` ya impone.
- THE SYSTEM SHALL comprobar el estado de salida de cada invocación **aparte** de su contenido y
  antes de mirarlo, sin `2>/dev/null` y sin quedar detrás de un pipe. Medido mientras se diseñaba:
  `docker compose config --services 2>&1 | tail -2` imprime el error y devuelve **`rc=0`**, porque
  en un pipe el estado de salida es el del último comando.
- THE SYSTEM SHALL **no volcar nunca** la salida de `config`: el hallazgo se compone solo de nombre
  de servicio y mapeo, del fallo se relata **solo la primera línea de `stderr`** saneada y acotada, y
  `stdout` no se relata jamás. En Actions `stdout` es un log persistido.
- THE SYSTEM SHALL imprimir **una etiqueta y un valor por línea**, un bloque por hallazgo, en orden
  determinista y con el mismo escape inyectivo de `compose-stacks.py` — y por el mismo motivo: los
  nombres de servicio y de profile son dato ajeno al formato.
- WHEN no hay ninguna infracción, THE SYSTEM SHALL salir con código cero **nombrando y contando** lo
  inspeccionado —servicios, mapeos y profiles—, para que el verde se lea como «vio esto» y no como
  «no vio nada». Hoy: 7 servicios, 4 mapeos, 0 profiles.
- IF cualquier paso de la cadena falla —`config` con error, JSON no parseable, enumeración rota,
  Compose por debajo del suelo de versión— THEN THE SYSTEM SHALL terminar en rojo con un mensaje
  propio que nombre el paso, y **nunca** en verde. No hay lógica de comparación de versiones: una
  bandera desconocida ya sale con código distinto de cero, y el mensaje lleva la pista.

**Qué NO es, y por qué no duplica la comprobación de `make up`.** La de `make up`
(§«Stacks en paralelo por worktree») asierta la **ausencia** de la clave `ports` en la configuración
**con overlay**, antes de levantar **un stack concreto**, para que un worktree no choque de puertos.
Ésta asierta la **postura del repositorio** sobre la configuración **desnuda**, en CI. Sujetos
distintos, ficheros distintos, momentos distintos, y direcciones opuestas: allí lo correcto es cero
mapeos, aquí lo correcto son cuatro. No se deben fundir.

**Limitaciones conocidas, las dos deliberadas:**

- **`::1` (loopback IPv6) sale en rojo.** Es loopback y por tanto seguro, pero no es la postura
  escrita. Fallar y dejar que una persona ensanche la regla a sabiendas es la dirección correcta.
- **Un mapeo construido con interpolación sale en rojo**, porque con `--no-interpolate` no se
  normaliza y llega como cadena cruda. No es una limitación que se acepte a regañadientes: es el
  mecanismo que hace verdadero que el veredicto sea función **solo del repositorio**. Un mapeo cuyo
  valor sale del entorno no es una postura del repositorio. `worktree-port-offset` (2026-08-19) tomó la
  primera de las dos salidas que aquí se le dejaron declaradas: **genera mapeos literales** y no reabrió
  esta regla. Y lo hizo **sin tocar esta guardia en absoluto** —ni el script ni su workflow—, porque el
  overlay del desplazamiento vive fuera del conjunto que Compose descubre por sí solo, así que esta
  guardia no lo ve y su `EXEMPT` sigue nombrando los dos pares literales `backend:8000` y
  `frontend:3000` en vez de tener que expresarse por desplazamiento.

  **La contrapartida, que se dice aquí para que nadie lea esta guardia como cobertura total**: el modo
  desplazado **no lo cubre ella**. Lo cubre la tabla `SERVICES` de `scripts/compose-offset.py` con sus
  tests —que asertan `5432+n`/`6379+n` únicamente en `127.0.0.1`— y los recoge el **mismo** workflow.
  La postura está sostenida en los dos modos, pero por dos mecanismos distintos y no por uno.

**Fuera de alcance, y por qué**: `docker-compose.deploy.yml`. Lo carga solo el CD, que le pasa `-f`,
así que un `docker compose` desnudo nunca lo ve; incluirlo exigiría un `--file` explícito, que es la
vía de elusión que esta guardia cierra. Y su regla es la **inversa** — allí `backend` y `frontend`
publican en `127.0.0.1` obligatoriamente (`specs/app-deploy-dev.md` R4.3) —, así que los dos pares
que aquí se eximen allí serían infracción. Dos conjuntos de exenciones opuestos no caben en una
guardia.

El script vive en `scripts/compose-ports.py` con `scripts/test_compose_ports.py` al lado, cargado por
`importlib` como los demás de `scripts/`. Su suite **sí** la recoge un workflow —`compose-ports.yml`,
con `uv run --no-project --with 'pytest==9.1.1' python -m pytest scripts/ -q`—, y es el primer
workflow del repositorio que ejecuta `scripts/test_*.py`: hasta entonces solo corrían a mano, porque
el `pytest` de `backend-tests.yml` va con `working-directory: backend`. En local sigue siendo
`python3 -m pytest scripts/`.

### Makefile como entrypoint único

- WHEN se ejecuta `make up` y no existe `.env`, THE SYSTEM SHALL crearlo automáticamente copiando `.env.example` antes de levantar el stack — cero pasos manuales para arrancar por primera vez.
- WHEN se ejecuta `make up` y falta `JWT_SECRET_KEY` en `.env` (o está vacía), THE SYSTEM SHALL generarla con `openssl rand -hex 32` bajo `umask 077`, escribirla en el `.env` local y dejar el fichero en `600`, de forma idempotente y también sobre un `.env` preexistente. Es la forma de cumplir a la vez la regla 8 de `steering/security.md` —la clave de firma nunca lleva valor por defecto en el repositorio— y el arranque sin pasos manuales: el valor se genera en la máquina del desarrollador (ver spec `auth-tenancy`).
- WHEN se ejecuta `make up`, `make down`, `make logs`, `make ps` o `make sh`, THE SYSTEM SHALL delegar en el comando `docker compose` equivalente.
- THE SYSTEM SHALL hacer que **los once targets que invocan `docker compose` desde el `Makefile`** (`up`, `down`, `logs`, `ps`, `sh`, `bootstrap`, `seed-demo`, `demo-reset`, `openapi`, `check-frontend-build`, `db-clean-test`) pasen por una única definición del comando, para que ninguno opere sobre un conjunto de ficheros distinto del que levantó el stack (ver §«Stacks en paralelo por worktree»). **Eran «diez» y son once**, y el que faltaba es `check-frontend-build`, que invoca `$(COMPOSE) exec -T` en su receta y no estaba ni en esta enumeración ni en la de los host-side: se recontó target por target contra el `Makefile` al añadir `check-rule11-ownership`, que es cuando se vio. Es el mismo fallo que esta spec y la regla 11 llevan documentado —un recuento en prosa al lado de la fuente envejece sin que nada se ponga rojo— y la razón de que la obligación sea recontar y no incrementar. `check-rule11-ownership` **no** entra en la cuenta: los **cinco** targets que delegan en un script host-side —`check-version-parity`, `compose-stacks`, `check-compose-ports`, `ports` y `check-rule11-ownership`— no invocan `docker compose` desde el `Makefile` y por tanto no entran en la cuenta. La cuenta mide targets que lo invocan **desde el `Makefile`** y garantiza que todos pasen por una única definición; `check-compose-ports` lo invoca su script, desde Python, con entorno propio y deliberadamente desnudo, que es lo contrario de lo que la cuenta garantiza — meterlo dentro la haría medir dos cosas distintas.

  En los cuatro que quedan fuera **por decisión y no por olvido**, el motivo es distinto en cada uno y no se lee de los demás:
  - `compose-stacks`: su ámbito es la máquina y no este proyecto, así que pasarlo por la definición común lo acotaría a los ficheros de este directorio y dejaría fuera justo los stacks que busca (ver §«Diagnóstico de stacks de Compose»).
  - `check-compose-ports`: pasar por `$(COMPOSE)` añadiría `docker-compose.worktree.yml` en un worktree enlazado, que retira los cuatro mapeos; la guardia vería **cero** claves `ports` y daría **verde en vacío**, que es precisamente el fallo contra el que existe. Medido en un worktree enlazado: desnudo ve 4 mapeos, con el overlay ve 0 (ver §«Guardia de la postura de red»).
  - `ports`: pasar por `$(COMPOSE)` no cambiaría la respuesta —`ps` direcciona el proyecto por su **nombre**— pero ataría la consulta al conjunto de ficheros de la invocación, y entonces preguntar por el desplazamiento exigiría saberlo ya.
  - `check-rule11-ownership`: la guardia de la regla 11 es una herramienta de **stdlib que sólo lee ficheros del árbol**, así que no necesita el stack levantado; y pasarla por `$(COMPOSE)` la ataría a un contenedor que ya no monta el árbol de prosa, porque `rule11-guard-trigger-and-scope` retiró los dos bind mounts de `./sdd` y `./docs` que existían sólo para ella (ver §«Guardia de la propiedad de la regla 11» de `sdd/specs/rule11-ownership-guard.md`).
- WHERE se invoque `docker compose` **desnudo** en lugar de por el `Makefile`, THE SYSTEM SHALL comportarse igual en el worktree principal —ahí `make` tampoco pasa `-f`— y **distinto** en un worktree enlazado, donde el comando desnudo carga solo el fichero base. Los que **no crean** contenedores (`exec`, `logs`, `ps`, `down`) funcionan igual en los dos sitios; los que crean o **recrean** (`up`, y `run` cuando arrastra dependencias) publicarían los cuatro puertos. Medido, porque la intuición dice lo contrario: tener las dependencias ya levantadas **no** protege — Compose recrea la que tenga un hash de configuración distinto, así que un `run` desnudo en un worktree las recrea publicando. Desde un worktree: `make`, o `--no-deps` cuando el comando no necesita la base de datos (por eso `make openapi` lo lleva).
- `make bootstrap` crea el tenant y los usuarios iniciales ejecutando `python -m app.cli.bootstrap` dentro del contenedor `backend` — deliberadamente **no** forma parte de `make up`, porque necesita valores que elige una persona (ver spec `auth-tenancy`). Usa `python -m` y no `uv run` para que el mismo comando valga contra la imagen `prod`, que no lleva `uv`.
- `make seed-demo` llena el tenant que `bootstrap` dejó con el dataset de demo de PRD §27 ejecutando `python -m app.cli.seed_demo` dentro del contenedor `backend` — igual que `bootstrap`, **no** forma parte de `make up` porque necesita valores que elige una persona, y **exige que el tenant ya exista**: sin él sale con error nombrando `make bootstrap` y sin escribir nada (ver spec `seed-data-demo`).
- `make demo-reset` devuelve el **tenant de demostración** a su estado inicial ejecutando `python -m app.cli.demo_reset` dentro del contenedor `backend` — igual que `bootstrap` y `seed-demo`, **no** forma parte de `make up`, y exige `DEMO_ACCOUNT_PASSWORD` puesta y de longitud suficiente: sin ella refusa sin escribir nada. Es el mismo comando que el workflow programado ejecuta contra el entorno desplegado, así que el target local sirve para probarlo (ver spec `demo-tenant`).
- WHEN se ejecuta `make ports`, THE SYSTEM SHALL informar del desplazamiento vigente y de los cuatro mapeos efectivos **sin volver a arrancar nada**, derivándolo del **stack vivo** (`docker compose ps`) y no del overlay generado. Esa es la decisión: el fichero describe la última *intención* —la del último `make up` que pasó un número—, mientras que el stack describe lo que está corriendo, así que la respuesta es verdad aunque alguien levantara con otro número, y existe también en el worktree principal, donde no hay overlay ninguno. El stack **parado** y el stack **sin puertos publicados** son estados normales: se informan y salen en verde. Un stack con desplazamientos incoherentes entre servicios se informa como tal, **sin inventar** un número que lo describa.
- WHERE se pasa `PORT_OFFSET=<n>`, THE SYSTEM SHALL exigirlo **solo en `up`**: `down`, `logs`, `ps` y `sh` dan con el mismo stack sin que se les repita el número, y nunca acaban hablando con otro. Conviene saberlo porque la lectura ingenua dice lo contrario; lo que lo hace cierto es que direccionan el proyecto por su **nombre** —que Compose saca del directorio, y el de cada worktree es distinto—, no por sus puertos. Un `up` con desplazamiento y un `down` posterior sin él operan sobre conjuntos de ficheros distintos, y es seguro precisamente porque el segundo no **crea** contenedores: los para y los borra por proyecto.

  El filo único, porque `up` es el único target que **crea** los mapeos: un **`make up SERVICE=<x>` parcial sin repetir el desplazamiento** recrearía ese servicio sin puertos. Ahí sí hay que repetir el número, y la aserción previa no lo cubre porque en ese caso no llega a ejecutarse.
- `PORT_OFFSET` es variable de **`make`**, no configuración de la aplicación: no está en `.env.example` ni en `Settings`, y el overlay generado lleva números literales, así que nada del `.env` puede desplazar el stack. `make` sí toma sus variables del entorno, de modo que un `export PORT_OFFSET=10` en la shell de un worktree desplaza todos sus `make up` sin repetirlo — deliberado y útil. Lo que **no** puede es mover a la guardia: `check-compose-ports` no pasa por `$(COMPOSE)` y su script construye el entorno del hijo por lista blanca, así que un `PORT_OFFSET` exportado no cambia su veredicto.
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

- Raíz: `docker-compose.yml`, `docker-compose.worktree.yml`, `Makefile`, `.env.example`, `.gitignore`, `README.md`. `.make/docker-compose.offset.yml` es **generado y gitignorado** (lo escribe `make up PORT_OFFSET=<n>`), y vive fuera de la raíz a propósito para que Compose no lo descubra por sí solo.
- Herramienta host-side (fuera de `$(COMPOSE)`, ejecutada con el `python3` del host y sin dependencias): `scripts/compose-stacks.py` + `scripts/test_compose_stacks.py` (diagnóstico de stacks huérfanos, `make compose-stacks`); `scripts/check-version-parity.py` + `scripts/test_check_version_parity.py`; `scripts/compose-offset.py` + `scripts/test_compose_offset.py` (desplazamiento de los cuatro puertos publicados, detrás de `make up PORT_OFFSET=<n>` y `make ports`).
- Backend: `backend/devops/Dockerfile`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/worker.py`, `backend/pyproject.toml` + `backend/uv.lock`, `backend/tests/test_health.py`.
- Frontend: `frontend/devops/Dockerfile`, `frontend/devops/docker-entrypoint.sh` (sincroniza `node_modules` con el lockfile en dev), `frontend/devops/test-entrypoint.sh` (test del entrypoint, `npm run test:entrypoint`), `frontend/app/page.tsx` (resuelve la decisión anónimo/autenticado en el servidor: sesión presente redirige `307` a `/dashboard`, sesión ausente sirve la landing pública), `frontend/app/opengraph-image.tsx` (imagen Open Graph de la landing generada en build), `frontend/app/layout.tsx`, `frontend/next.config.ts`, `frontend/app/route-wiring.test.tsx` (verifica el wiring de la ruta raíz).
