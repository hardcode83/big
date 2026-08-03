# AutoHostAI

Capa operativa inteligente sobre un PMS/Channel Manager externo para viviendas turísticas. Ver `docs/AutoHostAI_PRD_v5_Claude.md` para el PRD completo y `sdd/` para el flujo de desarrollo (Spec-Driven Development).

## Arrancar en local

Requisitos: Docker + Docker Compose v2, `make`.

```bash
make up   # levanta todo el stack: postgres, redis, backend, worker, frontend
```

Sin pasos previos: `make up` crea `.env` automáticamente desde `.env.example` (valores locales por defecto, sin secretos reales) si no existe todavía, y **genera en él la clave de firma JWT** con `openssl rand -hex 32` si falta — el valor se queda en tu máquina y nunca vive en el repositorio. Las migraciones de base de datos (Alembic) también se aplican solas — un servicio `migrate` corre `alembic upgrade head` antes de que `backend`/`worker` arranquen.

Al cabo de unos segundos:

- Backend (FastAPI): http://localhost:8000/health — API en http://localhost:8000/api/v1, documentación navegable en http://localhost:8000/docs
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

Para derivar los tipos TypeScript del contrato:

```bash
npx openapi-typescript backend/openapi.json -o frontend/lib/api/schema.d.ts
```

Todavía **no está cableado**: hacerlo es trabajo de la entrada `frontend-ci` del roadmap,
que añadirá `openapi-typescript` como `devDependency` del frontend —con versión en el
lockfile, en vez de este `npx` flotante— junto a un script de npm y la comprobación de que
los tipos no han derivado del contrato.

Ese typecheck es lo que rompe ante un cambio incompatible. El workflow `api-contract`
**no**: solo garantiza que `backend/openapi.json` esté al día respecto al código.

La documentación interactiva sigue disponible en http://localhost:8000/docs con el stack
levantado.

## Variables de entorno

Ver `.env.example` — trae valores por defecto funcionales para config local sin sensibilidad real (Postgres solo alcanzable dentro de la red de compose). Los secretos reales futuros (credenciales de proveedores externos) nunca llevarán valor por defecto ahí — solo el nombre (`security.md` #8).

## Estructura

- `backend/` — FastAPI + Celery (Python, `uv`). Dockerfile en `backend/devops/Dockerfile`. Código de dominio en `backend/app/<dominio>/` con las cuatro capas `domain/` → `application/` → `infrastructure/` → `api/` (regla de dependencia y fontanería en [`docs/adr/0004-backend-layering-pattern.md`](docs/adr/0004-backend-layering-pattern.md) y `sdd/steering/backend-architecture.md`). Son 16 dominios; los que todavía son **solo estructura de datos** —entidades y esquema, sin ningún caso de uso que los use— nacen con `domain/` + `infrastructure/` a secas, y ganan `application/`/`api/` cuando llega el primer caso de uso real: hoy `auth`, `reservations`, `integrations` y `tenants` son los únicos con las cuatro. Comandos operativos en `backend/app/cli/` y `backend/app/integrations/cli/`; adapters de sistemas externos en `backend/app/integrations/`, que además guarda la tabla `webhook_events`; migraciones en `backend/alembic/`.
- `frontend/` — Next.js App Router (TypeScript strict, Tailwind, shadcn/ui, TanStack Query, Zustand, react-i18next ES/EN). Application Shell organizado por capas `app/` → `features/` → `components/`·`lib/`. Convenciones detalladas en [`frontend/README.md`](frontend/README.md). Dockerfile en `frontend/devops/Dockerfile`.
- `docker-compose.yml` / `Makefile` — orquestación del stack **local** (build local, hot-reload), en la raíz.
- `docker-compose.deploy.yml` / `.env.deploy.example` — orquestación del **deploy a dev**: imágenes de GHCR por SHA (sin build), consumido por el CD en la VM.
- `sdd/` — flujo de Spec-Driven Development: specs, changes en curso, steering, roadmap.

## Despliegue a dev (CD)

Push a `main` que toque `backend/**`/`frontend/**` → `.github/workflows/deploy-dev.yml` construye las imágenes `prod` arm64, las publica en GHCR y las despliega en la VM dev (Oracle Cloud) mediante un runner self-hosted que corre en la propia VM (deploy local, sin SSH). Detalle de operación en [`infra/environments/dev/RUNBOOK.md`](infra/environments/dev/RUNBOOK.md) §6.

La app desplegada se sirve en **https://autohostai.digitalsec.work**, a través de un Cloudflare Tunnel: `cloudflared` corre en la VM y abre una conexión saliente al edge, que termina TLS y entrega al frontend por la red interna del compose. **Los puertos 8000 y 3000 ya no están expuestos** — el security list de la VM solo permite SSH (22), y no hay ningún puerto entrante para HTTP/HTTPS. Decisión y alternativas en [`docs/adr/0003-https-ingress-dev.md`](docs/adr/0003-https-ingress-dev.md); operación y diagnóstico en [`RUNBOOK.md`](infra/environments/dev/RUNBOOK.md) §7.
- `docs/` — documentación extendida por capability y diagramas (`docs/diagrams/`: C4, hexagonal, ER, state machine, secuencias).
- `infra/` — IaC por entorno (Terraform), no por dominio de negocio; ver `infra/environments/<entorno>/README.md`.
- `.github/workflows/` — pipelines de CI/CD (GitHub Actions).

## Tests

```bash
cd backend && uv run pytest
cd frontend && npm test
```

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
