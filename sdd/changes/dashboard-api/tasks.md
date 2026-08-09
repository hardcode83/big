# Tasks: dashboard-api

Orden pensado para que el sistema siga en pie tras cada sección: primero el mecanismo
compartido, luego un endpoint completo y verificable (timeline), luego los lectores que el
agregado necesita, y el agregado al final. Nada aquí crea tablas ni escrituras.

**Antes de la primera tarea**: `make up` en este worktree (levanta su propio stack, con base
vacía y reinstalación de dependencias la primera vez — `sdd/project.md` § Worktree bootstrap)
y `git branch --show-current` debe decir `sdd/dashboard-api`.

## 1. Mecanismo compartido de idioma <!-- panel: PASS 2026-08-09 -->

- [x] 1.1 `Locale` y `Catalog` en `backend/app/core/i18n.py`: enum `es`/`en` y resolución
      clave+locale→plantilla con formateo desde un `dict`. Sólo el mecanismo, cero mensajes
      (design D4). Test: resolución en ambos idiomas, clave ausente, y **valor desconocido de
      `preferred_language` degradando a `es`** — la columna es `String(5)` sin restricción
      (`backend/tests/test_i18n.py`). [R5]
- [x] 1.2 `preferred_language` en `RequestContext`
      (`backend/app/auth/domain/context.py`) y su relleno en
      `backend/app/auth/api/dependencies.py:239`, desde el usuario que `:223` ya reléé — cero
      consultas nuevas (design D3). Test: el contexto de una petición autenticada transporta
      el idioma del usuario, y `__post_init__` sigue validando lo que ya validaba
      (`backend/tests/auth/`). [R5]

## 2. Lectura del timeline (`GET /api/v1/timeline/{property_id}`) <!-- panel: PASS 2026-08-09 -->

- [x] 2.1 Catálogo y renderer en `backend/app/timeline/domain/rendering.py`: plantillas para
      los **45 valores de `TimelineEventType`** × `es`/`en`, y
      `render(event, locale) -> RenderedEntry` que compone desde `event_type` + `metadata` y
      **degrada al `title` almacenado** si el tipo no está en el catálogo. Python puro, sin
      pydantic ni sqlalchemy (lo verifica `tests/test_layering.py`). TDD: es `domain/` con
      regla real. Test: un caso por tipo, ambos idiomas, el camino de degradación, y un test
      que recorre el enum y **falla si un valor no tiene entrada** (`backend/tests/timeline/`).
      [R5]
- [x] 2.2 Puerto de lectura `TimelineEventReader` en
      `backend/app/timeline/domain/repositories.py` — `Protocol` **separado** de
      `TimelineEventRepository`, que sigue teniendo sólo `add` (design D2, Interface
      Segregation). Métodos: `list_for_property(...)` y `last_for_properties(...)`. Más
      `TimelineFilters` como value object (`eventType`, `severity`, `actorType`, `from`, `to`).
      [R4]
- [x] 2.3 Adaptador en `backend/app/timeline/infrastructure/repositories.py`:
      `ORDER BY created_at DESC, id DESC`, filtros AND-combinados, `LIMIT/OFFSET` y `total`
      del mismo conjunto filtrado (design D8). Integration test contra Postgres: orden,
      **paginación que ni repite ni omite con timestamps idénticos**, cada filtro por separado
      y combinados, y **aislamiento de tenant** (DoD §28.18). [R4]
- [x] 2.4 Capa `api/` nueva en `backend/app/timeline/`: `router.py`, `schemas.py`,
      `dependencies.py`. Ruta con `require(...)`, envelope de paginación de PRD §23, entradas
      con exactamente los campos de `TimelineEntry` y **sin serializar `metadata`**; `404`
      indistinguible para id inexistente y de otro tenant. Montar `timeline_router` en
      `backend/app/main.py`. Test de endpoint (httpx AsyncClient): forma de respuesta, filtros,
      404 en ambos casos, y que `metadata` no aparece. [R4, R5]

## 3. Estado operacional (`GET /api/v1/properties/{id}/state`) <!-- panel: PASS 2026-08-09 -->

- [x] 3.1 `last_for_property` en `PropertyStateTransitionRepository`
      (`backend/app/properties/domain/repositories.py`) y su adaptador — la lectura que hoy
      no existe junto al `add` que sí. Integration test con aislamiento de tenant. [R3]
- [x] 3.2 Ruta en `backend/app/properties/api/router.py` (el módulo que posee la columna,
      design D7) con `require(Permission.READ_PROPERTIES)`: devuelve el estado canónico y el
      instante ISO-8601 UTC de la última transición, **leídos**, sin recalcular nada — lo
      prohíbe `steering/backend.md`. Test: forma, 404 indistinguible, y que la respuesta
      coincide con lo que dejó una transición real. [R3]

## 4. Lectores por lotes de los dominios que el agregado compone <!-- panel: PASS 2026-08-09 -->

Cada uno en **su** dominio, con la firma que `ReservationRepository.list_for_properties` ya
estableció (design D2). Ninguno añade escritura.

- [x] 4.1 `list_live_for_properties(tenant_id, property_ids)` en
      `backend/app/cleaning/domain/repositories.py` + adaptador. **Ojo al merge**:
      `cleaning-photos-storage` toca este mismo fichero en paralelo con métodos distintos.
      Integration test con aislamiento de tenant. [R1, R2]
- [x] 4.2 Primer puerto de `maintenance`:
      `backend/app/maintenance/domain/repositories.py` con `count_open_for_properties` y
      `list_open_for_property`, y su adaptador en `infrastructure/repositories.py`. **Sólo
      lectura** — sin `add`, sin `save`; la escritura llega con el change `maintenance` y la
      firma es donde eso queda dicho. Integration test: cuenta correcta con la tabla vacía
      (el caso de hoy) y con filas sembradas, más aislamiento de tenant. [R2]
- [x] 4.3 Primer puerto de `statements`: `summary_for_property` en
      `backend/app/statements/domain/repositories.py` + adaptador, sólo lectura. Test
      equivalente: vacío hoy, poblado cuando se siembra. [R2]
- [x] 4.4 Implementar `last_for_properties` del `TimelineEventReader` (puerto declarado en
      2.2) en el adaptador de timeline: el último evento de cada propiedad en **una** consulta.
      Integration test que verifica que es una sola sentencia para N propiedades. [R1]

## 5. Dominio del módulo `dashboard` <!-- panel: PASS 2026-08-09 -->

- [x] 5.1 Proyecciones `frozen` en `backend/app/dashboard/domain/read_models.py`
      (`PropertyDashboardCard`, `PropertyDetail` y sus bloques), siguiendo el patrón de
      `GuestSummary`: **el huésped se proyecta sin documento y el acceso sin código**, de modo
      que ningún serializador futuro alcance un campo que no está (regla 4 de
      `steering/security.md`). Test: los campos prohibidos no existen en el tipo. [R2]
- [x] 5.2 Tabla de próxima acción en `backend/app/dashboard/domain/next_action.py`, pura y
      **exhaustiva sobre los once `PropertyOperationalState`** (tabla acordada en design D6;
      responsable como rol, no persona). Marcar `ASSUMPTION`: el PRD no la define. TDD. Test:
      un caso por estado y uno que **falla si el enum crece** sin actualizarla. [R1]
- [x] 5.3 Catálogo de etiquetas en `backend/app/dashboard/domain/labels.py` (estado de
      limpieza, acciones de 5.2, títulos de incidencia y aprobación) en `es`/`en`, sobre el
      `Catalog` de 1.1. Test: cobertura de claves en ambos idiomas. [R5]

## 6. Endpoints del dashboard <!-- panel: PASS 2026-08-09 -->

- [x] 6.1 `GetDashboardCardsUseCase` en
      `backend/app/dashboard/application/use_cases.py`: compone con los lectores por lotes de
      la sección 4 y agrupa en memoria. Unit test con **fakes en memoria** de los puertos (no
      la DB, `steering/testing.md`): forma de la card, `currentOrNextReservation: null`
      presente y no omitido, y la omisión de bloque por permiso de origen — `is_allowed(role,
      READ_RESERVATIONS)` y `READ_CLEANING_TASKS` (design D10). [R1]
- [x] 6.2 `GetPropertyDashboardUseCase` en el mismo fichero: el agregado de PRD §9.2.
      Los bloques sin escritor (`incidents`, `owner_approvals`, `expenses`) **consultan su
      tabla real** y devuelven vacío/`null`; `lastCleaningPhotos` devuelve `[]` marcado
      `EXTERNAL_DEPENDENCY` y **no** se toca el puerto de fotos (design D9). Unit test con
      fakes: bloques vacíos hoy, poblados cuando el fake tiene filas, omisión por permiso
      incluyendo `READ_ACCESS_RECORDS`. [R2]
- [x] 6.3 `backend/app/dashboard/api/{router,schemas,dependencies}.py` con las dos rutas:
      `GET /api/v1/dashboard/properties` (colección paginada) y
      `GET /api/v1/properties/{id}/dashboard` (agregado). Ambas con `require(...)`, envelope
      de PRD §23, límites `page`/`per_page` iguales a los de `GET /api/v1/properties`
      (`MAX_PAGE=100_000`, `MAX_PER_PAGE=100`) y `422` en el envelope de error ante parámetros
      inválidos. Montar `dashboard_router` en `backend/app/main.py`. Test de endpoint: forma,
      paginación, 404 indistinguible, y que `tests/test_route_authorization.py` recorre las
      dos rutas nuevas. [R1, R2]
- [x] 6.4 Test de **no-N+1** en `backend/tests/dashboard/`: un listener de SQLAlchemy cuenta
      las sentencias de `GET /api/v1/dashboard/properties` y **fija un techo constante**,
      verificado con 2 y con 10 propiedades — el mismo número. Es un aserto, no una métrica:
      el bucle que lo rompe es sintácticamente idéntico al código correcto (design, Risks).
      [R1]
- [x] 6.5 Test de aislamiento de tenant del módulo `dashboard` (DoD §28.18): un usuario del
      tenant A no ve ninguna propiedad, reserva, limpieza ni entrada de timeline del tenant B
      por ninguna de las cuatro rutas. [R1, R2, R3, R4]

## 7. Contrato y referencias <!-- panel: PASS 2026-08-09 -->

- [x] 7.1 Regenerar `backend/openapi.json` con `make openapi` y commitearlo — lo exige
      `.github/workflows/api-contract.yml:85`. Anotar `summary`/`description` y modelos de
      respuesta en las cuatro rutas para que el contrato se lea solo. [R6]
- [x] 7.2 Regenerar `frontend/lib/api/generated/openapi.d.ts` con
      `cd frontend && npm run api:generate` y commitearlo — la otra mitad del puente, que
      comprueba `.github/workflows/frontend-api-contract.yml:41`. Es el único fichero de
      `frontend/` que este change toca, y es generado. [R6]
- [x] 7.3 Corregir las tres referencias que el split del 2026-08-08 dejó atribuyendo esta
      mitad backend a `dashboard-web`: `backend/app/properties/api/router.py:10`,
      `docs/properties.md:109` y el bloque «Estado: solo lectura sobre datos mock» de
      `docs/dashboard.md:5-10`, que **deja de ser cierto** — no basta con cambiar el nombre.
      [R6]
- [x] 7.4 Verificar por `grep` que **no** se han tocado las menciones a `dashboard-web` que
      se refieren al frontend y siguen siendo correctas: `docs/properties.md:107`,
      `docs/reservations.md:145`, `docs/dashboard.md:68`, `sdd/specs/user-management.md:16,255`
      y `sdd/specs/reservations.md:16,286`. [R6]
- [x] 7.5 Actualizar `docs/dashboard.md` como página de capability (`steering/documentation.md`):
      cómo se usa/opera la API agregada, enlazando a las specs en vez de duplicarlas. Sin
      `.env.example` que tocar (no hay variables nuevas) ni strings de UI (no hay frontend).
      [R6]

## 8. Verification

- [x] 8.1 Suite completa del backend desde este worktree:
      `docker compose exec backend uv run pytest` (con el stack arriba) o
      `docker compose run --rm backend uv run pytest` (con el stack parado). [R1-R6]
- [x] 8.2 Sin deriva de contrato en ninguna de las dos mitades:
      `docker compose exec backend uv run python -m app.cli.openapi --check` y
      `cd frontend && npm run api:check`. [R6]
- [x] 8.3 Los tests transversales que este change puede romper pasan en verde:
      `tests/test_layering.py` (pureza de `domain/`), `tests/test_route_authorization.py`
      (permiso declarado en las cuatro rutas), `tests/test_openapi_contract.py` y
      `tests/test_tenant_filter.py`. [R1-R5]
- [x] 8.4 Comprobación manual del flujo, **desde dentro del stack** — este worktree no publica
      puertos, así que no hay navegador ni `localhost:8000` (`sdd/project.md`): `make bootstrap`
      para sembrar, y `docker compose exec backend python -c "..."` (o `curl` desde el
      contenedor) contra las cuatro rutas con un token de `TENANT_OWNER`, comprobando que el
      timeline llega en `es` y en `en` según `preferred_language`. [R1-R5]

**Sin lint ni typecheck que correr**: `pyproject.toml` del backend declara sólo pytest y la CI
no ejecuta mypy ni ruff (consta en `backend/app/core/db.py:142-143`). No se inventa un comando
para rellenar el hueco.
