# Tasks: tech-cycle-completion

Orden pensado para que la suite quede verde al final de cada sección. Las dos excepciones
están dichas donde ocurren: el renombrado de la sección 1 es atómico a través de cuatro capas
(partirlo dejaría la suite roja a mitad), y la sección 3 no se puede cerrar sin la migración.

TDD en `domain/` (test primero) por `steering/testing.md`; en `infrastructure/` y `api/` el
test acompaña a la tarea pero no la precede.

## 1. Dominio — el renombrado y la tabla de transiciones <!-- panel: PASS 2026-08-22 -->

- [x] 1.1 **Renombrar `start` → `en_route` de punta a punta, en una sola tarea.** Toca
  `backend/app/maintenance/domain/entities.py` (método `Incident.start` → `Incident.en_route`
  y la clave `"start"` de `_TRANSITIONS` → `"en_route"`, conservando origen `ACCEPTED` y
  destino `IN_PROGRESS`), `backend/app/maintenance/application/use_cases.py`
  (`StartIncidentUseCase` → `EnRouteIncidentUseCase`, su `_STEP` pasa a
  `("en_route", INCIDENT_STARTED, TimelineEventType.TECHNICIAN_EN_ROUTE)`, y `_TIMELINE_TITLES`
  gana la entrada de `TECHNICIAN_EN_ROUTE`), `backend/app/maintenance/api/dependencies.py`
  (`get_start_incident_use_case` → `get_en_route_incident_use_case`) y
  `backend/app/maintenance/api/incidents_router.py` (`POST /{id}/start` →
  `POST /{id}/en-route`, mismo `ExecuteDep`). **No queda alias ni ruta doble.**
  `ResumeWorkUseCase` no se toca: conserva `TECHNICIAN_STARTED`, y con él su escritor.
  Tests: en `backend/tests/maintenance/test_entities.py` la transición renombrada;
  en `test_use_cases.py` que la operación escribe `TECHNICIAN_EN_ROUTE` y que `resume_work`
  sigue escribiendo `TECHNICIAN_STARTED`; en `test_api_incidents.py` y
  `test_api_authorization.py` la ruta nueva, y que `/start` ya no existe (404).
  [R2.1, R2.2, R2.3, R2.4, R2.6] (D4)

- [x] 1.2 **`reject` en la tabla de transiciones y en la entidad.** TDD sobre
  `backend/app/maintenance/domain/entities.py`: entrada `"reject"` con orígenes
  `{ASSIGNED, ACCEPTED}` y destino `CLASSIFIED`, declarada por nombre de operación como el
  resto; método `Incident.reject(*, now)` que llama a `_check_transition("reject")`, pone a
  `NULL` **los tres** campos de la asignación vigente (`assigned_technician_id`, `eta_at`,
  `assignment_note`) y transiciona. Tests en `test_entities.py`: los dos orígenes válidos, la
  limpieza de los tres campos, y que desde terminal sale `IncidentAlreadyClosedError`, desde
  `AWAITING_OWNER_APPROVAL` sale `IncidentBlockedByPendingApprovalError` y desde el resto
  `InvalidIncidentTransitionError` **sin escribir ningún campo**. [R1.1, R1.2, R1.8] (D1, D2)

- [x] 1.3 **`eta_at` en la entidad, con su validación y su limpieza.** TDD sobre
  `entities.py`: campo `eta_at: datetime | None = None`; ayudante privado
  `_apply_eta(eta_at, now)` que retorna sin tocar nada si `eta_at is None`, levanta
  `MaintenanceValidationError` si la marca es naïve (`tzinfo is None or utcoffset() is None`)
  o **estrictamente anterior** a `now`, y sustituye el valor anterior en el resto de casos;
  `accept` y `en_route` pasan a aceptar `eta_at` opcional y lo aplican **después** de
  `_check_transition` y antes de `_transition`; `assign` pone `eta_at = None`
  incondicionalmente, junto a `assignment_note`. Tests: pasado rechazado sin escribir, naïve
  rechazada, futuro escrito, ausencia que preserva, y `assign` que la limpia.
  [R3.1, R3.3, R3.4, R3.5] (D6)

- [x] 1.4 **`materials` en la entidad, con su cota.** TDD sobre `entities.py`: constante
  `MAX_MATERIALS = 2000` junto a `MAX_INCIDENT_TITLE`/`MAX_INCIDENT_DESCRIPTION`; campo
  `materials: str | None = None`; `resolve(..., materials=None)` y
  `require_owner_approval(..., materials=None)` lo escriben **sólo cuando viene** (semántica
  que preserva, no que sustituye), con la misma simetría que ya tiene `final_cost` entre esas
  dos. Ningún cálculo cruzado con `final_cost`. Tests: que el cierre que abre la segunda
  puerta de aprobación conserva `materials`, y que un segundo cierre sin `materials` no lo
  borra. [R4.1, R4.2, R4.3, R4.4] (D7)

## 2. Vocabulario compartido: timeline y auditoría

- [x] 2.1 **`TECHNICIAN_REJECTED`.** Miembro nuevo en
  `backend/app/timeline/domain/enums.py` y su entrada ES/EN en
  `backend/app/timeline/domain/rendering.py` — el test que recorre el enum rompe si falta.
  Verificar en `backend/tests/timeline/` que el catálogo queda completo. [R1.9]

- [x] 2.2 **`INCIDENT_REJECTED` como acción de auditoría.** Constante en
  `backend/app/audit/domain/actions.py` y su entrada en el frozenset `ACTIONS` — que es como
  se llama de verdad; esta tarea decía `ALL_ACTIONS`, corregido en `/sdd:run` (2026-08-22).
  [R5.2]

- [x] 2.3 **`eta_at` entra en `AUDITABLE_FIELDS["INCIDENT"]`**, que pasa de doce a **trece**
  campos (`backend/app/audit/domain/value_objects.py`). `materials` queda **fuera** a
  propósito: nombrarla en un `ChangeSet` debe levantar `AuditContractError`.
  **La cifra `13` del guardián se ajusta AQUÍ, no en la sección 6** — corregido en `/sdd:run`
  (2026-08-22): esta tarea decía lo contrario, y diferirla habría dejado
  `test_free_text_sink_contract.py::test_the_note_is_excluded_by_absence_and_not_by_the_denylist`
  en rojo durante las secciones 3, 4 y 5. La cabecera de este documento declara **dos**
  excepciones al «verde al final de cada sección» —el renombrado de la 1 y la migración de la
  3— y la sección 2 no es ninguna de ellas, así que el `assert len(...) == 12` se mueve con el
  campo que lo invalida. A la 6.2 le queda `SINK_COLUMNS` de tres a cuatro y lo que eso
  arrastra. [R5.1, R4.6]

## 3. Persistencia y migración

- [x] 3.1 **Las dos columnas en el modelo.**
  `backend/app/maintenance/infrastructure/models.py`: `eta_at` `TIMESTAMPTZ` nullable y
  `materials: String(2000)` nullable, ambas `default=None`, junto a `assignment_note`. Test en
  `backend/tests/maintenance/test_models.py` de tipo, nulabilidad y **anchura real en el DDL**.
  [R3.1, R4.1]

- [x] 3.2 **El repositorio las persiste y las rehidrata.**
  `backend/app/maintenance/infrastructure/repositories.py`: `_MUTABLE_INCIDENT_COLUMNS` gana
  `eta_at` y `materials`, el `insert` inicial las incluye y `_to_incident` las devuelve. Tests
  en `test_repositories.py`: ida y vuelta de las dos, y que un `save` posterior las actualiza.
  [R3.1, R4.1]

- [x] 3.3 **La revisión de Alembic, una sola.**
  `backend/alembic/versions/<rev>_tech_cycle_completion.py` encadenada tras `b3f5d1c8a047`
  (la cabeza real medida en `/sdd:run`; el diseño decía `b9d24e70c1af`, que dejó de ser cabeza
  cuando `cleaner-incident-report` archivó `b3f5d1c8a047` encima — ver D9):
  dos `op.add_column` nullable y sin `server_default`, y
  `ALTER TYPE timeline_event_type ADD VALUE IF NOT EXISTS 'TECHNICIAN_REJECTED'` — sin
  `autocommit_block()`, porque la revisión no escribe ninguna fila de timeline. El `downgrade`
  quita las dos columnas y **deja la etiqueta**, con el motivo escrito en el docstring
  (PostgreSQL no sabe retirar un valor de un enum). Sin backfill. Verificar con
  `backend/tests/test_migrations.py`, que recorre la cadena en los dos sentidos.
  [R5.6] (D9)

## 4. Aplicación — los casos de uso

- [x] 4.1 **La mezcla de pasos del técnico deja de tener un diff fijo.**
  `backend/app/maintenance/application/use_cases.py`: `_TechnicianStepUseCase` gana
  `_STEP_AUDITED_FIELDS = ("status", "assigned_technician_id", "eta_at")`, fotografía esos
  tres campos antes de mutar y construye el `ChangeSet` **sólo con los que hayan cambiado**;
  gana `_TAKES_ETA` (por defecto `False`) para decidir si propaga el `eta_at` del cuerpo al
  método de la entidad; y gana el gancho `_timeline_extra`, que lee la foto previa para poder
  poner en el `metadata` del evento un valor que la entidad ya borró. `assignment_note`
  **fuera** de la tupla a propósito. Tests en `test_use_cases.py`: que los cuatro pasos sin
  ETA producen el mismo `ChangeSet` que hoy (`status` y nada más). [R5.2] (D5)

- [x] 4.2 **`RejectIncidentUseCase`.** Subclase de `_TechnicianStepUseCase` con
  `_STEP = ("reject", audit_actions.INCIDENT_REJECTED, TimelineEventType.TECHNICIAN_REJECTED)`,
  y un `_after_step` que (a) cancela el plazo de SLA pendiente de la notificación
  `TECHNICIAN_ASSIGNED` sobre esa incidencia, igual que hace `AcceptIncidentUseCase`, y (b)
  notifica al `PROPERTY_MANAGER` del tenant dejando su `NotificationLog`, **sin
  `sla_deadline_at`**. El constructor de la notificación va en
  `backend/app/maintenance/domain/notifications.py`:
  `NOTIFICATION_TYPE_INCIDENT_REJECTED = "INCIDENT_REJECTED"` como constante de texto (no
  miembro de `NotificationType`) e `incident_rejection_notification(...)` con
  `related_type=RELATED_TYPE_INCIDENT`. `_timeline_extra` pone
  `{"incident_id": …, "technician_id": <el asignatario anterior>}` y el título es constante.
  Tenant sin ningún `PROPERTY_MANAGER` activo: se registra el hecho y el rechazo queda
  aplicado, sin fallar. Tests en `test_use_cases.py` y `test_notifications.py`: SLA cancelado,
  notificación sin plazo, tenant sin manager, `AuditLog` + `TimelineEvent` en la **misma**
  transacción que el cambio y con el actor correcto.
  [R1.3, R1.4, R1.5, R1.9, R5.2] (D1, D3, D11)

- [x] 4.3 **Las dos operaciones que aceptan ETA.** `AcceptIncidentUseCase._TAKES_ETA = True`
  y `EnRouteIncidentUseCase._TAKES_ETA = True`; ninguna otra. Test de que un `eta_at` escrito
  aparece en el `ChangeSet` auditado (por 4.1) y en la entidad guardada. [R3.2]

- [x] 4.4 **`AssignIncidentUseCase` difunde la limpieza de la ETA.** La entidad ya la pone a
  `NULL` (1.3); aquí basta con que el caso de uso audite el campo cuando cambia. Test: asignar
  una incidencia que traía `eta_at` la deja a `NULL` y lo registra. [R3.5]

- [x] 4.5 **`ResolveIncidentUseCase` pasa `materials` por sus dos ramas** — la que cierra y la
  que abre la segunda puerta de aprobación. `materials` NEVER viaja al `metadata` del
  `TimelineEvent` de la resolución. Tests en `test_use_cases.py` de las dos ramas y de la
  ausencia del texto en el `metadata`. [R4.3, R4.6] (D7)

## 5. API — esquemas, rutas y dependencias

- [x] 5.1 **Los esquemas.** `backend/app/maintenance/api/schemas.py`: `IncidentEtaRequest`
  nuevo, **un solo esquema compartido** por `accept` y `en-route`, con
  `eta_at: datetime | None = None` y `extra="forbid"`; `ResolveIncidentRequest` gana
  `materials` opcional anotado `MultiLineText` (`app/core/storable_text.py`) con
  `str_strip_whitespace=True`, `min_length=1` y `max_length=MAX_MATERIALS` importado del
  dominio; `IncidentResponse` gana `eta_at` y `materials`, y su `from_domain` los rellena —
  el mismo esquema sirve detalle y listado, así que los dos campos salen también en el
  paginado. Tests: `422` por campo desconocido en los dos cuerpos, `""` rechazado,
  recorte de espacios, y los dos campos presentes en la respuesta.
  [R3.1, R3.6, R4.1, R4.2] (D7, D8)

- [x] 5.2 **Las rutas.** `backend/app/maintenance/api/incidents_router.py`:
  `POST /api/v1/incidents/{incident_id}/reject` bajo `EXECUTE_INCIDENTS` (`ExecuteDep`), y
  cuerpo **opcional** (`payload: IncidentEtaRequest | None = None`) en `accept` y en
  `en-route`, de modo que un `POST` sin cuerpo siga funcionando. El módulo pasa de trece a
  **catorce** rutas. `summary`/`description` anotados por `steering/documentation.md`. Tests
  en `test_api_incidents.py`: rechazo desde los dos orígenes, `409` con el error correcto
  fuera de orden, y `422` para la ETA en el pasado o sin zona horaria. [R1.6, R3.2, R4.2]

- [x] 5.3 **La dependencia del rechazo.** `backend/app/maintenance/api/dependencies.py`:
  `get_reject_incident_use_case`, cableando `users` y `notifications` como hace
  `get_accept_incident_use_case`. [R1.6]

- [x] 5.4 **Autorización de la ruta nueva.** Tests en
  `backend/tests/maintenance/test_api_authorization.py`: el técnico **asignado** puede, el
  `PROPERTY_MANAGER` puede, y un técnico que no es el asignado recibe el **mismo `404` con el
  mismo cuerpo** que para una incidencia inexistente o de otro tenant. Verificar que
  `backend/tests/test_route_authorization.py` sigue verde y que su allowlist de rutas anónimas
  no cambia. [R1.6, R1.7]

## 6. El censo de la regla 11 y sus dos guardianes

- [x] 6.1 **La fila del censo.** `sdd/steering/security.md`: fila propia para
  `incidents.materials` bajo la **excepción 3**, declarada como texto libre guardado tal cual.
  Los cuatro recuentos de la cabecera se **recuentan contra la tabla**, no se incrementan de
  memoria: 20/27/6/20 pasan a **21 columnas, 28 filas, 6 excepciones, 21 vivas**. Este
  documento y los del change no dicen quién escribe la columna — eso lo dice la tabla.
  [R4.5, R5.4] (D10)

- [x] 6.2 **El guardián del censo.**
  `backend/tests/maintenance/test_free_text_sink_contract.py`: `SINK_COLUMNS` pasa de tres a
  cuatro, con lo que arrastra — aserción de anchura en el DDL, las dos pruebas de que nombrar
  la columna en un `ChangeSet` levanta `AuditContractError` en `diff()` **y** en `redacted()`,
  la de exclusión por ausencia (y no por `REDACTED_FIELDS`), y el mapa `offenders` del censo
  de escritores. (El `assert len(AUDITABLE_FIELDS[...]) == 12` → `13` ya lo hizo la 2.3, por
  el motivo escrito allí; aquí sólo se verifica que sigue puesto.) [R4.6, R5.1, R5.3]

- [x] 6.3 **El guardián de la propiedad.** `backend/tests/test_rule11_ownership.py`:
  `SINK_TERMS` gana `"incidents.materials"`, cualificada con su tabla como
  `incidents.assignment_note`. [R5.4]

## 7. Contrato publicado

- [x] 7.1 **Regenerar y commitear `backend/openapi.json`** con `make openapi`. Debe reflejar
  las catorce rutas del módulo, la desaparición de `/start` y los dos campos nuevos de
  `IncidentResponse`. [R5.5]

- [x] 7.2 **Regenerar y commitear `frontend/lib/api/generated/openapi.d.ts`.** El
  `npm run api:generate` documentado **no funciona tal cual en un worktree enlazado**; usar la
  salida verificada de `sdd/project.md` (`mkdir -p /backend`, `docker compose cp` del
  `openapi.json`, symlink `/frontend` → `/app`, y entonces `npm run api:generate`). [R5.5]

## 8. Verification

- [x] 8.1 Stack levantado en este worktree: `make up` (o `make up PORT_OFFSET=<n>` si hace
  falta navegador). Suite de backend completa en verde:
  `docker compose exec backend uv run pytest`. Si la salida sale colapsada, repetir con
  `rtk proxy` para leer las cifras reales — «PASS (0) FAIL (0)» es una colección fallida, no
  un verde.
- [x] 8.2 `make openapi` no deja diff (el contrato commiteado corresponde al código) y
  `npm run api:check` pasa — con la salida de worktree de 7.2 para el segundo.
- [x] 8.3 Suite de frontend: `docker compose exec -T frontend npm test`. En un worktree hay
  dos ficheros que fallan con `ENOENT` por el bind-mount y **no son de este change**; usar la
  lista de `docker compose cp` de `sdd/project.md` para que la suite pase entera antes de
  dar la cifra por buena.
- [x] 8.4 Ciclo de migración: `alembic upgrade head` y `alembic downgrade -1` sobre una base
  con filas de `incidents` y de timeline, comprobando que ninguna se pierde y que la etiqueta
  del enum sobrevive al `downgrade`.
- [x] 8.5 Comprobación manual del ciclo completo contra la API: `assign` → `accept` (con
  `eta_at`) → `en-route` → `resolve` (con `materials`), y en paralelo `assign` → `reject`,
  verificando que la incidencia vuelve a `CLASSIFIED` sin asignatario, sin ETA y sin nota,
  que el manager tiene su `NotificationLog` sin plazo, y que el timeline muestra
  `TECHNICIAN_EN_ROUTE` y `TECHNICIAN_REJECTED` con sus etiquetas ES/EN.
