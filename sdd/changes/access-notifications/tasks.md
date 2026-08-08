# Tasks: access-notifications

Orden pensado para que el sistema siga funcionando tras cada sección. Las secciones 1-3 encienden
el emisor y cierran la deuda de `cleaning`; 4-6 traen el módulo de acceso; 7 el registro legal.

Convenciones vinculantes: `steering/backend-architecture.md` (regla de dependencia, TDD en
`domain/` con invariante real), `steering/testing.md` (test de tenant isolation por módulo,
transiciones inválidas testeadas), `steering/security.md` (reglas 1, 2, 3, 4, 9, 11),
`steering/documentation.md` (OpenAPI + `.env.example`).

## 1. Puerto de envío y adapters de canal <!-- panel: PASS 2026-08-08 (con la 2) -->

- [x] 1.1 `backend/app/notifications/domain/results.py` (nuevo): `NotificationErrorCode` (enum
  cerrado: `ADAPTER_ERROR`, `INVALID_RECIPIENT`, `TIMEOUT`, `NO_ADAPTER_FOR_CHANNEL`,
  `MAX_ATTEMPTS_EXCEEDED`) y `NotificationResult` (frozen dataclass: `delivered: bool`,
  `error_code: NotificationErrorCode | None`, `provider_message_id: str | None`). Test en
  `backend/tests/notifications/test_results.py` que demuestra que el resultado **no admite** texto
  libre de error — el tipo es el que hace cumplir la regla 11 (design D8). [R4]
- [x] 1.2 `backend/app/notifications/domain/ports.py` (nuevo): `NotificationAdapter` (`Protocol`,
  `async def send(*, recipient_contact, subject, body, channel) -> NotificationResult`). Sin
  imports de infra — `backend/tests/test_layering.py` ya lo verifica por glob. [R4]
- [x] 1.3 `backend/app/notifications/infrastructure/adapters.py` (nuevo): `ConsoleEmailAdapter`
  (log estructurado, nunca `print`), `MockWhatsAppAdapter`, `InAppNotificationAdapter` (no-op que
  devuelve éxito, design D5) y `adapter_registry()` que mapea `EMAIL`/`CONSOLE`/`WHATSAPP`/`IN_APP`
  y **deja `PUSH` fuera a propósito**. Tests en
  `backend/tests/notifications/test_adapters.py`: los tres entregan, el registro no resuelve
  `PUSH`, y ningún adapter registra en log el `body` recibido. [R4]
- [x] 1.4 `backend/app/notifications/domain/repositories.py`: añadir al puerto
  `list_pending(tenant_id, limit) -> Sequence[NotificationLog]` y
  `record_attempt(tenant_id, log_id, *, status, attempts, sent_at, last_error) -> None`, con
  docstrings que citen (no reformulen) la regla 11 para `last_error`. Implementación en
  `backend/app/notifications/infrastructure/repositories.py` con filtro explícito de `tenant_id` y
  `CrossTenantWriteError` en la escritura, igual que `mark_breached`. Tests en
  `backend/tests/notifications/test_repositories.py` incluyendo el caso cross-tenant. [R4]

## 2. El emisor: caso de uso, job y lectura in-app <!-- panel: PASS 2026-08-08 -->

- [x] 2.1 `backend/app/core/config.py`: `notification_max_attempts: int = 3` y
  `notification_batch_size: int = 100`, con comentario explicando por qué no hay backoff (design
  D4). Reflejar ambas en `.env.example` con comentario y sin valor sensible. Test en
  `backend/tests/test_config.py`. [R4]
- [x] 2.2 `backend/app/notifications/application/use_cases.py`: `DispatchPendingNotificationsUseCase`
  — por cada fila `PENDING`: incrementa `attempts` y comitea, llama al adapter del canal, escribe el
  resultado y comitea (design D4). `SENT` + `sent_at` al entregar; `PENDING` + `last_error`
  estructurado al fallar; `FAILED` al superar `notification_max_attempts`; `SKIPPED` cuando el
  canal no tiene adapter. Devuelve un `DispatchReport` con el desglose. Tests con fakes en memoria
  en `backend/tests/notifications/test_dispatch.py`: entrega, fallo con reintento, agotamiento a
  `FAILED`, canal sin adapter a `SKIPPED`, y que **nunca** se marca `SENT` sin confirmación del
  adapter. [R4]
- [x] 2.3 `backend/tests/notifications/test_dispatch_isolation.py`: el emisor de un tenant no lee ni
  escribe filas de otro, y `recipient_contact` de otro tenant no recibe nada (R4.7 + regla 1 de
  `steering/security.md`). [R4]
- [x] 2.4 `backend/app/scheduler/schedule.py` y `backend/app/scheduler/tasks.py`: tarea
  `dispatch_notifications` cada minuto, con el mismo `_guarded` + `task_lock` que los cuatro
  existentes, y docstring que declare la divergencia con PRD §8.3 (design D3). Test en
  `backend/tests/scheduler/` de que el lock perdido devuelve `skipped` y no envía. [R4]
- [x] 2.5 `backend/app/notifications/application/use_cases.py`: `ListOwnNotificationsUseCase` — solo
  las filas cuyo `recipient_user_id` es el del token, paginadas con el envelope de PRD §23. [R4]
- [x] 2.6 `backend/app/notifications/api/{__init__,router,schemas,dependencies}.py` (nuevos):
  `GET /api/v1/notifications`. El esquema de salida **no** expone `recipient_contact` de terceros ni
  `last_error`. Registrar el router en `backend/app/main.py`. Tests en
  `backend/tests/notifications/test_api.py`: paginación, que un usuario no ve las de otro usuario
  del mismo tenant, y que no ve las de otro tenant. [R4]

## 3. Cierre del SLA de asignación (deuda heredada de `cleaning` R6.4) <!-- panel: PASS 2026-08-08 -->

<!--
Desviaciones de esta sección, para que se lean como decisiones:
- 1.4 pedía `CrossTenantWriteError` en las escrituras nuevas. `record_attempt` y
  `cancel_sla_deadline` toman un **id**, no una entidad, así que no hay tenant de entidad con el
  que comparar: su aislamiento es el predicado `tenant_id` del UPDATE más la comprobación de
  rowcount. El revisor de tenancy lo juzgó equivalente y no un hueco.
- 3.4 pedía el test extremo a extremo en `tests/notifications/test_escalate_slas.py`. Vive en
  `tests/cleaning/test_assignment_notifications.py` porque necesita la API de limpieza para
  producir la fila de asignación; ponerlo en el otro fichero habría exigido fabricarla a mano,
  que es justo lo que el test quiere no dar por supuesto.
-->


- [x] 3.1 `backend/app/notifications/domain/repositories.py` +
  `infrastructure/repositories.py`: `cancel_sla_deadline(tenant_id, *, related_type, related_id,
  notification_type) -> int`, que pone `sla_deadline_at = NULL` y **no toca** `status`,
  `sla_breached`, `subject`, `body` ni `recipient_contact` (design D7). Cero filas es un caso
  normal, no un error — al contrario que `mark_breached`. Tests en
  `backend/tests/notifications/test_repositories.py`: anula la fila correcta, es idempotente, no
  cruza tenants y no altera ninguna otra columna. [R5]
- [x] 3.2 `backend/app/cleaning/application/use_cases.py`: `AcceptCleaningTaskUseCase` y
  `RejectCleaningTaskUseCase` reciben `notifications: NotificationLogRepository` y llaman
  `cancel_sla_deadline` con `related_type=RELATED_TYPE_CLEANING_TASK`, `related_id=task.id`,
  `notification_type=CLEANING_TASK_ASSIGNED`, **antes del commit** que ya hacen. Actualizar
  `backend/app/cleaning/api/dependencies.py`. [R5]
- [x] 3.3 `backend/tests/cleaning/test_assignment_notifications.py`: aceptar cierra el plazo;
  rechazar cierra el plazo; una tarea sin fila de asignación responde sin error; una tarea cuyo
  plazo ya está cerrado no cambia nada (R5.3). [R5]
- [x] 3.4 `backend/tests/notifications/test_escalate_slas.py`: test de extremo a extremo del hueco
  que este change cierra — fila `SENT` con plazo vencido **sí** escala; la misma fila tras
  `cancel_sla_deadline` **no** produce ningún `SLA_BREACH` en ejecuciones posteriores (R5.4). [R5]

## 4. Dominio de acceso: invariantes, puertos y repositorio

- [x] 4.1 (TDD) `backend/tests/access/test_entities.py` primero, luego
  `backend/app/access/domain/entities.py`: métodos `register_manual_code`, `mark_external_managed`,
  `mark_delivered`, `revoke`, `expire` que protegen la máquina de estados de design D14. **Todas
  las transiciones, incluidas las inválidas** (DoD §28.19): las inválidas levantan
  `InvalidAccessTransitionError`. [R2]
- [x] 4.2 `backend/app/access/domain/masking.py` (nuevo): `mask_access_code(code) -> str` con la
  forma `****XX` de la regla 4. Test que cubre códigos cortos, largos, vacíos y con espacios, y que
  demuestra que el valor original **no** aparece en la salida. [R2]
- [x] 4.3 `backend/app/access/domain/exceptions.py` (nuevo): `AccessRecordNotFoundError`,
  `InvalidAccessTransitionError`. [R2, R3]
- [x] 4.4 `backend/app/access/domain/repositories.py` (nuevo): puerto `AccessRecordRepository`
  (`get`, `list` con filtros y paginación, `get_by_reservation`, `add`, `save`,
  `list_reservations_missing_records`), `tenant_id` en cada método como en
  `app/auth/domain/ports.py`. [R1, R3]
- [x] 4.5 `backend/app/access/domain/ports.py` (nuevo): `AccessProviderAdapter` con las tres
  operaciones de PRD §15 (design D12). [R2]
- [x] 4.6 `backend/app/access/infrastructure/repositories.py` (nuevo):
  `SqlAlchemyAccessRecordRepository`, con `tenant_id` explícito en toda sentencia y
  `CrossTenantWriteError` en las escrituras. Tests de integración en
  `backend/tests/access/test_repositories.py`, incluido el de tenant isolation obligatorio por
  DoD §28.18. [R1, R3]
- [x] 4.7 `backend/app/access/infrastructure/adapters.py` (nuevo): `ManualAccessAdapter` y
  `MockAccessAdapter` (código demo `****23`). Tests en
  `backend/tests/access/test_adapters.py` que verifican la sustituibilidad (Liskov: mismas
  excepciones, misma forma de retorno) y que **ninguno devuelve ni registra el código en claro**
  (design D9). [R2]

## 5. Casos de uso y API de acceso

- [x] 5.1 `backend/app/audit/domain/actions.py`: `ENTITY_ACCESS_RECORD` y las acciones
  `ACCESS_CODE_REGISTERED`, `ACCESS_MARKED_EXTERNAL`, `ACCESS_DELIVERED`, `ACCESS_REVOKED`, con
  comentario citando la regla 9 (que nombra `AccessRecord` explícitamente). Añadirlas a
  `ENTITY_TYPES`/`ACTIONS`. [R2]
- [x] 5.2 (**Corregido tras el panel de feature**: los tests de los casos de uso NO viven en
  `backend/tests/access/test_use_cases.py`, que no existe. La proyección se prueba contra base
  real en `test_repositories.py` y las transiciones extremo a extremo en `test_api.py` — con
  fakes se habría probado el filtro del fake.)
  `backend/app/access/application/use_cases.py` (nuevo):
  `RegisterManualAccessCodeUseCase`, `MarkAccessExternallyManagedUseCase`,
  `MarkAccessDeliveredUseCase`. Cada uno: carga dentro del tenant, muta la entidad, persiste,
  escribe `TimelineEvent` (`ACCESS_CODE_MANUAL_ADDED` / `..._CREATED_EXTERNAL` / `..._DELIVERED`)
  vía `TimelineEventFactory`, proyecta `reservations.access_status` (design D1) y escribe
  `AuditLog` con `ChangeSet` — **el código en claro nunca entra en el `ChangeSet`**. Un solo
  `commit()` por caso de uso. Tests con fakes en `backend/tests/access/test_use_cases.py`. [R2]
- [x] 5.3 `backend/tests/access/test_repositories.py`: la proyección a `reservations.access_status`
  acompaña cada transición y `REVOKED` proyecta `NOT_REQUIRED` con el `ASSUMPTION` documentado
  (design D1). Un caso por cada valor del enum. [R1, R2]
- [x] 5.4 `backend/app/access/application/use_cases.py`: `ListAccessRecordsUseCase` y
  `GetAccessRecordUseCase`, con el envelope paginado y las mismas cotas de `page`/`per_page` que
  `reservations`. [R3]
- [x] 5.5 `backend/app/access/api/{__init__,router,schemas,dependencies,errors}.py` (nuevos): los
  cinco endpoints de la tabla del design. Los esquemas de salida exponen `code_masked` y **no**
  tienen campo para el código en claro. Registrar el router en `backend/app/main.py`. [R2, R3]
- [x] 5.6 `backend/tests/access/test_api.py`: RBAC por rol (lectura vs escritura, `403` para el rol
  sin permiso de escritura), `404` idéntico para «no existe» y «existe en otro tenant» (R3.3),
  `409` en transición inválida (R2.5), y que ninguna respuesta contiene el código en claro
  (R2.6). [R2, R3]

## 6. Reconciliador de accesos y estado inicial de la reserva

- [x] 6.1 `backend/app/access/application/use_cases.py`: `ProvisionAccessRecordsUseCase` (design
  D2) — por tenant: crea el `AccessRecord` `PENDING` que falte a cada reserva confirmada, escribe
  `ACCESS_CODE_PENDING` en el timeline, fija `reservations.legal_registration_status =
  PENDING_GUEST_DATA` (R6.2), revoca los de reservas canceladas y expira los de `valid_to`
  vencido. Actor `SYSTEM`; la fila de `AuditLog` va sin actor (design D2). [R1, R6]
- [x] 6.2 `backend/tests/access/test_provisioning.py`: crea el que falta; **no** crea un segundo si
  ya existe ni escribe un segundo evento de timeline (R1.3); revoca al cancelar (R1.4); es
  idempotente en dos pasadas seguidas; no cruza tenants. [R1]
- [x] 6.3 `backend/app/scheduler/schedule.py` y `tasks.py`: tarea `provision_access_records` cada
  5 minutos, con `_guarded` + `task_lock`, y docstring que declare la divergencia con PRD §8.3.
  Test del camino `skipped_locked`. [R1]
- [x] 6.4 Comprobar con `EXPLAIN` sobre el Postgres local si la consulta de
  `list_reservations_missing_records` usa índice por `(tenant_id, status)`; si no, migración
  Alembic que lo añada. Si sí lo usa, dejar constancia en el design de que no hizo falta. [R1]

## 7. SES.Hospedajes: documento del huésped y registro legal

- [x] 7.1 (TDD) `backend/tests/guests/test_legal_registration.py` primero, luego
  `backend/app/guests/domain/legal_registration.py`: servicio puro que decide `READY_TO_SUBMIT`
  sobre la unión huésped + reserva con los **ocho** campos de PRD §17 (design D11). Cubrir cada
  campo ausente por separado. [R6]
- [x] 7.2 `backend/app/guests/domain/ports.py` (nuevo): `SESHospedajesAdapter` (`submit_guest`,
  `get_submission_status`), `LegalSubmission` y `SubmissionResult`. `LegalSubmission` se construye
  desde el huésped y la reserva y es el **único** transporte del documento en claro. [R6]
- [x] 7.3 `backend/app/guests/infrastructure/adapters.py` (nuevo): `MockSESHospedajesAdapter`
  marcado `EXTERNAL_DEPENDENCY`, con camino de éxito y camino de fallo forzable para el test de
  R6.5. Tests en `backend/tests/guests/test_ses_adapter.py`. [R6]
- [x] 7.4 `backend/app/guests/domain/entities.py` + `infrastructure/repositories.py`: escritura y
  lectura del documento cifrado con `app/core/crypto.py` (regla 3). El puerto gana
  `set_document`, `get_document` y `get_full` — y las lecturas existentes siguen devolviendo
  `GuestSummary` sin documento. Tests en `backend/tests/guests/test_repositories.py`: el valor en
  la columna no es el texto plano, y `GuestSummary` no lo transporta. [R7]
- [x] 7.5 `backend/app/audit/domain/actions.py`: `ENTITY_GUEST` y las acciones
  `GUEST_DOCUMENT_UPDATED`, `GUEST_DOCUMENT_READ`, `LEGAL_REGISTRATION_SUBMITTED`. [R6, R7]
- [x] 7.6 `backend/app/guests/application/use_cases.py` (nuevo): `SetGuestDocumentUseCase`
  (cifra, mueve `document_status` a `PROVIDED`, reevalúa `READY_TO_SUBMIT`, audita con `ChangeSet`
  que registra **qué campos** cambiaron y nunca sus valores) y `ReadGuestDocumentUseCase`
  (descifra y audita el acceso, regla 9). Tests en
  `backend/tests/guests/test_use_cases.py` que verifican que el `ChangeSet` no contiene el número
  ni la fecha de nacimiento (R7.4). [R6, R7]
- [x] 7.7 (**Los «tres caminos» solo eran dos hasta el panel de feature**: nadie construía
  `MockSESHospedajesAdapter(fail=True)`, así que la rama de fallo funcionaba y no la guardaba
  ningún test. Cubierta ahora en `test_a_rejected_submission_fails_the_stay_and_alerts_the_managers`.)
  `backend/app/guests/application/use_cases.py`: `SubmitLegalRegistrationUseCase` — `409`
  si la reserva no está en `READY_TO_SUBMIT` (R6.6, sin invocar el adapter); al éxito
  `SUBMITTED` + `TimelineEvent` `LEGAL_REGISTRATION_SUBMITTED`; al fallo `FAILED` + notificación
  `PENDING` al manager y **sin** evento de submission (R6.5). Tests de los tres caminos. [R6]
- [x] 7.8 `backend/app/guests/api/{__init__,router,schemas,dependencies,errors}.py` (nuevos) y
  el endpoint de submit en el router de reservas o uno propio: los tres endpoints de la tabla del
  design. Registrar en `backend/app/main.py`. [R6, R7]
- [x] 7.9 `backend/tests/guests/test_api.py`: solo `TENANT_OWNER` y `PROPERTY_MANAGER` ven el
  documento completo; **`SUPER_ADMIN` recibe `403`** junto a `CLEANER` y `TECHNICIAN`
  (`test_a_role_without_the_permission_never_sees_a_document`). R7.2 es una **prohibición** —
  «no devolver a quien no sea…»— y retirar es más estrecho que su techo, así que no se
  incumple; el porqué está en D13 y en `policy.py`. Además: ningún listado devuelve el número
  (R7.1); `404` idéntico cross-tenant; y toda lectura del documento deja su fila de `AuditLog`
  (R7.3). Corregido en la segunda ronda del panel de feature — era la **cuarta** copia de la
  redacción superada, y sobrevivió a la ronda que arregló las otras tres. [R7]
- [x] 7.10 Tenant isolation del módulo `guests`, obligatorio por DoD §28.18. **No en un fichero
  propio** (`test_isolation.py` no existe): vive en `backend/tests/guests/test_api.py`
  —`test_a_neighbours_guest_is_the_same_404_as_a_missing_one`,
  `test_a_write_to_a_neighbours_guest_is_also_a_404`,
  `test_a_neighbours_reservation_cannot_be_submitted`— porque lo que hay que demostrar aquí es el
  `404` **idéntico** al inexistente, y eso solo se puede afirmar comparando dos respuestas HTTP.
  Corregido tras el panel de feature, que encontró la tarea citando un fichero inexistente. [R6, R7]

## 8. Contrato de API y documentación

- [x] 8.1 Anotar `summary`/`description`/`response_model` en los routers nuevos y regenerar el
  contrato: `make openapi` y `cd frontend && npm run api:generate`. Commitear
  `backend/openapi.json` **y** `frontend/lib/api/generated/openapi.d.ts` — son las dos mitades del
  mismo puente (`steering/documentation.md`). [R3, R4, R6]
- [x] 8.2 `.env.example`: las dos variables nuevas con comentario y sin valor. [R4]
- [x] 8.3 `README.md` raíz: mencionar los dos jobs nuevos del beat y los módulos que ganan API. [R1, R4]
- [x] 8.4 `docs/celery-jobs.md`: añadir `dispatch_notifications` y `provision_access_records` a la
  tabla de jobs con su cadencia y su propósito. [R1, R4]
- [x] 8.5 `docs/cleaning.md`: la página afirma que el escalado de SLA está inerte «porque nada
  marca las notificaciones como enviadas». Deja de ser cierto con este change — corregirlo y
  enlazar el cierre de plazo al responder. [R5]
- [x] 8.6 `docs/access-notifications.md` (nueva): cómo se opera la entrega de notificaciones, el
  registro de accesos y el registro legal — orientada a *cómo se usa*, sin duplicar las specs EARS.
  [R2, R3, R4, R6]
- [x] 8.7 Diagramas comprobados, **ninguno regenerado y ninguno obsoleto**. El ER
  (`2026-08-06_autohost-er-entidades.png`) se genera desde la metadata de SQLAlchemy y este
  change no añade ni una tabla ni una columna, así que saldría idéntico. El hexagonal
  (`2026-07-13_autohost-hexagonal-dominios.png`) dibuja los **dominios**, no las capas de cada
  uno: `access`, `guests` y `notifications` ya estaban en él y lo que cambia es que ahora tienen
  `application/`+`api/`, que el diagrama no representa. Regenerar por regenerar habría metido un
  fichero binario idéntico en el diff. [R1, R4]

## 9. Verification

- [x] 9.1 Suite completa del backend: `docker compose exec backend uv run pytest` (con el stack
  del worktree levantado con `make up`; ver «Worktree bootstrap» en `sdd/project.md`).
- [x] 9.2 Sin migraciones pendientes: `docker compose exec backend uv run alembic check`.
- [x] 9.3 Contrato al día: `make openapi` y `cd frontend && npm run api:generate` no dejan diff.
- [x] 9.4 Frontend sin romper por el contrato nuevo: 328/328. Nota operativa: desde un worktree
  hay que montar la raíz del repo (`-v $(pwd)/.github:/.github -v $(pwd)/docker-compose.yml:/docker-compose.yml`),
  porque `build-identity-contract.test.ts` lee ficheros de la raíz y en el contenedor `..` es `/`.
  Sin eso falla ese único test por entorno, no por código.
- [x] 9.5 Comprobación manual del flujo extremo a extremo con el stack levantado: crear una
  notificación `PENDING`, correr `dispatch_notifications`, verificar `SENT` + `sent_at`; aceptar
  una limpieza asignada y verificar que su `sla_deadline_at` queda a `NULL` y que
  `check_sla_breaches` no la escala.
- [x] 9.6 **OQ3 medido** y anotado en `BLOCKED.md`: la relación es **1:1** — de 7 filas con plazo
  vencido, 0 candidatas antes del emisor y 7 después, con `breached=7`. El total real de dev no es
  medible desde el worktree (base vacía); lo que queda registrado es la fórmula y la consulta.
