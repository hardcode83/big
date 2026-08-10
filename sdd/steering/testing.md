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
- **El esquema se construye una vez por ejecución, no por test** (change `backend-suite-runtime`). Una fixture de sesión crea la base de datos desechable desde cero y hace `create_all`; el aislamiento entre tests es **vaciado de filas** —una sola sentencia derivada de `Base.metadata.sorted_tables`— y no `create_all`/`drop_all`. Medido: crear y tirar el esquema costaba entre 13 y 20 veces lo que vaciar las filas, y era el 77,6 % del tiempo de la suite. Consecuencias al escribir tests: una tabla nueva entra sola en el vaciado por venir de la metadata, así que no hay lista que mantener; pero **un test que deje una transacción abierta bloquea el vaciado del siguiente**, que es por lo que la conexión que vacía lleva `lock_timeout` y falla en vez de colgarse.
- **Un test no puede depender del orden ni del proceso que le toque.** La suite corre en paralelo en CI (`pytest -n 4`), con una base de datos desechable y una base lógica de Redis **por worker**. En la práctica: nada de valores aleatorios dentro de `@pytest.mark.parametrize` ni de iterar `set`/`frozenset` para generar casos —el id del test cambiaría entre workers y la recolección aborta antes de ejecutar nada—, y nada de dar por hecho que un test ve lo que dejó otro. En local la suite sigue siendo en serie por defecto; `-n auto` es opcional.
- Mockear solo en la frontera de adapters — nunca mockear repositorios ni la state machine en tests de dominio.
- Cada tarea de implementación incluye su test (regla del flujo SDD); la sección Verification corre la suite completa.
- **TDD (test primero) en `domain/` con invariante real** — state machine, guardrails de pricing, checklist de limpieza (ver `backend-architecture.md` § "Cuándo simplificar"): escribe el test que exige la regla antes de implementarla, es barato porque `domain/` es Python puro sin infra que montar. No forzar TDD en `infrastructure/` (integration tests, más caro escribir-primero) ni en UI exploratoria de frontend.
