# Tasks: pms-sync-schedule

<!-- Markers, read by /sdd:run and the lifecycle gates. -->

## 1. Config y atribución <!-- panel: PASS 2026-09-11 receipt:73dfe915 -->

- [x] 1.1 `backend/app/core/config.py`: añadir `pms_sync_window_days: int = 2` a `Settings`,
      junto a los demás enteros de dominio (`notification_batch_size`, `beds24_max_pages`).
      `.env.example`: añadir la línea comentada `# PMS_SYNC_WINDOW_DAYS=2` junto a
      `BEDS24_MAX_PAGES`. [R2]
- [x] 1.2 `backend/app/integrations/application/use_cases.py`: añadir
      `SCHEDULED_SOURCE = "pms_scheduled"` junto a `PMS_SOURCE`/`CSV_SOURCE`/`WEBHOOK_SOURCE`,
      con un comentario corto (mismo estilo que el de `WEBHOOK_SOURCE`) explicando por qué es un
      cuarto valor y no una reutilización de `PMS_SOURCE`. Sin cambios en `execute()` — el
      parámetro `source: str` ya existe. [R3]

## 2. Job de beat <!-- panel: PASS 2026-09-11 receipt:654c6088 -->

- [x] 2.1 `backend/app/scheduler/schedule.py`: añadir `"sync_pms_reservations":
      timedelta(hours=6)` a `CADENCES`, con un comentario de docstring como los demás
      (referencia a `pms-sync-schedule`, por qué 6 h — la cadencia que Beds24 recomienda para
      sync completo — y que reemplaza la ausencia que `celery-jobs` D16 documentó). [R1]
- [x] 2.2 `backend/app/scheduler/tasks.py`: añadir `async def _sync_pms_reservations(session,
      tenant_id, now)` que construye `SyncReservationsFromPmsUseCase` con las mismas
      dependencias que `pms_sync.py` (`SqlAlchemyPMSAdapterFactory` +
      `SqlAlchemyPmsCredentialRepository`, `SqlAlchemyReservationRepository`,
      `SqlAlchemyPropertyRepository`, `SqlAlchemyGuestRepository`,
      `SqlAlchemyTimelineEventRepository`, `SqlAlchemyUnitOfWork`,
      `SqlAlchemyAuditLogRepository`, `PostgresGuestEmailExclusion`) y llama a `execute(
      tenant_id=tenant_id, since=now - timedelta(days=settings.pms_sync_window_days), now=now,
      source=SCHEDULED_SOURCE)` — sin `providers` (todos) ni `actor_type` (queda en su default
      `SYSTEM`, D4 del design). Añadir `@celery_app.task(name="sync_pms_reservations") def
      sync_pms_reservations() -> dict: return run_sync(_guarded("sync_pms_reservations",
      CADENCES["sync_pms_reservations"], _sync_pms_reservations))`, mismo patrón que
      `check_checkin_windows` y vecinos. Añadir los imports que falten
      (`SyncReservationsFromPmsUseCase`, `PostgresGuestEmailExclusion`, `SCHEDULED_SOURCE`, si
      no están ya en el módulo). [R1, R2, R3]

## 3. Disparo manual <!-- panel: PASS 2026-09-11 receipt:bc16d5b8 -->

- [x] 3.1 `Makefile`: target `pms-sync:` junto a `sim-advance:`, invocando `$(COMPOSE) exec -T
      backend python -m app.integrations.cli.pms_sync $(TENANT) $(if $(WINDOW),$(WINDOW),) $(if
      $(PROVIDER),--provider $(PROVIDER),)` — mismo patrón de argumentos opcionales que
      `sim-advance`. Añadir `pms-sync` a la lista de `.PHONY`. [R4]

## 4. Tests

- [x] 4.1 `backend/tests/scheduler/test_schedule.py`: añadir `sync_pms_reservations` a la tabla
      de divergencias declaradas (`BEYOND_PRD_8_3` o una tabla propia con su comentario, mismo
      estilo que las demás filas: nombre, cadencia, por qué) y verificar que `CADENCES` /
      `beat_schedule()` lo incluyen con `timedelta(hours=6)`. [R1]
- [x] 4.2 `backend/tests/scheduler/test_sync_pms_reservations.py` (nuevo, mismo patrón que
      `test_generate_price_recommendations.py`): dos mitades, no una.
      **Mitad 1 — wiring directo contra la sesión de test**: llamar `_sync_pms_reservations`
      con una sesión de test real, un tenant con propiedades `MOCK` sembradas, y verificar que
      usa `since = now - timedelta(days=settings.pms_sync_window_days)` (no los 30 días del
      CLI) y que el `TimelineEvent` resultante lleva `source="pms_scheduled"` (no `"pms"` ni
      `"webhook"`).
      **Mitad 2 — candado y lista de tenants, con la lista de tenants stubbeada**: verificar
      que el TTL que llega a `task_lock` es `lock_ttl_for(timedelta(hours=6))` (18 h) y que dos
      llamadas concurrentes producen un `skipped_locked` — **NO** contra `worker_session_factory()`
      real (esa apunta a la BD de dev, que `tests/conftest.py` no toca a propósito y no tiene
      tenants, así que una aserción sobre el report de una llamada real al task es vacía — el
      mismo problema que el docstring de `test_generate_price_recommendations.py` ya documentó
      y resolvió para pricing). [R1]
- [x] 4.3 Test de aislamiento entre tenants, mismo patrón que
      `test_a_tenant_never_sees_another_tenants_rows` de `test_runner.py`: dos tenants `ACTIVE`
      con propiedades `MOCK`, un ciclo de `sync_pms_reservations`, verificar que cada
      `Reservation`/`TimelineEvent` resultante queda con el `tenant_id` correcto y que ninguna
      fila del tenant A es visible bajo la sesión marcada del tenant B. [R5]

## 5. Verification

- [ ] 5.1 Suite completa del backend: `docker compose exec backend uv run pytest`
- [ ] 5.2 Typecheck: `uv run pyright .` (desde `backend`, con `uv sync --frozen` ya corrido)
- [ ] 5.3 Manual: `make pms-sync TENANT=<uuid-del-seed>` produce el mismo informe
      (`created`/`updated`/`skipped`) que `python -m app.integrations.cli.pms_sync <uuid>` a
      mano, y `docker compose exec backend celery -A app.worker beat` (o el log del worker tras
      `make up`) muestra `sync_pms_reservations` disparando y reportando `skipped=N` en el
      segundo ciclo sobre el seed ya importado (idempotencia). <!-- manual -->

## Implementation Notes

<!-- Append-only, escrito por cada implementador de sección para la siguiente. -->

### Section 1 (config y atribución) — para Section 2

- `pms_sync_window_days: int = 2` quedó en `backend/app/core/config.py`, en el bloque Beds24,
  justo después de `beds24_timeout_seconds` y antes del comentario de "Object storage for the
  `S3` adapter" — no junto a `notification_batch_size` (que vive en el bloque de
  `access-notifications`, lejos de PMS). El nombre exacto del campo es `pms_sync_window_days`,
  léelo con `settings.pms_sync_window_days` (import `from app.core.config import settings`).
- `.env.example`: la línea comentada `# PMS_SYNC_WINDOW_DAYS=2` quedó justo debajo del bloque
  `# BEDS24_TIMEOUT_SECONDS=30.0`, con un comentario de dos líneas explicando que es distinta
  del default de 30 días del CLI manual.
- `SCHEDULED_SOURCE = "pms_scheduled"` quedó en `backend/app/integrations/application/use_cases.py`,
  inmediatamente después del docstring de `WEBHOOK_SOURCE`, con su propio docstring corto en el
  mismo estilo (referencia a este change, design D4, R3). Import exacto:
  `from app.integrations.application.use_cases import SCHEDULED_SOURCE`.
- Sin sorpresas en la carga de `Settings`: el campo entero simple no dispara ningún validador ni
  interactúa con otros campos (a diferencia de `password_reset_grace_minutes`, que sí tiene un
  `model_validator` cruzado). No hace falta añadir nada a `_default_database_url` ni a ningún
  otro validador.
- Nota de entorno para quien repita la verificación: este worktree no tenía `.env` (no está
  versionado); `docker compose run --rm backend ...` falla en seco sin él
  (`required variable JWT_SECRET_KEY is missing a value`). Generé uno temporal a partir de
  `.env.example` con `JWT_SECRET_KEY`/`ENCRYPTION_KEY` válidos solo para las comprobaciones de
  humo, corrí `docker compose down` al terminar y borré el `.env` — no quedó en el árbol
  (`git status` limpio salvo los tres ficheros de código y `.env.example`).
- Verificado: import de `settings.pms_sync_window_days` (imprime `2`), import de
  `SCHEDULED_SOURCE`/`PMS_SOURCE`/`CSV_SOURCE`/`WEBHOOK_SOURCE` (imprime los cuatro valores
  distintos), `tests/test_schedule.py` (17 passed), `tests/test_config.py` (110 passed),
  `tests/integrations/test_webhook_processing.py` + `test_webhook_causality.py` (23 passed) —
  todo corrido dentro de `backend/` vía `docker compose run --rm backend uv run pytest tests/...`.

### Section 2 (job de beat) — para Section 4

- `CADENCES["sync_pms_reservations"] = timedelta(hours=6)` quedó en
  `backend/app/scheduler/schedule.py`, como última entrada del dict, con su comentario propio
  encima (mismo estilo que `classify_reviews`). `beat_schedule()` lo deriva sin más — no toqué
  `DAILY_JOBS`/`MONTHLY_JOBS`.
- `backend/app/scheduler/tasks.py`:
  - Función de trabajo: `async def _sync_pms_reservations(session: AsyncSession, tenant_id, now:
    datetime)`, colocada inmediatamente después de `_reconcile_owner_approvals_for_expenses` y
    antes de `_locked`. Construye `SyncReservationsFromPmsUseCase` con
    `SqlAlchemyPMSAdapterFactory(credentials=SqlAlchemyPmsCredentialRepository(session))` — SIN
    `forced_provider` — más `SqlAlchemyReservationRepository`, `SqlAlchemyPropertyRepository`,
    `SqlAlchemyGuestRepository`, `SqlAlchemyTimelineEventRepository`, `SqlAlchemyUnitOfWork`,
    `SqlAlchemyAuditLogRepository(session)` y `PostgresGuestEmailExclusion(session)`. Llama
    `execute(tenant_id=tenant_id, since=now - timedelta(days=settings.pms_sync_window_days),
    now=now, source=SCHEDULED_SOURCE)` — sin `providers` ni `actor_type`, ambos en su default
    (`None` → todos los providers; `TimelineActorType.SYSTEM`).
  - Tarea Celery: `@celery_app.task(name="sync_pms_reservations") def sync_pms_reservations() ->
    dict`, al final del fichero (después de `reconcile_owner_approvals_for_expenses`). Cuerpo
    literal: `return run_sync(_guarded("sync_pms_reservations",
    CADENCES["sync_pms_reservations"], _sync_pms_reservations))` — nombres de string literales,
    no constantes (mismo patrón que `check_checkin_windows`/`mark_occupied_estimated`, no el de
    `WEBHOOK_TASK`/`PRICING_TASK`).
  - Import añadido: `SCHEDULED_SOURCE` se coló en la línea ya existente de
    `SyncReservationsFromPmsUseCase` →
    `from app.integrations.application.use_cases import SCHEDULED_SOURCE,
    SyncReservationsFromPmsUseCase`. `SqlAlchemyGuestRepository` NO hizo falta añadirlo: ya
    estaba importado en el módulo (`from app.guests.infrastructure.repositories import
    SqlAlchemyGuestRepository`) para `_webhook_tenant_use_case`.
- Para llamar `_sync_pms_reservations` directamente en un test (mitad 1 de 4.2): es una
  `async def`, se le pasa la sesión de test real, un `tenant_id` (UUID) y un `now: datetime`
  ya tz-aware (UTC) — no abre su propia sesión ni marca el tenant, eso lo hace el caller
  (`run_for_every_tenant`/`run_in_marked_session` en producción; en el test, márcalo a mano con
  `bind_session_to_tenant` como hace `sync_with_session`, o usa el fixture que ya lo haga para
  otros tests del dominio).
- **`worker_session_factory()` apunta a la BD real de compose (`postgres:5432`), no a la sesión
  de test de `tests/conftest.py`.** Llamar a la task de Celery de extremo a extremo
  (`sync_pms_reservations()` o incluso `_guarded(...)` tal cual) contra esa fábrica golpea la
  BD de dev, que el propio `conftest.py` deja intacta a propósito y que no tiene tenants — así
  que un test que llame la task real y luego assert sobre su `report` está aserting sobre un
  resultado vacío por construcción, no sobre lógica rota. Es exactamente la trampa que el
  docstring de `test_generate_price_recommendations.py` ya documentó para `generate_price_
  recommendations`; la mitad 2 de 4.2 (candado/lista de tenants) tiene que stubbear
  `run_for_every_tenant`/`worker_session_factory` en vez de dejar que toquen la BD real, y la
  mitad 1 (wiring) tiene que llamar `_sync_pms_reservations` directo contra la sesión de test,
  nunca la task de Celery ni `_guarded`.
- El TTL que le llega a `task_lock` cuando dispara esta task es `lock_ttl_for(timedelta(hours=6))`
  = 18 h (`lock_ttl_for` en `app/scheduler/locks.py` multiplica por 3) — no hay una entrada en
  `DAILY_JOBS`/`MONTHLY_JOBS` que lo sobrescriba, así que el camino es el mismo `_guarded` → 
  `_locked` → `lock_ttl_for(cadence)` que usan `check_checkin_windows` y el resto de `CADENCES`.
- Suite no tocada (fuera de alcance de Section 2): `backend/tests/scheduler/test_schedule.py`
  falla ahora en 2 tests — `test_the_calendar_is_prd_8_3_plus_exactly_the_declared_additions` y
  `test_the_beat_schedule_covers_both_tables_and_nothing_else` — porque su `ALL_CADENCES` /
  `BEYOND_PRD_8_3` locales todavía no listan `sync_pms_reservations`. Es exactamente lo que 4.1
  tiene que añadir (ver líneas ~59-69 de ese fichero para el estilo de las filas existentes).
  El resto de `tests/scheduler/` (1581 tests) y `tests/test_layering.py` pasan limpios —
  `app/scheduler/tasks.py` sigue siendo el único módulo bajo `backend/app/` que importa Celery.
- Entorno: este worktree seguía sin `.env` (no versionado). Repetí el mismo procedimiento que
  Section 1: generé uno temporal desde `.env.example` con `JWT_SECRET_KEY`/`ENCRYPTION_KEY`
  válidos, corrí `docker compose down` al terminar y borré el `.env` — árbol limpio salvo
  `schedule.py`, `tasks.py` y este `tasks.md`.
- Comandos corridos (todos `docker compose run --rm backend uv run ...` desde la raíz del
  worktree): `python -c "from app.scheduler.schedule import CADENCES, beat_schedule; ..."`
  → `6:00:00` / `True`; `python -c "import app.scheduler.tasks"` → `ok`; `pytest tests/scheduler/
  tests/test_layering.py -q` → 1581 passed, 2 failed (los dos de arriba, esperados y para 4.1).
  No corrí la suite completa ni pyright — eso es Section 5.

### Section 3 (disparo manual) — para Section 5

- Target `pms-sync:` añadido al `Makefile`, inmediatamente después de `sim-advance:` (línea
  ~299), con el mismo comentario de dos líneas explicando `TENANT`/`WINDOW`/`PROVIDER` y la
  referencia a D5. `pms-sync` añadido a la lista `.PHONY:` de la línea 125, junto a
  `sim-advance`.
- Comando exacto: `$(COMPOSE) exec -T backend python -m app.integrations.cli.pms_sync $(TENANT)
  $(if $(WINDOW),$(WINDOW),) $(if $(PROVIDER),--provider $(PROVIDER),)`. Orden de argumentos
  confirmado contra `backend/app/integrations/cli/pms_sync.py::main`/`_extract_provider`:
  posicional 1 = tenant UUID (`args[0]`), posicional 2 opcional = window-days (`args[1]`, si no
  se pasa usa el default del propio CLI — 30 días, no los 2 de `pms_sync_window_days` que usa
  el scheduler), `--provider <valor>` puede ir en cualquier posición (se extrae de `argv` antes
  de mirar los posicionales), y si se omite usa `MOCK_PROVIDER`.
  **No verifiqué ni cambié el default de `window-days` en el propio CLI** — solo confirmé que
  es 30 leyendo `_extract_provider`/`main`; si Section 5 necesita el nombre exacto de la
  constante, es `DEFAULT_WINDOW_DAYS` en `pms_sync.py`.
- Verificado con `make -n` (dry-run, no se levantó el stack ni se llamó Docker):
  - `make -n pms-sync TENANT=00000000-0000-0000-0000-000000000000` →
    `docker compose -f docker-compose.yml -f docker-compose.worktree.yml exec -T backend python
    -m app.integrations.cli.pms_sync 00000000-0000-0000-0000-000000000000` (sin argumentos de
    más; el overlay `-f docker-compose.worktree.yml` es por correr desde un worktree, viene de
    `$(COMPOSE)` sin tocar).
  - `make -n pms-sync TENANT=00000000-0000-0000-0000-000000000000 WINDOW=7 PROVIDER=beds24` →
    mismo comando + ` 7 --provider beds24` al final, orden correcto.
  - `grep -n "pms-sync" Makefile` → confirma el target (línea 299) y la entrada en `.PHONY`
    (línea 125).
- Para la verificación manual real de 5.3 (`make pms-sync TENANT=<uuid-del-seed>` contra el
  stack levantado): usa un tenant ya sembrado con propiedades y credenciales PMS (el mismo
  patrón de seed que Section 1/2 usaron para sus pruebas de humo), y compara el informe
  `created`/`updated`/`skipped` contra invocar el mismo CLI a mano dentro del contenedor
  (`docker compose exec backend python -m app.integrations.cli.pms_sync <uuid>`) — deben ser
  idénticos porque `make pms-sync` no hace nada más que anteponer `docker compose exec -T
  backend`. No se necesita `.env` temporal solo para el dry-run (`make -n` no invoca Docker),
  pero si Section 5 levanta el stack (`make up`) necesitará el mismo `.env` temporal que
  Sections 1-2 generaron a partir de `.env.example`, y recordar bajarlo al terminar.

### Section 4 (tests) — para Section 5

- `backend/tests/scheduler/test_schedule.py`: `sync_pms_reservations` añadido a `BEYOND_PRD_8_3`
  con `timedelta(hours=6)` y su propia fila de comentario en el bloque de arriba (mismo estilo
  que las demás — nombre, cadencia, por qué), siguiendo exactamente el estilo que `schedule.py`
  ya usaba para su propio comentario de la entrada en `CADENCES`. Sin sorpresas: los dos tests
  que Section 2 dejó en rojo (`test_the_calendar_is_prd_8_3_plus_exactly_the_declared_additions`,
  `test_the_beat_schedule_covers_both_tables_and_nothing_else`) pasan ahora sin tocar nada más
  del fichero.
- `backend/tests/scheduler/test_sync_pms_reservations.py` (nuevo, 6 tests, docstring de módulo
  explica el mismo split de `test_generate_price_recommendations.py`):
  - Mitad 1 (wiring, contra `db_session` real, sin mockear nada):
    `test_since_is_derived_from_the_settings_window_and_not_the_cli_default` y
    `test_the_resulting_timeline_events_are_tagged_scheduled_not_manual_or_webhook`. Ambas
    siembran un tenant (`insert_tenant` de `tests.auth.conftest`) con una `PropertyModel` cuyo
    `pms_external_id=SEED_PROPERTY_CODE` (de `app.integrations.infrastructure.mock_pms`, no un
    literal repetido), marcan la sesión con `bind_session_to_tenant`, y llaman
    `_sync_pms_reservations(db_session, tenant.id, NOW)` directo — nunca la task de Celery.
    **Verificado que ambas aserciones son reales y no vacías**: mutando temporalmente
    `tasks.py` (since a 30 días fijos, y quitando `source=SCHEDULED_SOURCE`), cada test
    correspondiente falló como se esperaba; revertido antes de dejar el fichero — `git diff`
    de `backend/app/scheduler/tasks.py` queda limpio, solo tocado `test_schedule.py` y el
    nuevo fichero de test.
    `MockPMSAdapter._seed` construye sus dos reservas a partir de `since.date()` (NO de `now`),
    así que la fecha de `check_in_date`/`check_out_date` de la `Reservation` resultante es una
    señal real de qué `since` calculó el job — no hace falta espiar la llamada al adaptador.
  - Mitad 2 (candado/lista de tenants, tenant list stubbeada donde hace falta):
    `test_the_lock_ttl_is_the_cadence_times_three` (TTL == `lock_ttl_for(timedelta(hours=6))`
    == 18 h, contra el `task_lock` real parcheado, mismo patrón que el test de TTL de
    `generate_price_recommendations`), `test_a_run_that_loses_the_lock_is_skipped_not_failed`
    (dos llamadas concurrentes, la segunda `skipped_locked=True`) y
    `test_it_calls_the_sync_once_per_active_tenant` (loop, con `list_active_tenants` Y
    `_sync_pms_reservations` stubbeados — analogía exacta del test de
    `generate_price_recommendations` para el loop). Las tres corren contra
    `worker_session_factory()`/la BD real de compose (vacía de tenants) tal como lo hace su
    precedente, porque ninguna de sus aserciones depende de cuántos tenants existan ahí.
  - Aislamiento (R5, 4.3): `test_a_tenant_never_sees_another_tenants_reservations_or_timeline_events`,
    mismo patrón que `test_a_tenant_never_sees_another_tenants_rows` de `test_runner.py` — usa
    la misma fixture `worker_sessions` (duplicada localmente en este fichero, no importada de
    `test_runner.py`, que no la exporta) para apuntar `runner._session_factory` al motor de
    test. Dos tenants `ACTIVE` con una `PropertyModel` `MOCK` cada uno (mismo
    `SEED_PROPERTY_CODE`, distinto `tenant_id` — el índice único de `properties` está scopeado
    por tenant así que no colisiona), un `runner.run_for_every_tenant(TASK_NAME,
    _sync_pms_reservations, now=NOW)`, y dos aserciones: (a) contra `db_session` SIN marcar,
    que las filas resultantes de `ReservationModel`/`TimelineEventModel` llevan exactamente los
    dos `tenant_id` esperados; (b) contra una sesión nueva marcada para cada tenant
    (`bind_session_to_tenant`), que un `SELECT` sin `tenant_id` en el WHERE no devuelve ninguna
    fila del otro tenant.
- Comandos exactos para reproducir solo estos tests (desde la raíz del worktree, con `.env`
  temporal si el stack está abajo): `docker compose run --rm backend uv run pytest
  tests/scheduler/test_schedule.py tests/scheduler/test_sync_pms_reservations.py -q` → 23
  passed. `docker compose run --rm backend uv run pytest tests/scheduler/ -q` → 68 passed, 0
  failed (todo `tests/scheduler/`, incluidos los 6 nuevos). `docker compose run --rm backend
  uv run pytest tests/scheduler/ tests/test_layering.py -q` → 1589 passed, 0 failed — 1581 que
  Section 2 dejó pasando + los 2 que dejó en rojo (arreglados por 4.1) + los 6 nuevos de
  4.2/4.3.
- Entorno: este worktree seguía sin `.env`. Repetí el mismo procedimiento que Sections 1-3:
  `.env` temporal generado desde `.env.example` con `JWT_SECRET_KEY`/`ENCRYPTION_KEY` válidos
  (usando `secrets.token_urlsafe(32)` y `Fernet.generate_key()` respectivamente), `docker
  compose down` al terminar, `.env` borrado — árbol limpio salvo `test_schedule.py`,
  el nuevo `test_sync_pms_reservations.py` y este `tasks.md`.
- No corrí la suite completa ni pyright — eso sigue siendo Section 5, igual que dejó dicho
  Section 2.
