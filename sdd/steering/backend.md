---
applies_to: ["backend/**"]
---

# Backend conventions — AutoHostAI

## Estructura (hexagonal por dominio)

`backend/app/<dominio>/` con separación puertos/adaptadores: `domain/` (entidades, servicios puros), `application/` (casos de uso), `infrastructure/` (repositorios SQLAlchemy, adapters), `api/` (routers FastAPI). Adapters externos compartidos en `app/integrations/`.

Reglas de diseño dentro de cada capa (DDD + SOLID + regla de dependencia, con ejemplos): ver `steering/backend-architecture.md`.

## Patrones

- SQLAlchemy 2.x **async** + Alembic; toda entidad con `tenant_id`, `created_at`, `updated_at` (TIMESTAMPTZ), UUID PK — esquemas exactos del PRD §7.
- Pydantic v2 para request/response models; enums de Python espejando los del PRD con nombres exactos.
- Routers finos → casos de uso → servicios de dominio. La lógica nunca vive en el router.
- Convenciones API del PRD §23: paginación `?page&per_page`, errores `{error:{code,message,details}}`, fechas ISO 8601 UTC.
- Celery: jobs idempotentes (los ejecuta el beat cada pocos minutos), con nombres del PRD §8.3.
- Mensajes de sistema, logs y errores técnicos **en inglés**.

## Don'ts

- No saltarse `PropertyStateMachine` para cambiar estados.
- No acceder a un proveedor externo fuera de su adapter.
- No queries sin tenant scope.
