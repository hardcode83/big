# Proposal: worktree-port-offset

## Why

Desde `worktree-parallel-stack` (2026-08-05) un worktree enlazado levanta su stack **sin
publicar ningún puerto** (`ports: !reset []`), y eso resolvió lo único que colisionaba
entre dos stacks. El precio está escrito y aceptado: *«Lo que un worktree enlazado no
tiene: nada alcanzable desde el navegador del host, ni un cliente gráfico contra
`localhost:5432`»* (`specs/local-environment.md:134-136`).

Ese precio se ha pagado tres veces desde entonces, y la salida siempre fue la misma
frase aplazada — *«la salida es parametrizar los cuatro puertos con un desplazamiento
(`PORT_OFFSET`), no volver a publicarlos sin más»*:

- `worktree-parallel-stack` (design.md:65) lo rechazó: *«fuera de alcance por decisión de
  la propuesta; obliga a inventar puertos libres, y "no publicar" no»*.
- `api-ingress-routing` (design D9, decidido con Jose el 2026-08-08) lo rechazó otra vez
  y salió adelante sondeando el proxy **desde dentro de la red de compose** con
  `docker compose exec -T frontend node -e 'fetch(...)'`. Su propia corrección medida
  deja claro el límite de esa salida: *«Lo único que sigue sin existir es el navegador,
  que no hace falta para estas comprobaciones porque son de protocolo, no de interfaz.»*
- `compose-stacks-diagnostic` (proposal.md:69) volvió a citarlo como fuera de alcance.

Lo que cambia ahora es que **`hardening-release` trae la suite E2E de Playwright**
(PRD §26.25-28), que es exactamente una comprobación *de interfaz* y no de protocolo: un
navegador contra la app. Y el proyecto es **mobile-first**, con la comprobación en un
viewport de verdad hecha desde un móvil de la LAN — que hoy solo funciona en el worktree
principal. Trabajar esas features en un worktree aislado, que es lo que manda la regla 10
del toolkit, obliga hoy a elegir entre el aislamiento y poder ver la app.

**Nota sobre la premisa de partida**: esto no se pide para evitar choques de puertos.
Los choques ya no ocurren — no publicar nada los eliminó en vez de gestionarlos. Se pide
para recuperar el navegador que aquella decisión costó, **sin** reintroducir el choque.

## What changes

`make up PORT_OFFSET=<n>` levantará el stack de un worktree enlazado **publicando** los
cuatro puertos desplazados por `<n>` (`5432+n`, `6379+n`, `8000+n`, `3000+n`), de modo
que dos worktrees con desplazamientos distintos conviven publicando. Sin `PORT_OFFSET`
nada cambia: el worktree sigue sin publicar y el principal sigue publicando los cuatro
de siempre.

El desplazamiento **conserva la postura de red**: `postgres` y `redis` siguen acotados a
`127.0.0.1`, `backend` y `frontend` siguen en todas las interfaces, porque eso es lo que
permite abrir la app desde un móvil real por la IP de LAN — que es el motivo entero de
querer los puertos de vuelta.

## Requirements

### R1 — Un worktree puede publicar sus puertos desplazados

**Como** desarrollador trabajando una feature en un worktree aislado, **quiero** levantar
su stack con los puertos desplazados, **para que** pueda abrir la app en el navegador sin
bajar el stack de otra sesión.

Criterios de aceptación:

1. WHEN se ejecuta `make up PORT_OFFSET=<n>` en un worktree enlazado, THE SYSTEM SHALL
   publicar los cuatro puertos desplazados: `5432+n`, `6379+n`, `8000+n` y `3000+n`.
2. WHILE dos worktrees están levantados con desplazamientos distintos, THE SYSTEM SHALL
   arrancar ambos sin fallar por puerto ocupado.
3. THE SYSTEM SHALL aceptar el desplazamiento **también en el worktree principal**, para
   que el principal pueda apartarse en vez de obligar a bajarlo.
4. THE SYSTEM SHALL aplicar el mismo desplazamiento a los cuatro puertos —no uno por
   servicio— de modo que un solo número describa el stack entero.

### R2 — La postura de red se conserva bajo desplazamiento

**Como** responsable de la postura de red, **quiero** que desplazar no relaje nada,
**para que** la exención de la regla 8 de `steering/security.md` siga en pie.

Criterios de aceptación:

1. WHILE hay desplazamiento, THE SYSTEM SHALL publicar `postgres` y `redis` **únicamente
   en `127.0.0.1`**: ese Redis guarda los contadores del throttle de login y corre sin
   `requirepass`, y ese bind es su única defensa desde la red.
2. WHILE hay desplazamiento, THE SYSTEM SHALL publicar `backend` y `frontend` en **todas**
   las interfaces, que es lo que permite abrir la app desde un móvil de la LAN — el motivo
   de este change.
3. THE SYSTEM SHALL no publicar ningún puerto que no publique ya el stack sin
   desplazamiento: `worker`, `beat` y `migrate` siguen sin publicar nada.
4. THE SYSTEM SHALL dejar intacta la resolución **por nombre de servicio** dentro de la
   red de compose: `BACKEND_INTERNAL_URL` vale `http://backend:8000` y `REDIS_URL` es fija
   por la misma razón, así que el proxy `/api/` del frontend y la suite del backend no ven
   el desplazamiento en absoluto.

### R3 — Sin `PORT_OFFSET` no cambia nada

**Como** cualquiera que ya usa el proyecto, **quiero** que el comportamiento por defecto
sea idéntico al de hoy, **para que** este change no pueda romperle `make up` a nadie.

Criterios de aceptación:

1. WHEN se ejecuta `make up` sin `PORT_OFFSET` en un worktree enlazado, THE SYSTEM SHALL
   arrancar **sin publicar ningún puerto**, exactamente como hoy, y seguir abortando en
   rojo si en la configuración resuelta queda alguna clave `ports`.
2. WHEN se ejecuta `make up` sin `PORT_OFFSET` en el worktree principal, THE SYSTEM SHALL
   invocar `docker compose` **sin `-f`** y publicar los cuatro mapeos de siempre — lo que
   Compose descubre por sí solo debe seguir siendo la postura real del proyecto.
3. IF `PORT_OFFSET` vale `0` o está vacío, THEN THE SYSTEM SHALL comportarse como si no
   se hubiera pasado.

### R4 — El desplazamiento se anuncia; no hay que deducirlo

**Como** quien acaba de levantar el stack, **quiero** que `make up` me diga las URLs
reales, **para que** no tenga que sumar de cabeza ni leer el `Makefile`.

Criterios de aceptación:

1. WHEN `make up` arranca con desplazamiento, THE SYSTEM SHALL anunciar en qué modo lo
   hace y **enumerar los cuatro puertos efectivos**, ampliando el aviso de modo que ya
   existe hoy.
2. THE SYSTEM SHALL ofrecer una forma de consultar el desplazamiento vigente de un
   worktree ya levantado, sin volver a arrancarlo.
3. THE SYSTEM SHALL aplicar el mismo desplazamiento a los targets que dependen de él
   (`make down`, `make logs`, `make ps`, `make sh`), de modo que operar el stack
   desplazado no exija repetir el número en cada comando ni acabe hablando con otro stack.

### R5 — Falla pronto y en rojo ante un desplazamiento inservible

**Como** quien se equivoca al elegir el número, **quiero** un error que lo diga, **para
que** no se manifieste como «la app no carga».

Criterios de aceptación:

1. IF `PORT_OFFSET` no es un entero no negativo, THEN THE SYSTEM SHALL abortar antes de
   levantar nada, nombrando el valor recibido.
2. IF algún puerto desplazado cae fuera del rango válido (`> 65535`), THEN THE SYSTEM
   SHALL abortar nombrando cuál.
3. IF algún puerto desplazado ya está ocupado en el host, THEN THE SYSTEM SHALL abortar
   **antes** de arrancar, nombrando el puerto y el servicio — no dejar que Compose falle a
   medio levantar dejando contenedores a medias.
4. IF el desplazamiento se pide y `docker-compose.worktree.yml` no puede combinarse con
   él, THEN THE SYSTEM SHALL abortar con mensaje propio, nunca degradar a «publicar lo
   que salga».

### R6 — La guardia de puertos sigue siendo verdad bajo desplazamiento

**Como** responsable de la postura, **quiero** que la comprobación automática siga
diciendo la verdad cuando existe desplazamiento, **para que** este change no abra un
agujero en la guardia que lo protege.

Criterios de aceptación:

1. THE SYSTEM SHALL mantener válida la comprobación previa a levantar que ya hace
   `make up` en modo worktree, adaptándola: sin desplazamiento asierta **ausencia** de la
   clave `ports`; con desplazamiento asierta que cada mapeo publicado es el esperado para
   ese desplazamiento y con el prefijo de interfaz correcto.
2. THE SYSTEM SHALL dejar la exención de `compose-ports-guard` expresable bajo
   desplazamiento: hoy exime los pares **`backend:8000`** y **`frontend:3000`**, y un
   stack desplazado publica `backend:8000+n` y `frontend:3000+n`. Una exención por par
   literal daría rojo sobre un stack correcto.
3. THE SYSTEM SHALL mantener la vista canónica de la guardia sin desplazamiento: el
   resultado de la guardia es función **solo del repositorio**, así que `PORT_OFFSET` no
   puede ser una variable de entorno que le cambie el veredicto.

## Out of scope

- **La guardia de puertos en sí** — es `compose-ports-guard`, entrada hermana. Aquí solo
  se garantiza que sigue siendo expresable (R6); construirla es de allí.
- **Elegir el desplazamiento automáticamente** (derivarlo del nombre del worktree, de un
  hash de la ruta, o buscar el primer rango libre). El desplazamiento se pasa
  explícitamente; automatizarlo es justo lo que `worktree-parallel-stack` señaló como
  coste — *«obliga a inventar puertos libres»* — y merece su propia decisión con datos de
  uso, no un diseño a ciegas.
- **`docker-compose.deploy.yml`** — publica en `127.0.0.1:8000` y `127.0.0.1:3000` sobre
  la VM, lo carga solo el CD y nunca convive con otro stack. No se toca.
- **Volver a publicar por defecto en los worktrees.** El defecto sigue siendo no publicar:
  este change añade una salida explícita, no invierte la decisión de 2026-08-05.
- **Compartir datastores entre worktrees** — descartado en `worktree-parallel-stack` por
  acoplar los worktrees, y el coste de disco por proyecto sigue aceptado.
- **La suite E2E de Playwright** en sí. Llega con `hardening-release`; esto solo quita el
  impedimento de poder correrla desde un worktree.

## Affected specs

- `sdd/specs/local-environment.md` — **modificar**. §«Stacks en paralelo por worktree»:
  el bullet de líneas 134-136 deja de decir *«si alguna vez hace falta»* y pasa a describir
  el desplazamiento; el criterio de líneas 120-124 (comprobar antes de levantar que no
  queda ninguna clave `ports`) gana su variante con desplazamiento. §«Postura de red del
  stack local» gana la constancia de que la postura se conserva desplazada. §«Makefile como
  entrypoint único» refleja los targets que aceptan el parámetro.
- `sdd/project.md` — **modificar**. §«Worktree bootstrap» dice hoy *«Lo que no tendrás en
  un worktree: navegador»* y nombra `PORT_OFFSET` como salida futura; pasa a ser
  operativa.
- `README.md` — **modificar**. §«Postura de red del stack local» y el párrafo de worktrees
  (líneas ~40-42) afirman que en un worktree no hay nada que abrir en el navegador.
- `sdd/specs/frontend-auth-session.md` / `sdd/specs/api-contract.md` — **no se modifican**,
  pero conviene verificar al cerrar que ninguna instrucción de verificación local asume
  `localhost:3000` / `localhost:8000` literales.

## Relación con `compose-ports-guard`

Los dos changes se tocan en un punto concreto, y conviene decidirlo antes de implementar:
la guardia exime pares **servicio+puerto literales** (`backend:8000`, `frontend:3000`) y
un stack desplazado publica otros. Si la guardia se construye primero con la exención
literal, este change tendrá que reabrirla; si se construye sabiendo que el desplazamiento
existe, la exención se expresa una sola vez.

**Declarado** el 2026-08-18: la entrada de roadmap de este change lleva
`needs: compose-ports-guard`, de modo que la guardia aterrice primero y el desplazamiento
se diseñe contra una guardia que ya existe — en vez de que la guardia se diseñe contra un
desplazamiento hipotético. Consecuencia operativa: este change **no está en la frontera**
hasta que `compose-ports-guard` cierre.
