---
phases: [tasks, run]
---

# Testing — AutoHostAI (PRD §4, §28)

## Tipos y cuándo

- **Unit (pytest + pytest-asyncio)**: domain services y lógica pura — state machine, cálculo de precios, cálculo de estado contextual, validación de checklist.
- **Integration**: repositorios/DB, endpoints FastAPI (httpx AsyncClient), jobs Celery, adapters contra sus mocks.
- **Frontend**: Testing Library para componentes con lógica.
- **E2E (Playwright)**: solo los flujos críticos — login, cleaning flow completo, incident flow.

## Obligatorios por el PRD

- **Cobertura ≥ 80 % en domain services** (PRD §4).
- **Todas las transiciones de la state machine testeadas** (DoD §28.19), incluidas las inválidas (deben rechazarse).
- **Tests de tenant isolation en cada módulo** (DoD §28.18): usuario del tenant A no ve datos del tenant B.
- La fórmula de pricing con sus guardrails (min/max/max_daily_change) testeada con casos límite.

## Convenciones

- Tests junto al dominio que cubren (`backend/tests/<dominio>/`), fixtures compartidas en `conftest.py` (tenant, users por rol, properties seed).
- Mockear solo en la frontera de adapters — nunca mockear repositorios ni la state machine en tests de dominio.
- Cada tarea de implementación incluye su test (regla del flujo SDD); la sección Verification corre la suite completa.
- **TDD (test primero) en `domain/` con invariante real** — state machine, guardrails de pricing, checklist de limpieza (ver `backend-architecture.md` § "Cuándo simplificar"): escribe el test que exige la regla antes de implementarla, es barato porque `domain/` es Python puro sin infra que montar. No forzar TDD en `infrastructure/` (integration tests, más caro escribir-primero) ni en UI exploratoria de frontend.
