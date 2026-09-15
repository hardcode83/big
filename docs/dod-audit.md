# Auditoría del Definition of Done del MVP (PRD §28)

**Fecha de la medición: 2026-09-13.** Change: `hardening-release`, sección 6 (tareas 6.1–6.3, R5).

Este documento es un **acta**, no una página de capability. Su valor entero está en que una
lectura futura no tenga que volver a auditar desde cero: cada uno de los 20 ítems de PRD §28
lleva aquí su evidencia con nombre y apellidos —fichero, símbolo, test, comando— y, cuando no se
cumple, **lo dice**. Un DoD que se da por cerrado sin medirlo no es un DoD; el propósito de R5 es
precisamente sustituir la suposición por una medición fechada.

**Qué se audita y qué no.** Esta sección **no construye** capacidades: mide las que hay. Donde
encuentra un hueco real de producto —no de test— lo deja declarado como incumplido, con su razón,
en vez de cerrarlo a escondidas o de estirar un test vecino hasta que parezca evidencia.

## Veredicto global

| Resultado | Ítems |
|---|---|
| **CUMPLE** | 17 — #1, #3, #4, #5, #6, #7, #9, #10, #11, #12, #13, #14, #15, #16, #18, #19, #20 |
| **PARCIAL** | 3 — **#2** (el dashboard no se refresca solo), **#8** (la propietaria no puede crear una incidencia), **#17** (16 de 53 tipos de evento no tienen escritor) |
| **NO CUMPLE** | 0 |

Los tres parciales son **huecos de producto, no de test**: ninguno se cierra escribiendo un test,
y ninguno está en el alcance de `hardening-release`. Se declaran aquí para que la decisión de
cerrarlos —o de enmendar la redacción del PRD— sea explícita y de alguien.

## Tabla de los 20 ítems

| # | Ítem (PRD §28) | Veredicto | Evidencia |
|---|---|---|---|
| 1 | El propietario puede hacer login | CUMPLE | `backend/app/auth/application/use_cases.py::LoginUseCase`; `backend/tests/auth/test_api.py::test_login_returns_a_token_pair`, `::test_the_whole_flow_login_me_refresh_logout`; E2E `frontend/e2e/login.spec.ts` |
| 2 | Property cards con estado operacional **en tiempo real** y código de colores | **PARCIAL** | Colores y estado: `frontend/components/property-state-badge.tsx::STATE_COLOR_GROUP`; `frontend/components/property-state-badge.test.tsx` (`it.each` sobre los 11 estados); backend `backend/tests/dashboard/test_api.py::test_the_operational_state_is_the_canonical_literal`. **«Tiempo real» no se cumple literalmente** — ver §#2 abajo |
| 3 | Detalle de propiedad con timeline | CUMPLE | `backend/app/dashboard/application/use_cases.py::GetPropertyDashboardUseCase`; `backend/app/timeline/api/router.py::get_property_timeline`; `frontend/features/dashboard/components/detail/property-detail-view.test.tsx::"renders the detail sections and timeline on success"` |
| 4 | Reservas manuales y/o vía MockPMSAdapter o CSV | CUMPLE (3/3 vías) | Manual: `backend/tests/reservations/test_api.py::TestCreate::test_it_creates_and_derives_the_computed_fields`. MockPMS: `backend/tests/integrations/test_sync.py::test_it_imports_the_seed_reservations`. CSV: `backend/tests/integrations/test_import_csv.py::TestHappyPath::test_it_imports_a_valid_file_and_reports_it` |
| 5 | El checkout crea automáticamente una CleaningTask (job Celery) | CUMPLE | `backend/app/scheduler/tasks.py::process_checkouts` → `ProvisionCleaningTaskUseCase`; `backend/tests/cleaning/test_provisioning.py::test_checkout_creates_the_cleaning_task`, `::test_the_task_and_the_transition_share_the_transaction`, `::test_a_second_run_does_not_create_a_second_task` |
| 6 | La limpiadora acepta, completa el checklist y sube fotos | CUMPLE | `backend/tests/cleaning/test_tasks_api.py::test_the_whole_flow_from_assignment_to_completion` (asignar → aceptar → empezar → checklist → foto → cerrar); E2E `frontend/e2e/cleaning.spec.ts::"3.2 el CLEANER acepta, completa el checklist, sube las fotos requeridas y cierra la limpieza"` |
| 7 | Completar la limpieza cambia el estado según contexto | CUMPLE | `backend/app/properties/domain/state_resolution.py::ContextualStateResolver.after_cleaning_completion`; `backend/tests/properties/test_state_resolution.py::test_cleaning_completion_contextual_destinations` (los tres destinos); sobre HTTP `backend/tests/cleaning/test_tasks_api.py::test_completion_with_a_future_booking_is_ready_for_next_guest` y `::test_completion_with_a_booking_arriving_today_awaits_checkin` |
| 8 | **Huésped/limpiadora/propietario** puede crear una incidencia | **PARCIAL (2 de 3)** | Huésped: `backend/tests/maintenance/test_report_guest_incident.py::test_it_creates_the_incident_from_the_stay_the_token_resolved`. Limpiadora: `backend/tests/cleaning/test_task_incident_api.py::test_the_created_row_is_sealed_cleaner_and_linked_to_the_task`. **Propietaria: no existe** — ver §#8 abajo |
| 9 | MockAIAdapter clasifica severity y category de la incidencia | CUMPLE (con divergencia de nombre) | La capacidad está entera: `backend/app/maintenance/infrastructure/classifier.py::RuleBasedIncidentClassifier`; `backend/tests/maintenance/test_classifier.py::test_it_recognises_each_category` (las 13 categorías, `category` y `severity`); job `backend/tests/scheduler/test_classify_incidents.py::test_it_classifies_what_is_pending`. **Pero no la escribe `MockAIAdapter`** — ver §#9 abajo |
| 10 | El técnico acepta y resuelve una incidencia | CUMPLE | `backend/app/maintenance/application/use_cases.py::AcceptIncidentUseCase`, `::ResolveIncidentUseCase`; `backend/tests/maintenance/test_api_incidents.py::test_the_happy_path_of_every_route`; `backend/tests/maintenance/test_use_cases.py::test_the_technician_walks_the_whole_cycle`; E2E `frontend/e2e/incident.spec.ts::"4.2 …"` |
| 11 | Incidencias CRITICAL ponen la vivienda en rojo | CUMPLE | Estado: `_POLICY` manda `INCIDENT_CRITICAL` → `CRITICAL_INCIDENT` **desde los ocho estados que admiten el trigger** (`source_states_for(INCIDENT_CRITICAL)`; quedan fuera `CRITICAL_INCIDENT` —ya está ahí—, `BLOCKED_BY_OWNER` y `OUT_OF_SERVICE`); `backend/tests/maintenance/test_use_cases.py::test_classifying_by_triage_fires_the_same_trigger_as_the_automatic_path`. Color: `CRITICAL_INCIDENT: "red"` es el **único** estado rojo (`frontend/components/property-state-badge.tsx:54`). Las dos mitades juntas: `frontend/e2e/incident.spec.ts::"4.2 …"` comprueba el badge rojo mientras la CRITICAL sigue abierta y que deja de serlo al cerrarla |
| 12 | OwnerApproval para gastos > umbral configurado | CUMPLE | Umbral: `backend/app/tenants/domain/entities.py::TenantConfig.owner_approval_threshold_eur`; regla en la entidad: `backend/app/maintenance/domain/entities.py::Incident.needs_owner_approval`; `backend/tests/maintenance/test_use_cases.py::test_triage_above_the_threshold_opens_the_budget_gate` y su gemelo negativo `::test_triage_below_the_threshold_creates_nothing`; segunda puerta `::test_a_cost_over_the_threshold_opens_the_second_gate`; E2E `frontend/e2e/incident.spec.ts::"4.3 …"` |
| 13 | El estado del acceso se rastrea manualmente (AccessRecord) | CUMPLE | `backend/app/access/domain/entities.py::AccessRecord` (`register_manual_code`, `mark_external_managed`, `mark_delivered`, `revoke`, `expire`); `backend/tests/access/test_entities.py::test_the_whole_transition_matrix`; sobre HTTP `backend/tests/access/test_api.py::test_the_full_operator_path_ends_in_delivered` |
| 14 | Conversaciones con respuesta automática de MockAIAdapter | CUMPLE | `backend/app/messaging/infrastructure/ai.py::MockAIAdapter`; `backend/app/messaging/application/use_cases.py::ProcessInboundGuestMessageUseCase`; `backend/tests/messaging/test_api_conversations.py::test_a_guest_message_runs_the_whole_pipeline` (los remitentes guardados son exactamente `{GUEST, AI}`). La **respuesta humana sí sale** desde 2026-09-11 — ver §#14 abajo |
| 15 | Recomendaciones de precio por reglas configuradas | CUMPLE | `backend/app/pricing/application/use_cases.py::GeneratePriceRecommendationsUseCase`; `backend/tests/pricing/test_use_cases.py::test_a_tenant_wide_rule_prices_every_property_without_one_of_its_own` y, como prueba de que la regla es el motor, `::test_a_property_without_an_applicable_rule_is_skipped_without_failing` |
| 16 | El statement mensual se genera y se exporta a CSV | CUMPLE | `backend/app/statements/application/use_cases.py::GenerateOwnerStatementUseCase`, `::ExportOwnerStatementCsvUseCase`; `backend/tests/statements/test_use_cases.py::TestGenerate::test_creates_when_called_with_actor` y `::TestExports::test_csv_returns_header_and_in_statement_rows`; a nivel de bytes `backend/tests/statements/test_csv.py::test_csv_has_exact_header_rows_and_utf8`. Matiz sobre **qué lleva** el CSV en §#16 |
| 17 | **Todas** las acciones relevantes generan TimelineEvents | **PARCIAL** | Mecanismo único y sólido: `backend/app/timeline/domain/services.py::TimelineEventFactory.create`; censo del catálogo `backend/tests/timeline/test_rendering.py::test_the_catalogue_covers_the_whole_enum_and_nothing_else`. **Pero 16 de los 53 tipos carecen de escritor** — ver §#17 abajo |
| 18 | Tenant isolation implementado y testeado | CUMPLE | **18 de 18 dominios** con test de aislamiento tenant A / tenant B — tabla completa en §28.18. Más las tres guardas transversales: `backend/tests/test_tenant_filter.py` (13), `backend/tests/test_unscoped_reads.py` (4), `backend/tests/test_session_marking.py` (9) |
| 19 | Los tests cubren todas las transiciones de la state machine | CUMPLE | Exhaustivo y **derivado del propio `_POLICY`**, no de una lista a mano — tabla y aritmética en §28.19. `docker compose exec backend uv run pytest tests/properties/test_state_machine.py` → **643 passed, 41 skipped** |
| 20 | La app corre localmente con un solo `docker compose up` | CUMPLE | Un `docker-compose.yml` con los siete servicios (`postgres`, `redis`, `migrate`, `backend`, `worker`, `beat`, `frontend`) y el objetivo `up` del `Makefile`. Construido por `local-environment`/`infra-scaffold`; **no se reconstruye aquí**. Evidencia de ejecución: la corrida de la tarea 7.3 de este mismo change |

---

## Detalle de los ítems que no cumplen del todo

### #2 — «en tiempo real»

La mitad del ítem que trata del **estado** y del **código de colores** está cumplida y bien
testeada: la API emite el literal canónico y no el color (el mapeo es del cliente, por diseño), y
`property-state-badge.test.tsx` recorre los 11 estados contra los cinco grupos de PRD §9.1.

Lo que no se cumple literalmente es **«en tiempo real»**. El dashboard no se refresca solo:

- `frontend/lib/query/query-client.ts` fija `staleTime: 60_000` y `refetchOnWindowFocus: false`.
- `frontend/features/dashboard/hooks/use-dashboard-data.ts::useDashboardCards` **no** declara
  `refetchInterval`.
- No hay SSE ni WebSocket en ninguna parte. El propio código lo dice, en
  `frontend/features/guest-portal/hooks/use-conversation.ts`: *«No WebSocket and no SSE: the
  project has no realtime surface and this change does not open one.»*

**Y el proyecto sí tiene el idioma para hacerlo**, que es lo que convierte esto en una omisión y no
en una limitación: `frontend/features/notifications/hooks/use-unread-count.ts` y
`frontend/features/guest-portal/hooks/use-conversation.ts` usan `refetchInterval` +
`refetchIntervalInBackground: false`. La tarjeta se actualiza al navegar, al reintentar o tras una
mutación — no por sí sola.

**Lectura estricta**: PARCIAL. **Lectura laxa** («el estado que se muestra es el estado operacional
vivo que calcula el backend»): cumple. Se declara PARCIAL porque la redacción del PRD dice «en
tiempo real» y el usuario que deje el dashboard abierto no verá cambiar un estado que sí cambió.

**Cómo se cerraría**: un `refetchInterval` en `useDashboardCards`, con el mismo par de opciones que
ya usan los otros dos hooks. Es pequeño, pero es **producto**, no test, y está fuera del alcance de
`hardening-release`.

### #8 — la propietaria no puede crear una incidencia

Dos de los tres actores que el ítem nombra están cubiertos. El tercero no existe.

- **Huésped** ✅ — `ReportGuestIncidentUseCase`, ruta `POST /api/v1/guest/incident/{token}`.
- **Limpiadora** ✅ — `CleanerIncidentReporter` / `ReportTaskIncidentUseCase`, ruta
  `POST /api/v1/cleaning-tasks/{task_id}/incidents`.
- **Propietaria desde el dashboard** ❌ — **no hay ruta y no hay UI**.

`POST /api/v1/incidents` **no existe**, y su ausencia está **asertada como decisión** (diseño D14):
`backend/tests/maintenance/test_api_incidents.py::test_there_is_no_post_incidents` espera un `405`.
Lo corrobora `backend/tests/cleaning/test_task_incident_api.py::test_no_creation_route_appears_under_the_incidents_prefix`
y el contrato generado (`frontend/lib/api/generated/openapi.d.ts`: `/api/v1/incidents` sólo tiene
`get`). En el frontend, `frontend/features/incidents/` tiene listado, detalle y acciones de manager,
pero ninguna pantalla de alta.

El caso de uso genérico `ReportIncidentUseCase`
(`backend/app/maintenance/application/use_cases.py`) **existe y serviría**, pero su único cableado
de producción es el reporter de la limpiadora; la otra referencia es el sembrador de demo.

**Por qué esto es un hueco real y no una cuestión de redacción**: PRD §12 «Fuentes de creación de
incidencias» nombra explícitamente *«reporte del propietario desde dashboard»*, y §28.8 nombra a la
propietaria. No es una inferencia nuestra sobre lo que el PRD «querría decir».

**Nota sobre la tercera fuente viva**: existe además la creación desde el pipeline de mensajería
(`ReportIncidentFromConversationUseCase`), pero ése es de nuevo un **huésped** escribiendo, no la
propietaria.

**Cómo se cerraría**: una ruta autenticada de alta bajo `EXECUTE_INCIDENTS`/equivalente más su
pantalla. Es un change propio: D14 tomó la decisión contraria a conciencia («cada fuente que crea
una incidencia tiene dueño declarado»), así que reabrirla es una decisión de producto, no un
descuido que se parchee.

### #9 — la capacidad la cumple otro componente

El ítem dice **`MockAIAdapter`**. La clasificación automática de `severity` y `category` de una
incidencia la hace **`RuleBasedIncidentClassifier`**
(`backend/app/maintenance/infrastructure/classifier.py`, `ADAPTER_NAME = "RuleBasedIncidentClassifier"`),
detrás del puerto `IncidentClassifier`, aplicada por `Incident.classify` contra el
`ai_confidence_threshold` del tenant y disparada por el job `classify_incidents`.

`MockAIAdapter` (`backend/app/messaging/infrastructure/ai.py`) es **otra cosa**: vive en
`messaging`, su `classify_message` devuelve un `MessageClassification(intent, confidence)` para
conversación, y **no produce ni `severity` ni `category` de incidencia**. Comprobado: ninguna
referencia a `MockAIAdapter` en todo `backend/app/` toca el dominio `maintenance`.

Se registra como **CUMPLE con divergencia de nombre declarada**, no como PARCIAL: la capacidad que
el ítem pide está entera y testeada (las 13 categorías, con `category` y `severity`, en
`test_it_recognises_each_category`). Lo que está desactualizado es el **nombre** en el PRD. Por la
norma del proyecto el PRD no se edita: la divergencia vive aquí y en el ADR/spec del change que la
introdujo.

### #14 — la respuesta humana **sí** sale (desde 2026-09-11)

Se audita en detalle porque la sospecha contraria estaba anotada y **ya no es cierta**. Hasta el
2026-09-11 la respuesta que la manager escribía en `/conversations` se guardaba en la base de datos
y no salía por ningún canal. El change `human-reply-outbound-delivery`
(`sdd/changes/archive/2026-09-11-human-reply-outbound-delivery`) lo cerró:
`RecordHumanReplyUseCase.execute` llama `await adapter.send(...)` y **sólo después** construye el
`Message` con su `delivery_status`/`delivery_error_code`, sobre
`outbound_registry` / `DelegatingOutboundAdapter` (`backend/app/messaging/infrastructure/channels.py`).

Tests: `backend/tests/messaging/test_use_cases.py::test_a_whatsapp_human_reply_records_delivery_status_sent_when_the_send_delivers`,
`::test_an_email_human_reply_resolves_the_guests_email_address`,
`::test_a_whatsapp_human_reply_preserves_a_translated_failure_code`;
a nivel de adapter `backend/tests/messaging/test_channels.py::test_a_delegated_channel_delivers`.

**Cuatro matices que acotan la palabra «entregada»**, todos decisiones y no fallos:

- `MANUAL` y `PORTAL` responden `ok()` **sin enviar nada**: la fila *es* la entrega, el lector la
  saca de `GET /conversations/{id}/messages` o del portal del huésped.
- `PHONE_TRANSCRIPT` es sólo de entrada (`CHANNEL_INBOUND_ONLY`).
- `AIRBNB_MSG` / `BOOKING_MSG` **no tienen entrada en el registro, a propósito**: la respuesta se
  persiste con `delivery_status=FAILED` y `delivery_error_code=ADAPTER_UNAVAILABLE`, y el commit
  ocurre igual. Para esos dos canales de OTA la respuesta sigue siendo sólo de base de datos, hasta
  que llegue `beds24-messaging-adapter`.
- La entrega por red real sólo ocurre configurada (`whatsapp_provider == "meta"`, `smtp_host`);
  si no, adapters mock/consola.

### #16 — qué lleva el CSV

El ítem se cumple: hay generación mensual (manual y por job `generate_owner_statements`) y hay
export CSV por ruta (`GET /owner-statements/{id}/export.csv`).

Matiz honesto: el CSV son las **líneas de gasto** del statement
(`date,category,description,amount,currency,receipt_storage_key`), **no** los totales ni el neto al
propietario, que van en el PDF (`backend/app/statements/infrastructure/pdf.py`). PRD §28.16 dice
«generarse y exportarse a CSV» sin decir qué columnas, así que esto no lo incumple — pero conviene
que quien lo lea no espere el resumen financiero en ese fichero.

**Defecto menor encontrado de camino** (no afecta al veredicto):
`backend/tests/statements/test_api.py::TestExportEndpoints::test_export_csv_route_returns_csv_content_type`
arrastra un `pytest.importorskip("app.statements.infrastructure.csv_export", reason="CsvStatementExporter lands in task 7.3")`
y un comentario que afirma que el serializador «todavía no existe». El módulo **sí** existe, así que
el skip nunca dispara y el test corre — pero el comentario engaña a quien cite ese test solo. La
cita primaria para el CSV debe ser el test de caso de uso, no el de la ruta.

### #17 — «todas» las acciones no es literal

El **mecanismo** es sólido y de una sola vía: todo evento se construye con
`TimelineEventFactory.create` (o `.property_state_changed`), y el catálogo bilingüe está cerrado
contra el enum por `test_the_catalogue_covers_the_whole_enum_and_nothing_else`
(`assert len(TimelineEventType) == 53`).

Lo que no es literal es **«todas las acciones relevantes»**. Medido contra el árbol el 2026-09-13
—contando referencias `TimelineEventType.<X>` en todo `backend/app/` fuera de `app/timeline/`—
**16 de los 53 miembros no tienen ningún escritor de producción**:

`CHECKIN_WINDOW_OPENED`, `CHECKOUT_WINDOW_REACHED`, `CLEANING_TASK_CREATED`, `CLEANER_ASSIGNED`,
`CLEANER_ACCEPTED`, `CLEANER_REJECTED`, `CLEANING_STARTED`, `CLEANING_PHOTO_UPLOADED`,
`CLEANING_COMPLETED`, `CLEANING_FAILED_VALIDATION`, `LOCK_ALERT_RECEIVED`, `REVIEW_IMPORTED`,
`SLA_BREACH_WARNING`, `NOTIFICATION_SENT`, `NOTIFICATION_FAILED`, `WEBHOOK_RECEIVED`.

(La medición bruta devuelve 17; `PROPERTY_STATE_CHANGED` no cuenta porque se escribe por el método
con nombre `TimelineEventFactory.property_state_changed` y no por una referencia al enum.)

**Lo más visible es que la familia de limpieza entera está sin escribir**:
`backend/app/cleaning/application/use_cases.py` sólo escribe el `PROPERTY_STATE_CHANGED` que le
devuelve la state machine, y nunca construye `CLEANING_TASK_CREATED`, `CLEANER_ACCEPTED`,
`CLEANING_COMPLETED`… Dicho de otro modo: **los ítems #5, #6 y #7 de este mismo DoD aparecen en el
timeline sólo como cambios de estado genéricos, no como sus propios eventos con nombre.**

Esto **no está oculto**: `sdd/specs/timeline-state-machine.md` lo lleva contando explícitamente
(«los declarados sin escritor bajaron a 18» cuando el enum tenía 47 miembros; hoy son 16 de 53).

**El segundo hueco, y el que importa para un DoD**: no existe un **censo de escritores** del
timeline. El proyecto tiene exactamente esa guarda, basada en AST, para otro enum —
`backend/tests/notifications/test_writer_census.py`, con sus frozensets `WITH_WRITER`/`WITHOUT_WRITER`
y `test_the_measured_writers_are_exactly_the_declared_ones` / `test_every_orphan_really_has_no_writer`—
pero **nada equivalente guarda `TimelineEventType`**. Hoy nada en la suite se pondría rojo si se
declarase un tipo que nadie escribe, ni si un escritor desapareciera.

**Cómo se cerraría**, en dos piezas separables: (a) el análogo de `test_writer_census.py` para
`TimelineEventType`, que convierte el 16 en una cifra medida y vigilada en vez de en prosa que
envejece — eso **sí** es trabajo de test; y (b) darles escritor a los tipos que deban tenerlo,
empezando por la familia de limpieza — eso es producto. Ninguna de las dos está en el alcance de
`hardening-release`.

---

## §28.18 — Los 18 dominios de negocio y su test de aislamiento

**Método.** Se enumeran los directorios bajo `backend/app/` y se excluyen los cuatro que son
infraestructura y no dominio de negocio: `cli` (comandos de consola), `core` (mecanismo compartido:
sesión, filtro global, i18n), `provenance` (procedencia de la build) y `scheduler` (capa de entrega
para el reloj). Quedan **18**. Para cada uno se busca en `backend/tests/<dominio>/` un test que
demuestre que un actor del tenant A no alcanza datos del tenant B — **sin limitar la búsqueda a los
dos nombres canónicos** (`test_isolation.py` / `test_tenant_isolation.py`), porque la mayoría de la
cobertura real no vive con esos nombres.

**Resultado: 18 de 18 cubiertos. Cero huecos, cero «no aplica». No hubo ningún test que escribir.**

Ése es el hallazgo de la tarea 6.1, y conviene decir por qué la expectativa de partida era otra —
**buscar por nombre de fichero inventa huecos que no existen**. Las cifras exactas, medidas el
2026-09-13:

- **7 dominios** tienen un fichero con uno de los dos nombres canónicos `test_isolation.py` /
  `test_tenant_isolation.py`: `auth`, `dashboard`, `messaging`, `platform`, `reservations`,
  `reviews`, `tenants`.
- **10 dominios** tienen algún fichero con `isolation` en el nombre — los 7 anteriores más
  `maintenance` (`test_photo_isolation.py`), `notifications` (`test_dispatch_isolation.py`,
  `test_read_isolation.py`) y `properties` (`test_action_id_isolation.py`).
- **Los 8 restantes** —`access`, `audit`, `cleaning`, `guests`, `integrations`, `pricing`,
  `statements`, `timeline`— no tienen **ningún** fichero con `isolation` en el nombre, y **los ocho
  están cubiertos igualmente**: su aislamiento vive en el fichero del repositorio, del caso de uso o
  de la API, con nombres como `test_get_does_not_cross_tenants`,
  `test_reads_never_cross_tenants` o `test_a_tenant_gets_the_same_404_for_another_tenants_endpoint`.

De ahí el método: se busca por **nombre de función**, no por nombre de fichero.

| # | Dominio | Tablas propias | Test de aislamiento (cita representativa) | Nº de tests con nombre de aislamiento |
|---|---|---|---|---|
| 1 | `access` | 1 | `tests/access/test_repositories.py::test_reads_never_cross_tenants`, `::test_writes_refuse_an_entity_of_another_tenant`; API `tests/access/test_api.py::test_a_neighbours_record_is_the_same_404_as_a_missing_one` | 4 |
| 2 | `audit` | 1 | `tests/audit/test_repositories.py::test_it_refuses_an_entry_of_another_tenant` — **es la superficie entera**: ver nota abajo | 1 |
| 3 | `auth` | 3 | `tests/auth/test_isolation.py`; `tests/auth/test_user_admin_isolation.py`; `tests/auth/test_repositories.py::test_get_active_by_id_will_not_cross_tenants` | 58 |
| 4 | `cleaning` | 5 | `tests/cleaning/test_repositories.py::test_get_from_another_tenant_returns_none`, `::test_save_never_moves_a_task_to_another_tenant`; API `tests/cleaning/test_tasks_api.py::test_reading_another_tenants_task_is_a_404` | 42 |
| 5 | `dashboard` | **ninguna** (lado de lectura) | `tests/dashboard/test_isolation.py::test_the_collection_shows_no_property_of_another_tenant`; `tests/dashboard/test_use_cases.py::test_a_property_of_another_tenant_raises_the_very_same_error` | 14 |
| 6 | `guests` | 2 | `tests/guests/test_repositories.py::test_get_does_not_reach_another_tenants_guest`, `::test_find_by_email_does_not_cross_tenants`; portal `tests/guests/test_portal_repositories.py::test_a_marked_session_cannot_see_another_tenants_token` | 28 |
| 7 | `integrations` | 3 | `tests/integrations/test_beds24_end_to_end.py::test_one_tenants_beds24_sync_never_reaches_another_tenants_data`; `tests/integrations/test_pms_credentials.py::test_a_credential_cannot_be_anchored_to_another_tenants_property` | 13 |
| 8 | `maintenance` | 4 | `tests/maintenance/test_repositories.py::test_the_open_list_never_reads_another_tenants_incidents`; `tests/maintenance/test_photo_isolation.py`; `tests/maintenance/test_api_approvals.py::test_another_tenants_approvals_never_appear` | 36 |
| 9 | `messaging` | 4 | `tests/messaging/test_tenant_isolation.py` (11 casos: listar, leer, escribir, escalar, portal, WhatsApp) | 34 |
| 10 | `notifications` | 1 | `tests/notifications/test_read_isolation.py`; `tests/notifications/test_dispatch_isolation.py`; `tests/notifications/test_repositories.py::test_candidates_never_cross_tenants` | 19 |
| 11 | `platform` | **ninguna** (escribe en las de otros) | `tests/platform/test_isolation.py::test_creating_a_user_in_tenant_a_does_not_leak_to_tenant_b`, `::test_creating_a_user_in_tenant_b_lands_under_b_not_a` — **forma distinta a propósito**: ver nota abajo | 9 |
| 12 | `pricing` | 2 | `tests/pricing/test_repositories.py::test_get_does_not_cross_tenants`, `::test_the_upsert_cannot_touch_another_tenants_property`; `tests/pricing/test_api_tenant_scoping.py` | 12 |
| 13 | `properties` | 2 | `tests/properties/test_repositories.py::test_get_does_not_reach_another_tenants_property`, `::test_list_by_state_does_not_reach_another_tenant`; `tests/properties/test_action_id_isolation.py` | 26 |
| 14 | `reservations` | 1 | `tests/reservations/test_isolation.py`; `tests/reservations/test_identity_isolation.py` | 30 |
| 15 | `reviews` | 2 | `tests/reviews/test_tenant_isolation.py` (11 casos: listar, leer, escribir, aprobar, agregados) | 15 |
| 16 | `statements` | 2 | `tests/statements/test_api.py::test_other_tenants_statements_are_not_visible`, `::test_cross_tenant_id_returns_404`; `tests/statements/test_reconciliation.py::test_approval_from_tenant_a_does_not_apply_to_tenant_b_expense` | 8 |
| 17 | `tenants` | 2 | `tests/tenants/test_isolation.py::test_reading_another_tenant_answers_404`, `::test_a_cross_tenant_patch_is_indistinguishable_from_an_invented_id` | 10 |
| 18 | `timeline` | 1 | `tests/timeline/test_read_repository.py::test_it_never_returns_an_event_of_another_tenant`, `::test_the_batch_reader_never_crosses_a_tenant_boundary` | 6 |

*(La última columna cuenta funciones de test cuyo **nombre** nombra el cruce de tenants; es un suelo,
no un total — no cuenta las que prueban aislamiento sin decirlo en el nombre.)*

**Dos dominios merecen nota, porque su test no tiene la forma habitual y podría leerse como un
hueco:**

- **`audit` es de sólo escritura.** `SqlAlchemyAuditLogRepository` tiene **un único método,
  `add()`**: no hay lectura, no hay API, y sus escritores viven en `access`, `auth` y `platform`.
  Por tanto su superficie de aislamiento **entera** es que la escritura rechace una entrada de otro
  tenant, que es exactamente lo que asevera su único test. No es cobertura escasa: es cobertura
  completa de una superficie pequeña.
- **`platform` es la excepción nombrada de `steering/security.md` regla 1.** Su actor es
  `SUPER_ADMIN` con **sesión sin marcar** (`tenant_id=None`), así que el filtro global **no le
  aplica** — y el alcance cross-tenant es el propósito del dominio, no un fallo. Lo que el filtro no
  puede hacer lo hace el caso de uso: `CreateUserInTenantUseCase` toma el `tenant_id` del **segmento
  de la ruta**, no de la fila del actor. Su test de aislamiento fija por eso los tres estados
  posibles (tenant correcto, tenant equivocado, `NULL`) y asevera el primero. Un test con la forma
  «el tenant A no ve al B» sería aquí **vacuo**, porque no hay filtro que probar.

**Además del aislamiento por dominio, tres guardas transversales** sostienen la regla 1 y son parte
de la evidencia de #28.18:

| Guarda | Qué prueba | Tests |
|---|---|---|
| `backend/tests/test_tenant_filter.py` | La red de debajo: una query que **olvidó** su filtro sigue sin ver filas de otro tenant | 13 |
| `backend/tests/test_unscoped_reads.py` | El censo de lecturas sin scope es un **frozenset**, no un párrafo — añadir un llamante sin declararlo es rojo | 4 |
| `backend/tests/test_session_marking.py` | Ningún código de aplicación **desmarca** una sesión (apagaría el filtro para el resto de la petición) | 9 |

### Corrección de la cifra de dominios

El recuento real es **18**. Dos sitios lo decían mal:

- **`README.md` (§Estructura) decía «19 dominios»**, con un roster de cuatro capas que ya no
  incluía `statements` (ganó `application/`/`api/` con `revenue-statements`) ni mencionaba `audit`.
  **Corregido en este change**: 18, con la nota de qué cuatro directorios se excluyen y por qué,
  `statements` de vuelta en el roster de quince, y `audit` nombrado como el único que sigue siendo
  sólo estructura de datos.
- **`sdd/steering/architecture.md` sigue diciendo «diecisiete dominios»** (línea 40) y su lista de
  la línea 46 nombra catorce, sin `audit`, `dashboard`, `platform` ni `reviews`. Esa cifra es
  anterior al dominio `platform`. **No se ha corregido aquí**: el párrafo razona sobre un diagrama
  de dieciséis cajas, y reescribirlo sin volver a medir el diagrama sería cambiar prosa por prosa.
  **Queda declarado como pendiente**, para el change que regenere el diagrama hexagonal.

Reparto de capas hoy, para que el roster no vuelva a envejecer en silencio: **quince** dominios con
las cuatro capas (`access`, `auth`, `cleaning`, `guests`, `integrations`, `maintenance`, `messaging`,
`notifications`, `pricing`, `properties`, `reservations`, `reviews`, `statements`, `tenants`,
`timeline`); **dos** sin `infrastructure/` propia porque no tienen tabla (`dashboard`, `platform`);
**uno** todavía sólo `domain/` + `infrastructure/` (`audit`).

---

## §28.19 — Las transiciones de `PropertyStateMachine`

**Método.** Se enumeran las transiciones desde el propio `_POLICY` de
`backend/app/properties/domain/state_machine.py` y se cruzan con
`backend/tests/properties/test_state_machine.py`.

**Resultado: cobertura exhaustiva. Cero huecos. No hubo ningún caso que añadir.**

Y lo es por construcción, que es lo que la hace difícil de romper: el test **no mantiene una lista a
mano** de transiciones. Declara `EXPECTED_POLICY`, lo asevera **igual** a `_POLICY`
(`test_original_66_policy_candidates_are_explicitly_classified`) y **deriva** de él todas sus
parametrizaciones. Añadir una fila a la matriz sin tocar el test pone la suite en rojo; añadirla a
las dos genera sola la batería de casos nueva.

**El espacio y su cobertura**, medidos el 2026-09-13 (11 estados × 16 triggers = 176 pares):

| Qué | Cuántos | Test que lo cubre |
|---|---|---|
| Pares `(estado, trigger)` **declarados** en `_POLICY` | **39** | — |
| Relaciones **válidas** `(estado, trigger, destino)` | **75** | `test_every_declared_policy_relation_is_evaluable` — evalúa cada una y comprueba `from_state`, `to_state` y que emite `PROPERTY_STATE_CHANGED` |
| Pares **no declarados** (deben rechazarse) | **137** | `test_every_undeclared_state_trigger_pair_is_rejected` — parametrizado sobre los 176 pares, salta los 39 declarados |
| Destinos **inválidos** para un par declarado | **354** | `test_every_invalid_destination_for_declared_pair_is_rejected` (39 pares × 11 estados − 75 válidos) |
| Relaciones **retiradas a propósito** del superconjunto contextual | **8** | `test_non_transitions_are_not_declared_as_valid_policy_relations` |

**Aritmética de verificación**: 75 + 176 + 354 + 8 = 613 casos parametrizados de la matriz, más ~71
de precondiciones, actor, razón, atomicidad y evidencia = **684 recolectados**. De los 176, **39
saltan** (son los declarados), que es exactamente el número de skips que reporta la corrida. Cuadra.

```
docker compose exec backend uv run pytest tests/properties/test_state_machine.py
→ 643 passed, 41 skipped
```

*(41 skips = los 39 pares declarados + 2 de otros casos.)*

**Las transiciones válidas, por estado de origen** (destino único salvo donde se indica; los
contextuales los resuelve `ContextualStateResolver`):

| Estado de origen | Trigger | Destino(s) |
|---|---|---|
| `VACANT_READY` | `CHECKIN_WINDOW_OPENED` | `AWAITING_CHECKIN` |
| `VACANT_READY` | `OWNER_BLOCKED` | `BLOCKED_BY_OWNER` |
| `VACANT_READY` | `PROPERTY_MARKED_OUT_OF_SERVICE` | `OUT_OF_SERVICE` |
| `VACANT_READY` | `INCIDENT_HIGH` | `MAINTENANCE_REQUIRED` |
| `VACANT_READY` | `INCIDENT_CRITICAL` | `CRITICAL_INCIDENT` *(añadido por `maintenance` D8)* |
| `AWAITING_CHECKIN` | `CHECKIN_TIME_REACHED` | `OCCUPIED_ESTIMATED` |
| `AWAITING_CHECKIN` | `INCIDENT_HIGH` / `INCIDENT_CRITICAL` / `OWNER_BLOCKED` | `MAINTENANCE_REQUIRED` / `CRITICAL_INCIDENT` / `BLOCKED_BY_OWNER` |
| `AWAITING_CHECKIN` | `RESERVATION_CANCELLED_BEFORE_CHECKIN` | `VACANT_READY` |
| `OCCUPIED_ESTIMATED` | `CHECKOUT_TIME_REACHED` | `AWAITING_CLEANING` |
| `OCCUPIED_ESTIMATED` | `INCIDENT_HIGH` / `INCIDENT_CRITICAL` | `MAINTENANCE_REQUIRED` / `CRITICAL_INCIDENT` |
| `AWAITING_CLEANING` | `CLEANER_ASSIGNED` | `CLEANING_SCHEDULED` |
| `AWAITING_CLEANING` | `INCIDENT_HIGH` / `INCIDENT_CRITICAL` / `OWNER_BLOCKED` | `MAINTENANCE_REQUIRED` / `CRITICAL_INCIDENT` / `BLOCKED_BY_OWNER` |
| `AWAITING_CLEANING` | `CLEANING_CANCELLED` | **contextual, 5 destinos** *(`cleaning-stall-blocks-next-stay` D7)* |
| `CLEANING_SCHEDULED` | `CLEANING_STARTED` | `CLEANING_IN_PROGRESS` |
| `CLEANING_SCHEDULED` | `CLEANER_REJECTED` | `AWAITING_CLEANING` |
| `CLEANING_SCHEDULED` | `INCIDENT_CRITICAL` | `CRITICAL_INCIDENT` |
| `CLEANING_SCHEDULED` | `INCIDENT_HIGH` | `MAINTENANCE_REQUIRED` *(añadido por `maintenance` D8)* |
| `CLEANING_SCHEDULED` | `CLEANING_CANCELLED` | **contextual, 6 destinos** |
| `CLEANING_IN_PROGRESS` | `CLEANING_COMPLETED` | **contextual, 3**: `READY_FOR_NEXT_GUEST` / `AWAITING_CHECKIN` / `VACANT_READY` |
| `CLEANING_IN_PROGRESS` | `INCIDENT_HIGH` / `INCIDENT_CRITICAL` | `MAINTENANCE_REQUIRED` / `CRITICAL_INCIDENT` |
| `CLEANING_IN_PROGRESS` | `CLEANING_CANCELLED` | **contextual, 5 destinos** |
| `READY_FOR_NEXT_GUEST` | `CHECKIN_WINDOW_OPENED` | `AWAITING_CHECKIN` |
| `READY_FOR_NEXT_GUEST` | `INCIDENT_HIGH` / `INCIDENT_CRITICAL` / `OWNER_BLOCKED` | `MAINTENANCE_REQUIRED` / `CRITICAL_INCIDENT` / `BLOCKED_BY_OWNER` |
| `MAINTENANCE_REQUIRED` | `INCIDENT_RESOLVED` | **contextual, 7 destinos** |
| `MAINTENANCE_REQUIRED` | `INCIDENT_CRITICAL` / `OWNER_BLOCKED` | `CRITICAL_INCIDENT` / `BLOCKED_BY_OWNER` |
| `CRITICAL_INCIDENT` | `INCIDENT_HIGH` | `MAINTENANCE_REQUIRED` |
| `CRITICAL_INCIDENT` | `INCIDENT_RESOLVED` | **contextual, 7 destinos** |
| `CRITICAL_INCIDENT` | `OWNER_BLOCKED` | `BLOCKED_BY_OWNER` |
| `BLOCKED_BY_OWNER` | `OWNER_MANAGER_UNBLOCKED` | **10 destinos** (todo estado salvo él mismo), con `requested_state` explícito y validado contra el contexto |
| `OUT_OF_SERVICE` | `PROPERTY_REACTIVATED` | `VACANT_READY` |

**Más allá de la matriz**, el mismo fichero cubre las precondiciones que deciden si una transición
declarada además **procede**: estado de la reserva y ventanas horarias
(`test_reservation_trigger_preconditions_reject_incompatible_statuses`), estado de la tarea de
limpieza (`test_cleaning_trigger_preconditions_reject_incompatible_statuses`), severidad y estado de
la incidencia (`test_incident_trigger_preconditions_reject_incompatible_evidence`), el actor y la
razón obligatorios de las transiciones manuales (`test_manual_actions_require_user_and_reason`), el
`requested_state` explícito del desbloqueo (`test_unblock_requires_actor_reason_and_explicit_destination`),
el rechazo del no-cambio y del destino que no casa (`test_noop_and_requested_state_mismatch_are_rejected`),
el scope de tenant y propiedad del contexto (`test_context_scope_is_validated_for_tenant_and_property`)
y la atomicidad de la evidencia (`test_evidence_failure_is_atomic`).

**Nota de documentación, no de test**: el diagrama `docs/diagrams/2026-07-13_autohost-maquina-estados.png`
es del 2026-07-13 y por tanto **anterior** a las cinco filas que añadieron `maintenance` (D8, dos) y
`cleaning-stall-blocks-next-stay` (D7, las tres de `CLEANING_CANCELLED`). La matriz autoritativa es
`_POLICY`, y el test la fija; el diagrama va por detrás. Regenerarlo queda fuera del alcance de este
change.

---

## Cómo reproducir esta auditoría

```bash
# §28.18 — dominios de negocio (18) y su cobertura de aislamiento
ls backend/app/                       # menos cli, core, provenance, scheduler
grep -rn "def test_" backend/tests/<dominio> --include="*.py" \
  | grep -iE "isolat|other_tenant|cross_tenant|another_tenant|tenant_boundary"

# §28.19 — la matriz y su cobertura
docker compose exec backend uv run pytest tests/properties/test_state_machine.py
docker compose exec backend uv run pytest tests/properties/test_state_machine.py --collect-only -q

# §28.17 — los tipos de evento sin escritor (la medición de 16/53)
docker compose exec backend uv run python -c "
import re, pathlib
from app.timeline.domain.enums import TimelineEventType
used = set()
for p in pathlib.Path('/app/app').rglob('*.py'):
    if 'timeline/' in str(p.relative_to('/app/app')): continue
    used |= set(re.findall(r'TimelineEventType\.([A-Z_]+)', p.read_text()))
print(sorted({e.name for e in TimelineEventType} - used))"

# La suite entera
docker compose exec backend uv run pytest
# → 11076 passed, 44 skipped in 649.42s (medido el 2026-09-13)
```

## Qué queda abierto tras esta auditoría

Ninguno de estos puntos está en el alcance de `hardening-release`. Se listan para que tengan dueño.

1. **#8 — alta de incidencia por la propietaria** (producto). Ruta autenticada + pantalla. Reabre
   deliberadamente la decisión D14, así que necesita change propio.
2. **#17a — censo de escritores de `TimelineEventType`** (test). El análogo de
   `backend/tests/notifications/test_writer_census.py`. Convierte «16 de 53» en una cifra vigilada.
3. **#17b — escritor para la familia de limpieza** (producto). `CLEANING_TASK_CREATED`,
   `CLEANER_ACCEPTED`, `CLEANING_COMPLETED`… hoy sólo aparecen como `PROPERTY_STATE_CHANGED`.
4. **#2 — refresco del dashboard** (producto, pequeño). `refetchInterval` en `useDashboardCards`,
   con el par de opciones que ya usan `use-unread-count.ts` y `use-conversation.ts`.
5. **Cifra de dominios en `sdd/steering/architecture.md`** (documentación). Dice diecisiete; son
   dieciocho. Junto con el diagrama hexagonal sobre el que razona.
6. **Diagrama de la state machine** (documentación). `2026-07-13_autohost-maquina-estados.png` no
   lleva las cinco filas añadidas después.
7. **`importorskip` obsoleto** en
   `backend/tests/statements/test_api.py::TestExportEndpoints::test_export_csv_route_returns_csv_content_type`
   (limpieza menor). El módulo que dice que no existe, existe.
