# Design: revenue-reviews

## Context

`backend/app/reviews/` ya contiene un esqueleto de cinco ficheros creados en
`revenue-reviews` (anterior a esta propuesta) sin propietario de capacidad: los enums
`ReviewChannel`/`ReviewSentiment`/`ReviewStatus` (`backend/app/reviews/domain/enums.py`),
las dataclasses `Review` y `ReviewResponseDraft` (`backend/app/reviews/domain/entities.py`),
los modelos ORM `ReviewModel` y `ReviewResponseDraftModel`
(`backend/app/reviews/infrastructure/models.py`) y los `__init__.py` correspondientes.
La migración histórica `96d526599bc1_domain_foundation_financial.py` **crea ambas tablas
como placeholder y solo las dropea en `downgrade()`** (líneas 187, 244 vs. 254, 258) —
no en `upgrade()`. `revenue-reviews` es el dueño de la capability, así que su primera
migración (`r3v1ew5a01`) las dropea explícitamente si están presentes (gated por
`inspector.get_table_names()`, idempotente) antes de crearlas con el shape definitivo,
y crea los tres enum types con `postgresql.ENUM(...).create(checkfirst=True)` porque
`sa.Enum` dentro de `create_table` no crea el type implícitamente en contexto Alembic. `TimelineEventType` ya enumera
`REVIEW_IMPORTED`/`REVIEW_RESPONSE_DRAFTED`/`REVIEW_RESPONSE_APPROVED`
(`backend/app/timeline/domain/enums.py:65-67`) y la columna `timeline_events.event_type`
de la baseline los acepta — tres eventos del flujo nacen pre-aprobados por el esquema, y
los otros dos (`REVIEW_CREATED`, `REVIEW_IGNORED`, `REVIEW_CLASSIFIED_LOW_CONFIDENCE`,
`REVIEW_DRAFT_EDITED`, `REVIEW_POSTED_MANUALLY`) entran con este change. `NotificationType`
tiene diecisiete miembros hoy y no enumera todavía `REVIEW_RESPONSE_APPROVED`. El
puerto `IncidentClassifier` (`backend/app/maintenance/domain/ports.py:24`) y el
`AIAdapter` (`backend/app/messaging/domain/ports.py`) ya fijaron el patrón: una
`Protocol` por capability, con un value object de retorno que rechaza por construcción
contenido fuera de un vocabulario cerrado. `messages` y `incidents` ya demostraron las
dos formas de la regla 11 de `steering/security.md` aplicables a reseñas —excepción 2
(prosa de tercero en `messages.content`) y forma estructurada con vocabulario declarado
en valor de retorno (adaptador de `IncidentClassifier` sobre `incidents.ai_summary`)—;
las cuatro columnas de la regla 11 que el proposal enumera se acogen a la primera,
a la segunda y a una nueva que es la que la regla aún no tiene (etiqueta cerrada en
JSONB).

## Decisions

### D1 — `AIReviewPort` propio, no `AIAdapter` reutilizado (resuelve OQ1)

**Chosen:** declarar dos `Protocol` nuevos en `backend/app/reviews/domain/ports.py` —
`AIReviewAnalyzer.analyze_review(*, content: str, language: str | None) ->
ReviewAnalysis` y `AIReviewDraftGenerator.generate_draft(*, review: Review, language:
str | None) -> GeneratedDraft`— con dos value objects (`ReviewAnalysis` y
`GeneratedDraft`) que rechazan por construcción un `confidence` fuera de `0..1`, un
`language` fuera de `SUPPORTED_LANGUAGES` y un `summary` o `content` fuera del
vocabulario cerrado que declaran en el valor de retorno.

Rejected: (a) `AIAdapter.draft_review(...)` en `messaging` — `messaging-ai` R2 cerró
explícitamente que `AIAdapter` no añade métodos que no le incumben, y añadir uno rompe
Liskov sobre el mismo razonamiento que motivó `PMSMessagingPort` (ADR 0006 decisión 3);
(c) refactor de los tres a un `AIProvider` base — `ai-port-consolidation` queda como
candidato de roadmap si la convergencia se justifica, pero encabezarlo desde
`revenue-reviews` cambiaría `messaging-ai` y `maintenance` por un cambio que no los
usa. **El "puerto nuevo por capability" es la regla del proyecto** —
`IncidentClassifier` lo hizo en `maintenance`, `AIAdapter` lo hizo en `messaging`, y
deja dos adaptadores en producción (`MockAIAdapter` + `RuleBasedIncidentClassifier` +
los dos nuevos aquí) en lugar de uno, a cambio de que un swap futuro a un proveedor
real se haga capability por capability, no en tres frentes a la vez. Es la forma
coherente con la regla 11 ("un adaptador declara el vocabulario en el valor que
devuelve", que se sostiene adapter por adapter) y la que el proposal recomienda.

### D2 — Pipeline asíncrona vía Celery, no síncrona al `POST` (resuelve OQ2)

**Chosen:** `CreateReviewUseCase` persiste la `Review` con `sentiment = NEUTRAL`,
`ai_summary = NULL`, `recurring_issues = []`, emite `TimelineEvent REVIEW_CREATED`
en la misma transacción, y agenda la fila para análisis en un nuevo job Celery
`classify_reviews` que corre cada cinco minutos, anota su `tenant_id`, su `review_id`,
su tipo y nunca su contenido. El job respeta el patrón de `classify_incidents`
(`backend/app/scheduler/tasks.py:79-83`): usa `run_for_every_tenant` y abre una sesión
marcada por tenant, llama a `ClassifyPendingReviewsUseCase` por tenant y termina con
un informe `{scanned, classified, low_confidence, failed, manual_triage}`.

Rejected: ejecutar la pipeline dentro del `POST /api/v1/reviews` — el mock es O(10 ms),
pero el adaptador real no lo será, y la diferencia entre las dos arquitecturas es lo
que el cambio quiere validar antes de que un proveedor real entre. Vale la pena
recordar el matiz de R2.4: la pipeline reintenta hasta tres veces una reseña con
`ai_summary IS NULL`, y al tercer fallo la deja pendiente de triaje manual sin más
reintentos automáticos. Eso encaja con un job periódico: el reloj barre
`WHERE ai_summary IS NULL AND attempts < 3`, contabiliza los
`attempts == 3` como manual-triage y emite `REVIEW_CLASSIFIED_LOW_CONFIDENCE` cuando
la confianza del adaptador está por debajo de `TenantConfig.ai_confidence_threshold`
(según `RuleBasedIncidentClassifier._UNMATCHED_CONFIDENCE`, mismo borde
estrictamente-menor que `maintenance` R4).

### D3 — Permisos globales por rol, sin permisos-por-tenant (resuelve OQ3)

**Chosen:** añadir al `Permission` enum en `backend/app/auth/domain/policy.py` los
cinco miembros `READ_REVIEWS`, `CREATE_REVIEW`, `APPROVE_REVIEW`, `IGNORE_REVIEW`,
`MARK_REVIEW_POSTED` (uno por acción del flujo, no por recurso como `messaging`
porque las acciones de reseñas tienen RBAC distinto: leer es de los dos roles,
aprobar y publicar también, **ignorar** lo es y `CREATE_REVIEW` se acota al
`PROPERTY_MANAGER` por la misma razón que `MANAGE_CONVERSATIONS`), y mapearlos en
`ROLE_PERMISSIONS` siguiendo el patrón `_CONVERSATION_*`: `TENANT_OWNER` recibe
`READ_REVIEWS`, `APPROVE_REVIEW`, `IGNORE_REVIEW` y `MARK_REVIEW_POSTED`; el manager
recibe los cinco. `CLEANER` y `TECHNICIAN` no tocan reseñas — un borrador de respuesta
no es parte de limpiar ni de reparar. El reparto lo fija `PRD §6` literal
("`PROPERTY_MANAGER` opera reservas, limpiezas, incidencias, conversaciones; `TENANT_OWNER`
ve y configura") y `PRD §18` no añade permisos nuevos, así que el reparto por rol se
cita sin abrirse.

Rejected: permisos-por-tenant — `auth-tenancy` R2 los descarta expresamente y este
change no ve un caso donde un manager cambie de tenant. Si aparece, es un cambio
propio del módulo de identidad, no de reseñas.

### D4 — Estado de `Review` transicionado por métodos en la entidad, no en un servicio

**Chosen:** declarar las cinco transiciones (`NEW → DRAFTED`, `DRAFTED → APPROVED`,
`DRAFTED → IGNORED`, `APPROVED → POSTED_MANUALLY`, `NEW → IGNORED` si llega sin
clasificación) como métodos de `Review` que mutan `status` con `_assert_transition`,
siguiendo el mismo patrón de dos tablas que `Conversation` dibuja en `messaging`
(`messaging-ai` R5: eje de escalación con tabla propia y eje de conversación con
tabla propia, validadas antes de tocar ningún campo). Una transición ilegal lanza
`InvalidReviewTransitionError` (símil de `InvalidConversationTransitionError`) y el
router responde `409`. Los métodos `mark_drafted()`, `approve()`, `ignore()`,
`mark_posted_manually()` y `mark_classified_low_confidence()` son el único camino
para mover `status`.

Rejected: state machine en un servicio externo (`ReviewStateMachine` separado, como
`PropertyStateMachine`) — `messaging` también lo evitó y la regla de coherencia entre
los dos módulos pesa más que el beneficio. Si en el futuro la máquina crece (caso
`Conversation` después de `messaging-ai`), se refactoriza siguiendo ese precedente.

### D5 — `ReviewResponseDraft` con un único activo por `Review`, vía UNIQUE constraint

**Chosen:** la columna `review_response_drafts.review_id UNIQUE NOT NULL` (PRD §7.21)
es la única invariante de unicidad; la API expone `PATCH /reviews/{id}/response` con
`action ∈ {APPROVE, IGNORE, EDIT}` y `POST /reviews/{id}/response` para regenerar el
borrador. Regenerar reemplaza la fila en una sola transacción (`UPDATE` por
`review_id`, no `DELETE` + `INSERT`); `ai_generated` queda siempre `TRUE` —
la columna es bitácora de origen, no de estado (R3.5). Se añade además
`edits_count INT NOT NULL DEFAULT 0` (resuelve OQ4): cada `EditReviewDraftUseCase`
incrementa el contador en la misma transacción que actualiza `draft_content`, sin
cambiar `ai_generated`. Es una desviación menor del PRD §7.21 documentada como
`ASSUMPTION` y registrada en la migración.

Rejected: múltiples borradores por reseña con `is_active` — la cardinalidad 1:1 es
del PRD y la UNIQUE la impone por esquema; un flag `is_active` introduce estados
intermedios sin valor (¿cuál es la versión canónica?). El cambio de borrador
`DRAFTED → APPROVED` no se deshace (R3.6); el campo `approved_by`/`approved_at`
queda como marca de auditoría. Sin `edits_count`, el audit no sabe cuántas veces
se modificó un borrador tras la generación — sólo sabe que `AuditLog` emitió un
evento `REVIEW_DRAFT_EDITED` — y ese contador es lo que distingue un borrador
intacto de uno iterado sin contradecir R3.5.

### D6 — Vocabulario cerrado de plantillas por `(sentiment, language)` con detección de promesa prohibida

**Chosen:** declarar `REVIEW_DRAFT_TEMPLATES: Mapping[tuple[ReviewSentiment, str], str]`
en `backend/app/reviews/domain/templates.py` con tres sentimentos × dos idiomas = seis
entradas (positiva, neutra, negativa — `IGNORED` no genera borrador y `POSTED_MANUALLY`
lo genera sólo si vuelve atrás). Cada entrada es una **constante sin interpolación**
—ni `{...}`, ni `%s`, ni `f-string`— y `tests/reviews/test_draft_templates.py`
recorre el catálogo y rechaza uno, calcado de `tests/messaging/test_templates.py`.
`test_no_draft_can_promise_what_rule_10_forbids` barre el catálogo con la lista de
frases prohibidas que `messaging` ya usa (`reembolso`, `compensación`, `indemniz`,
`responsabilidad`, etc.), una red y no una garantía. Versión
`REVIEW_DRAFT_TEMPLATES_VERSION = "2026-09-01.1"` se persiste en
`review_response_drafts.metadata["template_version"]` (no tenemos columna; añadir
`metadata` a la tabla rompería el PRD — ver OQ4).

Rejected: dejar que el adaptador redacte por sí mismo sin catálogo —
`incidents.ai_summary` ya documenta por qué la red textual es la única defensa, y
`GeneratedDraft.vocabulary` rechazado en construcción es la condición de admisión que
la regla 11 pide. **`GeneratedDraft.content` es una forma estructurada bajo la regla
11**, así que se atiene a la admisión de cualquier adaptador y a la segunda red del
catálogo en `app.use_cases.assert_in_catalogue(...)` antes de persistir.

### D7 — Cuatro columnas a la regla 11; el censo se amplia con `reviews.recurring_issues` como excepción nueva

**Chosen:** las cuatro entradas que el proposal enumera van al censo de
`sdd/steering/security.md` §"Sumideros de texto en claro":

| Columna | Forma | Quién la escribe |
|---|---|---|
| `reviews.content` | **excepción 4** (prosa de tercero) — la misma que `messages.content` con `sender_type = GUEST` | `revenue-reviews` (escritura manual desde `POST /api/v1/reviews` y futura importación PMS) |
| `reviews.ai_summary` | estructurada (forma cerrada por sumidero: el vocabulario del `AIReviewAnalyzer`) | `revenue-reviews` (adaptador de análisis — condición de admisión análoga a `IncidentClassifier`) |
| `reviews.recurring_issues` | **forma estructurada por enum cerrado** (lista de miembros de `RecurringIssueTag`; cualquier valor no reconocido degrada a `OTHER` y registra un warning, nunca se persiste tal cual) | `revenue-reviews` (adaptador de análisis) |
| `review_response_drafts.draft_content` | estructurada (forma cerrada: `REVIEW_DRAFT_TEMPLATES`, sin interpolación) | `revenue-reviews` (adaptador de borrador — condición de admisión análoga a `GeneratedResponse`) |

`reviews.recurring_issues` es **una forma nueva** que el censo aún no tenía (la
excepción 1 era `****XX`, la 2 era prosa de tercero, la 3 era prosa autenticada, la 4
prosa de huésped): un JSONB con conjunto cerrado de etiquetas. Se declara como
fila propia de la tabla, con la **cláusula de admisión** que el `Review.recurring_issues`
valida en `__post_init__` (`RecurringIssueTag` enum + degradación a `OTHER` con
warning), no como excepción de la regla 11 — es una **forma estructurada por
defecto**, igual que `incidents.ai_classification`.

Rejected: tratar `recurring_issues` como excepción 4 — la columna no es prosa del
huésped, es una inferencia que hace el adaptador y por tanto le aplica la admisión
por valor de retorno de `ReviewAnalysis.recurring_issues_vocabulary`. El warning de
degradación cubre el caso de un adaptador que invente una etiqueta nueva.

### D8 — Timeline con cinco eventos del flujo, de los cuales tres ya existen en el enum

**Chosen:** los eventos que `Review` y `ReviewResponseDraft` emiten son
`REVIEW_IMPORTED`/`REVIEW_CREATED`/`REVIEW_RESPONSE_DRAFTED`/`REVIEW_DRAFT_EDITED`/
`REVIEW_CLASSIFIED_LOW_CONFIDENCE`/`REVIEW_RESPONSE_APPROVED`/`REVIEW_IGNORED`/
`REVIEW_POSTED_MANUALLY`. Tres (`REVIEW_IMPORTED`, `REVIEW_RESPONSE_DRAFTED`,
`REVIEW_RESPONSE_APPROVED`) ya están en `TimelineEventType` y se reutilizan; los
otros cinco (`REVIEW_CREATED`, `REVIEW_DRAFT_EDITED`,
`REVIEW_CLASSIFIED_LOW_CONFIDENCE`, `REVIEW_IGNORED`, `REVIEW_POSTED_MANUALLY`) entran
con el change. Cada uno lleva `metadata` con **sólo identificadores** — `review_id`,
`property_id`, `sentiment` cuando aplique— y `actor_type` derivado del caso de uso
que lo emite (`USER` cuando el actor es el manager/owner con su token;
`SCHEDULER` cuando lo emite `classify_reviews`; nunca `GUEST` porque la reseña la
crea el manager/owner). Las traducciones al español/inglés se añaden a
`TIMELINE_TITLE_TEMPLATES` en `backend/app/timeline/domain/rendering.py` para los
cinco nuevos; los tres viejos ya las tienen (líneas 240-251).

Rejected: un solo `REVIEW_STATE_CHANGED` con `from_state`/`to_state` en metadata —
el patrón del timeline lo es en `PROPERTY_STATE_CHANGED` y le va bien porque
`PropertyStateMachine` tiene una sola máquina; aquí `Review` tiene cinco transiciones
que la gente quiere leer como cosas distintas (creada, redactada, aprobada, ignorada,
publicada, editada), y los nombres ya existen en `TimelineEventType`. Reutilizar
`PROPERTY_STATE_CHANGED` mezclaría dos máquinas y diluiría el feed.

### D9 — Notificación de aprobación al propietario del tenant, sin emisor nuevo

**Chosen:** añadir `NotificationType.REVIEW_RESPONSE_APPROVED` al enum existente
(hoy tiene diecisiete miembros; pasa a dieciocho) con su entrada en
`_POLICY`/`escalation_for` (`backend/app/notifications/domain/escalation.py:62`)
con SLA opcional (R6.2 dice "notificación", no "notificación con plazo"). El
`ReviewApprovedUseCase` resuelve destinatarios con
`RoleRecipients.managers_or_owners` (patrón `auth/domain/recipients.py:69`) y el
`NotificationDispatcher` existente (`backend/app/notifications/application/use_cases.py`)
(resuelve OQ2). R6.3 lo dice explícito: no notificación en `NEW → DRAFTED`
(es ruido de la pipeline) ni en `APPROVED → POSTED_MANUALLY` (la publica una
persona que ya estaba mirando la fila). Las notificaciones se emiten en la misma
transacción que la transición, vía `CallerOwnedUnitOfWork` por el mismo mecanismo
que `messaging-ai` usa para `GUEST_ESCALATION` (`messaging-ai` R5, D12).

Rejected: añadir un emisor nuevo — `notification-writers-gap` ya documenta que el
camino correcto es añadir al catálogo y `escalation_for` y reusar el
`NotificationDispatcher`. R6.2 lo prohíbe. Resolver destinatarios como
"solo `TENANT_OWNER`" — divide la regla 1 (`RoleRecipients.managers_or_owners` es
la práctica operativa de todo el proyecto, documentada en `notifications-inbox-web`
R5.1) y deja al manager que aprueba sin notificación del propio acto, lo que rompe
la simetría con `GUEST_ESCALATION` y el resto del catálogo.

### D10 — `tenant_id` propio en `reviews`, NO en `review_response_drafts`

**Chosen:** `reviews` lleva `tenant_id` propio (R1.1) y se acota por el filtro global
de `_scope_statement_to_tenant` igual que cualquier entidad scopada;
`review_response_drafts` no lleva `tenant_id` propio y se acota **transitivamente** por
`JOIN` con `reviews` (R1.2, análoga a `messages` sin `tenant_id` scopada por
`conversations`). Esto ya está reflejado en el comentario del modelo ORM existente
(`backend/app/reviews/infrastructure/models.py:46-53`) y se sostiene con test propio de
aislamiento por tenant. La asimetría es deliberada: la regla 1 de `steering/security.md`
documenta que `messages` se acota por JOIN, no por columna propia; el mismo argumento
se aplica al borrador de respuesta y la propuesta lo dice.

Rejected: `tenant_id` propio en `review_response_drafts` — duplicaría la columna y
exigiría mantenerla en sincronía con `reviews.tenant_id`, que es exactamente lo que la
excepción documentada de `messages` evita.

### D11 — Cinco endpoints HTTP, todos en `/api/v1/reviews`, con `404` indistinguible

**Chosen:** las rutas de R5 son cinco (`POST /api/v1/reviews`, `GET /api/v1/reviews`,
`GET /api/v1/reviews/{id}`, `GET /api/v1/reviews/{id}/response`,
`GET /api/v1/properties/{id}/reviews/summary`) más dos que R3+R4 añaden
(`PATCH /api/v1/reviews/{id}/response` con `action ∈ {APPROVE, IGNORE, EDIT}`,
`POST /api/v1/reviews/{id}/response` para regenerar el borrador cuando la reseña
cambia de sentimento). El permiso es `READ_REVIEWS` para los tres `GET`,
`APPROVE_REVIEW`/`IGNORE_REVIEW`/`MARK_REVIEW_POSTED` para los `PATCH`,
`CREATE_REVIEW` para el `POST` (manager) y `READ_REVIEWS` para el resumen. `404`
indistinguible entre "no existe", "es de otro tenant" y "no es accesible por tu rol"
(igual que `messaging-ai` R7.5). Paginación envelope `{data, total, page, per_page,
total_pages}` del PRD §23, orden por defecto `published_at DESC` con nulos al final
(como `messaging-ai` R7). El endpoint de summary agrega los últimos 90 días por
sentimento y top N de `recurring_issues` (`N` por defecto 5, configurable por tenant
en `TenantConfig.review_recurring_issues_top_n` — ver OQ4). Los cinco endpoints
quedan cubiertos por el test estructural `tests/test_route_authorization.py` igual
que cualquier otra ruta autenticada.

Rejected: una sola `PATCH /reviews/{id}` con `state` en el body — la acción
(`APPROVE` vs `IGNORE` vs `MARK_REVIEW_POSTED`) tiene permisos distintos, y separarlas
en paths distintos hace el guard trivial y el log de auditoría más legible.

### D12 — Plantillas `REVIEW_DRAFT_TEMPLATES` con contenido en inglés y castellano, plantillas de `IGNORED`/`POSTED_MANUALLY` no generan borrador

**Chosen:** seis entradas (tres sentimentos × dos idiomas), siguiendo el catálogo de
`messaging` (`messaging-ai` R2.6, R2.7). `IGNORED` no genera borrador (no hay
respuesta que mandar) y `POSTED_MANUALLY` no genera borrador nuevo (la persona
posteó a mano; si quiere regenerar, llama a `POST /reviews/{id}/response` con
actor humano y `EDIT`). La regla 10 de `steering/security.md` aplica: ningún
template puede prometer reembolsos, admitir responsabilidad, dar asesoría legal,
revelar otros huéspedes, inventar disponibilidad o códigos, o afirmar que un
técnico va. `test_no_draft_can_promise_what_rule_10_forbids` recorre el catálogo
con esa lista, calcado del test de `messaging`.

Rejected: una plantilla genérica por idioma independiente del sentimiento — el
sentimiento del huesped cambia el tono de la respuesta y es información que el
manager usa para decidir; un template neutro único desperdicia esa señal.

### D13 — Sin metadatos en `review_response_drafts` (PRD §7.21); `template_version` se pierde

**Chosen:** la tabla `review_response_drafts` no tiene columna `metadata` en el
PRD §7.21, y no la añadimos. `template_version` se mantiene en memoria durante
la ejecución y se incluye en el log estructurado (`logger.info(...)` con
`extra={"template_version": ...}`) para que un operador pueda cruzar la versión
con el catálogo vigente; la fila persistida sólo lleva `draft_content` y `language`,
que es lo que la columna `draft_content` del PRD admite. Si en el futuro hace
falta persistir la versión, es un cambio aparte con su propia migración.

Rejected: añadir `metadata JSONB NULL` a `review_response_drafts` — la regla 11
vigilaría la nueva columna y el catálogo sumaría una fila por cada capability que
escriba ahí. Es más caro que el valor que aporta y abre un sumidero nuevo.

### D14 — Detección de idioma por stop-words ES/EN, sin librería externa

**Chosen:** `backend/app/reviews/domain/language.py` implementa `detect(content: str |
None) -> str | None` con dos conjuntos de stop-words (`_ES_STOPS`, `_EN_STOPS`),
`fold(content)` (mismo normalizador que `messaging/domain/language.py`) y devuelve
`"es"`/`"en"`/None cuando ningún conjunto gana por ≥1.5×. A2 del proposal fija
que una confianza baja devuelve `None` y deja `language` para triaje humano. Un test
cubre seis casos (solo ES, solo EN, ES mayoritario, EN mayoritario, ambiguo → None,
None → None).

Rejected: usar `langdetect` o `langid` — una dependencia externa para un problema
que dos docenas de stop-words resuelven. Si la heurística resulta insuficiente, se
mide contra un corpus y se decide.

### D15 — Schema Alembic nuevo, no reaprovechar `domain-foundation-financial`

**Chosen:** nueva migración `backend/alembic/versions/<rev>_revenue_reviews.py` que
**crea** ambas tablas con su `tenant_id`/`property_id`/`reservation_id`/`user`
FKs, sus índices (`ix_reviews_tenant_id`, `ix_reviews_property_id`,
`ix_review_response_drafts_review_id` ya UNIQUE), sus `server_default` y la
degradación de `rating` (mantenemos `Numeric(3,1)` sin CHECK: la restricción es
del dominio, no del esquema — lo dice ya el comentario en `models.py:28-29`). La
migración incluye `op.create_table` para `reviews` y `review_response_drafts` con
`if_not_exists`-equivalente semántico (Alembic no lo soporta nativamente — la
convención es `try/except` con `sqlalchemy.exc.ProgrammingError` en el `upgrade()`).

Rejected: reutilizar la migración `96d526599bc1_domain_foundation_financial.py`
que ya crea y descarta — eso sería resucitar el `downgrade()` y dejaría la serie
imposible de mantener. Cada capability crea sus tablas en su propia migración;
`domain-foundation-financial` ya documentó que no era propietaria de las tablas.

### D16 — Pipeline de análisis fuera del `POST` pero en el mismo proceso del worker

**Chosen:** el job `classify_reviews` (Celery, cada 5 min) usa
`run_for_every_tenant` de `app.scheduler.runner` (igual que `classify_incidents`),
abre sesión marcada por tenant con `bind_session_to_tenant`, instancia
`ClassifyPendingReviewsUseCase(analyzer=MockReviewAnalyzer(),
draft_generator=MockReviewDraftGenerator(), reviews=…, drafts=…, timeline=…)`,
y barre `WHERE ai_summary IS NULL AND attempts < 3`. Una excepción no controlada
del adaptador de análisis se registra con `logger.exception(...)` y la reseña queda
con `attempts += 1`; al tercer fallo, `attempts = 3` y el siguiente ciclo la ignora
(queda pendiente de triaje manual, igual que R2.4 del proposal).

Rejected: cola en Redis con publish/subscribe — más infraestructura para un
volumen bajo (decenas de reseñas por día en MVP), y complica el camino de
reintento.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Domain — enums | `backend/app/reviews/domain/enums.py` | añadir `RecurringIssueTag` (nuevo, 9 miembros), mantener los tres enums existentes |
| Domain — entities | `backend/app/reviews/domain/entities.py` | mantener dataclasses existentes; añadir `Review.recurring_issues` con `__post_init__` que degrada a `[OTHER]` y registra warning; añadir métodos `mark_drafted()`, `approve()`, `ignore()`, `mark_posted_manually()`, `mark_classified_low_confidence()`, `increment_attempts()`, `assign_analysis()`; misma forma en `ReviewResponseDraft.edit()` y `.approve()` |
| Domain — value objects | `backend/app/reviews/domain/value_objects.py` (nuevo) | `ReviewAnalysis` (confidence, sentiment, summary, recurring_issues, vocabulary), `GeneratedDraft` (content, confidence, language, vocabulary, template_version) — ambos con `__post_init__` que rechaza por construcción |
| Domain — ports | `backend/app/reviews/domain/ports.py` (nuevo) | `AIReviewAnalyzer`, `AIReviewDraftGenerator` (los dos `Protocol` de D1); `ReviewRepository` (8 métodos: `add`, `get`, `save`, `list_for_property`, `list_for_tenant`, `count_by_sentiment_for_property`, `aggregate_recurring_issues_for_property`, `list_pending_classification`); `ReviewResponseDraftRepository` (4 métodos: `add`, `get`, `save`, `get_for_review`) |
| Domain — language | `backend/app/reviews/domain/language.py` (nuevo) | `detect(content) -> str \| None` con stop-words ES/EN (D14) |
| Domain — templates | `backend/app/reviews/domain/templates.py` (nuevo) | `REVIEW_DRAFT_TEMPLATES` (6 entradas), `REVIEW_DRAFT_TEMPLATES_VERSION`, `REVIEW_DRAFT_VOCABULARY` (frozenset), `INTENTS_WITHOUT_DRAFT` (frozenset con `IGNORED`/`POSTED_MANUALLY`), `assert_in_catalogue(...)` |
| Domain — repositories | `backend/app/reviews/domain/repositories.py` (nuevo) | los dos puertos como `Protocol` siguiendo el patrón `messaging/domain/repositories.py` |
| Domain — notifications | `backend/app/reviews/domain/notifications.py` (nuevo) | `build_review_response_approved_log(...)` — la fila que se escribe en `notification_logs` cuando una reseña pasa a `APPROVED` (R6.2). Disciplina de `maintenance/domain/notifications.py` |
| Domain — exceptions | `backend/app/reviews/domain/exceptions.py` (nuevo) | `InvalidReviewTransitionError`, `ReviewValidationError`, `ReviewNotFoundError`, `DraftLanguageUnsupportedError`, `ReviewLanguageInferenceError` |
| Application — use cases | `backend/app/reviews/application/use_cases.py` (nuevo) | `CreateReviewUseCase`, `ListReviewsUseCase`, `GetReviewUseCase`, `GetReviewDraftUseCase`, `ApproveReviewUseCase`, `IgnoreReviewUseCase`, `MarkPostedManuallyUseCase`, `RegenerateReviewDraftUseCase`, `EditReviewDraftUseCase`, `ListReviewsSummaryForPropertyUseCase`, `ClassifyPendingReviewsUseCase` (job) |
| Infrastructure — repositories | `backend/app/reviews/infrastructure/repositories.py` (nuevo) | `SqlAlchemyReviewRepository`, `SqlAlchemyReviewResponseDraftRepository` con JOIN explícito a `reviews` para acotar `review_response_drafts` (R1.1) |
| Infrastructure — AI | `backend/app/reviews/infrastructure/ai.py` (nuevo) | `MockReviewAnalyzer` (keyword-based, mismo patrón que `RuleBasedIncidentClassifier`); `MockReviewDraftGenerator` (catálogo cerrado, mismo patrón que `MockAIAdapter`) |
| Infrastructure — models | `backend/app/reviews/infrastructure/models.py` | los dos modelos ya están; añadir índice `ix_reviews_property_id_status` para acelerar el listado por propiedad con estado |
| API — schemas | `backend/app/reviews/api/schemas.py` (nuevo) | `CreateReviewRequest`, `ReviewResponse`, `ReviewDraftResponse`, `ReviewSummaryResponse`, `ReviewResponseActionRequest` (con `Literal["APPROVE", "IGNORE", "MARK_POSTED", "EDIT"]`), `ReviewPageResponse` (envelope §23) |
| API — router | `backend/app/reviews/api/router.py` (nuevo) | los siete endpoints con `require(...)` (D11) |
| API — dependencies | `backend/app/reviews/api/dependencies.py` (nuevo) | `get_review_use_cases(...)` que cablea los puertos |
| API — errors | `backend/app/reviews/api/errors.py` (nuevo) | mapea las excepciones de dominio al sobre `{error: {code, message, details}}` |
| Scheduler — task | `backend/app/scheduler/tasks.py` | añadir `classify_reviews` (cada 5 min, mismo TTL que `classify_incidents`); registrar en `CADENCES` |
| Scheduler — schedule | `backend/app/scheduler/schedule.py` | añadir `classify_reviews: 300` (5 min) y registrar en `beat_schedule()` |
| Auth — policy | `backend/app/auth/domain/policy.py` | añadir 5 permisos al `Permission` enum + `ROLE_PERMISSIONS` según D3 |
| Tenants — entity | `backend/app/tenants/domain/entities.py` | añadir `review_recurring_issues_top_n: int = 5` a `TenantConfig` con `_require_positive_int`; misma forma de validación que `auto_create_cleaning_task` |
| Tenants — schema | `backend/app/tenants/api/schemas.py` | añadir `review_recurring_issues_top_n: int | None = None` a `TenantConfigPatch` (Pydantic, `ge=1, le=50`) |
| Tenants — model + migration | `backend/app/tenants/infrastructure/models.py`, migración nueva | añadir columna `review_recurring_issues_top_n INT NOT NULL DEFAULT 5` con CHECK |
| Notifications — enum | `backend/app/notifications/domain/enums.py` | añadir `REVIEW_RESPONSE_APPROVED` (D9) |
| Notifications — escalation | `backend/app/notifications/domain/escalation.py` | añadir entrada en `_POLICY` con SLA opcional (None) y `recipient_role=PROPERTY_MANAGER`/`TENANT_OWNER` (manager-or-owner fallback) |
| Timeline — enum | `backend/app/timeline/domain/enums.py` | añadir `REVIEW_CREATED`, `REVIEW_DRAFT_EDITED`, `REVIEW_CLASSIFIED_LOW_CONFIDENCE`, `REVIEW_IGNORED`, `REVIEW_POSTED_MANUALLY` (D8) |
| Timeline — rendering | `backend/app/timeline/domain/rendering.py` | añadir traducciones ES/EN para los cinco eventos nuevos (D8) |
| Timeline — schema | `backend/alembic/versions/<baseline>` | ampliar el enum `timeline_event_type` con los cinco nombres (igual que la baseline actual con `REVIEW_IMPORTED`/`REVIEW_RESPONSE_DRAFTED`/`REVIEW_RESPONSE_APPROVED`) |
| Migración nueva | `backend/alembic/versions/<rev>_revenue_reviews.py` | crea `reviews` y `review_response_drafts` con sus FKs, índices y defaults (D15); amplía el enum `review_channel`/`review_sentiment`/`review_status` con el nombre nativo del Postgres enum; **NO** amplía `timeline_event_type` (eso entra con su propia migración siguiendo el patrón del baseline) |
| Migración nueva | `backend/alembic/versions/<rev>_revenue_reviews_tenant_config.py` | añade `review_recurring_issues_top_n` a `tenant_configs` |
| Migración nueva | `backend/alembic/versions/<rev>_revenue_reviews_timeline_events.py` | amplía el enum `timeline_event_type` con los cinco nombres (D8) |
| Tests — review | `backend/tests/reviews/` (nuevo) | `test_tenant_isolation.py` (R1.3), `test_state_machine.py` (R4.1), `test_draft_templates.py` (R3.2), `test_no_draft_can_promise_what_rule_10_forbids` (R3.4), `test_pipeline_classification.py` (R2), `test_recurring_issues_vocabulary.py` (R2.2), `test_language_detection.py` (R5.1, D14), `test_review_endpoints.py` (R5) |
| Specs | `sdd/specs/auth-tenancy.md`, `sdd/specs/api-contract.md`, `sdd/specs/notifications-inbox-web.md`, `sdd/steering/security.md` | modificar para añadir permisos, rutas, tipo de notificación y entradas del censo (R1.7, R6, OQ4) |
| Spec nueva | `sdd/specs/revenue-reviews.md` (nuevo, al archivar) | el módulo `reviews` siguiendo el formato de `sdd/specs/messaging-ai.md` |
| Docs | `docs/reviews.md` (nuevo) | cómo se opera la capability, mismo nivel que `docs/messaging-ai.md` |
| OpenAPI | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | regenerados (el script documenta `cd frontend && npm run api:check` — ver nota de `local-environment.md`) |

## Data & interfaces

### Schema

**Migración nueva `revenue_reviews`:**

```python
# reviews
op.create_table(
    "reviews",
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
    sa.Column("property_id", sa.Uuid, sa.ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False),
    sa.Column("reservation_id", sa.Uuid, sa.ForeignKey("reservations.id", ondelete="RESTRICT"), nullable=True),
    sa.Column("external_id", sa.String(200), nullable=True),
    sa.Column("channel", sa.Enum("AIRBNB", "BOOKING", "GOOGLE", "MANUAL", "OTHER", name="review_channel", native_enum=True), nullable=False),
    sa.Column("reviewer_name", sa.String(200), nullable=True),
    sa.Column("rating", sa.Numeric(3, 1), nullable=True),
    sa.Column("content", sa.Text, nullable=True),
    sa.Column("language", sa.String(5), nullable=True),
    sa.Column("sentiment", sa.Enum("POSITIVE", "NEUTRAL", "NEGATIVE", name="review_sentiment", native_enum=True), nullable=True),
    sa.Column("ai_summary", sa.Text, nullable=True),
    sa.Column("recurring_issues", postgresql.JSONB, nullable=True),
    sa.Column("status", sa.Enum("NEW", "DRAFTED", "APPROVED", "POSTED_MANUALLY", "IGNORED", name="review_status", native_enum=True), nullable=False, server_default="NEW"),
    sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("classification_attempts", sa.Integer, nullable=False, server_default="0"),
)
op.create_index("ix_reviews_tenant_id", "reviews", ["tenant_id"])
op.create_index("ix_reviews_property_id_status", "reviews", ["property_id", "status"])
op.create_index("ix_reviews_tenant_id_published_at", "reviews", ["tenant_id", "published_at"])

# review_response_drafts
op.create_table(
    "review_response_drafts",
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("review_id", sa.Uuid, sa.ForeignKey("reviews.id", ondelete="RESTRICT"), nullable=False, unique=True),
    sa.Column("draft_content", sa.Text, nullable=False),
    sa.Column("language", sa.String(5), nullable=False),
    sa.Column("ai_generated", sa.Boolean, nullable=False, server_default=sa.text("true")),
    sa.Column("edits_count", sa.Integer, nullable=False, server_default="0"),  # D5 / OQ4 resuelto
    sa.Column("approved_by", sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
)
op.create_unique_constraint("uq_review_response_drafts_review_id", "review_response_drafts", ["review_id"])
```

`classification_attempts` se añade al esquema (no en el PRD §7.20, pero es la columna
que sostiene R2.4 — la pipeline incrementa el contador y al llegar a 3 la reseña
deja de reintentarse). Es una desviación menor del PRD documentada como
`ASSUMPTION` en el proposal; se anota para revisión al archivar.

**Migración `revenue_reviews_tenant_config`:**

```python
op.add_column(
    "tenant_configs",
    sa.Column("review_recurring_issues_top_n", sa.Integer, nullable=False, server_default="5"),
)
op.create_check_constraint(
    "ck_tenant_configs_review_recurring_issues_top_n_positive",
    "tenant_configs",
    "review_recurring_issues_top_n BETWEEN 1 AND 50",
)
```

**Migración `revenue_reviews_timeline_events`:** `ALTER TYPE timeline_event_type
ADD VALUE ...` con los cinco nombres nuevos, en cinco sentencias idempotentes
(`IF NOT EXISTS` no existe en `ADD VALUE` antes de Postgres 12.5; se documenta
el matiz en el cuerpo de la migración y se usa `try/except`).

### API contracts

| Ruta | Método | Permiso | Body / query | Respuesta |
|---|---|---|---|---|
| `/api/v1/reviews` | `POST` | `CREATE_REVIEW` | `CreateReviewRequest` (R5.1) | `201 ReviewResponse` (R5.2) |
| `/api/v1/reviews` | `GET` | `READ_REVIEWS` | `?page&per_page&property_id&channel&sentiment&status&rating_min&rating_max&date_from&date_to` (R5.3) | `200 ReviewPageResponse` (envelope §23) |
| `/api/v1/reviews/{id}` | `GET` | `READ_REVIEWS` | — | `200 ReviewResponse` (R5.4) |
| `/api/v1/reviews/{id}/response` | `GET` | `READ_REVIEWS` | — | `200 ReviewDraftResponse` (R5.4) |
| `/api/v1/reviews/{id}/response` | `POST` | `APPROVE_REVIEW` (regenerar) | `{}` o `{language?}` | `200 ReviewDraftResponse` |
| `/api/v1/reviews/{id}/response` | `PATCH` | `APPROVE_REVIEW`/`IGNORE_REVIEW`/`MARK_REVIEW_POSTED` | `{action, draft_content?}` (R3.5, R4.2) | `200 ReviewResponse` o `204` |
| `/api/v1/properties/{id}/reviews/summary` | `GET` | `READ_REVIEWS` | `?window_days=90&top_n?` | `200 ReviewSummaryResponse` (R5.5) |

### Timeline events

| Evento | Actor | Metadata | Severidad |
|---|---|---|---|
| `REVIEW_CREATED` | `USER` (manager/owner) | `{review_id, property_id, channel}` | INFO |
| `REVIEW_RESPONSE_DRAFTED` | `SCHEDULER` (job) | `{review_id, property_id, sentiment, template_version}` | INFO |
| `REVIEW_DRAFT_EDITED` | `USER` (manager/owner) | `{review_id, property_id}` | INFO |
| `REVIEW_CLASSIFIED_LOW_CONFIDENCE` | `SCHEDULER` (job) | `{review_id, property_id, sentiment, confidence}` | WARNING |
| `REVIEW_RESPONSE_APPROVED` | `USER` | `{review_id, property_id}` | INFO |
| `REVIEW_IGNORED` | `USER` | `{review_id, property_id}` | INFO |
| `REVIEW_POSTED_MANUALLY` | `USER` | `{review_id, property_id}` | INFO |

Los tres primeros ya tienen traducción; los otros cinco se añaden a
`TIMELINE_TITLE_TEMPLATES`.

### NotificationType

`REVIEW_RESPONSE_APPROVED` (D9). Una entrada nueva en `_POLICY` de
`backend/app/notifications/domain/escalation.py` con `sla_minutes=None` y
`recipient_resolver="managers_or_owners"`. Sin plazo propio — R6.2 lo dice.

### TenantConfig

`review_recurring_issues_top_n: int = 5`. Validación `1..50` en
`TenantConfig.update(...)` por simetría con `auto_create_cleaning_task`. La columna
acepta `PATCH /api/v1/tenants/{id}/config` (regla de los settings que
`auth-tenancy` ya fija).

### Env / config

Ninguna variable nueva en `.env.example` — la pipeline es asíncrona con el worker
existente, no introduce `REDIS_URL` ni nada.

## Risks & mitigations

1. **Alembic y el `ADD VALUE` de Postgres**: el `ALTER TYPE` para ampliar
   `timeline_event_type` no puede ejecutarse dentro de una transacción hasta
   Postgres 12.5+. Se documenta en la migración y se separa el `ADD VALUE` del
   resto, siguiendo el patrón que la baseline original usó. Mitigación: probar la
   migración en el stack del worktree antes de archivarla; si Postgres local es
   <12.5, marcar el paso como manual (no aplica al target del proyecto, que es 16).
2. **Concurrencia en `classify_reviews`**: dos workers podrían intentar clasificar
   la misma reseña. Mitigación: el job usa `SELECT ... FOR UPDATE SKIP LOCKED`
   sobre las filas con `ai_summary IS NULL AND classification_attempts < 3`,
   patrón análogo al que `process_webhook_events` ya usa. La columna
   `classification_attempts` se incrementa en la misma transacción que la
   actualización de `ai_summary`/`sentiment`/`recurring_issues`.
3. **`RecurringIssueTag.OTHER` como degradación silenciosa**: si el adaptador
   inventa una etiqueta, se degrada a `OTHER` y se registra un warning. Si el
   warning pasa desapercibido, perdemos señal de que el catálogo se quedó corto.
   Mitigación: el test `test_recurring_issues_vocabulary` barre
   `backend/app/reviews/infrastructure/` y verifica que cada etiqueta escrita
  pertenece al enum; las degradaciones se loguean con `logger.warning(...)` y se
   emiten como `incidents.classification_failed` (métrica, no fila) con
   `tenant_id`/`review_id`/etiqueta-origen. Mismo mecanismo que R2.4 del proposal.
4. **Posting a mano**: R4.4 lo dice literal y `POSTED_MANUALLY` no invoca al PMS.
   El adapter de PMS no entra en este módulo — el cambio de estado lo hace una
   persona fuera del sistema. Riesgo: que un futuro autor añada un
   `PMSAdapter.post_review(...)` aquí. Mitigación: el módulo no importa
   `app/integrations/` en ninguna capa (verificable con `tests/test_layering.py`).
5. **Detección de idioma en reseñas cortas**: una reseña sin palabras reconocibles
   queda con `language = NULL` (D14 + A2 del proposal). Riesgo: el catálogo de
   plantillas necesita idioma. Mitigación: el caso de uso `CreateReviewUseCase`
   rechaza con `422` si la reseña no es clasificable y `language` no se infiere;
   el manager puede entonces pasar `language` explícito en el body. Test cubre
   el caso.
6. **Worktree con `REVIEW_*` en baseline**: el enum `timeline_event_type` ya
   contiene tres nombres de reseñas, pero ningún módulo los emite. Riesgo: un
   worktree recién levantado pasa los tests sin que `reviews` exista. Mitigación:
   el `STATE.md` ya fija que `revenue-reviews` se construye antes de merge, y el
   baseline actual no impide arrancar — los nombres pre-aprobados son
   preparativos, no código vivo.
7. **El catálogo de plantillas es chico (6 entradas)**: PRD §18 dice
   "respuesta consistente con el tono del producto", no "un párrafo único por
   combinación de sentimiento × idioma × variante". Riesgo: la IA real puede
   encontrar 6 entradas insuficientes. Mitigación: el catálogo es versionado
   (`REVIEW_DRAFT_TEMPLATES_VERSION`) y `assert_in_catalogue(...)` rechaza
   cualquier `content` que no esté en él; ampliar el catálogo es añadir una
   constante, no un cambio de arquitectura. Roadmap: si hace falta más
   variedad, el design del proveedor real lo decide.

## Open questions

### OQ1 — ¿`classification_attempts` como columna nueva o `attempts` se lleva en `recurring_issues`?

El PRD §7.20 no nombra esta columna. **Recomendación**: añadirla como
`classification_attempts INT NOT NULL DEFAULT 0` y declararla como `ASSUMPTION`
en la spec — es la única forma de sostener el contrato R2.4 ("hasta tres
intentos; al tercero, queda pendiente de triaje manual sin reintentos
automáticos") sin un job que recorra `audit_logs` para contar reintentos. Si el
design decide que el intento se mide por timestamps en `updated_at`/`audit_logs`,
se ahorra la columna y se complica el job; no lo recomiendo, pero está abierto.

### OQ3 — ¿El `GET /reviews/{id}/response` para managers/owners autenticados muestra borradores en `IGNORED`?

R5.4 lo lista como ruta, pero una reseña ignorada no tiene borrador y devolver
`404` o `200 {draft: null}` cambia la forma del frontend. **Recomendación**:
`404` indistinguible, igual que cualquier otra "no existe" — el manager ve la
reseña en el listado y la pantalla de detalle sabe que está `IGNORED` por el
campo `status` de `ReviewResponse`. Pero hay una alternativa razonable (devolver
`200 {draft: null}` y dejar que el frontend decida), y la decisión es del
frontend, no del backend. Lo anoto aquí para que la persona que diseñe
`conversations-inbox`-análogo de reseñas (`/reviews` UI) lo decida antes de
empezar a tareas.

### Resolved during the gate

- **OQ2 (recipient of `REVIEW_RESPONSE_APPROVED`)** — aceptado: `managers_or_owners`,
  con `RoleRecipients.managers_or_owners` y entrada en `_POLICY` con
  `recipient_resolver="managers_or_owners"`. Reflejado en D9.
- **OQ4 (`edits_count` en `review_response_drafts`)** — aceptado: añadir
  `edits_count INT NOT NULL DEFAULT 0`. Reflejado en D5 y en el esquema Alembic
  arriba. Desviación menor del PRD §7.21 documentada como `ASSUMPTION` al
  archivar.
- **OQ5 (diagrama de secuencia)** — aceptado: diferir al archivado, con la
  spec ya escrita. Sigue el patrón de `maintenance.md` y `messaging-ai.md`.