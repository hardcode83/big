# Reviews (`revenue-reviews`)

Capability del change `revenue-reviews` (PRD §18, §26.24). Esta página cuenta **qué
hace** el sistema, en presente, con criterios EARS. El *cómo se opera* está en
[`docs/reviews.md`](../docs/reviews.md); el contrato HTTP en `backend/openapi.json`.

## Purpose

El módulo `reviews` registra las reseñas que el huésped dejó sobre una vivienda,
analiza sentimiento/resumen/problemas recurrentes, propone un borrador de respuesta
desde un catálogo cerrado de plantillas, y deja la aprobación final al manager
u owner. La transición a `POSTED_MANUALLY` la ejecuta una persona fuera del
sistema; ninguna ruta invoca un PMS sobre reseñas (`beds24-messaging-adapter` y un
futuro `pms-review-adapter` son cambios aparte). **No incluye UI** — la pantalla
del manager es otro change (mismo criterio que `messaging-ai` BE y
`conversations-inbox` FE).

## Requirements

### R1 — Persistencia de `Review` y `ReviewResponseDraft` con aislamiento por tenant

- THE SYSTEM SHALL crear las tablas `reviews` y `review_response_drafts` en una
  migración Alembic siguiendo la forma exacta de PRD §7.20 y §7.21, con
  `tenant_id UUID NOT NULL` en `reviews` (y por tanto en el JOIN que une la tabla
  del borrador). `messages` no lleva `tenant_id` y se acota por JOIN con
  `conversations`; **`reviews` sí lleva `tenant_id` propio** porque no hay agregado
  padre del que colgarse, y la ausencia de la columna obligaría al JOIN con
  `properties` que aquí no tiene justificación de modelo.
- THE SYSTEM SHALL declarar dos puertos de repositorio —uno por raíz de agregado—
  con los métodos que esta capability consume: `ReviewRepository` (`add`, `get`,
  `save`, `list_for_property`, `list_for_tenant`, `count_by_sentiment_for_property`,
  `aggregate_recurring_issues_for_property`, `list_pending_classification`) y
  `ReviewResponseDraftRepository` (`add`, `get`, `save`, `get_for_review`).
- THE SYSTEM SHALL demostrar con test de aislamiento de tenant propio que un
  tenant no lee ni escribe reseñas de otro en cada vía de acceso: alta, detalle,
  listado por propiedad, listado por tenant, aprobación, ignorado, marcado como
  publicada manualmente, regenerar/editar borrador y resumen por propiedad. La
  regla 1 de `steering/security.md` se aplica aquí como en cualquier otro módulo
  nuevo.
- THE SYSTEM SHALL exigir que toda `Review` rechace en construcción un `rating`
  fuera de `1.0..5.0` (un decimal), un `channel` que no sea miembro del enum
  `ReviewChannel`, un `sentiment` que no sea miembro de `ReviewSentiment` o un
  `status` que no sea miembro de `ReviewStatus`. La restricción vive en el tipo,
  no en un barrido del esquema Pydantic.
- THE SYSTEM SHALL exigir `property_id` en toda `Review`, rechazándola en
  construcción si falta.
- THE SYSTEM SHALL tratar `reviews.content` como **prosa de tercero**: el valor
  no es nuestro, ningún código nuestro debe renderizar ahí un valor de la regla 3,
  y la columna se acota con tipo y longitud máxima. Misma excepción 4 de
  `steering/security.md` que `messages.content` cuando `sender_type = GUEST`.
- THE SYSTEM SHALL auditar en `AuditLog` la aprobación y el ignorado, con el
  vocabulario cerrado `REVIEW_APPROVED` y `REVIEW_IGNORED`. El diff de estado
  lleva el estado **previo** a la mutación (snapshot), no el posterior: la única
  forma de reconstruir qué estado tenía la fila antes de la acción sin
  reproducir el timeline. La creación (`REVIEW_CREATED`) y el marcado manual
  (`REVIEW_POSTED_MANUALLY`) son `TimelineEvent`s; el audit row llega con la
  acción de transición de estado, no con `REVIEW_CREATED`/`POSTED_MANUALLY`.

### R2 — Pipeline de análisis de IA: sentimiento, resumen, problemas recurrentes

- THE SYSTEM SHALL persistir `sentiment`, `ai_summary` y `recurring_issues` en cada
  `Review` creada, con `ai_summary` poblado **sólo** cuando la pipeline se completa
  — un fallo del adaptador deja la reseña con `sentiment = NEUTRAL`,
  `ai_summary = NULL` y `recurring_issues = []`, sin impedir la creación.
- THE SYSTEM SHALL acotar `recurring_issues` a un conjunto cerrado de etiquetas
  —mínimo `wifi`, `noise`, `cleanliness`, `access`, `communication`, `location`,
  `value`, `amenities`, `other`— declarado como enum `RecurringIssueTag` en el
  dominio. La columna JSONB guarda **siempre** una lista de miembros del enum y
  nada más; cualquier valor no reconocido degrada a `OTHER` y registra un warning,
  no se persiste tal cual.
- WHEN el adaptador de análisis devuelve una confianza por debajo del umbral de
  tenant (`TenantConfig.ai_confidence_threshold`), THE SYSTEM SHALL marcar
  `sentiment = NEUTRAL`, fijar `ai_summary = NULL`, vaciar `recurring_issues` y
  emitir un `REVIEW_CLASSIFIED_LOW_CONFIDENCE` para que el caso sea visible sin
  enturbiar el resumen.
- IF el adaptador de análisis falla, THEN THE SYSTEM SHALL dejar la reseña creada
  con `sentiment = NEUTRAL` y los tres campos de IA vacíos, registrando
  `reviews.classification_failed` con `tenant_id`, `review_id` y el tipo de error
  — nunca el contenido del huésped. La reseña vuelve a entrar en el siguiente
  ciclo de clasificación mientras `ai_summary IS NULL`, hasta tres intentos; al
  tercero, queda pendiente de triaje manual.
- THE SYSTEM SHALL cubrir la pipeline con test de aislamiento por tenant (regla 1)
  que demuestre que reseñas de otro tenant no contaminan ni el agregado de
  `recurring_issues` ni el cálculo de `count_by_sentiment_for_property`.

### R3 — Borrador de respuesta generado por IA con revisión humana obligatoria

- THE SYSTEM SHALL crear exactamente una fila `ReviewResponseDraft` por cada
  `Review` aprobada para responder, vinculada por `review_id UNIQUE`, con
  `ai_generated = TRUE`, `language` declarado en `SUPPORTED_LANGUAGES` y
  `draft_content` poblado por el adaptador de generación.
- THE SYSTEM SHALL generar el borrador **desde plantillas constantes versionadas
  por sentimiento y por idioma** (`es`/`en`), **sin ningún hueco de
  interpolación** —ni `{...}`, ni `%s`, ni `f-string`— y un test recorre el
  catálogo y lo rechaza si aparece uno. Misma forma cerrada que `messaging-ai`
  R2 exige para `RESPONSE_VOCABULARY`.
- THE SYSTEM SHALL exigir que el borrador declare el **vocabulario cerrado** del
  que sale: `GeneratedDraft` rechaza en construcción un `content` que no pertenezca
  al vocabulario, una confianza fuera de `0..1` o un `language` que no esté en
  `SUPPORTED_LANGUAGES`.
- THE SYSTEM SHALL exigir **regla 10 de `steering/security.md` completa** sobre
  el borrador: no prometer reembolsos ni compensaciones, no admitir
  responsabilidad, no dar asesoría legal, no inventar disponibilidad ni códigos,
  no afirmar que un técnico va sin assignment real. Un test
  `test_no_draft_can_promise_what_rule_10_forbids` recorre el catálogo y falla en
  rojo si una frase incumple.
- THE SYSTEM SHALL permitir editar `draft_content` desde `status = DRAFTED` hasta
  `APPROVED`; la edición es siempre con actor del token, queda registrada en
  `AuditLog` con `REVIEW_DRAFT_EDITED` y nunca cambia `ai_generated` a `FALSE`.
  `edits_count` es la columna que lleva el contador de iteraciones.
- WHEN el manager o el owner aprueba (`PATCH /reviews/{id}/response` con
  `action = APPROVE`), THE SYSTEM SHALL fijar `approved_by` y `approved_at`,
  transicionar `Review.status` a `APPROVED` y bloquear la edición posterior del
  borrador. La aprobación dispara una notificación `REVIEW_RESPONSE_APPROVED`
  resuelta por `RoleRecipients.managers_or_owners`.

### R4 — Aprobación humana y transición de estado explícita

- THE SYSTEM SHALL modelar `Review.status` con la máquina `NEW → DRAFTED → APPROVED
  | IGNORED → POSTED_MANUALLY`, transiciones vía métodos en la entidad
  (`mark_drafted`, `approve`, `ignore`, `mark_posted_manually`,
  `mark_classified_low_confidence`, `increment_attempts`, `assign_analysis`) que
  mutan `status` con `_assert_transition` y lanzan `InvalidReviewTransitionError`
  ante cualquier salto ilegal. La fila en `POSTED_MANUALLY` o `IGNORED` no admite
  nuevas transiciones.
- THE SYSTEM SHALL exigir permiso `APPROVE_REVIEW` para `PATCH /reviews/{id}/response`
  con `action = APPROVE`, `IGNORE_REVIEW` para `action = IGNORE`, y
  `MARK_REVIEW_POSTED` para `action = MARK_POSTED`. El acotado por RBAC vive en
  backend (regla 2 de `steering/security.md`), no solo en frontend.
- THE SYSTEM SHALL permitir transicionar `APPROVED → POSTED_MANUALLY` **sin**
  invocar al PMS: el cambio de estado lo hace una persona fuera del sistema,
  registrándolo después. La transición no desencadena ninguna llamada de red; el
  adapter de PMS no entra en este módulo.

### R5 — Creación manual y listado de reseñas

- THE SYSTEM SHALL exponer `POST /api/v1/reviews` con body validado: `property_id`,
  `channel` (obligatorio, miembro de `ReviewChannel`), `reviewer_name` (opcional
  hasta 200 caracteres), `rating` (1.0–5.0), `content` (opcional hasta 4000
  caracteres), `language` (opcional; si falta, se infiere de `content` con
  heurística de stop-words ES/EN; `422` si no se puede inferir).
- THE SYSTEM SHALL responder `201` con la reseña creada y `sentiment = NEUTRAL`,
  `ai_summary = NULL`, `recurring_issues = []` si la pipeline de R2 aún no ha
  corrido — la pipeline se dispara asíncrono y la fila se actualiza sin volver
  a llamar al endpoint.
- THE SYSTEM SHALL exponer `GET /api/v1/reviews` con paginación
  `?page&per_page`, filtros por `property_id`, `channel`, `sentiment`, `status`,
  `rating_min`/`rating_max`, `date_from`/`date_to`, y el envelope `{data, total,
  page, per_page, total_pages}` del PRD §23. Orden por defecto
  `published_at DESC` con nulos al final.
- THE SYSTEM SHALL exponer `GET /api/v1/reviews/{id}` y
  `GET /api/v1/reviews/{id}/response` con `404` indistinguible entre "no
  existe", "es de otro tenant" y "no es accesible por tu rol".
- THE SYSTEM SHALL exponer `GET /api/v1/properties/{id}/reviews/summary` con
  conteo por `sentiment` y top N de `recurring_issues` agregados de los últimos
  90 días (`N` por defecto `5`, configurable por tenant en
  `TenantConfig.review_recurring_issues_top_n`, rango `1..50`). Es el input del
  bloque "valoraciones" del dashboard rediseñado.

### R6 — Eventos de timeline y notificaciones

- THE SYSTEM SHALL emitir `TimelineEvent REVIEW_CREATED` con `property_id` y
  `actor_user_id` del token en la misma transacción que la creación de la fila, y
  SHALL emitir `REVIEW_RESPONSE_DRAFTED` tras la pipeline de R3. Ambos con
  `metadata` identificadora (`review_id`, `sentiment`) y nunca con el contenido
  del huésped (regla 11).
- THE SYSTEM SHALL emitir `NotificationType.REVIEW_RESPONSE_APPROVED` al
  propietario del tenant cuando una reseña pasa a `APPROVED`, vía el
  `NotificationDispatcher` que `access-notifications` ya tiene. Los destinatarios
  los resuelve `RoleRecipients.managers_or_owners` — no se introduce un emisor
  nuevo. La entrada en `_POLICY` de `escalation.py` existe con `sla_minutes=None`
  para mantener el catálogo cerrado contra el enum (R6.2 no fija SLA).
- THE SYSTEM SHALL no emitir notificaciones en `NEW → DRAFTED` ni en
  `APPROVED → POSTED_MANUALLY`: la primera es ruido de la pipeline automática, y
  la segunda la ejecuta una persona que ya estaba mirando la fila.

## Key files

- `backend/app/reviews/domain/` — `entities.py` (`Review`, `ReviewResponseDraft`),
  `enums.py` (`ReviewChannel`, `ReviewSentiment`, `ReviewStatus`,
  `RecurringIssueTag`), `ports.py` (puertos de repositorio y de IA), `value_objects.py`
  (`ReviewAnalysis`, `GeneratedDraft`), `templates.py` (`REVIEW_DRAFT_TEMPLATES`,
  `REVIEW_DRAFT_VOCABULARY`), `templates.py` (versión), `language.py` (detección
  ES/EN), `notifications.py` (`build_review_response_approved_log`).
- `backend/app/reviews/application/use_cases.py` — los once casos de uso del flujo
  (Create, List, Get, GetDraft, Approve, Ignore, MarkPostedManually, RegenerateDraft,
  EditDraft, ListSummary, ClassifyPending).
- `backend/app/reviews/infrastructure/` — `repositories.py` (SQLAlchemy adapters con
  `SELECT ... FOR UPDATE SKIP LOCKED` en `list_pending_classification`),
  `ai.py` (`MockReviewAnalyzer`, `MockDraftGenerator`), `models.py`.
- `backend/app/reviews/api/` — `router.py` (siete endpoints), `schemas.py`
  (`CreateReviewRequest`, `ReviewResponse`, `ReviewDraftResponse`,
  `ReviewSummaryResponse`, `ReviewResponseActionRequest`, `ReviewPageResponse`),
  `dependencies.py` (`get_review_use_cases`), `errors.py`.
- `backend/app/scheduler/tasks.py` — `classify_reviews` (Celery, cada 5 min).
- `backend/tests/reviews/` — `test_tenant_isolation.py`, `test_state_machine.py`,
  `test_draft_templates.py` (incluye `test_no_draft_can_promise_what_rule_10_forbids`),
  `test_recurring_issues_vocabulary.py`, `test_recurring_issues_read_coercion.py`,
  `test_pipeline_classification.py`, `test_review_endpoints.py`, `test_entities.py`,
  `test_value_objects.py`, `test_language.py`, `test_models.py`.
