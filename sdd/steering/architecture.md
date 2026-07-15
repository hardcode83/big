---
phases: [design, tasks]
---

# Architecture — AutoHostAI

Diagramas: `2026-07-13_autohost-c4-contenedores.png`, `-hexagonal-dominios.png`, `-er-entidades-core.png`, `-maquina-estados.png`, `-secuencia-{limpieza,mantenimiento}.png`.

## Forma del sistema

**Monolito modular** con arquitectura hexagonal, separado por dominios de negocio (PRD §3.2): `auth`, `tenants`, `properties`, `reservations`, `guests`, `cleaning`, `maintenance`, `messaging`, `access`, `pricing`, `statements`, `notifications`, `timeline`, `integrations`. Sin microservicios en MVP; el código debe permitir extraer servicios en el futuro.

Monorepo: `/backend` (FastAPI + Celery, con `backend/devops/Dockerfile`), `/frontend` (Next.js, con `frontend/devops/Dockerfile`). Sin `/docker` a nivel de raíz — `docker-compose.yml` y `Makefile` orquestando todo el stack viven en la raíz del repo (change `local-environment`). Despliegue remoto (IaC/CI-CD): convención en `infra/` — ver `steering/infra.md`, ortogonal a este layout por dominio.

## Decisiones firmes

- **Todo sistema externo detrás de adapter** (PRD §3.3): PMSAdapter, AccessProviderAdapter, AIAdapter, WhatsAppAdapter, EmailAdapter, PhoneAdapter, SESHospedajesAdapter, PricingDataAdapter, StorageAdapter, DoorSensorAdapter. El core nunca se acopla a un proveedor. MVP = implementaciones mock/manual con la interfaz definitiva.
- **PropertyStateMachine es el único lugar donde ocurren transiciones de estado** (PRD §8). Estados y transiciones son los del PRD, nombres exactos. Cada transición persiste `PropertyStateTransition` + `TimelineEvent`.
- **Timeline inmutable y ciudadano de primera clase** (PRD §10): nunca se editan eventos pasados; toda acción relevante lo genera.
- **GrinPass sin API directa** (PRD §5.5): el flujo pasa por el PMS. `OCCUPIED_ESTIMATED` se calcula sin sensor de puerta (§5.6); nada puede requerir `DOOR_OPENED`.
- Jobs programados = Celery beat (PRD §8.3), SLA enforcement cada minuto sobre `NotificationLog`.
- API REST `/api/v1/` con las convenciones del PRD §23 (paginación, errores `{error:{code,...}}`, ISO 8601 UTC, Bearer JWT).

## Anti-patrones (prohibido)

- Acoplar dominio a proveedor externo sin adapter.
- Transiciones de estado fuera de `PropertyStateMachine`.
- Lógica dependiente de eventos de apertura de puerta.
- Scraping o automatización no autorizada contra GrinPass.
- Empezar módulos por la UI (el orden es backend-first, PRD §26).
- Queries sin scope de tenant (ver `security.md`).
