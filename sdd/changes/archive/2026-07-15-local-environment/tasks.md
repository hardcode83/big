# Tasks: local-environment

## 1. Root scaffold & shared config

- [x] 1.1 Crear `.gitignore` en la raíz (`.env`, `__pycache__/`, `*.pyc`, `.venv/`, `node_modules/`, `.next/`, `dist/`, `build/`) — antes de cualquier `git init`/`git add` (D11) — files: `.gitignore` [R6]
- [x] 1.2 Crear `.env.example` en la raíz: nombres de variable únicamente, sin valores (`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `REDIS_URL`, `BACKEND_INTERNAL_URL`, `NEXT_PUBLIC_*`), separando explícitamente server-only vs cliente (D6, security.md #8) — files: `.env.example` [R4, R2]
- [x] 1.3 Actualizar la línea "Monorepo" de `sdd/steering/architecture.md` a `/backend` (con `backend/devops/`), `/frontend` (con `frontend/devops/`), sin `/docker` raíz (D1) — files: `sdd/steering/architecture.md` [R1]

## 2. Backend skeleton

- [x] 2.1 Inicializar proyecto Python con `uv` (`backend/pyproject.toml`, `backend/uv.lock`): deps `fastapi`, `uvicorn[standard]`, `pydantic-settings`; grupo dev con `pytest`, `pytest-asyncio`, `httpx` (D3) — files: `backend/pyproject.toml`, `backend/uv.lock` [R5, R4]
- [x] 2.2 `Settings(BaseSettings)` como único punto de lectura de env vars del backend (D6) — files: `backend/app/core/config.py` [R4]
- [x] 2.3 App FastAPI con `GET /health` → `200 {"status":"ok"}`, más su test de integración con `httpx.AsyncClient` (R5.1, testing.md) — files: `backend/app/main.py`, `backend/tests/test_health.py` [R5]
- [x] 2.4 `backend/devops/Dockerfile` multi-stage: `base` (uv sync) → `dev` (reload, deps dev incluidas) y `base` → `builder` → `prod` (imagen lean, sin deps dev) (D3) — files: `backend/devops/Dockerfile` [R1, R4, R5]
- [x] 2.5 App Celery mínima (`app/worker.py`, broker/backend en `REDIS_URL`, sin tasks reales todavía) — necesaria para que el servicio `worker` de 4.2 (`celery -A app.worker worker`, D4) tenga algo que ejecutar; hueco detectado al ejecutar, añadido aquí en vez de en el proposal/design porque es un detalle de implementación de D4, no una decisión nueva — files: `backend/app/worker.py` [R5]

## 3. Frontend skeleton

- [x] 3.1 Inicializar proyecto Next.js 14+ App Router, TypeScript strict, Tailwind (steering `frontend.md`) — files: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/next.config.ts` — sin `tailwind.config.ts`: Tailwind v4 es CSS-first (`@import "tailwindcss"` en `globals.css`), no requiere fichero de config [R5, R4]
- [x] 3.2 Página raíz: fetch server-side a `${BACKEND_INTERNAL_URL}/health`, muestra "backend: ok/ko"; test con Testing Library mockeando el fetch (D9, testing.md) — files: `frontend/app/page.tsx`, `frontend/app/page.test.tsx` [R5]
- [x] 3.3 `frontend/devops/Dockerfile` multi-stage: `deps` → `dev` (bind mount, hot reload) y `deps` → `builder` → `prod` (`next build`, standalone output) (D3) — files: `frontend/devops/Dockerfile` [R1, R4, R5]

## 4. Docker Compose stack

- [x] 4.1 Servicios `postgres` (postgres:16) y `redis` (redis:7) con `healthcheck:` nativo, variables desde `.env` con `${VAR:?...}` fail-fast (D8) — files: `docker-compose.yml` [R2]
- [x] 4.2 Servicios `backend` y `worker`: mismo `build` (`context: ./backend`, `dockerfile: devops/Dockerfile`, `target: dev`), `command` distinto (`uvicorn --reload` vs `celery -A app.worker worker -l info`), bind mount `./backend:/app` + volumen nombrado propio en `/app/.venv` (`backend_venv`/`worker_venv` separados, ver D5 actualizado), `env_file: .env`, `depends_on: {postgres,redis: condition: service_healthy}`, `healthcheck` de `backend` contra `/health` (D4, D5, D6, D7, D8) — files: `docker-compose.yml` [R2, R4]
- [x] 4.3 Servicio `frontend`: `build` (`context: ./frontend`, `dockerfile: devops/Dockerfile`, `target: dev`), bind mount `./frontend:/app` + volúmenes nombrados en `/app/node_modules` y `/app/.next`, `BACKEND_INTERNAL_URL` vía `.env`, `depends_on: {backend: condition: service_started}` (D5, D7, D8) — files: `docker-compose.yml` [R2, R5]
- [x] 4.4 Verificar fail-fast: quitar/vaciar una variable requerida (p.ej. `POSTGRES_PASSWORD`) y confirmar que `docker compose up` falla con error explícito en vez de arrancar mal configurado (R2.3) — files: `docker-compose.yml` [R2]

## 5. Makefile

- [x] 5.1 `Makefile` raíz con targets `up`, `down`, `logs`, `ps`, `sh` que aceptan `SERVICE=` opcional (`make up` = stack completo; `make up SERVICE=backend` = ese servicio + sus dependencias vía `depends_on`) (D10) — files: `Makefile` [R3]

## 6. Git init & documentación

- [x] 6.1 `git init` en la raíz, `git add -A`, commit inicial `chore: scaffold monorepo + docker-compose dev stack` (después de que 1.1–5.1 existan) (D11) — [R6]
- [x] 6.2 `README.md` raíz: cómo arrancar (`make up`), URLs locales (`localhost:8000`, `localhost:3000`), variables de `.env.example` y su propósito, cómo levantar un componente suelto (`make up SERVICE=...`) (documentation.md) — files: `README.md` [R2, R3, R5]

## 7. Verification

- [x] 7.1 `make up` levanta postgres+redis+backend+worker+frontend sin errores; `curl localhost:8000/health` → `200 {"status":"ok"}`; `localhost:3000` muestra "backend: ok" [R2, R5]
- [x] 7.2 `make up SERVICE=backend` levanta backend+postgres+redis únicamente (frontend no arranca) [R3]
- [x] 7.3 Con el stack arriba, editar `backend/app/main.py` y `frontend/app/page.tsx`: el cambio se refleja sin rebuild manual (hot reload) [R2]
- [x] 7.4 Test suite backend: `cd backend && uv run pytest`; test suite frontend: `cd frontend && npm test` — ambas en verde [R5]
- [x] 7.5 `git log`/`git status`: un único commit inicial, sin `.env`/`node_modules`/`__pycache__`/`.venv` trackeados [R6]
