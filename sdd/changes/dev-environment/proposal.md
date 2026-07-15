# Proposal: dev-environment

## Why

El proyecto es greenfield: no existe todavía ni código ni repositorio git. Antes de escribir cualquier lógica de dominio (change `foundation`/`domain-foundation`), hace falta un scaffold de monorepo y un stack local reproducible con un solo comando, para que todo el desarrollo posterior (backend, frontend, DB) tenga un entorno consistente desde el primer día — y que ese entorno esté construido de forma que despliegue en la nube más adelante sin rehacer la estructura.

## What changes

Se crea la estructura de monorepo (`backend/`, `frontend/`, cada uno con su propio `Dockerfile`), un `docker-compose.yml` en la raíz que levanta el stack completo (postgres, redis, backend, worker, frontend), un `Makefile` en la raíz como único punto de entrada (`make up`, `make down`, `make logs`, ...), un esqueleto mínimo ejecutable en cada componente (backend: FastAPI con `/health`; frontend: Next.js con página placeholder) para verificar que el stack arranca de extremo a extremo, y la inicialización del repositorio git (primer commit, `.gitignore`).

## Requirements

### R1 — Estructura de monorepo por componente

**As a** developer, **I want** cada componente (backend, frontend) en su propio directorio de primer nivel con su propio Dockerfile, **so that** cada componente se pueda construir/desplegar de forma independiente y el layout coincida con cómo se desplegará en la nube.

Acceptance criteria:

1. WHEN se scaffoldea el repo, THE SYSTEM SHALL contener los directorios de primer nivel `backend/` y `frontend/`, cada uno con su propio `Dockerfile`.
2. WHEN se añada un nuevo componente en el futuro (p.ej. un worker separado), THE SYSTEM SHALL poder seguir la misma convención (directorio propio + Dockerfile propio) sin cambiar el layout raíz.

### R2 — Stack local vía Docker Compose

**As a** developer, **I want** un único fichero docker-compose que levante el stack completo (postgres, redis, backend, worker, frontend), **so that** pueda desarrollar contra un entorno realista sin instalar dependencias en local.

Acceptance criteria:

1. WHEN se ejecuta `docker compose up` en la raíz del repo, THE SYSTEM SHALL arrancar los contenedores de postgres:16, redis:7, backend, worker (Celery) y frontend.
2. WHEN cambia el código fuente de backend o frontend, THE SYSTEM SHALL reflejar el cambio sin reconstruir la imagen manualmente (bind mount + hot reload), para uso en desarrollo.
3. IF falta una variable de entorno requerida, THEN THE SYSTEM SHALL fallar de forma explícita con un mensaje claro en vez de arrancar mal configurado en silencio.

### R3 — Makefile como punto de entrada único

**As a** developer, **I want** un Makefile en la raíz que envuelva los comandos de docker-compose, **so that** no tenga que recordar flags de docker-compose para el día a día.

Acceptance criteria:

1. WHEN se ejecuta `make up`, THE SYSTEM SHALL levantar el stack completo de docker-compose (equivalente a R2.1).
2. WHEN se ejecuta `make down`, THE SYSTEM SHALL parar y eliminar los contenedores del stack.
3. WHEN se ejecutan otros comandos comunes (`make logs`, `make ps`, `make sh-backend`, ...), THE SYSTEM SHALL delegar en el comando docker-compose equivalente.

### R4 — Compatibilidad con despliegue remoto/nube

**As a** developer, **I want** que la configuración del stack local siga patrones compatibles con un futuro despliegue en la nube, **so that** no haya que rehacer las imágenes ni la estructura al desplegar remoto.

Acceptance criteria:

1. WHEN backend o frontend leen configuración, THE SYSTEM SHALL obtenerla de variables de entorno (12-factor), nunca de valores hardcodeados en el código.
2. WHEN se construye una imagen Docker de un componente, THE SYSTEM SHALL ser utilizable tanto en local (vía docker-compose) como en un runtime remoto (misma imagen, distinto orquestador/entorno) — sin asunciones exclusivas de docker-compose horneadas en la imagen (p.ej. hostnames de compose hardcodeados).
3. WHERE se necesiten secretos/credenciales en local, THE SYSTEM SHALL usar un fichero `.env` ignorado por git, con una plantilla `.env.example` versionada.

### R5 — Esqueleto mínimo ejecutable por componente

**As a** developer, **I want** una app esqueleto mínima en cada componente, **so that** se pueda verificar que el stack completo arranca de extremo a extremo antes de que exista lógica de dominio.

Acceptance criteria:

1. WHEN arranca el contenedor de backend, THE SYSTEM SHALL exponer un endpoint `/health` (FastAPI) que responda 200 OK.
2. WHEN arranca el contenedor de frontend, THE SYSTEM SHALL servir una página placeholder (Next.js) que confirme conectividad con el `/health` del backend.

### R6 — Inicialización del repositorio git

**As a** developer, **I want** el repo inicializado en git con ignores sensatos, **so that** todos los changes siguientes se puedan trackear y revisar.

Acceptance criteria:

1. WHEN se aplica este change, THE SYSTEM SHALL tener un repositorio git inicializado en la raíz con un commit inicial.
2. WHEN se generan artefactos de build, `.env`, `node_modules`, `__pycache__`, volúmenes de datos, etc., THE SYSTEM SHALL excluirlos vía `.gitignore`.

## Out of scope

- Modelos de dominio, enums, esquema de base de datos y migraciones Alembic — pasan a una entrada de roadmap separada (`domain-foundation`), que se construirá encima de este scaffold.
- Despliegue real en la nube (Terraform, ECS/EKS, CI/CD) — este change solo garantiza que las imágenes/configuración sean *compatibles*, no implementa el despliegue en sí.
- Autenticación, lógica de negocio, cualquier endpoint más allá de `/health` — quedan para changes posteriores del roadmap.
- Suite E2E con Playwright — cubierta por el change `hardening-release` al final del roadmap.

## Affected specs

- `sdd/specs/dev-environment.md` (no existe aún — se creará al archivar este change).
