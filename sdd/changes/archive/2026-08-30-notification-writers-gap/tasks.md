# Tasks: notification-writers-gap

Orden elegido para que el árbol quede verde al final de cada sección: primero las dos
superficies compartidas (resolvedor de destinatarios y puerto de idempotencia), luego los
seis escritores dominio a dominio, y el guardián del censo al final — cuando los seis ya
existen y su lista literal puede declarar los cuatro huérfanos de R6.2 sin mentir.

## 1. Resolvedor de destinatarios (D1) <!-- panel: PASS 2026-08-29 -->

- [x] 1.1 TDD: escribir `backend/tests/auth/test_recipients.py` contra un `UserRepository`
  falso — `managers_or_owners` devuelve los `PROPERTY_MANAGER` activos; cae a los
  `TENANT_OWNER` activos sólo si no hay ninguno; devuelve vacío si no hay ni unos ni otros;
  `active_holders(tenant, role)` devuelve una página y `Recipients.dropped` cuenta
  `page.total - len(page.items)`; `Recipients` es `frozen` y no emite ningún log. [R5.1, R5.2]
- [x] 1.2 Crear `backend/app/auth/domain/recipients.py` con `Recipients(users, dropped)`
  congelado y `RoleRecipients(users: UserRepository)` exponiendo `managers_or_owners(tenant_id)`
  y `active_holders(tenant_id, role)`; el módulo no importa de ningún otro dominio. Docstring
  que diga por qué vive en `auth` y por qué el log de truncamiento lo emite el llamante. [R5.1]
- [x] 1.3 Migrar `backend/app/notifications/application/use_cases.py`:
  `_resolve_recipients`/`_active_holders` pasan a delegar en `RoleRecipients`, conservando
  intactos `EscalationReport.recipients_truncated` y la clave de log
  `scheduler.escalation_recipients_truncated`. Ajustar los fakes de
  `backend/tests/notifications/conftest.py` y `backend/tests/scheduler/` si cambia la
  construcción; `backend/tests/notifications/test_escalate_slas.py` debe pasar **sin cambios de
  aserción** — es una refactorización sin cambio observable. [R5.1]
- [x] 1.4 Migrar `backend/app/guests/application/use_cases.py::_managers` a una llamada a
  `RoleRecipients.managers_or_owners`; borrar la consulta inline y el `_MAX_RECIPIENTS` local si
  queda huérfano. Los tests de `backend/tests/guests/` pasan sin cambios de aserción. [R5.1]

## 2. Idempotencia del aviso de severidad (D2) <!-- panel: PASS 2026-08-29 -->

- [x] 2.1 Añadir `exists_for(tenant_id, *, related_type, related_id, notification_type) -> bool`
  al `Protocol` de `backend/app/notifications/domain/repositories.py`, con docstring que diga
  por qué es lectura y no índice único (migración fuera de alcance) y que `add` hace `flush()`,
  de modo que la fila escrita antes en la misma transacción ya es visible. [R1.3]
- [x] 2.2 Implementarlo en `backend/app/notifications/infrastructure/repositories.py` como
  `SELECT ... LIMIT 1` con scope de tenant, sobre la misma tripleta que cubre
  `ix_notification_logs_related_type_related_id`. [R1.3]
- [x] 2.3 Test de integración en `backend/tests/notifications/test_repositories.py`: `False`
  cuando no hay fila; `True` tras un `add` **en la misma transacción, sin commit**; `False` para
  otro `notification_type`, otro `related_id` y otro tenant (aislamiento). [R1.3]

## 3. El escalado del técnico se llama por su nombre (D8, R3) <!-- panel: PASS 2026-08-29 -->

- [x] 3.1 En `backend/app/notifications/domain/escalation.py`, la entrada `TECHNICIAN_ASSIGNED`
  de `_POLICY` produce `notification_type=NotificationType.TECHNICIAN_NO_RESPONSE`, conservando
  `recipient_role=PROPERTY_MANAGER` y `reason="technician_assignment_unanswered_no_phone_adapter"`.
  Actualizar el comentario de PRD §14 que hay encima para que no siga describiendo un
  `SLA_BREACH` que ya no escribe esa rama. Nada más cambia: sin campo nuevo en `Escalation`, sin
  tocar `_escalation_row` ni su `subject` constante `"SLA breach"`. [R3.1, R3.3]
- [x] 3.2 Actualizar `backend/tests/notifications/test_escalation.py`: `escalation_for("TECHNICIAN_ASSIGNED")`
  da `TECHNICIAN_NO_RESPONSE`; `escalation_for("CLEANING_TASK_ASSIGNED")` sigue dando `SLA_BREACH`
  (R3.2); `escalation_for("TECHNICIAN_NO_RESPONSE")` devuelve `None` — el escalado no escala
  (R3.4); y el conjunto «sin escalado» del test pierde `TECHNICIAN_NO_RESPONSE` y gana
  `SLA_BREACH`. Ningún test escribe ni reescribe filas históricas (R3.5). [R3.1, R3.2, R3.4, R3.5]

## 4. R1 — la incidencia grave avisa al manager (D3, D4, D5) <!-- panel: PASS 2026-08-29 -->

- [x] 4.1 TDD en `backend/tests/maintenance/test_notifications.py`: los dos builders nuevos
  producen `status=PENDING`, `channel=IN_APP`, `related_type="incident"`, `related_id` la
  incidencia, `notification_type` el literal correcto, **`sla_deadline_at is None`**, y un
  `subject`/`body` de constante más identificadores que **no** contiene `title`, `description`
  ni `ai_summary` de la incidencia (pásale una entidad con texto reconocible y afirma que no
  aparece). [R5.3, R5.4, R5.5, R5.6]
- [x] 4.2 Añadir `incident_critical_notification` e `incident_high_notification` a
  `backend/app/maintenance/domain/notifications.py`, cada uno con su
  `notification_type=NotificationType.<X>.value` escrito a mano en el `NotificationLog(...)` y
  **sin parámetro de plazo en la firma**, calcando la docstring de contrato de los builders que
  ya hay. [R1.1, R1.2, R5.3, R5.4, R5.5, R5.6, R6.3]
- [x] 4.3 En `backend/app/maintenance/application/use_cases.py`, añadir el mixin
  `_NotifiesSeverity` junto a `_ApprovalGateMixin` con `_notify_severity(tenant_id, incident, now)`:
  resuelve destinatarios con `RoleRecipients.managers_or_owners`, consulta `exists_for` y escribe
  una fila por destinatario; si no hay destinatarios, no escribe y registra (R5.2). [R1.3, R5.1, R5.2]
- [x] 4.4 `ClassifyIncidentUseCase` gana los puertos `users` + `notifications` y llama a
  `_notify_severity` **antes** de su `await self._uow.commit()`, sólo si
  `incident.status is CLASSIFIED` y `incident.severity in {CRITICAL, HIGH}`.
  `TriageIncidentUseCase` (que ya tiene ambos puertos por `_gate_kwargs`) llama igual tras
  `set_triage`, antes de su commit. [R1.1, R1.2, R1.5, R1.6]
- [x] 4.5 Wiring: `backend/app/maintenance/api/dependencies.py::get_classify_incident_use_case`,
  `backend/app/scheduler/tasks.py` y `backend/app/cli/seed_demo.py::_incident_flow_kwargs` pasan
  los dos puertos nuevos. [R1.1]
- [x] 4.6 Tests de caso de uso en `backend/tests/maintenance/` (fixtures de
  `tests/maintenance/conftest.py` actualizadas con los puertos nuevos): clasificación por encima
  del umbral a `CRITICAL` escribe una fila por manager; a `HIGH` escribe `INCIDENT_CREATED_HIGH`;
  clasificar y luego triar confirmando la misma severidad escribe **una sola** fila (R1.3); un
  triage que sube de `HIGH` a `CRITICAL` escribe la `CRITICAL` **además** de la `HIGH` que ya
  existía (R1.4); por debajo del umbral (`OPEN`/`MEDIUM`, sólo `ai_classification`) no escribe
  nada (R1.5); sin manager activo la fila va al owner y sin ninguno de los dos no se escribe y
  la operación no falla (R5.1, R5.2). Añadir un test que compruebe que la fila y la incidencia
  llegan en el mismo commit (R1.6). [R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R5.1, R5.2]

## 5. R2 — el lazo de la limpieza se cierra en las dos direcciones (D4, D6) <!-- panel: PASS 2026-08-29 -->

- [x] 5.1 TDD en `backend/tests/cleaning/test_notifications.py`: `completion_notification` y
  `validation_failed_notification` con `related_type="cleaning_task"`, `related_id` la tarea,
  `status=PENDING`, `channel=IN_APP`, `sla_deadline_at is None`, y `subject`/`body` que no
  arrastran texto libre de la tarea (checklist, notas, motivo del fallo). [R5.3, R5.4, R5.5, R5.6]
- [x] 5.2 Añadir los dos builders a `backend/app/cleaning/domain/notifications.py`, cada uno con
  su literal `NotificationType.CLEANING_COMPLETED.value` / `NotificationType.CLEANING_FAILED.value`
  y sin parámetro de plazo. [R2.1, R2.2, R5.3, R5.4, R5.5, R5.6, R6.3]
- [x] 5.3 En `backend/app/cleaning/application/use_cases.py`, subir `notifications` y `users` a
  `_TaskLifecycleBase`; **reescribir** el párrafo de la docstring de `_AnswersAnAssignmentBase`
  que dice que completar y validar no reciben el puerto — la razón que daba sigue siendo cierta
  (no cierran SLA), lo que cambia es que ahora tienen otro motivo para necesitarlo.
  `_AnswersAnAssignmentBase` conserva `_close_assignment_sla`. [R2.1, R2.2]
- [x] 5.4 `CompleteCleaningTaskUseCase` escribe `CLEANING_COMPLETED` a los destinatarios de R5.1
  antes de su commit. `ValidateCleaningTaskUseCase` escribe `CLEANING_FAILED` **a la limpiadora
  asignada** —resuelta con `UserRepository.get_active_by_id(tenant_id, task.assigned_cleaner_id)`—
  sólo cuando `validation_status = FAILED`, antes de su commit; si no hay limpiadora asignada o
  está de baja, no escribe fila, lo registra y **no falla la validación**. `PASSED` y `WAIVED`
  no escriben nada. [R2.1, R2.2, R2.3, R2.4, R2.5, R5.1, R5.2]
- [x] 5.5 Wiring: `backend/app/cleaning/api/dependencies.py` — `_lifecycle_kwargs` incluye los
  dos puertos, se retiran los `notifications=` sueltos de accept/reject/cancel y se corrige el
  comentario de `get_accept_...` que repite la afirmación enmendada en 5.3.
  `backend/app/cli/seed_demo.py::_cleaning_lifecycle_kwargs` gana los puertos. [R2.1, R2.2]
- [x] 5.6 Tests de caso de uso en `backend/tests/cleaning/` (fixtures actualizadas): completar
  escribe una fila por manager con caída al owner; validar `FAILED` escribe exactamente una fila
  y su destinatario es la limpiadora, **no** el manager; validar `FAILED` sin limpiadora asignada
  y con limpiadora inactiva no escribe y devuelve `200`; `PASSED` y `WAIVED` no escriben; ambas
  filas viajan en el commit del caso de uso. Añadir el test de aislamiento de tenant del módulo.
  [R2.1, R2.2, R2.3, R2.4, R2.5]

## 6. R4 — la recomendación de precio llega a quien la aprueba (D7, D11) <!-- panel: PASS 2026-08-29 -->

- [x] 6.1 TDD en `backend/tests/pricing/test_notifications.py`: `price_recommendation_notification`
  con `related_type="property"`, `related_id` la propiedad, `status=PENDING`, `channel=IN_APP`,
  `sla_deadline_at is None` (R4.6) y `subject`/`body` de constante más identificadores — ni
  precio, ni explicación, ni nombre de la propiedad. [R4.6, R5.3, R5.4, R5.5, R5.6]
- [x] 6.2 Crear `backend/app/pricing/domain/notifications.py` con `RELATED_TYPE_PROPERTY = "property"`
  y `price_recommendation_notification`, con el literal
  `NotificationType.PRICE_RECOMMENDATION.value` escrito a mano y sin parámetro de plazo.
  [R4.1, R5.3, R5.4, R5.5, R5.6, R6.3]
- [x] 6.3 Añadir `pricing/domain/notifications.py` a la fila «`notification_logs.subject`/`body`
  — el contrato vivo» de la tabla de la regla 11 en `sdd/steering/security.md` (misma fila, no
  una nueva). Comprobar que `backend/tests/test_rule11_ownership.py` pasa. [R5.4]
- [x] 6.4 En `backend/app/pricing/application/use_cases.py`,
  `GeneratePriceRecommendationsUseCase` gana `users` + `notifications`; resolución **perezosa y
  memorizada por ejecución** de la unión de `PROPERTY_MANAGER` activos y `TENANT_OWNER` activos
  vía `RoleRecipients.active_holders` (dos consultas la primera vez que alguna propiedad crea
  algo, no por propiedad y no al entrar en `execute`). [R4.4, R5.1]
- [x] 6.5 Dentro de `_price_one_property`, justo antes de su `await self._uow.commit()` y sólo si
  `written.inserted` no está vacío, escribir **una** fila `PRICE_RECOMMENDATION` por destinatario
  para esa propiedad; si `written.inserted` está vacío no se escribe nada. Sin destinatarios: no
  escribe y registra, sin fallar el barrido. [R4.1, R4.2, R4.3, R5.2]
- [x] 6.6 Wiring: `backend/app/pricing/api/dependencies.py` y `backend/app/scheduler/tasks.py`
  pasan los puertos nuevos, de modo que la fila se escribe igual en el job nocturno (sin actor)
  que en `POST /api/v1/price-recommendations/generate` (con actor). [R4.5]
- [x] 6.7 Tests en `backend/tests/pricing/` (fixtures de `tests/pricing/conftest.py`
  actualizadas): una ejecución que crea N recomendaciones para una propiedad escribe **una** fila
  por destinatario y propiedad, no N (R4.1, R4.2); una segunda pasada que sólo actualiza no
  escribe nada (R4.2, R4.3); los destinatarios son la **unión** de managers y owners activos y no
  la caída de R5.1 (R4.4); las dos consultas de destinatarios se hacen **una vez por ejecución**
  aunque haya varias propiedades que crean (usar `backend/tests/sql_counter.py`); la fila nace sin
  `sla_deadline_at` (R4.6); y la ruta HTTP produce la misma fila que el job (R4.5).
  [R4.1, R4.2, R4.3, R4.4, R4.5, R4.6]

## 7. R6 — el censo deja de poder pudrirse (D9) <!-- panel: PASS 2026-08-29 -->

- [x] 7.1 Crear `backend/tests/notifications/test_writer_census.py`: barre el AST de todos los
  `backend/app/**/*.py` **excepto** `notifications/domain/enums.py` y cuenta como escritor de un
  tipo exactamente dos formas, con el *callee* fijado en ambas — (a) llamada cuyo callee es
  literalmente `NotificationLog` con `notification_type=NotificationType.<X>.value`, y (b)
  llamada cuyo callee es literalmente `Escalation` con `notification_type=NotificationType.<X>`
  (sin `.value`), en `notifications/domain/escalation.py`. El fallo nombra fichero y línea, al
  modo de `test_layering.py` y `test_rule11_ownership.py`. [R6.1, R6.3]
- [x] 7.2 El test declara dos listas literales, `WITH_WRITER` (trece) y `WITHOUT_WRITER`
  (`LOCK_ALERT`, `CHECKIN_REMINDER_24H`, `CHECKIN_REMINDER_2H`, `CHECKOUT_REMINDER`), y afirma
  tres cosas: que su unión es exactamente el conjunto de miembros de `NotificationType` —de modo
  que un miembro nuevo que no esté en ninguna de las dos rompe (R6.4)—, que `WITHOUT_WRITER` es
  exactamente esos cuatro (R6.2), y que el conjunto medido coincide con `WITH_WRITER` **en las
  dos direcciones**. [R6.1, R6.2, R6.4]
- [x] 7.3 Verificar a mano que el guardián discrimina de verdad: comprobar que las cuatro
  llamadas a `cancel_sla_deadline` (`cleaning/application/use_cases.py:730`,
  `maintenance/application/use_cases.py:1729`, `:1901`, `:1979`) **no** cuentan como escritor, y
  que `SLA_BREACH` y `TECHNICIAN_NO_RESPONSE` sí cuentan por la vía (b). [R6.3]

## 8. Verification

- [x] 8.1 Suite backend completa en verde desde este worktree:
  `docker compose exec backend uv run pytest`. Anotar la cifra de partida antes de empezar y
  compararla, no un número recordado.
- [x] 8.2 `docker compose exec backend uv run alembic check` en verde — el repo no configura
  linter ni typecheck de backend (no hay `[tool.ruff]`/`[tool.mypy]` en `backend/pyproject.toml`
  ni paso de lint en `.github/workflows/backend-tests.yml`), y esta comprobación es la que
  demuestra lo que D12 promete: ningún modelo movido deja una migración pendiente.
- [x] 8.3 Confirmar el resto de D12 — sin contrato nuevo: `make openapi` deja
  `backend/openapi.json` sin cambios (`git diff --exit-code backend/openapi.json`), no hay
  fichero nuevo en `backend/alembic/versions/`, y `git status` no muestra nada bajo `frontend/`
  ni `locales/`.
- [x] 8.4 Comprobación manual del flujo extremo a extremo con el stack levantado (`make up`,
  `make bootstrap`): reportar una incidencia desde el portal del huésped, dejar que
  `classify_incidents` la clasifique como grave, y verificar en `notification_logs` que existe la
  fila `INCIDENT_CREATED_CRITICAL`/`HIGH` para el manager y que `dispatch_notifications` la pasa
  a `SENT` sin generar ningún candidato de SLA (`sla_deadline_at IS NULL`).
- [x] 8.5 Correr el guardián del censo aislado y leer su salida:
  `docker compose exec backend uv run pytest -q tests/notifications/test_writer_census.py` —
  trece con escritor, cuatro sin. Es la cifra que `sdd/specs/access-notifications.md` heredará al
  archivar, así que se mide, no se recuerda.
