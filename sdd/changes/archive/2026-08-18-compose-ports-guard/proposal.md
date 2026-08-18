# Proposal: compose-ports-guard

## Why

`docker-compose.yml` publica `postgres` y `redis` **solo en `127.0.0.1`**, y eso no es
higiene: ese Redis guarda los contadores del límite de intentos de login
(`login:ip:*`, `login:fail:*`, `login:lock:*`) y corre **sin `requirepass`**, así que
quien alcance el puerto anula el límite de 10 intentos/min y el bloqueo tras 10 fallos
que exige la regla 7 de `steering/security.md`. Ese bind es además lo que sostiene la
exención de la regla 8 para `POSTGRES_PASSWORD=localdev` en `.env.example`.

**Hoy esa postura no tiene ninguna comprobación automática**: la afirman tres
documentos (`README.md:57`, `specs/local-environment.md:73`, `steering/security.md:34`)
y los tres dicen lo mismo — *«hoy solo lo atrapa la revisión del diff»*. Un mapeo al
que se le caiga el prefijo `127.0.0.1:` entra en verde, y con él se cae la exención de
la regla 8 sin que nada lo diga.

Esta entrada se separó de `local-dev-network-hardening` el 2026-08-05 tras cinco rondas
de panel. Motivo medido, no estimado: los ~19 hallazgos del panel fueron **todos** de la
guardia y cuatro de ellos fueron regresiones que introdujo el arreglo anterior. Aquel
change entregó la postura sin un solo hallazgo; lo que faltaba —y sigue faltando— es lo
que impide la regresión. Entrada de roadmap y análisis completo en
`sdd/roadmap/compose-ports-guard.md` y en las líneas 35-47 de `sdd/roadmap.md`, que
arrastran el censo de vías de elusión y las decisiones que no hay que volver a derivar.

## What changes

Existirá una guardia ejecutable —`python3 scripts/compose-ports.py`, invocada por
`make check-compose-ports` y por `.github/workflows/compose-ports.yml`— que en cada Pull
Request falla en rojo, nombrando servicio y mapeo, si algún servicio del compose local
publica un puerto en el host fuera de `127.0.0.1`, salvo los dos pares **servicio+puerto**
exentos a propósito. Los tres documentos que hoy afirman que esa comprobación no existe
pasan a describirla.

La guardia se construye **afirmando en positivo lo que ha visto** antes de dar verde, y
no comprobando la ausencia de fallo paso a paso — ese es el diagnóstico estructural que
este historial deja escrito y la única forma de cerrar las dos vías de elusión que
siguen abiertas.

**Y trae consigo una excepción que hay que declarar, no descubrir.**
`specs/local-environment.md:202-208` **prohíbe `docker compose config` en cualquier
forma**, en tres sitios a la vez y por un motivo portante: resuelve e imprime los valores
del `.env`, con `JWT_SECRET_KEY`, `POSTGRES_PASSWORD` y `ENCRYPTION_KEY` dentro. Esa
prohibición se escribió para `compose-stacks.py`, que puede hacer su trabajo con
`docker compose ls`. Esta guardia **no puede**: `config` es su única fuente correcta. Así
que este change acota la prohibición y añade la obligación que la sustituye aquí — nunca
volcar la configuración (R1.7), que en un workflow de Actions importa el doble porque stdout
es un log persistido.

**Cómo se acota, precisado el 2026-08-18 por `design.md` D1**: no por sujeto —«prohibido salvo
para este script», que es una excepción nominal que el siguiente script pediría también— sino
por **forma**, que es mecánica y verificable: prohibido `docker compose config` **sin
`--no-interpolate --no-env-resolution`**. Con las dos banderas la salida no contiene ningún
valor del `.env` (medido); sin ellas inlina el fichero entero. `docker inspect` sin `--format`
sigue prohibido sin excepción.

## Requirements

### R1 — La postura de red se comprueba sola, en local y en cada Pull Request

**Como** desarrollador del proyecto, **quiero** que un comando y un check de CI
verifiquen la postura de red del compose local, **para que** un mapeo sin prefijo de
interfaz no llegue a `main` por un descuido de revisión.

Criterios de aceptación:

1. THE SYSTEM SHALL exponer la guardia como `python3 scripts/compose-ports.py`,
   invocable con `make check-compose-ports`, siguiendo el patrón ya establecido por
   `make check-version-parity` y `make compose-stacks`: Python de la stdlib en
   `scripts/`, sin dependencias nuevas. **No una receta de shell en el `Makefile`** — es
   la forma que acumuló ~18 hallazgos en cinco rondas y que `compose-stacks-diagnostic`
   ya descartó por precedente.
2. WHEN se abre o actualiza un Pull Request, THE SYSTEM SHALL ejecutar la guardia en
   `.github/workflows/compose-ports.yml` con **un solo job**, siguiendo el patrón de
   `api-contract.yml` — el patrón de tres jobs de `backend-tests.yml` no se paga en una
   comprobación que cuesta segundos. El job SHALL llamarse igual que el workflow, porque
   el check run toma el nombre del **job**.
3. THE SYSTEM SHALL declarar ese workflow **sin `paths:` en `on:`**, de modo que el
   check se reporte siempre — `specs/backend-ci.md` lo prohíbe explícitamente, y un
   filtro de rutas dejaría el check en «pendiente» en vez de en verde.
4. THE SYSTEM SHALL mantener la guardia **fuera de `backend/tests/`**:
   `backend-tests.yml:137` decide el área con
   `case "$f" in backend/* | .github/workflows/backend-tests.yml)`, así que un PR que
   solo toque `docker-compose.yml` no ejecutaría esa suite — justo el PR donde la
   guardia tiene que hablar.
5. THE SYSTEM SHALL inspeccionar la configuración **sin `.env` de ninguna clase**, ni
   presente en el clon ni bootstrapeado en el job. Reescrito el 2026-08-18 tras medirlo en
   `design.md` D1: `docker compose config --no-interpolate --no-env-resolution --format json`
   sale con **código 0 en un clon limpio sin `.env`** y normaliza igual los mapeos de puertos.
   La redacción anterior de este criterio exigía bootstrapear un `.env` completo porque tres
   servicios declaran `env_file: .env` y el compose interpola `${POSTGRES_DB:?...}`,
   `${POSTGRES_PASSWORD:?...}` y `${JWT_SECRET_KEY:?...}`; eso es cierto de `config` **a
   secas** —y sigue siendo el motivo por el que `make up` crea el fichero— pero no de la
   invocación que esta guardia usa. Un criterio cuyo sujeto no existe no se puede verificar,
   así que se sustituye en vez de dejarse en pie.
6. THE SYSTEM SHALL no introducir **ningún secreto en el job**: ni real, ni de GitHub
   Secrets, ni efímero generado en el propio job. Con R1.5 no hay `.env` que rellenar, así
   que la exigencia ya no es «usar valores sin significado» sino que no haya valores. Y la
   salida que la guardia lee **no contiene nada del `.env`**: medido, las variables quedan
   literales (`${JWT_SECRET_KEY:?…}`), mientras que `config` sin esas banderas inlina el
   fichero entero en `environment` —también variables que el compose no menciona—, que es lo
   que sostiene la prohibición de `specs/local-environment.md`.
7. THE SYSTEM SHALL **no volcar nunca** la salida de `docker compose config`, ni entera
   ni en fragmentos, ni como diagnóstico ni en un fallo: contiene los secretos resueltos
   (`JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `ENCRYPTION_KEY`, `BOOTSTRAP_*_PASSWORD`,
   `CHANNEX_API_KEY`) y en Actions stdout es un log persistido. El mensaje de fallo se
   compone **solo** de nombre de servicio y mapeo (R2.1), que no son sensibles.

### R2 — Falla nombrando el servicio y el mapeo concretos

**Como** quien recibe el rojo, **quiero** que el mensaje diga qué servicio y qué mapeo
lo provocan, **para que** arreglarlo no exija reproducir la comprobación a mano.

Criterios de aceptación:

1. IF algún servicio publica un puerto en el host sin acotarlo a `127.0.0.1`, THEN THE
   SYSTEM SHALL terminar con estado de salida distinto de cero nombrando el **servicio**
   y el **mapeo** infractor.
2. WHERE un mapeo se declara sin prefijo de interfaz, THE SYSTEM SHALL tratarlo como
   infractor: `docker compose config` **no** devuelve `"0.0.0.0"`, y Docker publica en todas
   las interfaces. Precisión medida el 2026-08-18 con Compose 5.1.1: la clave `host_ip` sale
   **ausente**, no como `null` — la comparación por igualdad con `"127.0.0.1"` cubre las dos
   formas, así que la guardia no depende de cuál sea (`design.md`, Data & interfaces).
3. WHEN no hay ninguna infracción, THE SYSTEM SHALL terminar con estado de salida cero y
   decir cuántos servicios y cuántos mapeos ha inspeccionado, para que el verde sea
   legible como «vio esto» y no como «no vio nada».

### R3 — La exención es por par servicio+puerto, nunca por servicio

**Como** responsable de la postura, **quiero** que la exención se declare por par,
**para que** un puerto extra en un servicio exento siga siendo un fallo.

Criterios de aceptación:

1. THE SYSTEM SHALL eximir exactamente dos pares **servicio+puerto**: `backend:8000` y
   `frontend:3000`, que publican en todas las interfaces a propósito porque el proyecto
   es mobile-first y así se abre la app desde un móvil real por la IP de LAN.
2. IF un servicio exento publica **cualquier otro** puerto fuera de loopback, THEN THE
   SYSTEM SHALL fallar igual — la exención cubre el par, no el servicio.
3. IF un servicio **no** exento publica en `backend:8000` o `frontend:3000`, THEN THE
   SYSTEM SHALL fallar — la exención cubre el par, no el puerto.

### R4 — Ve todo lo que el stack levantaría, y lo afirma antes de dar verde

**Como** revisor, **quiero** que la vista de la guardia no pueda ser más estrecha que la
de `make up`, **para que** un fichero, un profile o una variable de entorno no la
desvíen a mirar otra cosa.

Criterios de aceptación:

1. THE SYSTEM SHALL tomar su dato de `docker compose config --format json` y **no** del
   YAML a pelo, porque Compose es quien normaliza las formas de escribir un mapeo.
2. THE SYSTEM SHALL **delegar en Compose el descubrimiento de ficheros** —invocarlo sin
   `--file`— desinfectando antes el entorno (`COMPOSE_FILE`, `COMPOSE_PROFILES` y
   equivalentes), de modo que ni un `COMPOSE_FILE` exportado en el shell ni un
   `compose.yaml` que sustituya a `docker-compose.yml` desvíen la comprobación. Fijar
   los ficheros con `--file` **desactiva** la carga automática del override y una lista
   escrita a mano se queda corta.
3. THE SYSTEM SHALL evaluar los servicios declarados bajo `profiles:` **estén o no
   activos**: un servicio bajo un profile no activo es invisible para
   `docker compose config`.
4. THE SYSTEM SHALL **afirmar en positivo** antes de dar verde que el conjunto de
   servicios inspeccionados contiene los que el fichero declara y que el conjunto de
   profiles resueltos coincide con el enumerado; IF no puede confirmarlo, THEN SHALL
   fallar. Esta única aserción cierra a la vez la enumeración de profiles que se traga
   su propio fallo, el nombre de profile **con una coma** que rompe el viaje por
   `COMPOSE_PROFILES` (la coma es un carácter legítimo del dato y Compose no lo
   restringe) y un `config` que sale con **éxito** devolviendo `{}`.

### R5 — Detecta las formas de publicar que no declaran mapeo de host

**Como** responsable de la postura, **quiero** que la aserción sea sobre la presencia de
la clave `ports`, **para que** las formas que Docker publica en un puerto efímero no
pasen por conformes.

Criterios de aceptación:

1. THE SYSTEM SHALL asertar sobre la **presencia de la clave `ports`** y no sobre
   `published` ni sobre `host_ip`: `ports: ["5432"]` (corta, solo puerto de contenedor)
   y `{target: 6379, mode: ingress}` (larga sin `published`) salen como
   `{mode, target, protocol}` **sin `published` ni `host_ip`**, y Docker las publica en
   un puerto efímero y en todas las interfaces.
2. IF un servicio declara `network_mode: host`, THEN THE SYSTEM SHALL fallar: publica
   todo sin generar **ninguna** entrada `ports`, así que un bucle sobre `ports` lo trata
   como conforme.

### R6 — Nunca degrada a verde, y se demuestra en rojo antes de darse por buena

**Como** quien confía en el check, **quiero** que ningún fallo de la cadena produzca un
verde y que cada vía del censo tenga su prueba, **para que** el verde signifique algo —
esta guardia ya pasó verde cinco veces siendo eludible.

Criterios de aceptación:

1. IF cualquier paso de la cadena falla —`config` con error, JSON no parseable,
   enumeración de profiles rota, Compose por debajo de la versión mínima— THEN THE
   SYSTEM SHALL terminar en rojo con un mensaje propio que nombre el paso, y nunca en
   verde.
2. THE SYSTEM SHALL comprobar el estado de salida de cada invocación **aparte** de su
   contenido, sin `2>/dev/null` y sin quedar detrás de un pipe cuyo estado de salida sea
   el del último comando.
3. THE SYSTEM SHALL llevar suite de pruebas en `scripts/test_compose_ports.py`, siguiendo
   el patrón de `scripts/test_compose_stacks.py`, que **demuestre la guardia en rojo**
   para cada una de las **nueve** vías del censo, con un caso por vía: las ocho (a)-(h) de
   la entrada de roadmap más la **(i)** que midió `design.md` D2 — un mapeo de puertos
   construido con interpolación no se normaliza y sale como cadena cruda, así que una guardia
   que asuma objeto revienta o lo deja pasar. La obligación de método viene del historial: esta misma guardia pasó
   verde **cinco veces** siendo eludible, y el precedente del guard de fixtures de
   `channex-staging-adapter` pasó verde cubriendo un fichero de tres.
4. THE SYSTEM SHALL ejecutar esa suite en el mismo workflow de R1, de modo que una
   guardia que deje de detectar una vía rompa el check. Hoy **ningún workflow recoge
   `scripts/test_*.py`**: `backend-tests.yml` invoca pytest con
   `working-directory: backend`, así que las pruebas de `scripts/` solo se ejecutan a
   mano. Este change es el primero que las lleva a CI.
5. THE SYSTEM SHALL no duplicar ni contradecir la comprobación previa que `make up` ya
   hace en modo worktree (`specs/local-environment.md:120-124`): aquella asierta la
   **ausencia** de la clave `ports` antes de levantar un stack concreto; esta asierta la
   postura del repositorio en CI. Son sujetos distintos y deben seguir siéndolo.

## Out of scope

- **`PORT_OFFSET`** — publicar los puertos de un worktree enlazado con un desplazamiento
  para poder navegar la app. Es otra capacidad y va en su propio change; declarada fuera
  de alcance en `specs/local-environment.md:135-136`.
- **`docker-compose.deploy.yml`** — la guardia cubre la postura del stack **local**. Lo
  carga solo el CD (`deploy-dev.yml` le pasa `-f`), así que un `docker compose` desnudo
  nunca lo ve: incluirlo exigiría un `--file` explícito, que es exactamente la vía de
  elusión (f) del censo y rompería el criterio de que el veredicto sea función solo del
  repositorio. Además su regla es la **inversa**: allí `backend`/`frontend` publican en
  `127.0.0.1:8000` y `127.0.0.1:3000` **obligatoriamente** (`app-deploy-dev` R4.3: sin el
  prefijo se crearía una vía alternativa al túnel), así que los dos pares que aquí se
  eximen allí serían infracción. Dos conjuntos de exenciones opuestos no caben en una
  guardia.
- **Autenticar Redis** (`requirepass`) — el residual de que otro proceso de la propia
  máquina toque los contadores está aceptado en `specs/local-environment.md` y no se
  reabre aquí.
- **Verificación en red viva** de la postura (probar desde otro host de la LAN que los
  puertos acotados no responden) — quedó diferida al separar esta guardia y sigue fuera:
  esto comprueba la **declaración**, que es lo que impide la regresión.
- **Ampliar la lista de exenciones** o cambiar qué publica cada servicio. La postura ya
  está decidida en `local-dev-network-hardening`; esto solo la protege.

## Affected specs

- `sdd/specs/local-environment.md` — **modificar**, en cuatro sitios:
  1. §«Postura de red del stack local», líneas 73-77: el bullet *«Esta postura no tiene
     comprobación automática todavía»* pasa a describir la guardia.
  2. Sección propia que la describa, al lado de §«Diagnóstico de stacks de Compose».
  3. §«Diagnóstico de stacks de Compose», líneas 202-208: el criterio que **prohíbe
     `docker compose config` en cualquier forma** se acota **por forma y no por sujeto**
     (`design.md` D1): prohibido sin `--no-interpolate --no-env-resolution`, que es una
     condición comprobable, en vez de una excepción nominal para este script. La obligación
     que lo acompaña sigue siendo R1.7. La prohibición está escrita en tres sitios a propósito
     —docstring del script, comentario del `Makefile` y la spec—, así que **los tres**
     hay que tocarlos o el arreglo queda a medias.
  4. §«Makefile como entrypoint único», línea 251: dice que los targets que delegan en un
     script host-side *«no invocan `docker compose` desde el `Makefile` y por tanto no
     entran en la cuenta»* de nueve. Este script **sí** invoca `docker compose`, aunque
     desde Python: hay que decidir y escribir si la cuenta pasa a diez o si la frase se
     reformula.
- `sdd/steering/security.md` — **modificar**. La regla 8, párrafo de la exención de
  `POSTGRES_PASSWORD` (línea 34), afirma *«Hoy no hay comprobación automática de esa
  postura … hasta entonces esto depende de la revisión del diff»*. Pasa a citar la
  guardia como lo que sostiene la exención.
- `README.md` — **modificar**. §«Postura de red del stack local», líneas 57-58, misma
  afirmación que los dos anteriores.
- `sdd/specs/backend-ci.md` — **no se modifica**, pero se cita: es quien prohíbe `paths:`
  en `on:` y quien declara la suite del backend hermética a `backend/**`. Verificar al
  cerrar que el workflow nuevo no la contradice.

## Relación con `worktree-port-offset`

Escrito el mismo día (change hermano). El punto de contacto es R3: la exención se declara
hoy como los pares literales `backend:8000` y `frontend:3000`, y un stack con
desplazamiento de puertos publicaría `backend:8000+n` y `frontend:3000+n`. Si esta
guardia se construye con la exención literal, aquel change tendrá que reabrirla.

Esta entrada **no depende** de la otra y puede construirse ya: la vista canónica de la
guardia es la del repositorio sin desplazamiento. Lo que conviene es que el diseño deje
la exención expresada de forma que admitir un desplazamiento después sea un cambio de
datos y no de estructura. La relación inversa (`worktree-port-offset needs
compose-ports-guard`) es la que se propone declarar, y se decide allí.
