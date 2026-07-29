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
