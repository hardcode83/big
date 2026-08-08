# AutoHostAI

Capa operativa inteligente sobre un PMS/Channel Manager externo para viviendas turísticas. Ver `docs/AutoHostAI_PRD_v5_Claude.md` para el PRD completo y `sdd/` para el flujo de desarrollo (Spec-Driven Development).

## Arrancar en local

Requisitos: Docker + **Docker Compose ≥ 2.24**, **git ≥ 2.31**, `make`.

Los dos suelos de versión son del soporte para varios stacks a la vez: Compose 2.24 introdujo el tag `!reset` que usa `docker-compose.worktree.yml`, y git 2.31 el `--path-format` con el que `make up` distingue un worktree enlazado del principal. Por debajo del suelo de git la detección falla hacia «publicar», así que un worktree chocaría de puertos en vez de arrancar sin ellos.

```bash
make up   # levanta todo el stack: postgres, redis, backend, worker, beat, frontend
```

Sin pasos previos: `make up` crea `.env` automáticamente desde `.env.example` (valores locales por defecto, sin secretos reales) si no existe todavía, y **genera en él la clave de firma JWT** con `openssl rand -hex 32` si falta — el valor se queda en tu máquina y nunca vive en el repositorio. Las migraciones de base de datos (Alembic) también se aplican solas — un servicio `migrate` corre `alembic upgrade head` antes de que `backend`/`worker`/`beat` arranquen.

Al cabo de unos segundos:

- Backend (FastAPI): http://localhost:8000/health — API en http://localhost:8000/api/v1, documentación navegable en http://localhost:8000/docs
- La misma API, **en el origen del frontend**: http://localhost:3000/api/v1 — la sirve un proxy same-origin (`frontend/app/api/[...path]/route.ts`), que es el camino que usa el navegador y el único que existe en el entorno desplegado. Enruta **solo** `/api/`: `/docs` y `/openapi.json` no viajan por ahí a propósito, así que para la documentación navegable usa el puerto 8000 de arriba. Ver [`docs/ingress-https.md`](docs/ingress-https.md)
- Frontend (Next.js): http://localhost:3000 — Application Shell; `/` redirige a `/dashboard`. El **dashboard** (`/dashboard`) y el **detalle de propiedad** (`/properties/[id]`) son funcionales en modo solo lectura sobre datos mock (ver [`docs/dashboard.md`](docs/dashboard.md)); el resto de rutas de módulos muestran un placeholder "en preparación". No requiere backend para renderizar.
- Postgres: localhost:5432 — ya con el esquema de dominio creado (`tenants`, `users`, `properties`, `guests`, `reservations`, `timeline_events`, ...)
- Redis: localhost:6379

```bash
make bootstrap         # crea el tenant y los usuarios iniciales (ver abajo)
make openapi           # regenera el contrato de API (ver abajo)
make down              # para y elimina los contenedores del stack
make logs               # sigue los logs de todos los servicios
make ps                  # estado de los contenedores
```

Las URLs de arriba son las del **worktree principal**. Un worktree enlazado de git levanta su propio
stack en paralelo, pero **sin publicar puertos**, así que allí no hay nada que abrir en el navegador
del host — la suite sí corre, porque va por la red de compose. `make up` te dice en qué modo arranca.
Detalle y coste en `sdd/project.md` §«Worktree bootstrap».

### Postura de red del stack local

`docker-compose.yml` publica `postgres` y `redis` **solo en `127.0.0.1`**: no son alcanzables
desde otros equipos de tu red, solo desde esta máquina (`localhost:5432` y `localhost:6379`
siguen funcionando igual, incluida la suite ejecutada en el host). No es higiene: ese Redis
guarda los contadores del límite de intentos de login, y quien pueda borrarlos entre intentos
anula el límite de 10/min por IP y el bloqueo tras 10 fallos.

`backend` (`8000`) y `frontend` (`3000`) sí publican en **todas** las interfaces, y es
deliberado: es lo que permite abrir la app desde un móvil real por la IP de tu LAN, que es
como se comprueba el diseño mobile-first. Así que el stack local no es "invisible desde la
red" — la UI y la API sí lo son; el acceso directo al datastore, no.

**Esta postura no tiene todavía comprobación automática**: si alguien publica un puerto sin el
prefijo `127.0.0.1:`, hoy solo lo atrapa la revisión del diff. La guardia que lo comprobaría en
cada PR es una entrada propia del roadmap (`compose-ports-guard`), separada de este cambio
porque construirla bien resultó ser un problema con más fondo del que parece — ver el análisis
heredado en esa entrada.

**Ojo con el alcance, para no leerlo de más**: lo que esto protege es el acceso *desde la red*.
Redis corre sin `requirepass`, así que otro proceso de tu propia máquina sí puede tocar esos
contadores; se acepta porque es una máquina de desarrollo con datos de prueba.

**Los cuatro mapeos son del worktree principal.** Un worktree enlazado de git levanta su stack
**sin publicar ninguno**: `make up` añade allí `docker-compose.worktree.yml`, que los retira con
`ports: !reset []`, y comprueba antes de levantar que en la configuración resuelta no queda **ningún
mapeo de puertos declarado** — no solo ninguno con puerto de host explícito, porque hay formas de
`ports:` que Docker publica en un puerto efímero sin declararlo. Los mapeos siguen
declarados en `docker-compose.yml` a propósito, y no en un fichero aparte: es esa declaración la que
describe la postura de red del proyecto, la que ve un `docker compose config` desnudo y la que
`compose-ports-guard` podrá comprobar.

**Consecuencia práctica para los `docker compose` desnudos de este README**, y conviene ser preciso
porque no afecta a todos igual. En el worktree principal valen todos, porque ahí `make` tampoco pasa
`-f`. En un worktree enlazado solo importan los que **crean** contenedores, que cargarían el fichero
base e intentarían publicar los cuatro puertos:

- `docker compose up ...` (Migraciones usa `docker compose up -d postgres`) → usa `make up SERVICE=postgres`.
- `docker compose run ...` **cuando arrastra dependencias**, y aquí está el caso que más engaña:
  `run` no publica lo suyo, pero su `depends_on` toca `postgres`/`redis` — y **tenerlos ya levantados
  no protege**. Compose recrea una dependencia cuyo hash de configuración no coincide con la que está
  corriendo, y un `docker compose` desnudo en un worktree calcula la configuración del fichero base,
  *con* los cuatro mapeos. **Medido**: con la dependencia viva y sin puertos, un `run` desnudo imprime
  `Recreate` y la deja publicando. Así que desde un worktree la única salida es que el conjunto de
  ficheros coincida (ve por `make`, que añade el overlay) o `--no-deps` si el comando no necesita la
  base de datos — que es exactamente por lo que `make openapi` lo lleva.
- `docker compose exec`, `logs`, `ps`, `down` → **no crean nada**, actúan sobre los contenedores ya
  vivos del proyecto, y funcionan igual desde un worktree. Por eso el
  `docker compose exec backend uv run pytest` de §Tests es correcto en los dos sitios.

Si algo choca de puertos, `docker compose ls` dice qué proyectos hay vivos y desde qué fichero; el
diagnóstico con marcas (huérfano, otro worktree, ajeno) es una entrada propia del roadmap,
`compose-stacks-diagnostic`.

### Levantar un solo componente

`SERVICE=` es opcional en `up`/`down`/`logs`/`sh`. Compose arranca automáticamente las dependencias declaradas de ese servicio:

```bash
make up SERVICE=backend    # backend + postgres + redis (sin frontend)
make up SERVICE=frontend   # frontend + backend + sus dependencias
make sh SERVICE=backend    # shell dentro del contenedor de backend
```

## Entrar en la aplicación

El producto no tiene registro público, así que los usuarios iniciales se crean con un
comando. Rellena los `BOOTSTRAP_*` de tu `.env` (van sin valor a propósito: son
contraseñas de personas) y ejecuta:

```bash
make bootstrap   # crea el tenant, su config y dos usuarios: TENANT_OWNER y PROPERTY_MANAGER
```

Es idempotente y falla antes de escribir nada si falta alguna variable. No está
enganchado a `make up` para que el arranque siga sin pasos manuales.

A partir de ahí **el resto de las cuentas se dan de alta por API**, sin volver a tocar la
máquina: `POST /api/v1/users` crea el usuario y devuelve una contraseña temporal una sola vez.
El bootstrap sigue siendo lo único que da la primera entrada a un entorno nuevo.

Endpoints de auth: `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`,
`POST /api/v1/auth/logout`, `GET /api/v1/auth/me`. Operación, configuración del límite de
intentos y las cosas que sorprenden: [`docs/auth-tenancy.md`](docs/auth-tenancy.md).

Administración del tenant: `/api/v1/users` (alta, listado, edición, baja, reset de contraseña)
y `/api/v1/tenants/{id}` (datos del tenant y sus umbrales, SLAs y ventanas). Quién puede hacer
qué y qué rastro deja: [`docs/user-management.md`](docs/user-management.md).

Inventario de viviendas: `/api/v1/properties` (alta, listado paginado, detalle y edición). Es lo
que hay que hacer **antes** de poder crear ninguna reserva, porque toda vía de entrada —el alta
manual, el import CSV y el sync del PMS— resuelve la propiedad primero. Quién puede darlas de
alta, cómo se retira una sin borrar historial y por qué la contraseña del wifi no se puede leer
de vuelta: [`docs/properties.md`](docs/properties.md).

## Migraciones (Alembic)

El esquema se aplica solo al arrancar (`make up` → servicio `migrate`). Para cambiarlo:

```bash
cd backend
uv run alembic revision --autogenerate -m "descripción del cambio"   # genera una migración
uv run alembic upgrade head                                          # aplica pendientes
uv run alembic downgrade -1                                           # revierte la última
```

Requiere Postgres alcanzable (`make up` levantado, o al menos `docker compose up -d postgres`).

## Contrato de API (OpenAPI)

`backend/openapi.json` es el contrato de la API, versionado en el repositorio. Es lo que
consume el frontend para saber la forma de cada endpoint, y el sitio donde un cambio de
respuesta se ve en el diff del Pull Request que lo provoca.

```bash
make openapi   # regenéralo tras cambiar la forma de una respuesta
```

No necesita el stack levantado: la generación no toca base de datos, Redis ni red. El
workflow `api-contract` lo comprueba en cada PR y falla si el fichero commiteado ya no
corresponde al código, indicando este mismo comando.

El frontend consume el contrato mediante el generador fijado
`openapi-typescript@6.7.6`. Desde `frontend/`, `npm run api:generate` regenera
`frontend/lib/api/generated/openapi.d.ts` y `npm run api:check` comprueba que el artefacto
versionado no ha derivado. Ambos comandos usan Node 22, `npm ci` y la misma implementación
versionada en macOS, Linux y CI. El workflow `frontend-api-contract` ejecuta ese check en cada
PR y push a `main`; si hay diferencias muestra el diff y el comando de regeneración.

El cliente permanece genérico y solo expone tipos derivados de OpenAPI: no crea wrappers por
endpoint ni conecta todavía el dashboard al backend real. El workflow `api-contract` del backend
continúa comprobando por separado que `backend/openapi.json` corresponde al código backend.

La documentación interactiva sigue disponible en http://localhost:8000/docs con el stack
levantado.

## Variables de entorno

Ver `.env.example` — trae valores por defecto funcionales para config local sin sensibilidad real. Lo que hace aceptable ese default de Postgres es que `docker-compose.yml` publica `postgres` y `redis` **solo en `127.0.0.1`**, así que la base de datos no es alcanzable desde otros equipos de tu red. Los secretos reales (credenciales de proveedores externos) nunca llevan valor por defecto ahí — solo el nombre (`security.md` #8).

`make up` genera **dos** claves en tu `.env` local si faltan, y nunca se versionan:

- `JWT_SECRET_KEY` — firma de tokens, `openssl rand -hex 32`.
- `ENCRYPTION_KEY` — cifrado en reposo (Fernet) de las credenciales de PMS. **No tiene la misma forma que la anterior**: Fernet exige base64 de 32 bytes, así que un `rand -hex 32` lo rechaza el validador al arrancar. Se genera con `openssl rand 32 | base64 | tr '+/' '-_' | tr -d '\n'`. El `tr -d` no es opcional: `base64` cierra con salto de línea y sin él salen 45 caracteres, que el validador rechaza al arrancar.

A diferencia de la de firma, la de cifrado **no se regenera sola si ya hay un valor**: cambiarla deja indescifrable todo lo ya cifrado, así que ante una clave con forma incorrecta `make up` para y avisa en lugar de sustituirla.

## Estructura

- `backend/` — FastAPI + Celery (Python, `uv`). Dockerfile en `backend/devops/Dockerfile`. Código de dominio en `backend/app/<dominio>/` con las cuatro capas `domain/` → `application/` → `infrastructure/` → `api/` (regla de dependencia y fontanería en [`docs/adr/0004-backend-layering-pattern.md`](docs/adr/0004-backend-layering-pattern.md) y `sdd/steering/backend-architecture.md`). Son 16 dominios; los que todavía son **solo estructura de datos** —entidades y esquema, sin ningún caso de uso que los use— nacen con `domain/` + `infrastructure/` a secas, y ganan `application/`/`api/` cuando llega el primer caso de uso real: hoy `auth`, `properties`, `reservations`, `integrations`, `tenants`, `cleaning`, `access`, `guests` y `notifications` son los que tienen las cuatro —`properties` ganó su `api/` con `properties-crud`, y `access`, `guests` y `notifications` con `access-notifications`, que trajo la operación de accesos (PRD §15), el registro legal de huéspedes (§17) y la entrega de notificaciones (§14). El **scheduler** vive en `backend/app/scheduler/` — capa de entrega para el reloj, el equivalente de `api/` para Celery beat: seis tareas —las cuatro de PRD §8.3 más `dispatch_notifications` y `provision_access_records`, que el PRD no nombra y `access-notifications` declara como divergencia—, su calendario y el lock que evita solapes (ver [`docs/celery-jobs.md`](docs/celery-jobs.md)). Comandos operativos en `backend/app/cli/` y `backend/app/integrations/cli/`; adapters de sistemas externos en `backend/app/integrations/`, que además guarda la tabla `webhook_events`; migraciones en `backend/alembic/`. **`backend/scripts/`** queda deliberadamente **fuera de `app/`**: son herramientas de un solo uso contra servicios externos (provisión y sondeo del sandbox de Channex — ver [`docs/channex-staging.md`](docs/channex-staging.md)) o de medición puntual (`measure_tenant_filter.py`) que no deben viajar en el paquete desplegado.
- `frontend/` — Next.js App Router (TypeScript strict, Tailwind, shadcn/ui, TanStack Query, Zustand, react-i18next ES/EN). Application Shell organizado por capas `app/` → `features/` → `components/`·`lib/`. En `app/` vive además la **única pieza de servidor del frontend**: `app/api/[...path]/route.ts`, el proxy same-origin que reenvía `/api/` al backend por la red interna — es lo que hace que el navegador alcance la API sin exponer el backend, y su alcance está fijado por `app/proxy-scope.test.ts` ([`docs/ingress-https.md`](docs/ingress-https.md)). Convenciones detalladas en [`frontend/README.md`](frontend/README.md). Dockerfile en `frontend/devops/Dockerfile`.
- `docker-compose.yml` / `Makefile` — orquestación del stack **local** (build local, hot-reload), en la raíz.
- `docker-compose.worktree.yml` — overlay que **retira la publicación de puertos** en el host. `make up` lo añade solo cuando detecta un worktree enlazado de git, para que varios stacks de desarrollo convivan sin chocar. El worktree principal no lo usa y el CD no lo ve nunca.
- `docker-compose.deploy.yml` / `.env.deploy.example` — orquestación del **deploy a dev**: imágenes de GHCR por SHA (sin build), consumido por el CD en la VM.
- `sdd/` — flujo de Spec-Driven Development: specs, changes en curso, steering, roadmap.

Comandos de consola del backend (no hay endpoint para ninguno, a propósito):

- `python -m app.integrations.cli.pms_sync <tenant>` — sincroniza reservas desde el PMS de cada propiedad.
- `python -m app.integrations.cli.pms_credentials set|rotate|show-providers` — guarda y rota las credenciales de proveedor. El secreto se pasa por `PMS_CREDENTIAL_SECRET`, **nunca como argumento**: un argumento queda en el historial del shell y es visible en `ps`. Ver `docs/pms-credentials.md`.

## Despliegue a dev (CD)

Push a `main` que toque `backend/**`/`frontend/**` → `.github/workflows/deploy-dev.yml` construye las imágenes `prod` arm64, las publica en GHCR y las despliega en la VM dev (Oracle Cloud) mediante un runner self-hosted que corre en la propia VM (deploy local, sin SSH). Detalle de operación en [`infra/environments/dev/RUNBOOK.md`](infra/environments/dev/RUNBOOK.md) §6.

La app desplegada se sirve en **https://autohostai.digitalsec.work**, a través de un Cloudflare Tunnel: `cloudflared` corre en la VM y abre una conexión saliente al edge, que termina TLS y entrega al frontend por una red de compose dedicada al ingress — desde la que **no** se alcanzan `postgres`, `redis` ni `backend`, para que el routing remoto del túnel no pueda publicarlos. **Los puertos 8000 y 3000 ya no están expuestos** — el security list de la VM solo permite SSH (22), y no hay ningún puerto entrante para HTTP/HTTPS. Decisión y alternativas en [`docs/adr/0003-https-ingress-dev.md`](docs/adr/0003-https-ingress-dev.md); operación y diagnóstico en [`RUNBOOK.md`](infra/environments/dev/RUNBOOK.md) §7.
- `docs/` — documentación extendida por capability y diagramas (`docs/diagrams/`: C4, hexagonal, ER, state machine, secuencias).
- `infra/` — IaC por entorno (Terraform), no por dominio de negocio; ver `infra/environments/<entorno>/README.md`.
- `.github/workflows/` — pipelines de CI/CD (GitHub Actions).

## Tests

```bash
docker compose exec backend uv run pytest      # backend, con el stack levantado
docker compose run --rm backend uv run pytest  # backend, con el stack parado (solo en el principal)
cd frontend && npm test                        # frontend, en el host
```

El backend corre **en Docker** y `uv` no está instalado en el host, así que su suite se ejecuta
dentro del contenedor (una versión anterior de este README decía `cd backend && uv run pytest`, que
no funciona en una máquina limpia). El frontend sí se ejecuta en el host, con las dependencias que
`npm install` deja en `frontend/node_modules`.

**Desde un worktree enlazado**: la suite habla con `postgres:5432` y `redis:6379` por la red de
compose, que es el camino que ha usado siempre — los puertos del host nunca estuvieron en esa ruta, así
que no publicar no le afecta. La primera forma (`exec`) va siempre: no crea ni recrea nada, se engancha
a los contenedores que ya corren.

La segunda (`run --rm`) **no vale desnuda en un worktree, ni siquiera con el stack levantado**.
Medido, porque la intuición dice lo contrario: Compose recrea una dependencia cuyo hash de
configuración no coincide con la que está corriendo, y un `docker compose` desnudo ahí calcula la del
fichero base —con los cuatro mapeos—, así que recrea `postgres`/`redis` **publicando**. Con el stack
vivo y sin puertos, un `run` desnudo imprime `Recreate` y los deja publicados. Desde un worktree: o
`make up` y `exec`, o `--no-deps` si el comando no toca base de datos, o pasa los dos `-f` a mano.
Mismo criterio, en más detalle, en §«Postura de red del stack local».

El backend tiene **gate de CI en cada PR** (`.github/workflows/backend-tests.yml`):
migraciones Alembic sobre un PostgreSQL limpio, `alembic check`, la suite completa y
`downgrade base`, con Postgres y Redis como services.

La suite tarda ~6 minutos, así que **solo se ejecuta cuando el diff toca `backend/**` o el
propio workflow**. El check `backend-tests`, en cambio, **se reporta siempre**: en un PR que
no toca el backend termina en verde en segundos, y el resumen de la ejecución dice
explícitamente que la suite se omitió, para que ese verde no se lea como una suite que pasó.
Un `workflow_dispatch` manual la ejecuta entera en cualquier caso.

Que el check reporte siempre no es un detalle: un filtro de rutas en el disparador `on:`
haría que el workflow no arrancase, y un check requerido que nunca reporta deja el PR
bloqueado para siempre. Por eso la decisión vive dentro de la ejecución y no en `on:`.

Hoy **no está marcado como obligatorio**: el repositorio es privado en un plan sin protección
de rama, así que se ejecuta y reporta pero nada impide fusionar con él en rojo (ver
`sdd/specs/backend-ci.md` §Estado). Cuando pueda marcarse, el contexto a exigir es
`backend-tests` —el job consolidador—, nunca `backend-tests-suite`, que se salta de forma
legítima.

Al abrir la app, el pie muestra la **versión desplegada** (`0.1.0+2026-07-31.5872022`), en el
workspace, las apps de campo y también en `/login` sin sesión — así no hace falta entrar en la
VM para saber qué está corriendo. La versión base vive en `VERSION` (raíz) y el CD la compone
con la fecha de build y el commit corto; el pie muestra esa cadena completa, la misma que
llevan los labels OCI de las imágenes. Cómo se opera:
[`docs/app-version-visibility.md`](docs/app-version-visibility.md).

La API de negocio ya tiene su primera capability: **reservas** (`/api/v1/reservations` más la
importación por CSV `/api/v1/integrations/pms/import-csv`). Se opera por API — el frontend llega
con `dashboard-web` — y la sincronización con el PMS se lanza como comando:

```bash
docker compose exec backend uv run python -m app.integrations.cli.pms_sync <tenant-uuid>
```

Roles, formato del CSV, idempotencia y qué queda en el timeline:
[`docs/reservations.md`](docs/reservations.md).

### Verificación del frontend

```bash
cd frontend
npm run dev         # servidor de desarrollo (http://localhost:3000)
npm run typecheck   # TypeScript strict, sin emitir
npm run lint        # ESLint (incluye las fronteras app → features → components/lib)
npm test            # Vitest + Testing Library
npm run build       # build de producción
npm run test:entrypoint  # test del entrypoint de dev (sincronización de node_modules)
```

> Al añadir o actualizar una dependencia del frontend basta con `docker compose up` (o `make up SERVICE=frontend`): el contenedor de dev sincroniza `node_modules` con `package-lock.json` en el arranque, sin `npm install` manual ni reconstruir la imagen.

## Desarrollo con SDD

Este proyecto se desarrolla con **Spec-Driven Development**: cada feature pasa por fases con aprobación humana entre ellas, y el estado completo vive versionado en [`sdd/`](sdd/README.md) — cualquier sesión de agente puede continuar donde lo dejó la anterior.

**Setup (una vez):** los comandos `/sdd:*` los da el plugin [sdd-toolkit](https://github.com/hardcode83/sdd-toolkit) de Claude Code:

```
/plugin marketplace add hardcode83/sdd-toolkit
/plugin install sdd@sdd-toolkit
```

**El ciclo de cada feature:**

| Paso | Comando | Resultado |
|---|---|---|
| 1 | `/sdd:status` | ¿Dónde estamos? Changes activos + roadmap como to-do list |
| 2 | `/sdd:new` | Proposal con requisitos EARS desde la siguiente entrada del roadmap (`sdd/roadmap.md`) — **apruebas tú** |
| 3 | `/sdd:design` | Decisiones técnicas (se salta si el cambio es trivial) — **apruebas tú** |
| 4 | `/sdd:tasks` | Checklist de tareas verificables — **apruebas tú** |
| 5 | `/sdd:run` | Implementa en orden; panel de revisores (architect/security/qa) por sección |
| 6 | `/sdd:archive` | Fusiona en `sdd/specs/`, actualiza README/`docs/`, archiva el change |

**Reglas del repo:**

- Los cambios no triviales entran por `/sdd:new`, nunca directo a código — así `sdd/specs/` sigue siendo la verdad de lo construido.
- Las reglas de arquitectura/seguridad/testing viven en `sdd/steering/` — son vinculantes para agentes (las carga cada fase y las verifica el panel) y para humanos.
- El PRD (`docs/AutoHostAI_PRD_v5_Claude.md`) es la referencia funcional origen; el estado real del sistema son las specs.

Para aprender el flujo completo: [guía paso a paso](https://github.com/hardcode83/sdd-toolkit/blob/main/docs/guide.md) (10 min).
