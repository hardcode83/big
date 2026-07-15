# Design: dev-environment

## Context

Repo greenfield: hoy solo existen el PRD, diagramas y `sdd/`. No hay código, no hay `.git`. Este change crea el primer código del repo: el scaffold de monorepo y el stack de desarrollo local. Todo lo que sigue (`domain-foundation` y el resto del roadmap) se construye encima de esta estructura.

`sdd/steering/architecture.md` fija hoy: *"Monorepo: `/backend` (FastAPI + Celery), `/frontend` (Next.js), `/docker`."* — un `/docker` **compartido a nivel de monorepo**. Se sustituye por un `devops/` **dentro de cada componente** (ver D1): ni queda un `/docker` raíz, ni un `Dockerfile` suelto en la raíz de cada componente. `architecture.md` se actualiza como tarea de este change (ya no es open question, ver D1).

## Decisions

### D1 — Layout: `devops/` por componente (Dockerfile + assets de CI/CD futuros), orquestación en la raíz

**Chosen:** `backend/devops/Dockerfile` y `frontend/devops/Dockerfile`, cada uno dentro de una subcarpeta `devops/` de su componente — reservada para lo que un pipeline CI/CD de ese componente necesite a futuro (scripts de build/test/lint propios), sin mezclarlo con el código de aplicación (`backend/app/`, `frontend/app/`). `docker-compose.yml` y `Makefile` **quedan en la raíz del repo**: son quienes conocen y orquestan *todos* los componentes a la vez (postgres/redis compartidos + backend + worker + frontend), así que no pueden vivir dentro de un solo componente. No se crea ningún `/docker` a nivel de monorepo.

Rejected: `/docker` compartido en la raíz con todos los Dockerfiles (texto actual de `architecture.md`) — separa el Dockerfile de su contexto de build y de los assets de CI/CD del propio componente. Rejected también: meter `docker-compose.yml`/`Makefile` dentro de `backend/devops/` o `frontend/devops/` — ninguno de los dos puede orquestar el stack completo desde dentro de un solo componente sin indirección extra (ver D2 para la alternativa descentralizada considerada y descartada).

Actualiza `sdd/steering/architecture.md`: la línea "Monorepo: `/backend`, `/frontend`, `/docker`" pasa a "Monorepo: `/backend` (con `backend/devops/`), `/frontend` (con `frontend/devops/`)" — se añade como tarea en `tasks.md`.

### D2 — `docker-compose.yml` y `Makefile` en la raíz del repo (no descentralizados)

**Chosen:** ambos ficheros viven en la raíz (`/docker-compose.yml`, `/Makefile`). Es la convención más habitual (`git clone && make up`) y mantiene la raíz como único punto de entrada local, coherente con D1.

Rejected: un `docker-compose.yml`/`Makefile` propio por componente (`backend/devops/docker-compose.yml`, con la raíz combinándolos vía `include:` de Compose v2.20+) — permitiría levantar cada componente de forma 100% autónoma, pero añade una capa de indirección (dos Makefiles, dos compose files por componente) que este change no necesita todavía; se puede introducir más adelante si el CI/CD real de un componente lo pide (YAGNI).

### D3 — Dockerfile multi-stage con target `dev` / `prod` (mismo Dockerfile, misma imagen base), gestor de paquetes `uv`

**Chosen:** cada Dockerfile (`backend/devops/Dockerfile`, `frontend/devops/Dockerfile`) define stages `base → dev` y `base → builder → prod`. `docker-compose.yml` construye con `context: ./backend` / `./frontend` y `dockerfile: devops/Dockerfile`, `target: dev` (deps de desarrollo, código montado por bind mount, reload activo). El despliegue remoto futuro construirá la misma imagen con `target: prod` (o el target por defecto, sin especificar). Esto cumple R4.2: una sola fuente de verdad de la imagen, sin comportamiento exclusivo de compose horneado dentro.

Backend usa **`uv`** como gestor de paquetes Python (stage `base` instala deps vía `uv sync` desde `pyproject.toml`/`uv.lock`): resolver rápido en Rust, buen cacheo de capas Docker (el `uv.lock` cambia menos que el código, así que la capa de deps se cachea entre builds), lockfile determinista.

Rejected: `Dockerfile.dev` + `Dockerfile` separados — duplica la lógica de instalación de dependencias y diverge con el tiempo. Rejected para el gestor de paquetes: `poetry` (más lento en builds Docker, misma expresividad que `uv` para este caso) y `pip`+`requirements.txt` (sin resolver de dependencias avanzado ni lockfile determinista de serie).

### D4 — Backend y worker comparten imagen

**Chosen:** un único `backend/devops/Dockerfile`; el servicio `worker` de docker-compose usa el mismo `build` que `backend` (misma imagen) con `command: celery -A app.worker worker -l info` en vez de `uvicorn`. Mismas dependencias exactas para API y Celery — no hay razón para dos imágenes.

Rejected: Dockerfile separado para el worker — duplicación sin beneficio; ambos comparten el mismo código de dominio.

### D5 — Hot reload vía bind mount + volúmenes nombrados por servicio para dependencias

**Chosen:** en el target `dev`, docker-compose monta `./backend:/app` y `./frontend:/app`, con un volumen **nombrado y distinto por servicio** sobre `/app/node_modules` (frontend) y sobre `/app/.venv` (backend y worker) para que no se pisen con el contenido del host. `backend` y `worker` comparten imagen (D4) pero **no** el volumen de `.venv` (`backend_venv` / `worker_venv` separados) — compartirlo causa una condición de carrera real al arrancar ambos contenedores a la vez: los dos intentan el "copy-up" inicial del volumen desde la misma imagen simultáneamente y el segundo falla (`mkdir ...: file exists`), detectado durante la implementación. Se prefieren volúmenes nombrados sobre anónimos por ser identificables en `docker volume ls` y depurables. Solo aplica a los contenedores `dev`; las imágenes `prod` copian el código y no montan nada.

Rejected: un volumen anónimo o nombrado compartido entre `backend` y `worker` — race condition confirmada al ejecutar (ver arriba).

Rejected: reconstruir la imagen en cada cambio — rompe el ciclo rápido de desarrollo que pide el proposal (R2.2).

### D6 — Configuración: `.env` + `.env.example`, pydantic-settings en backend

**Chosen:** `.env` en la raíz (gitignored), consumido por cada servicio de compose vía `env_file: .env`. `.env.example` versionado, solo con nombres de variable (cumple `security.md` #8). Backend expone `app/core/config.py` con una clase `Settings(BaseSettings)` (pydantic-settings) como único punto de lectura de env vars — nada de `os.getenv` disperso por el dominio. Frontend separa explícitamente en `.env.example`: variables server-only (p.ej. `BACKEND_INTERNAL_URL=http://backend:8000`) de variables expuestas al cliente (prefijo `NEXT_PUBLIC_...`).

Rejected: variables hardcodeadas o repartidas por múltiples ficheros — viola R4.1 (12-factor) y dificulta portar a un entorno remoto donde los valores cambian.

### D7 — Nombres de servicio y networking interno

**Chosen:** servicios de compose: `postgres`, `redis`, `backend`, `worker`, `frontend` (coincide con `sdd/project.md`). Dentro de la red de compose, el frontend llama al backend por DNS interno (`http://backend:8000`), nunca por `localhost`. Desde el host, se exponen los puertos publicados (`localhost:8000`, `localhost:3000`) para que el desarrollador los use directamente.

Rejected: `localhost` interno entre contenedores — no funciona en compose (cada contenedor tiene su propio localhost); confundiría además el futuro despliegue remoto donde el descubrimiento de servicios tampoco será `localhost`.

### D8 — Orden de arranque y healthchecks

**Chosen:** `postgres` y `redis` declaran `healthcheck:` nativo de compose; `backend`/`worker` usan `depends_on: condition: service_healthy` sobre ambos. `backend` expone su propio `healthcheck:` contra `/health` (R5.1); `frontend` depende de `backend` con `condition: service_started` (no bloquea si el backend tarda, ya que el placeholder solo hace un fetch informativo).

Rejected: sin `depends_on`/healthchecks — arrancar todo a la vez causa errores de conexión intermitentes a Postgres/Redis en el primer `make up`.

### D9 — Página placeholder del frontend verifica conectividad real

**Chosen:** la página raíz del frontend hace un fetch server-side a `${BACKEND_INTERNAL_URL}/health` y muestra el resultado (¬ "backend: ok/ko"). Verifica de extremo a extremo R5.2 y D7 (networking interno) en un solo vistazo tras `make up`.

Rejected: página estática sin fetch — no demuestra que el stack completo (networking incluido) funciona, que es el objetivo explícito de R5.

### D10 — Levantar por componente vía Makefile parametrizado (`SERVICE=`)

**Chosen:** el Makefile acepta una variable opcional `SERVICE`: `make up` levanta el stack completo; `make up SERVICE=backend` o `make up SERVICE=frontend` delega en `docker compose up -d $(SERVICE)`, que ya arranca ese servicio **más sus dependencias** declaradas vía `depends_on` (D8) — p.ej. `SERVICE=backend` trae consigo `postgres`+`redis`; `SERVICE=frontend` trae además `backend` y sus dependencias. Mismo patrón para `make down SERVICE=...`, `make logs SERVICE=...`, `make sh SERVICE=...` (shell dentro del contenedor). Reutiliza el grafo de dependencias de compose sin duplicar lógica ni mantener un target por servicio.

Rejected: un target por servicio (`make up-backend`, `make up-frontend`, ...) — más código de Makefile a mantener y a extender cada vez que aparezca un servicio nuevo (p.ej. en `domain-foundation`). Rejected también: Compose `profiles:` para aislar cada componente — útil si quisiéramos *excluir* dependencias automáticas (p.ej. frontend sin arrastrar backend), caso que no se pide aquí; se puede añadir más adelante si hace falta ese aislamiento explícito.

Nota derivada de D1 (no requiere mecanismo nuevo): al tener cada componente su propio `devops/Dockerfile` autocontenido, siempre es posible `docker build`/`docker run` un componente suelto fuera de compose — pierde el networking/env que aporta el stack (backend necesita postgres/redis; frontend necesita un backend accesible), así que el camino recomendado para el día a día sigue siendo `make up SERVICE=...`.

### D11 — `.gitignore` y primer commit

**Chosen:** `.gitignore` en la raíz cubriendo `.env`, `__pycache__/`, `*.pyc`, `.venv/` (o el equivalente del gestor de paquetes elegido), `node_modules/`, `.next/`, `dist/`, `build/`. `git init` + commit inicial `chore: scaffold monorepo + docker-compose dev stack`.

Rejected: `git init` sin `.gitignore` previo — riesgo real de commitear `.env`/`node_modules` en el primer commit si se hace en el orden equivocado.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Raíz | `docker-compose.yml`, `Makefile`, `.env.example`, `.gitignore`, `.git/` | Nuevos — stack, entrypoint, plantilla de config, ignores, repo git inicializado |
| Backend | `backend/devops/Dockerfile`, `backend/pyproject.toml` + `backend/uv.lock`, `backend/app/main.py` (FastAPI app + `/health`), `backend/app/core/config.py` (Settings) | Nuevo esqueleto mínimo — sin lógica de dominio todavía |
| Worker | (reusa `backend/devops/Dockerfile`) | Nuevo servicio de compose, comando `celery worker` |
| Frontend | `frontend/devops/Dockerfile`, `frontend/app/page.tsx` (placeholder + fetch a `/health`) | Nuevo esqueleto mínimo Next.js App Router |
| Steering | `sdd/steering/architecture.md` (línea "Monorepo: ...") | Actualizar a "Monorepo: `/backend` (con `backend/devops/`), `/frontend` (con `frontend/devops/`)" reflejando D1 |

## Data & interfaces

- Sin esquema de base de datos todavía (lo trae `domain-foundation`); `postgres` arranca con una DB vacía por defecto (`POSTGRES_DB` vía env var).
- Contrato nuevo: `GET /health` → `200 {"status": "ok"}`. Es el único endpoint de este change.
- Variables de entorno nuevas (nombres, en `.env.example`): `POSTGRES_*`, `REDIS_URL`, `BACKEND_INTERNAL_URL`, `NEXT_PUBLIC_*` (ninguna con valores reales en el repo, per `security.md` #8).

## Risks & mitigations

- **Bind mounts lentos/permisos en macOS**: mitigar con volúmenes anónimos para `node_modules`/venv (D5); si el rendimiento sigue siendo un problema, revisar en un change posterior (`:cached`/`:delegated` mount flags son mitigación conocida, no bloqueante aquí).
- **Drift entre target `dev` y `prod` del mismo Dockerfile**: mitigar compartiendo el stage `base` al máximo; el build real de `target: prod` no se verifica en este change (el despliegue remoto es out of scope), riesgo residual aceptado y explícito.
- **Primer commit accidental de secretos**: mitigado por D10 (`.gitignore` antes que `git add`).

## Open questions

Ninguna pendiente — resueltas durante este diseño:

1. ~~Actualizar `architecture.md`~~ → **Resuelto (D1)**: se corrige a `/backend` (con `backend/devops/`), `/frontend` (con `frontend/devops/`); sin `/docker` raíz.
2. ~~Gestor de paquetes Python~~ → **Resuelto (D3)**: `uv`.
