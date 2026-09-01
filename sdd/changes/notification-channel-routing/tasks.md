# Tasks: notification-channel-routing

## 1. Resolutor de canales (puro, TDD)

- [x] 1.1 Tests primero: `backend/tests/notifications/test_channel_resolver.py` cubriendo R1.1 (IN_APP siempre; +EMAIL si flag; +WHATSAPP si flag), R1.5 (config ausente → `{IN_APP}` y log `notifications.tenant_config_missing`), R3.1 (sin `phone` excluye `WHATSAPP`), R3.2 (sin email utilizable excluye `EMAIL`) y la intersección de los dos flags. [R1, R3]
- [x] 1.2 Crear `backend/app/notifications/domain/channel_resolver.py` con `RecipientContact` (dataclass frozen: `email: str | None`, `phone: str | None`) y `resolve_channels(tenant_config, recipient) -> frozenset[NotificationChannel]`. Función pura: sin imports de `sqlalchemy`/`fastapi`/`pydantic` ni de `infrastructure/`. Registra la exclusión por contacto ausente vía `logger.info("notifications.channel_dropped_for_missing_contact", extra=...)` con `tenant_id`, `notification_type`, `channel` y `recipient_role` (nada de `recipient_contact`/`subject`/`body`, por regla 11 de `steering/security.md`). La suite de 1.1 debe pasar entera. [R1, R3]

## 2. Fan-out de canal (aplicación)

- [x] 2.1 Tests primero: `backend/tests/notifications/test_channel_dispatch.py` cubriendo R2.1 (N filas idénticas excepto `channel` y `recipient_contact`), R2.3 (cada fila lleva `status = PENDING` y `recipient_contact` del canal: `email` para EMAIL/IN_APP, `phone` para WHATSAPP), R4.1 (`sla_deadline_at` solo en la fila IN_APP), R4.2 (`cancel_sla_deadline` cierra las N filas en una sola llamada, sin tocar el contrato) y R4.3 (abanicar `CLEANING_TASK_ASSIGNED` y `TECHNICIAN_ASSIGNED` con los dos flags activos da una sola candidata por aviso). [R2, R4]
- [x] 2.2 Crear `backend/app/notifications/application/channel_dispatch.py` con `dispatch_channels(*, recipient, template, channels, log_builder, tenant_config)` que itera `channels` y delega al builder del dominio con `(channel, contact)` ajustados al canal. El builder fija `sla_deadline_at` solo si el canal pasado es `IN_APP` (cuando proceda por tipo). La suite de 2.1 debe pasar entera. Aquí cae la lógica que el `BLOCKED.md` del change anterior dejó abierta (R7.5 del S0). [R2, R4]

## 3. Builders de los cinco módulos (parametrizar canal y contacto)

- [x] 3.1 `backend/app/cleaning/domain/notifications.py` — los 4 builders ganan `channel: NotificationChannel = IN_APP` y `contact: str | None = None` opcionales. La `recipient_contact` actual pasa a derivarse del canal pasado (`email` para IN_APP/EMAIL, `phone` para WHATSAPP, fallback al valor actual si `contact` es `None`). `sla_deadline_at` solo cuando `channel == IN_APP`. Tests del módulo actualizados al nuevo parámetro (siguen construyendo una fila, ahora con `channel=IN_APP` explícito). [R2, R4]
- [x] 3.2 `backend/app/maintenance/domain/notifications.py` — idem para los 5 builders; tests del módulo actualizados. [R2, R4]
- [x] 3.3 `backend/app/messaging/domain/notifications.py` — idem para el builder; test del módulo actualizado. [R2, R4]
- [x] 3.4 `backend/app/pricing/domain/notifications.py` — idem para el builder; test del módulo actualizado. [R2, R4]
- [x] 3.5 `backend/app/guests/application/use_cases.py` — el literal `NotificationChannel.IN_APP` se reemplaza por una llamada a `dispatch_channels(...)` (carga `TenantConfig` desde `TenantConfigRepository`, ya inyectado en el módulo). La fila con `notification_type = "LEGAL_REGISTRATION_FAILED"` (no es miembro del enum) conserva el texto crudo en la columna `String(100)` y se sigue escribiendo como hasta ahora. [R2]

## 4. Casos de uso — integrar `dispatch_channels`

- [x] 4.1 `backend/app/cleaning/application/use_cases.py` — las llamadas a los 4 builders pasan a través de `dispatch_channels`; la `TenantConfig` se carga una vez por `execute` (no por destinatario) desde `TenantConfigRepository` y se pasa al resolutor. Tests del módulo actualizados al patrón `dispatch_channels(...)`. [R1, R2, R4]
- [x] 4.2 `backend/app/maintenance/application/use_cases.py` — idem para los 5 builders; tests del módulo actualizados. [R1, R2, R4]
- [x] 4.3 `backend/app/messaging/application/use_cases.py` — idem; tests del módulo actualizados. [R1, R2, R4]
- [x] 4.4 `backend/app/pricing/application/use_cases.py` — idem; tests del módulo actualizados. [R1, R2, R4]

## 5. Bandeja in-app — filtro por canal

- [x] 5.1 `backend/app/notifications/domain/repositories.py` — `list_for_recipient` y `count_unread` aceptan un parámetro keyword-only `channel: NotificationChannel = NotificationChannel.IN_APP`. La cláusula WHERE gana `AND channel = :channel`; el default perezoso fija `IN_APP` y el docstring documenta que pasar otro canal es opt-in para diagnóstico. [R5]
- [x] 5.2 `backend/app/notifications/application/use_cases.py` — `ListOwnNotificationsUseCase`, `CountUnreadNotificationsUseCase`, `MarkNotificationReadUseCase`, `MarkAllNotificationsReadUseCase` propagan el default `channel=IN_APP` (no se filtra explícitamente, se delega en el default del repositorio). Eliminar `_escalation_row` del módulo y delegar la fila de escalada en `dispatch_channels` (queda abanicada). [R2, R4, R5]
- [x] 5.3 `backend/app/notifications/api/router.py` — comprobar que el router no fija filtros de canal (D4); el default del repositorio cubre R5.1 y R5.2 sin tocar el router. Si algún `Depends(...)` pasara `channel=...`, dejarlo tal cual o eliminarlo para que aplique el default. [R5]

## 6. Guard AST de literales de canal

- [x] 6.1 Crear `backend/tests/notifications/test_channel_literals.py` que enumere literales `NotificationChannel.<X>` sobre el AST de `backend/app/` con la whitelist exacta de D6: `notifications/application/channel_dispatch.py` (resuelve canales), `notifications/domain/channel_resolver.py` (devuelve el conjunto resuelto), `auth/application/recovery.py` (R6 declarado), `notifications/infrastructure/adapters.py` (registro de adapters, sin fila), `messaging/infrastructure/channels.py` (canales de conversación), `tests/notifications/test_channel_literals.py` (el propio guard). El test falla si aparece un literal de canal fuera de la whitelist y enumera los 13 sitios actuales como evidencia. [R2]

## 7. Tests existentes a actualizar al patrón multi-fila

- [x] 7.1 `backend/tests/notifications/test_writer_census.py` — añadir `notifications/application/channel_dispatch.py` a `CONSTRUCTION_SITES`; la regla "`cancel_sla_deadline` no es un escritor" se conserva (R6.3). [R2]
- [x] 7.2 `backend/tests/notifications/test_repositories.py` — añadir un test que verifique que `list_for_recipient` y `count_unread` con el default aplicado devuelven exclusivamente filas con `channel = IN_APP`, y que pasar `channel=EMAIL` explícitamente con el mismo conjunto de avisos da cero (el default no es bypassable por el router accidentalmente). [R5]
- [x] 7.3 `backend/tests/notifications/test_api.py` — añadir la invariante R5.4: con `notification_email_enabled` activado en el tenant del destinatario, `GET /api/v1/notifications` devuelve el mismo número de elementos que con la flag apagada. [R5]
- [x] 7.4 `backend/tests/notifications/test_escalate_slas_atomicity.py` — añadir el test que cubre R4.3 explícitamente: abanicar `CLEANING_TASK_ASSIGNED` y `TECHNICIAN_ASSIGNED` con los dos flags del tenant activos y verificar que `list_sla_breach_candidates` devuelve una sola candidata por aviso. [R4]
- [x] 7.5 Tests de las use cases de los cinco módulos (cleaning, maintenance, messaging, pricing, guests). **Corregido en la ronda de fixes de `/sdd:review`**: la primera pasada dejó las aserciones existentes de cada módulo pinadas al caso de los dos flags apagados (1 fila IN_APP, vía `insert_tenant`/`world`/`FakeTenantConfigRepository` con los flags en `False` por defecto) sin añadir ningún test que ejercitara el camino real (HTTP/use case → `dispatch_and_persist`) con los flags activos — el panel de QA lo encontró como una reclamación falsa (checkbox marcado sin la cobertura descrita). Añadido ahora: **un test de integración nuevo por módulo** (`test_manual_assignment_fans_out_across_the_tenants_enabled_channels` en cleaning, `test_a_critical_classification_fans_out_across_the_tenants_enabled_channels` en maintenance, `test_escalation_fans_out_across_the_tenants_enabled_channels` en messaging, `test_a_run_fans_out_across_the_tenants_enabled_channels` en pricing, `test_a_rejected_submission_fans_out_across_the_tenants_enabled_channels` en guests) que activa los dos flags y confirma 3 filas (IN_APP + EMAIL + WHATSAPP) con el `recipient_contact` correcto por canal, a través del camino de producción real. El caso de `phone`/`email` ausente (R3.1/R3.2) sigue cubierto solo a nivel de función pura en `test_channel_resolver.py` — no se duplica por módulo porque la exclusión es responsabilidad exclusiva del resolutor (R1.3) y no depende del escritor que lo invoca. [R2, R3, R4]

## 8. Specs EARS

- [x] 8.1 `sdd/specs/access-notifications.md` — modificar §«El censo de escritores, y la forma común de todos ellos»: el `SHALL` actual (*"con `status = PENDING` y `channel = IN_APP`"*) pasa a leerse como una fila por canal resuelto. Añadir una viñeta declarando la excepción de `auth/application/recovery.py` (R6.1). Modificar §«La bandeja in-app» para que el listado y el contador se acoten por `AND channel = IN_APP`. Ampliar el censo AST con la nueva forma `dispatch_channels`. [R1, R2, R4, R5, R6]
- [x] 8.2 `sdd/specs/notifications-inbox-web.md` — modificar R1 y R2: `GET /api/v1/notifications` y `unread-count` se acotan a `channel = IN_APP`; el resto del contrato (envelope, orden, `unread`, `read_at`, conjunto de campos publicados) se conserva. [R5]
- [x] 8.3 `sdd/specs/celery-jobs.md` — modificar §«check_sla_breaches»: solo la fila IN_APP lleva `sla_deadline_at`; las demás se escriben con `NULL`; `cancel_sla_deadline` sigue casando por `tenant_id + related_type + related_id + notification_type` (sin canal) y cierra las N filas en una sola llamada. Confirmar que `list_sla_breach_candidates` exige `sla_deadline_at IS NOT NULL` y por tanto solo la IN_APP puede llegar a candidata. [R4]
- [x] 8.4 `sdd/specs/auth-tenancy.md` — modificar §«TenantConfig`: declarar `notification_email_enabled` y `notification_whatsapp_enabled` como interruptores de canal gobernados por `notifications/domain/channel_resolver.py` (R1.1). [R1]

## 9. Contrato API regenerado (`steering/documentation.md`)

- [x] 9.1 Regenerar `backend/openapi.json` con `make openapi` y commitearlo en el mismo commit del cambio de código (el workflow `api-contract` falla si hay deriva). [R5]
- [x] 9.2 Regenerar el artefacto derivado del frontend con `cd frontend && npm run api:generate` y commitear `frontend/lib/api/generated/openapi.d.ts` (el workflow `frontend-api-contract` falla si hay deriva). [R5]

## 10. Verification

- [x] 10.1 Suite backend completa: `docker compose exec backend uv run pytest` (con el stack levantado) o `docker compose run --rm backend uv run pytest` (con el stack parado). Cero regresiones, todos los tests nuevos de 1.1, 2.1, 3.x, 4.x, 6.1, 7.x en verde. (R1–R6)
- [x] 10.2 Contrato frontend: `cd frontend && npm run api:check` — no hay deriva entre el OpenAPI commiteado y los tipos generados en `frontend/lib/api/generated/openapi.d.ts`. (R5)
- [x] 10.3 Inspección manual del inbox: en un tenant de seed, activar `PATCH /api/v1/tenants/{id}` con `notification_email_enabled=true`, generar un aviso nuevo (p. ej. asignar una limpieza) y confirmar que el `GET /api/v1/notifications` y el contador de no leídas devuelven el mismo número que con la flag apagada. (R5.4)
