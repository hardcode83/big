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

## 2. Job de beat

- [ ] 2.1 `backend/app/scheduler/schedule.py`: añadir `"sync_pms_reservations":
      timedelta(hours=6)` a `CADENCES`, con un comentario de docstring como los demás
      (referencia a `pms-sync-schedule`, por qué 6 h — la cadencia que Beds24 recomienda para
      sync completo — y que reemplaza la ausencia que `celery-jobs` D16 documentó). [R1]
- [ ] 2.2 `backend/app/scheduler/tasks.py`: añadir `async def _sync_pms_reservations(session,
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

## 3. Disparo manual

- [ ] 3.1 `Makefile`: target `pms-sync:` junto a `sim-advance:`, invocando `$(COMPOSE) exec -T
      backend python -m app.integrations.cli.pms_sync $(TENANT) $(if $(WINDOW),$(WINDOW),) $(if
      $(PROVIDER),--provider $(PROVIDER),)` — mismo patrón de argumentos opcionales que
      `sim-advance`. Añadir `pms-sync` a la lista de `.PHONY`. [R4]

## 4. Tests

- [ ] 4.1 `backend/tests/scheduler/test_schedule.py`: añadir `sync_pms_reservations` a la tabla
      de divergencias declaradas (`BEYOND_PRD_8_3` o una tabla propia con su comentario, mismo
      estilo que las demás filas: nombre, cadencia, por qué) y verificar que `CADENCES` /
      `beat_schedule()` lo incluyen con `timedelta(hours=6)`. [R1]
- [ ] 4.2 `backend/tests/scheduler/test_sync_pms_reservations.py` (nuevo, mismo patrón que
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
- [ ] 4.3 Test de aislamiento entre tenants, mismo patrón que
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
