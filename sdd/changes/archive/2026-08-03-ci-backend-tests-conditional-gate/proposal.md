# Proposal: ci-backend-tests-conditional-gate

## Why

`backend-tests` tarda **~7 minutos** en cada Pull Request y otra vez en cada push a `main`,
y **el 89 % de ese tiempo es un solo paso**: `pytest -q -rs` consume 6m15s de los 7m05s
totales (medido el 2026-08-03 sobre el run de `sdd/frontend-api-contract-consumer`; el resto
—containers, checkout, `uv`, migraciones, `alembic check`, `downgrade base`— suma 49s).
Marta lo reporta como fricción real en su ciclo de trabajo.

Lo que hace ese coste injustificado no es su tamaño, sino **cuándo se paga**: de los
**últimos 20 commits en `main`, ninguno toca `backend/**`** — son SDD, documentación y
frontend. Hoy pagamos 7 minutos × 2 en prácticamente todos los merges recientes para
ejecutar 2 357 tests sobre un árbol de backend que no ha cambiado una línea.

Un detalle agrava la desalineación: tanto el workflow (`backend-tests.yml:16`) como su spec
afirman *"la suite tarda ~1 minuto; no merece el riesgo"*. Esa cifra **ya no es cierta** —
es 6 veces mayor—, así que la decisión de no filtrar se tomó sobre un dato que hoy no se
sostiene y que nadie ha vuelto a medir.

## What changes

`backend-tests` deja de ejecutar la suite en los Pull Request que no tocan el backend, **sin
dejar de reportar el check en ninguno**. Hoy esas dos propiedades parecen incompatibles, y
por eso `specs/backend-ci.md` prohíbe el filtro de rutas; este change las separa. La
prohibición apunta a un mecanismo concreto —`paths:` en el disparador `on:`, que hace que el
workflow *no arranque* y deje un check requerido esperando para siempre— y ese mecanismo
sigue prohibido aquí. Lo que se sustituye es la regla por el invariante que en realidad
protegía: **el check `backend-tests` termina con una conclusión en todo Pull Request**,
toque o no `backend/**`. La decisión de área pasa de vivir en el disparador a vivir dentro
de la ejecución, que es donde puede ser condicional sin dejar de reportar.

La topología concreta (un job barato que decide, el job pesado condicionado, un job final
que consolida y da nombre al check) es materia de `/sdd:design`, no de esta propuesta.

**Verificado antes de proponerlo — no se pierde superficie de calidad.** La suite es
hermética a `backend/`: ningún test lee un fichero fuera de ese directorio. Los tres sitios
que mencionan rutas externas son aserciones sobre constantes escritas en el propio test, no
lecturas —`tests/test_error_envelope.py:3` (forma que espera `frontend/lib/api/errors.ts`),
`tests/auth/test_user_admin_api.py:560` y `tests/tenants/test_value_objects.py:103`
(locales `es`/`en`)—, y `tests/auth/test_bootstrap.py:237` documenta explícitamente que el
contenedor solo monta `backend/`, así que el `.env.example` de la raíz **es inalcanzable**
para la suite. Consecuencia: un cambio de solo-frontend ya hoy deja esos tests en verde
pase lo que pase; no detectan esa deriva ahora y saltarlos no deja de detectar nada. La
señal eliminada es exactamente cero.

## Requirements

### R1 — El check reporta siempre, toque el diff el backend o no

**As a** persona que abre un Pull Request, **I want** que `backend-tests` llegue siempre a
una conclusión, **so that** el PR nunca quede bloqueado esperando un check que no va a
llegar, ni hoy ni cuando el repositorio pueda exigirlo como obligatorio.

Acceptance criteria:

1. WHEN se abre o actualiza un Pull Request, o se hace push a `main`, THE SYSTEM SHALL
   reportar una conclusión para el check `backend-tests`, con independencia de qué rutas
   toque el diff.
2. THE SYSTEM SHALL NOT declarar filtros `paths` ni `paths-ignore` en el disparador `on:`
   del workflow.
3. IF la suite no se ejecuta porque el diff no toca el área del backend, THEN el check
   `backend-tests` SHALL terminar en `success`.
4. IF la suite se ejecuta y falla, THEN el check `backend-tests` SHALL terminar en `failure`
   — un camino corto no puede enmascarar un fallo real.

### R2 — Detección del área a partir del diff

**As a** responsable del pipeline, **I want** que "toca el backend" sea una decisión
explícita y auditable, **so that** el criterio no dependa del evento que disparó la
ejecución ni quede implícito.

Acceptance criteria:

1. WHEN arranca la ejecución, THE SYSTEM SHALL determinar si el diff toca `backend/**` o
   `.github/workflows/backend-tests.yml`, y SHALL dejar esa decisión visible en el log.
2. WHERE el evento es `pull_request`, THE SYSTEM SHALL comparar contra la base del Pull
   Request; WHERE es push a `main`, contra el estado anterior de la rama.
3. WHEN el workflow se dispara por `workflow_dispatch`, THE SYSTEM SHALL ejecutar la suite
   completa sin condicionarla al diff — la ejecución manual es la vía de escape cuando se
   quiere la señal completa.
4. IF no se puede determinar el conjunto de ficheros cambiados, THEN THE SYSTEM SHALL
   ejecutar la suite completa. La duda se resuelve verificando, nunca saltando.

### R3 — El camino largo conserva íntegra la verificación de hoy

**As a** revisor, **I want** que un Pull Request que toca el backend se verifique
exactamente como se verifica hoy, **so that** este change acelere el pipeline sin rebajar
el gate.

Acceptance criteria:

1. WHERE el diff toca el área del backend, THE SYSTEM SHALL levantar PostgreSQL 16 y Redis 7
   con healthcheck y ejecutar, sin alteración, los pasos hoy especificados en
   `specs/backend-ci.md`: `alembic upgrade head`, `alembic check`, `pytest -q -rs` y
   `alembic downgrade base`.
2. THE SYSTEM SHALL conservar la clave JWT de usar y tirar, `uv sync --frozen`, el pineado
   de actions por SHA, `contents: read`, el grupo de concurrencia con `cancel-in-progress`
   y el límite de 20 minutos.
3. WHERE el diff no toca el área del backend, THE SYSTEM SHALL NOT instalar dependencias
   del backend ni ejecutar migraciones ni la suite.

### R4 — El camino corto es rápido de verdad

**As a** persona esperando el merge de un Pull Request de documentación, **I want** que el
check tarde segundos, **so that** el ahorro sea perceptible y comprobable, no teórico.

Acceptance criteria:

1. WHEN el diff no toca el área del backend, THE SYSTEM SHALL completar el workflow en menos
   de 60 segundos.
2. THE SYSTEM SHALL dejar constancia en el resumen de la ejecución de que la suite se omitió
   y por qué, de modo que un check verde en 20 segundos no se confunda con una suite que
   pasó.

### R5 — La documentación del gate deja de mentir sobre su coste

**As a** persona que decide sobre el pipeline, **I want** que el coste declarado del
workflow sea el medido, **so that** la próxima decisión no se tome sobre una cifra obsoleta
como ha pasado con esta.

Acceptance criteria:

1. THE SYSTEM SHALL sustituir la afirmación *"la suite tarda ~1 minuto"* del comentario de
   cabecera de `backend-tests.yml` por la duración medida, fechada y con el desglose del
   paso dominante.
2. THE SYSTEM SHALL registrar en `specs/backend-ci.md` el invariante de R1 en lugar del
   requisito *"sin filtro de rutas"*, conservando la razón original (por qué `paths:` en el
   disparador sigue prohibido) para que la restricción no se pierda al reescribir la regla.

## Out of scope

- **Reducir los 6m15s de `pytest`.** Es la palanca mayor —y la única que ayuda en los Pull
  Request que **sí** tocan backend, que son los de Marta cuando trabaja en backend—, pero es
  un refactor de fixtures de riesgo distinto: el sospechoso dominante es la fixture
  `test_engine` de `backend/tests/conftest.py:62-84`, *function-scoped*, que hace
  `create_all` + `drop_all` del esquema completo en cada test, con **201 funciones de test**
  que la piden. Su docstring documenta que el diseño actual evita fallos de *"attached to a
  different loop"*, así que tocarla exige su propio design. Va como entrada nueva de
  roadmap, inmediatamente después de esta.
- **`frontend-tests` y `api-contract`.** El mismo patrón les aplica y sus specs tienen la
  misma regla, pero tardan ~1m30–2m15 y <1m: no es donde duele. Se decide aparte una vez
  este patrón esté probado.
- **Marcar `backend-tests` como check obligatorio y la protección de rama.** Hoy es
  imposible (la API responde `403: Upgrade to GitHub Pro or make this repository public`,
  limitación ya registrada en `specs/backend-ci.md`), y configurarlo a mano en la consola
  violaría la norma IaC-first de `steering/infra.md`. Pertenece a la entrada de roadmap
  `infra-github-iac`. Este change se limita a **dejarlo posible**: cumplido R1, marcarlo
  como obligatorio deja de poder bloquear un PR.
- **`pytest-xdist` y cualquier paralelización de la suite.** Hoy no es dependencia del
  proyecto; entra en la valoración de la entrada de optimización, no aquí.

## Affected specs

- `sdd/specs/backend-ci.md` — se amenda: el requisito *"sin filtro de rutas"* (línea 23) se
  sustituye por el invariante de R1, se añaden la detección de área y el camino corto, y se
  corrige la duración declarada del gate.
