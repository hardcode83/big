# Project Steering — AutoHostAI

## Overview

AutoHostAI es una **capa operativa inteligente sobre un PMS/Channel Manager externo** para viviendas turísticas: sustituye el trabajo de la gestora (MAGNO) — limpiezas, mantenimiento, mensajería con IA, accesos, reporting — empezando con 2 viviendas en Madrid y escalando después a SaaS. **No es un PMS ni un Channel Manager.**

Fuente de verdad funcional: `AutoHostAI_PRD_v5_Claude (1).md` (PRD técnico v5, cerrado). Los proposals citan sus secciones.

## Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2.x async, Alembic, Pydantic v2, PostgreSQL 16, Redis 7, Celery.
- **Frontend**: Next.js 14+ (App Router), TypeScript strict, Tailwind, shadcn/ui, TanStack Query v5, Zustand, react-i18next (ES/EN), mobile-first.
- **Auth**: JWT (access 15 min + refresh 7 días con rotation), RBAC en backend, bcrypt.
- **Infra dev**: docker-compose (postgres:16, redis:7, backend+worker, frontend). Monorepo: `/backend` (con `backend/devops/Dockerfile`), `/frontend` (con `frontend/devops/Dockerfile`); `docker-compose.yml`/`Makefile` en la raíz.
- **Infra remota**: Terraform + GitHub Actions confirmados; proveedor cloud (AWS/GCP/Vercel/Railway) pendiente de decisión. Ver `steering/infra.md`.
- **Arquitectura**: monolito modular hexagonal por dominios; todo sistema externo detrás de adapter (mocks en MVP). Ver `steering/architecture.md`.

## Commands

- Arranque completo local: `make up` (copiar `.env.example` a `.env` antes). Por componente: `make up SERVICE=backend|frontend`.
- Backend tests: `cd backend && uv run pytest`
- Frontend: `cd frontend && npm run dev` / `npm test`
- E2E: `npx playwright test` (previsto — llega con `hardening-release`)

## Conventions

- Nombres canónicos exactos del PRD en código: estados operacionales (`VACANT_READY`…), enums, entidades (§7-8).
- Mensajes de sistema/logs/errores backend en **inglés**; UI con traducciones ES/EN en `locales/`.
- Marcar supuestos como `ASSUMPTION` y dependencias sin credenciales como `EXTERNAL_DEPENDENCY` en el código/docs.
- Reglas duras en `steering/`: architecture (vinculante en design), security (design/run), testing (tasks/run), documentation (tasks/archive), backend/frontend/infra por paths.

## Context

- PRD: `AutoHostAI_PRD_v5_Claude (1).md` + diagramas en `docs/diagrams/` (C4, hexagonal, ER, state machine, secuencias).
- Roadmap: `sdd/roadmap.md` (13 changes desde PRD §26).
- MCPs activados: `playwright` (verificación E2E en run), `context7` (docs de stack). `postgres` pendiente de añadir cuando exista la DB.
- Perfil de modelos SDD: **Mixto** (opus new/design, sonnet grueso, haiku archive/status).
- Repo git inicializado (rama `main`) en el change `local-environment`.
