# Project Steering — AutoHostAI

## Overview

AutoHostAI es una **capa operativa inteligente sobre un PMS/Channel Manager externo** para viviendas turísticas: sustituye el trabajo de la gestora (MAGNO) — limpiezas, mantenimiento, mensajería con IA, accesos, reporting — empezando con 2 viviendas en Madrid y escalando después a SaaS. **No es un PMS ni un Channel Manager.**

Fuente de verdad funcional: `docs/AutoHostAI_PRD_v5_Claude.md` (PRD técnico v5, cerrado). Los proposals citan sus secciones.

## Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2.x async, Alembic, Pydantic v2, PostgreSQL 16, Redis 7, Celery.
- **Frontend**: Next.js 14+ (App Router), TypeScript strict, Tailwind, shadcn/ui, TanStack Query v5, Zustand, react-i18next (ES/EN), mobile-first.
- **Auth**: JWT (access 15 min + refresh 7 días con rotation), RBAC en backend, bcrypt.
- **Infra dev**: docker-compose (postgres:16, redis:7, backend+worker, frontend). Monorepo: `/backend` (con `backend/devops/Dockerfile`), `/frontend` (con `frontend/devops/Dockerfile`); `docker-compose.yml`/`Makefile` en la raíz.
- **Infra remota**: Terraform + GitHub Actions confirmados; proveedor cloud (AWS/GCP/Vercel/Railway) pendiente de decisión. Ver `steering/infra.md`.
- **Arquitectura**: monolito modular hexagonal por dominios; todo sistema externo detrás de adapter (mocks en MVP). Ver `steering/architecture.md`.

## Commands

- Arranque completo local: `make up` (copiar `.env.example` a `.env` antes). Por componente: `make up SERVICE=backend|frontend`.
- Backend tests: `docker compose exec backend uv run pytest` (el backend corre en Docker; `uv` no está instalado en el host). Con el stack parado: `docker compose run --rm backend uv run pytest`.
- Frontend: `cd frontend && npm run dev` / `npm test`
- E2E: `npx playwright test` (previsto — llega con `hardening-release`)

## Conventions

- Nombres canónicos exactos del PRD en código: estados operacionales (`VACANT_READY`…), enums, entidades (§7-8).
- Mensajes de sistema/logs/errores backend en **inglés**; UI con traducciones ES/EN en `locales/`.
- Marcar supuestos como `ASSUMPTION` y dependencias sin credenciales como `EXTERNAL_DEPENDENCY` en el código/docs.
- Reglas duras en `steering/`: architecture (vinculante en design), security (design/run), testing (tasks/run), documentation (tasks/archive), backend/frontend/infra por paths.

## Context

- PRD: `docs/AutoHostAI_PRD_v5_Claude.md` + diagramas en `docs/diagrams/` (C4, hexagonal, ER, state machine, secuencias).
- Roadmap: `sdd/roadmap.md` (16 changes desde PRD §26; `domain-foundation` se dividió en `-core`/`-ops`/`-financial`).
- MCPs activados: `playwright` (verificación E2E en run), `context7` (docs de stack). `postgres` todavía no añadido — la DB ya existe (`domain-foundation-core`, 8 tablas), se puede añadir con `/sdd:init` cuando se quiera (declinado de nuevo en el re-run de 2026-07-17).
- LSPs activados: `pyright-lsp` (Python/backend), `typescript-lsp` (TypeScript/frontend) — binarios instalados; falta ejecutar `/plugin install pyright-lsp` y `/plugin install typescript-lsp`.
- Reviewers de proyecto: `.claude/agents/sdd-review-tenancy.md` (tenant isolation, `steering/security.md` regla 1) y `sdd-review-i18n.md` (i18n es/en, `steering/frontend.md`) — añadidos 2026-07-17, descubiertos automáticamente por `/sdd:run` y `/sdd:review`.
- Usage metrics: activado (OTEL → `http://127.0.0.1:4318`, `.sdd-usage/` en `.gitignore`). Efectivo a partir de la próxima sesión.
- Perfil de modelos SDD: **Mixto** (opus new/design, sonnet grueso, haiku archive/status).
- Repo git inicializado (rama `main`) en el change `local-environment`.
