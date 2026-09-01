# BLOCKED — revenue-statements

## Activo

### 2026-09-01 — /sdd:review veredicto FAIL (7 hallazgos)

- **Tipo**: `decision` (bloquea `READY_FOR_PR`; requiere corregir código, steering, docs
  y i18n antes de re-certificar).
- **Fase**: review. Panel completo (architect · security · qa · cicd · documentation ·
  i18n · tenancy). Rango revisado `0ef4c45..HEAD` (`02bc4b7`). CICD y tenancy PASS; los
  otros cinco FAIL. **Los `<!-- panel: PASS -->` de §§6–7 quedaron invalidados para HEAD**:
  eran ciertos de un estado anterior de `schemas.py` (`04f528d`), no del actual.

- **H1 — CRÍTICO (qa) · la app no arranca — [RESUELTO 2026-09-01, tick autónomo]**:
  `backend/app/statements/api/schemas.py:331` declaraba `date: date | None = None`; el nombre
  de campo `date` ensombrecía el símbolo importado `datetime.date` en el resolver de anotaciones
  de Pydantic (el propio comentario 326–330 lo advierte y exige `Optional[date]`, pero `Optional`
  no estaba importado, línea 31). `create_app()` lanzaba `TypeError` en import; el contenedor
  `backend` estaba en crash-loop. **32+ tests fallaban en colección**. Entró con la modernización
  automática `Optional→| None` de `424bce9`. **Falsificaba §11.1/§11.2 para HEAD.**
  **Fix aplicado**: revert al estado bueno conocido (`04f528d`, §6 PASS) — `from typing import
  Annotated, Any, Optional` + `date: Optional[date] = None`. Verificado: `create_app()` arranca.
- **H1b — CRÍTICO (encontrado al verificar H1) · `test_api.py` nunca ejecutó — [RESUELTO
  2026-09-01, tick autónomo]**: tras arreglar H1, los 29 tests de `tests/statements/test_api.py`
  seguían en error de colección por una causa distinta que el crash de arranque tapaba: su
  fixture `world` depende de `tenant_a`/`tenant_b`/`users_by_role_a`/`users_by_role_b`, definidos
  en `tests/auth/conftest.py`, pero **`conftest.py` es de ámbito de directorio** y `tests/statements/`
  no los ve. El comentario del propio `test_api.py` (líneas 51–53) declaraba la intención de
  reutilizarlos, pero **faltaba el import**. **Fix aplicado**: añadido `from tests.auth.conftest
  import (tenant_a, tenant_b, users_by_role_a, users_by_role_b)  # noqa: F401`, igual que hacen
  `tests/dashboard/conftest.py` y los demás módulos de integración. Verificado: **29 passed**.
- **Estado de tests tras H1+H1b (verificado, tick autónomo)**: `tests/statements tests/audit
  tests/auth/test_policy.py tests/scheduler tests/test_openapi_contract.py
  tests/test_route_authorization.py tests/timeline/test_rendering.py` → **685 passed, 0 fallos**.
  §11.1 vuelve a ser cierto para el scope afectado (falta la suite completa, la re-corre `/sdd:run`).
  `test_openapi_contract.py` verde ⇒ `openapi.json` es coherente con las rutas (mitiga la parte
  estructural de la duda de artefactos; H2 sigue siendo un desajuste de texto de status aparte).
- **H2 — ALTO (architect) · contrato ≠ runtime**: `backend/app/statements/api/errors.py:61`
  mapea `NamedExpenseInClosedPeriodError` a `409 CONFLICT`, pero D6.3 y el docstring del router
  `POST /expenses` (router.py:439–441, horneado en `openapi.json`) publican **422**. Un cliente
  codificado contra el contrato OpenAPI maneja mal la respuesta. Fix: fila `(…, 422,
  ErrorCode.VALIDATION_ERROR)` + corregir el comentario 57–59. (D9 tiene una inconsistencia
  interna POST=422 / PATCH=409 para "período cerrado"; D6.3 manda: 422.)
- **H3 — MEDIO (security) · fila de censo que miente — [RESUELTO 2026-09-01, tick autónomo]**:
  `sdd/steering/security.md:186-187` afirmaba que `owner_statements.notes`/`expenses.description`
  estaban **"fuera de `AUDITABLE_FIELDS`"**. Falso: ambos están DENTRO (`value_objects.py:462,480`)
  y la redacción `{"changed": true}` la impone `REDACT_ONLY_FIELDS` (`:531-532`), como el precedente
  JSONB de `pricing_rules`. La regla 11 declara que una fila que miente es peor que una sin censar.
  El mismo error estaba en el docstring `use_cases.py:252-253`. **Fix aplicado**: reescritas ambas
  filas del censo al mecanismo real (EN `AUDITABLE_FIELDS` **y** `REDACT_ONLY_FIELDS`, `diff()` lanza,
  sólo `redacted()` emite `{"changed": true}`) + corregido el docstring. Verificado: la guardia
  `test_rule11_ownership.py` acepta la nueva redacción (parsing del censo verde).
- **H4 — MEDIO (security) · excepción mal clasificada**: el carve-out "el job mensual no escribe
  `AuditLog`" es una excepción de **regla 9** (D12: "sexta excepción de regla 9"), pero se añadió
  como **"Excepción 7" de la lista de regla 11** (sumideros de texto) y se subió el contador
  seis→siete (`security.md:200-205`), aunque no se añadió ninguna forma de sumidero nueva (las dos
  columnas usan la excepción 3 existente). Fix: moverla a la enumeración de regla 9 (tras la
  "Quinta excepción", `security.md:81`) como sexta; revertir el contador de regla 11 a "seis".
- **H5 — MEDIO (i18n) · catálogo muerto que diverge del canon**: `backend/app/statements/domain/messages.py`
  (`STATEMENTS_ERROR_MESSAGES`) sólo se usa en `tests/statements/test_messages.py`; el handler
  `errors.py:86` renderiza `str(exc)` (inglés). Los 13 módulos backend (incl. el canónico
  `pricing`, que **no** tiene catálogo) traducen por `ErrorCode` + frontend (react-i18next), que
  es lo que R7.7 pide de verdad. Fix: **eliminar** el catálogo muerto y `test_messages.py` para
  igualar el canon (no cablearlo).
- **H6 — BAJO (documentation) · README — [RESUELTO 2026-09-01, tick autónomo]**: la viñeta del
  módulo `statements` estaba bajo "## Despliegue a dev (CD)" en vez de en "## Estructura".
  **Fix aplicado**: movida a la sección "## Estructura" (tras la viñeta `sdd/`), describiendo las
  cuatro capas y que `revenue-statements` le dio `application/`/`api/`, con el enlace a
  `docs/revenue-statements.md` preservado.
- **H7 — BAJO (qa) · cobertura de frontera — [RESUELTO 2026-09-01, tick autónomo]**: R5.7 usa
  `amount > threshold` **estricto**; `test_use_cases.py` sólo probaba 50/150 contra umbral 100.
  **Fix aplicado**: añadido `TestCreateExpense::test_amount_equal_to_threshold_creates_no_approval`
  (amount == 100.00 → sin `OwnerApproval`). Verificado: **1 passed** (el código respeta el `>` estricto).

- **Hallazgo fuera de alcance (encontrado al verificar H3, NO es de revenue-statements)**:
  `tests/test_rule11_ownership.py::test_no_block_outside_the_table_declares_who_writes_a_sink`
  está en **rojo**, pero por `sdd/specs/access-notifications.md:373,526,690` (enum `NotificationType`
  / bloques "sin escritor"), un spec que este change **no toca** e idéntico al merge-base `0ef4c45`
  (⇒ también falla en `main`). No lo causan ni el código de este feature ni los fixes de este tick
  (la guardia sólo señala `access-notifications.md`, ningún fichero mío). Es higiene de censo de otra
  capacidad; se deja para su dueño. **Implica que el `pytest -n 2` completo de §11.1 no está del todo
  verde por una causa preexistente y ajena** — a tener en cuenta al re-verificar.

- **Deriva de design (sólo archivado, sin cambio de código)**: `design.md:290` referencia una
  "D14" inexistente y "dos claves" (hay cinco); D7 (`:151`) describe el mecanismo redact-only al
  revés del que invoca; D12 (`:94`) sigue diciendo "sexta" donde el steering ya renumeró a "séptima".
- **Consecuencia de artefactos**: `backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts`
  (§9) se regeneraron en el commit roto `424bce9`; no se pueden re-verificar hasta que la app
  arranque. Tras H1, re-ejecutar `make openapi` + `npm run api:check`.

- **Comando de reanudación**: resueltos y verificados **H1, H1b, H3, H6, H7** (arriba). Quedan
  abiertos, dejados a criterio humano por arrastrar juicio o borrado:
  - **H4** (steering) — **[RESUELTO 2026-09-01, decisión del usuario]**: la excepción "job mensual
    no escribe `AuditLog`" se movió de la lista de regla 11 ("Excepción 7") a la enumeración de
    **regla 9** como **sexta excepción** (tras la quinta, `security.md`), y el contador de regla 11
    volvió a "seis". Sin cambio de comportamiento del job. Alinea con D12 ("sexta excepción de regla
    9"). Verificado: `test_rule11_ownership.py` sólo señala `access-notifications.md` (preexistente),
    ningún flag nuevo en la security.md editada; `tests/audit` verde. `tasks.md §8.1` anotado con la
    corrección (su redacción original conflaba regla 9 con regla 11). **Re-review de seguridad focalizado:
    la reubicación en el steering es correcta y completa; encontró 1 gap de consistencia — tres comentarios
    de código citaban aún "seventh exception" (`use_cases.py:9,1087`, `timeline/domain/rendering.py:243`).
    Corregidos a "sixth exception" (comment-only, sin cambio de comportamiento); grep confirma 0 refs
    stale; `tests/statements` + `tests/timeline/test_rendering.py` = 255 passed.** H4 cerrado.
  - **H5** (i18n) — **[RESUELTO 2026-09-01, decisión del usuario: eliminar]**: borrados
    `backend/app/statements/domain/messages.py` y `backend/tests/statements/test_messages.py`.
    **Gate de STOP evaluado**: no hay consumidor (sólo el test lo referenciaba) y no hay requirement
    explícito que obligue el catálogo — R7.7 pide "las mismas claves de error que revenue-pricing… el
    frontend reutiliza las tablas por status HTTP", y `pricing` (canónico) no tiene catálogo backend;
    los 13 módulos renderizan `str(exc)` + `ErrorCode`. El `Catalog` de `core.i18n` se usa sólo para
    **contenido** (timeline/dashboard), no para errores. Verificado: `tests/statements` verde sin el
    catálogo. **Re-review i18n focalizado: PASS (0 hallazgos)** — sin refs colgantes, R7.7 sigue
    satisfecho por el patrón canónico `ErrorCode`+frontend, sin ErrorCodes nuevos. H5 cerrado.
  - **H2** (código, `errors.py`) — **[RESUELTO 2026-09-01, decisión del usuario: Opción B — 409
    consistente]**. Racional: el payload puede ser válido; el rechazo lo causa el estado de negocio
    (período ya cerrado), así que es **conflicto de estado (409)**, no validación (422). El mapping
    de runtime **ya era 409** (`errors.py:61`, comentario 57-59 ya lo agrupaba con los 409), así que
    sólo se reconciliaron **wording/artefactos/tests** (sin cambiar el mapping, sin ampliar alcance):
    docstring del router POST `/expenses` 422→409 (`router.py:440`); `openapi.json` regenerado
    (`make openapi`, diff de 1 línea) + tipos frontend regenerados (`api:generate` — además sincronizó
    una deriva preexistente: los endpoints export CSV/PDF tenían `content: never` en el `.d.ts` mientras
    `openapi.json` ya declaraba `text/csv`/`application/pdf`); D6.3, fila POST de D9 y la fila de test-map
    de `design.md` reescritas a 409/CONFLICT (fila PATCH de D9 ya decía 409); comentario del test
    `test_api.py:691` 422→409 (su aserción ya era 409). **Verificado**: `tests/statements/test_api.py`
    + `test_use_cases.py` + `test_openapi_contract.py` + `test_route_authorization.py` = **85 passed**.
    Análisis original entregado al usuario (conservado abajo por trazabilidad):
    - **Exception**: `NamedExpenseInClosedPeriodError` (`domain/exceptions.py:68`), lanzada en
      `use_cases.py:369` (CreateExpense / **POST** `/api/v1/expenses`) y `use_cases.py:542`
      (UpdateExpense / **PATCH** `/api/v1/expenses/{id}`).
    - **Mapping actual** (`errors.py:61`): `(NamedExpenseInClosedPeriodError, 409, ErrorCode.CONFLICT)`.
    - **Mapping propuesto por el reviewer**: `(…, 422, ErrorCode.VALIDATION_ERROR)`.
    - **Inconsistencia de D9**: fila POST dice "`422` validación / period cerrado (D6.3)"; fila PATCH
      dice "`409` period cerrado". D6.3 dice 422/VALIDATION_ERROR. El docstring del router POST
      (`router.py:439-441`, en `openapi.json`) dice 422. **Pero** el código devuelve 409 y el test
      `test_api.py:691 test_create_expense_in_closed_period_returns_409` **asierta 409** — con un
      comentario interno que dice "is a `422`". Una sola entrada de `_MAPPING` no puede dar 422 en
      POST y 409 en PATCH a la vez.
    - **Dos resoluciones, ninguna trivial** (por eso el HOLD): (A) 422 en ambas vías → cambiar
      `errors.py`, renombrar/ajustar el test a 422, y actualizar la fila PATCH de D9 a 422; (B) 409
      en ambas → corregir el docstring POST del router + regenerar `openapi.json`, y corregir D6.3 y
      la fila POST de D9 a 409. Semántica: 409 lo trata como conflicto de estado (como
      `ExpenseAlreadyConsolidatedError`); 422 lo trata como validación del `date` de entrada.
  - Deriva de design (sólo archivado): "D14" inexistente, D7 invertido; **D12 "sexta/séptima" ya no
    aplica** — tras H4 el steering tiene la excepción como sexta de regla 9, que es justo lo que D12 decía.
  Tras corregirlas: re-verificar la suite y regenerar §9 si algo cambió (`/sdd:run revenue-statements 11`),
  y volver a certificar con `/sdd:review revenue-statements`. **No marcar `READY_FOR_PR` hasta PASS.**

### 2026-08-30 — §11.4 CI checks (deferred)

- **Tipo**: `deferred` (el flujo lo reanuda; no requiere decisión humana).
- **Qué y por qué**: §11.4 verifica que los workflows `compose-ports`, `backend-tests`
  y `api-contract` siguen verdes vía `gh pr checks`. No es ejecutable durante `/sdd:run`:
  `gh pr checks` no tiene PR hasta que `/sdd:ship` lo abra (`no pull requests found for
  branch`). Permanece `[ ]` en `tasks.md`, explícitamente **deferred-to-PR_OPEN**.
- **Comando de reanudación**: tras `/sdd:ship`, `gh pr checks` sobre el PR abierto.

## Resuelto

### 2026-09-01 — §11.2 tooling Pyright reproducible (RESUELTO)

El blocker anterior era de **entorno**: `uv run ruff`/`uv run pyright` no arrancaban
porque las herramientas no estaban declaradas y la imagen carecía del runtime Node
(`libatomic.so.1`). El change cross-cutting `backend-pyright-tooling` (mergeado en
`main`, `e690ccb` / archivo `2026-09-01-backend-pyright-tooling`) aporta el mecanismo
canónico. Tras sincronizar `origin/main` en la rama (merge, sin rebase/force/reset) y
reconstruir la imagen `dev` del worktree:

- **Pyright arranca y ejecuta el análisis**: `uv sync --frozen` instala `pyright 1.1.411`
  + `nodejs-wheel 24.19.0` (`node` en `/app/.venv/bin/node`); preflight
  `uv run pyright --version` → `1.1.411`; comando canónico `uv run pyright .` (workdir
  `/app` == `backend`) termina con **exit 1 = findings** (arranque normal, no fallo de
  tooling). Distinción arranque-vs-findings de `sdd/specs/backend-tooling.md` satisfecha.
- **Criterio de la capacidad**: la spec `backend-tooling` declara que Pyright **no es un
  gate de cero findings**, que los findings de tipos son baseline fuera de alcance y que
  su corrección es un cambio aparte. §11.2 se cumple porque el tooling es reproducible y
  llega a ejecutar el análisis. **No se añadieron suppressions ni se relajó configuración**
  para forzar verde.
- **`ruff`**: no es herramienta declarada del proyecto (ausente de `backend/pyproject.toml`,
  `backend/uv.lock` y sin `[tool.ruff]`/`ruff.toml`). El único estático canónico es Pyright.
  Baseline previo medido vía `uvx` (registro anterior): **0 findings en el diff del feature**.

#### Evidencia Pyright (medida, no recordada)

- **Baseline / global actual**: `685 errors, 0 warnings, 0 informations` en todo el backend.
- **Preexistentes en origin/main** (baseline real, NO introducidos por este feature): de los
  685, atribuibles a este feature por path/línea son **19**; los **666** restantes son
  preexistentes en el árbol (no introducidos por revenue-statements). Dentro de paths de
  `statements`, sólo **2** findings son preexistentes: `app/statements/infrastructure/models.py:84`
  ×2 (`reportGeneralTypeIssues`/`reportInvalidTypeForm`), introducidos por `95016d5`
  (domain-foundation-financial, 2026-07-31), no por este change.
- **Introducidos por revenue-statements** (paths/líneas de commits `f98366a`/`424bce9`) —
  clasificados como **type findings no-gating / deuda de tipado candidata a follow-up**,
  NO como baseline (aunque algunas categorías ya existan en el baseline, la línea la
  introduce este feature). Total **19**:
  - `app/statements/application/reconciliation.py:223` — `fetch_period_for` no declarado en el Protocol `ReconciliationStore` (impl concreta lo tiene; tests verdes). 1
  - `app/statements/infrastructure/reconciliation.py:100,110` — `Result[Any].rowcount` (gap de SQLAlchemy; misma categoría aparece 30× en el baseline global). 2
  - `app/statements/infrastructure/repositories.py:413,467` — `Result[Any].rowcount`. 2
  - `app/statements/infrastructure/csv_export.py:44` — `.isoformat()` sobre `object` (protocol `_ExpenseRow` con `date: object`). 1
  - `tests/statements/test_csv.py:23,40,80` — `list[Expense]` vs `Iterable[_ExpenseRow]` (invarianza del protocol laxo). 3
  - `tests/statements/test_entities.py:165` — `object` a `update_notes(notes: str)` (test negativo deliberado del rechazo). 1
  - `tests/statements/test_generation.py:39` — `'DIRECT'` literal vs `ReservationChannel`. 1
  - `tests/statements/test_repositories.py:238,302,303,325,326,327,328` — `reportOptionalMemberAccess` sobre resultado de `.get()` (patrón de test omnipresente en el baseline). 7
  - `tests/statements/test_use_cases.py:755` — `None` vs return `ReservationModel` (doble de test). 1
- **No se corrigen ahora** (fuera del alcance de §11 verificación; no se reabren §§1–10).
  Candidato a change de tipado aparte, coherente con la spec `backend-tooling`
  ("su corrección es un cambio aparte").

#### Evidencia §11.1 (conservada)

- Suite backend completa: **9225 passed, 41 skipped**. Sin roturas de test ni de runtime;
  los findings de Pyright son de análisis estático, no fallos de ejecución.
