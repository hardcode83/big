# AutoHostAI

Capa operativa inteligente sobre un PMS/Channel Manager externo para viviendas turísticas. Ver `AutoHostAI_PRD_v5_Claude (1).md` para el PRD completo y `sdd/` para el flujo de desarrollo (Spec-Driven Development).

## Arrancar en local

Requisitos: Docker + Docker Compose v2, `make`.

```bash
cp .env.example .env   # rellena los valores (ver comentarios en el propio fichero)
make up                # levanta todo el stack: postgres, redis, backend, worker, frontend
```

Al cabo de unos segundos:

- Backend (FastAPI): http://localhost:8000/health
- Frontend (Next.js): http://localhost:3000 — muestra "backend: ok" cuando el backend responde
- Postgres: localhost:5432
- Redis: localhost:6379

```bash
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

## Variables de entorno

Ver `.env.example` — nombres y formato esperado de cada variable, sin valores reales (nunca se commitea `.env`).

## Estructura

- `backend/` — FastAPI + Celery (Python, `uv`). Dockerfile en `backend/devops/Dockerfile`.
- `frontend/` — Next.js App Router (TypeScript, Tailwind). Dockerfile en `frontend/devops/Dockerfile`.
- `docker-compose.yml` / `Makefile` — orquestación del stack local, en la raíz.
- `sdd/` — flujo de Spec-Driven Development: specs, changes en curso, steering, roadmap.

## Tests

```bash
cd backend && uv run pytest
cd frontend && npm test
```

## Desarrollo con SDD

Este proyecto se desarrolla con **Spec-Driven Development**: cada feature pasa por proposal (requisitos EARS) → design → tasks → implementación con panel de revisión → archivado en las specs vivas. Todo el estado vive en [`sdd/`](sdd/README.md); las specs de lo ya construido están en `sdd/specs/` y el plan en `sdd/roadmap.md`.

Los comandos (`/sdd-toolkit:*`) los proporciona el plugin [sdd-toolkit](https://github.com/hardcode83/sdd-toolkit) de Claude Code:

```
/plugin marketplace add hardcode83/sdd-toolkit
/plugin install sdd-toolkit@sdd-toolkit
```

Para aprender el flujo: [guía de uso paso a paso](https://github.com/hardcode83/sdd-toolkit/blob/main/docs/guide.md) (10 min). Regla de oro del repo: los cambios no triviales entran por `/sdd-toolkit:new`, nunca directo a código — así las specs siguen siendo verdad.
