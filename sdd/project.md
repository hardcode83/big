# Project Steering — AutoHostAI

## Overview

AutoHostAI es una **capa operativa inteligente sobre un PMS/Channel Manager externo** para viviendas turísticas: sustituye el trabajo de la gestora (MAGNO) — limpiezas, mantenimiento, mensajería con IA, accesos, reporting — empezando con 2 viviendas en Madrid y escalando después a SaaS. **No es un PMS ni un Channel Manager.**

Fuente de verdad funcional: `docs/AutoHostAI_PRD_v5_Claude.md` (PRD técnico v5, cerrado). Los proposals citan sus secciones.

## Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2.x async, Alembic, Pydantic v2, PostgreSQL 16, Redis 7, Celery.
- **Frontend**: Next.js 14+ (App Router), TypeScript strict, Tailwind, shadcn/ui, TanStack Query v5, Zustand, react-i18next (ES/EN), mobile-first.
- **Auth**: JWT (access 15 min + refresh 7 días con rotation), RBAC en backend, bcrypt.
- **Infra dev**: docker-compose (postgres:16, redis:7, backend+worker, frontend). Monorepo: `/backend` (con `backend/devops/Dockerfile`), `/frontend` (con `frontend/devops/Dockerfile`); `docker-compose.yml`/`Makefile` en la raíz.
- **Infra remota**: Terraform + GitHub Actions; dev **operativo** en Oracle Cloud (VM única + docker-compose — `docs/adr/0001-dev-hosting-provider.md`) con CD real a dev (GHCR + runner self-hosted en la VM, `specs/app-deploy-dev.md`); staging/prod pendientes de decisión propia. Norma **IaC-first** innegociable en `steering/infra.md`.
- **Arquitectura**: monolito modular hexagonal por dominios; todo sistema externo detrás de adapter (mocks en MVP). Ver `steering/architecture.md`.

## Commands

- Arranque completo local: `make up` (copiar `.env.example` a `.env` antes). Por componente: `make up SERVICE=backend|frontend`.
- Backend tests: `docker compose exec backend uv run pytest` (el backend corre en Docker; `uv` no está instalado en el host). Con el stack parado: `docker compose run --rm backend uv run pytest`.
- Frontend: `cd frontend && npm run dev` / `npm test`
- E2E: `npx playwright test` (previsto — llega con `hardening-release`)

teardown: docker compose down --volumes --remove-orphans --rmi local

Lo que `/sdd:archive` corre **dentro** del worktree antes de borrarlo. Se lee entero, porque
cada trozo está elegido:

- `--volumes` **borra el `postgres_data` de ese worktree**, y eso es deliberado: el stack de un
  worktree es desechable por diseño (`worktree-parallel-stack`), y sin esta bandera cada worktree
  retirado deja ~8 volúmenes que, una vez borrado el directorio, ya no son atribuibles a nadie.
  No aplica nunca al stack del worktree principal, que `retire` no toca.
- `--rmi local` borra las 5 imágenes que compose construye para el proyecto y **conserva
  `postgres:16` y `redis:7`**, que son de Docker Hub y las comparten los stacks vivos de los
  demás worktrees. Un `--rmi all` se los llevaría por delante.

Declarado el 2026-08-15 al archivar `backend-response-hardening`: sin esta línea `retire` se
niega —correctamente— a adivinar un `down --volumes` sobre la base de datos de alguien, y el
worktree sobrevive al archivado con 4,1 GB colgando.

## Worktree bootstrap

Un worktree levanta **su propio stack**, en paralelo con el del principal y con el de cualquier otro worktree (change `worktree-parallel-stack`). No hay que apagar nada de nadie:

1. En el worktree de la feature: `make up`
2. Los comandos de *Commands* funcionan igual desde ahí
3. Al terminar, `make down` — y hazlo **antes** de borrar el worktree (ver «stacks huérfanos» abajo)

Lo que lo hace posible: Compose ya aísla contenedores, red y volúmenes por nombre de proyecto —que sale del nombre del directorio, y el del worktree es distinto—, así que lo único que colisionaba era la publicación de puertos en el host. Un worktree enlazado **no publica ninguno**: `make up` lo detecta por git (`--git-dir` distinto de `--git-common-dir`) y añade `docker-compose.worktree.yml`, que los retira con `ports: !reset []`. Te lo dice al arrancar, y antes de levantar comprueba que en la configuración resuelta no queda ningún mapeo `ports` — la ausencia del mapeo, no la de un puerto de host concreto, porque hay formas de `ports:` que Docker publica en un puerto efímero sin declararlo.

Y **sigue sin valer reutilizar el stack del principal**: `backend` y `frontend` montan el código por bind-mount (`./backend:/app`, `./frontend:/app`), así que sus contenedores sirven siempre el árbol desde el que se levantaron. Un `docker compose exec backend uv run pytest` desde el worktree apuntando al proyecto del principal probaría el código del principal, no el del change. Por eso cada worktree levanta el suyo.

**Lo que tampoco funciona tal cual: regenerar el contrato del frontend.** `cd frontend && npm run api:generate` (y su `api:check`) falla en un worktree enlazado, y no por el aislamiento de puertos: el contenedor `frontend` monta **solo** `./frontend` en `/app`, mientras que `frontend/scripts/generate-api-types.mjs` resuelve sus rutas dos niveles por encima de `scripts/` — busca `/backend/openapi.json` y escribe `/frontend/lib/api/generated/openapi.d.ts`, y ninguno de los dos existe ahí dentro. En el host tampoco corre, porque `node_modules` vive en un volumen de Docker y no en el árbol.

La salida mientras nadie lo arregle, usada y verificada en `dashboard-api` (produce un fichero idéntico al del comando documentado, y `api:check` lo confirma):

```bash
docker compose exec -T frontend mkdir -p /backend        # una vez por contenedor
docker compose cp backend/openapi.json frontend:/backend/openapi.json
docker compose exec -T frontend ln -sfn /app /frontend    # una vez por contenedor
docker compose exec -T frontend npm run api:generate
```

El `mkdir` de la primera línea no estaba y hace falta: `docker compose cp` **no** crea el
directorio padre en el destino, así que sin él la copia falla con *«Could not find the file
/backend in container …»* (visto en `backend-response-hardening`, 2026-08-15). En
`dashboard-api` no se notó porque aquel contenedor ya lo tenía creado a mano.

El arreglo de verdad es que el script acepte rutas por parámetro o que el contenedor monte la raíz del repo; no se hizo en `dashboard-api` porque es tooling del monorepo y no de esa capacidad. **Ojo**: la sección Verification de cualquier change que toque el contrato manda `cd frontend && npm run api:check`, y ese comando literal no funciona desde aquí.

**Y `npm test` tiene el mismo problema, con más ficheros.** Dos ficheros de test leen el árbol por encima de `/app` y fallan con `ENOENT` en un worktree —`features/provenance/workflow-contract.test.ts` y `lib/config/build-identity-contract.test.ts`—, así que un `npm test` recién levantado da **2 ficheros en rojo que no son del change que estés haciendo**. Es la misma causa que lo de arriba (el contenedor monta sólo `./frontend`) y tiene la misma salida; la lista exacta la levantó `tech-incident-context` el 2026-08-22 siguiendo los `ENOENT` uno a uno, y con ella la suite pasa entera. **La cifra de referencia se mide, no se recuerda**: `pricing-web` la midió el 2026-08-23 en **123 ficheros y 1101 tests**, y descubrió al hacerlo que el «63 ficheros, 415 tests» que esta línea traía era de varios changes atrás — el árbol *antes* de aquel change ya tenía 103 ficheros. Compara contra lo que dé tu `npm test` de partida, no contra un número escrito aquí, y recuerda que `make up` recrea el contenedor y con él se pierden los `docker compose cp`, así que los dos ENOENT reaparecen:

```bash
docker compose exec -T frontend mkdir -p /backend/app/provenance/api /backend/tests/fixtures /.github/workflows /.github/scripts
docker compose cp backend/app/provenance/provenance-contract.json  frontend:/backend/app/provenance/provenance-contract.json
docker compose cp backend/app/provenance/api/router.py             frontend:/backend/app/provenance/api/router.py
docker compose cp backend/tests/fixtures/build-identity-provenance.json frontend:/backend/tests/fixtures/build-identity-provenance.json
docker compose cp backend/openapi.json                             frontend:/backend/openapi.json
docker compose cp .github/workflows/deploy-dev.yml                 frontend:/.github/workflows/deploy-dev.yml
docker compose cp .github/workflows/frontend-tests.yml             frontend:/.github/workflows/frontend-tests.yml
docker compose cp .github/scripts/extract-pr.sh                    frontend:/.github/scripts/extract-pr.sh
docker compose cp docker-compose.yml                               frontend:/docker-compose.yml
docker compose cp docker-compose.deploy.yml                        frontend:/docker-compose.deploy.yml
```

Conviene saber **por qué importa copiar `backend/openapi.json`** y no sólo los ficheros de CI: uno de esos tests comprueba el esquema publicado contra el contrato de provenance, así que es el único de los dos que un change del backend puede romper de verdad. Los demás `ENOENT` son ruido del entorno; ése no. En el worktree principal no hace falta nada de esto, y en CI tampoco — allí el checkout está completo.

**Navegador en un worktree: por defecto no, y hay una salida explícita.** Sin puertos publicados no hay UI ni API alcanzables desde el host — ni `localhost:3000` ni `localhost:8000` ni un cliente gráfico contra `localhost:5432`. La suite sí corre, porque va por la red de compose (`postgres:5432`, `redis:6379`), que es por donde ha ido siempre.

Cuando **sí** necesitas el navegador —comprobar la UI, abrirla desde un móvil real de la LAN, correr Playwright—, `make up PORT_OFFSET=<n>` publica los cuatro puertos desplazados por `<n>`:

```bash
make up PORT_OFFSET=10   # postgres 5442, redis 6389, backend 8010, frontend 3010
make ports               # qué desplazamiento tiene el stack que está corriendo
```

La postura de red **se conserva**: `postgres` y `redis` siguen acotados a `127.0.0.1`, `backend` y `frontend` siguen en todas las interfaces (que es lo que permite abrirlo desde el móvil por la IP de esta máquina). Dos worktrees con desplazamientos distintos conviven publicando, y funciona también en el principal — con el matiz de que ahí no crea un segundo stack, **mueve el que hay**, porque el nombre de proyecto sale del directorio. Sin `PORT_OFFSET` —o con `PORT_OFFSET=0`— no cambia absolutamente nada.

El número solo hay que pasarlo a `up`: `down`, `logs`, `ps` y `sh` direccionan el proyecto por su nombre, no por sus puertos, así que dan con el mismo stack sin repetirlo. El filo único es que `up` es el que **crea** los mapeos, así que un **`make up SERVICE=<x>` parcial sin repetir `PORT_OFFSET`** recrearía ese servicio sin puertos.

**Con `PORT_OFFSET` la página hidrata y sirve para una pasada visual completa.** Re-medido el
2026-08-30 desde el worktree `guest-portal-messaging` con `PORT_OFFSET=41`, en Chromium real y
contra el stack de ese worktree: el `<form>` de login tiene `__reactProps` con `onSubmit`
cableado, el login redirige por React a `/dashboard` **sin** credenciales en la query string, y la
consola sale limpia —ni un error, y ningún fallo de handshake de HMR—. Sobre esa base se corrió
entera la comprobación manual extremo a extremo de `guest-portal-messaging` (tarea 12.6): portal
del huésped, envío de mensaje, respuesta automática, escalación, bandeja del manager con el canal
traducido y respuesta humana leída de vuelta desde el portal.

**Lo que decía antes esta sección, y por qué ya no.** Hasta el 2026-08-30 aquí ponía que la página
«se sirve pero NO hidrata», medido el 2026-08-23 en `cleaning-assign-preconditions` con
`PORT_OFFSET=37` —submit nativo del login, conmutador de idioma mudo, sin props de React en el
`<form>`, y un `ERR_INVALID_HTTP_RESPONSE` en el WebSocket de HMR—, y atribuía la causa, **sin
confirmarla**, a `next dev` sin `allowedDevOrigins`. Ninguno de esos síntomas se reproduce hoy, y
`frontend/next.config.ts` **sigue sin declarar `allowedDevOrigins`**: así que la causa que se
apuntaba era la equivocada, o el síntoma dependía de algo del entorno de aquella sesión. No se ha
diagnosticado por qué desapareció, y esa es la parte honesta de esta nota: lo que está medido es
que **hoy funciona**, no que no pueda volver.

La consecuencia práctica se invierte: para una pasada visual **no** hace falta el worktree
principal ni `dev`. Si vuelve a aparecer, el síntoma que lo delata en dos segundos es el `<form>`
sin `__reactProps`, y el arreglo candidato sigue siendo declarar `allowedDevOrigins`.

**Nada que copiar a mano**: `make up` crea `.env` desde `.env.example`, genera `JWT_SECRET_KEY` y ajusta permisos; las dependencias viven en volúmenes de Docker (`backend_venv`, `frontend_node_modules`), no en el árbol de ficheros. Requiere Docker Compose ≥ 2.35.0 y git ≥ 2.31 (por `--path-format`). El suelo de Compose lo fijan tres cosas y manda la mayor: 2.24 por el tag `!reset` de `docker-compose.worktree.yml`, 2.24.4 por el tag `!override` del overlay que genera `make up PORT_OFFSET=<n>`, y 2.35.0 por la bandera `--no-env-resolution` que usa `make check-compose-ports` (`specs/local-environment.md`).

Aviso de coste, que no desaparece: los volúmenes con nombre van **por proyecto de compose**. El stack de un worktree arranca con **base de datos vacía** y reinstala dependencias la primera vez — es lento, no está roto. Re-siembra con `make bootstrap`. Y ocupa sus propios gigas de disco: dos stacks a la vez son dos Postgres, dos Redis y dos juegos de dependencias.

**Stacks huérfanos**: si borras un worktree sin bajar su stack, los contenedores siguen vivos y ya no queda nada que lo explique — y ojo, que `git worktree remove` **falla** si Docker dejó ficheros suyos en el árbol, así que el caso normal es «worktree desregistrado, directorio en pie». Por eso: `make down` **antes** de borrar el worktree. Y lo que retiene un huérfano es **disco** —volúmenes e imágenes—, no puertos: un worktree enlazado no publica ninguno, así que el coste es silencioso y solo el stack del principal puede chocar de puertos. Para verlo a posteriori, `make compose-stacks` lista los proyectos de la máquina con su directorio de origen y los marca (`vivo` con su rama, `huérfano`, `ajeno`, `indeterminado`); informa y no baja nada. Atribuye cruzando rutas contra `git worktree list` y **no** por etiquetas de contenedor, que cualquier contenedor de la máquina puede poner.

## Conventions

- Nombres canónicos exactos del PRD en código: estados operacionales (`VACANT_READY`…), enums, entidades (§7-8).
- Mensajes de sistema/logs/errores backend en **inglés**; UI con traducciones ES/EN en `locales/`.
- Marcar supuestos como `ASSUMPTION` y dependencias sin credenciales como `EXTERNAL_DEPENDENCY` en el código/docs.
- Reglas duras en `steering/`: architecture (vinculante en design), security (design/run), testing (tasks/run), documentation (tasks/archive), backend/frontend/infra por paths.

## Context

- PRD: `docs/AutoHostAI_PRD_v5_Claude.md` + diagramas en `docs/diagrams/` (C4, hexagonal, ER, state machine, secuencias).
- Roadmap: `sdd/roadmap.md` (25 entradas: los changes del PRD §26 más los añadidos de infra/CD sobre la marcha; `domain-foundation` se dividió en `-core`/`-ops`/`-financial`).
- MCPs activados: `playwright` (verificación E2E en run), `context7` (docs de stack), `postgres` (inspección read-only del esquema local; la cadena en `.mcp.json` lleva la contraseña de dev `localdev`, exenta por `steering/security.md` regla 8) y `github` (repo/PRs/issues, OAuth al primer uso) — los dos últimos añadidos en el re-run de 2026-07-29.
- LSPs activados: `pyright-lsp` (Python/backend), `typescript-lsp` (TypeScript/frontend) — binarios instalados; falta ejecutar `/plugin install pyright-lsp` y `/plugin install typescript-lsp`.
- Reviewers de proyecto (en `.claude/agents/`, descubiertos automáticamente por `/sdd:run` y `/sdd:review`): `sdd-review-tenancy.md` (tenant isolation, `steering/security.md` regla 1) y `sdd-review-i18n.md` (i18n es/en, `steering/frontend.md`) desde 2026-07-17; `sdd-review-cicd.md` (workflows + Terraform contra las reglas EARS de `specs/infra-dev-terraform.md` y `steering/infra.md`) y `sdd-review-documentation.md` (`steering/documentation.md`, modelo haiku) desde 2026-07-29.
- Usage metrics: activado (OTEL → `http://127.0.0.1:4318`, `.sdd-usage/` en `.gitignore`). Efectivo a partir de la próxima sesión.
- Perfil de modelos SDD: **Mixto** (opus new/design, sonnet grueso, haiku archive/status).
- Repo git inicializado (rama `main`) en el change `local-environment`; alojado en GitHub bajo la org **`autohostai-labs`** (`git@github.com:autohostai-labs/AutoHostAI.git`) — motivo y alternativas en `docs/adr/0002-github-org-hosting.md`.
