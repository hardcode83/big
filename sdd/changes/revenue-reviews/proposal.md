# Proposal: revenue-reviews

## Why

La gestión de reseñas que hacía MAGNO no tiene hoy módulo que la reemplace: no existe ninguna
entidad `Review` ni `ReviewResponseDraft` en el esquema, no hay endpoints que las lean o las
escriban, y ninguna fuente externa las importa. Mientras tanto, la IA del proyecto —el
`MockAIAdapter` de `messaging-ai` y el `IncidentClassifier` de `maintenance`— ya está en pie, así
que la herramienta para hacer la mitad del trabajo está, pero **no encuentra con qué trabajar**.

PRD §18 ("Gestión de reseñas") fija un flujo de seis pasos que termina en aprobación humana
**sin** posting automático en OTAs. La entrada del roadmap `revenue-reviews` lo desglosa en
cinco capacidades —`Review` + `ReviewResponseDraft`, análisis de sentimiento, detección de
problemas recurrentes, borrador de respuesta y aprobación humana— y deja escrito el motivo de
existir como change aparte: se separó de `revenue` el 2026-08-16 porque agrupaba cuatro
capacidades distintas (reseñas, liquidaciones, pricing, ajustes), cada una con su dominio. La
dependencia (`needs: messaging-ai`) está resuelta desde el 2026-08-17.

Fuente: entrada del roadmap `revenue-reviews` (línea 234 de `sdd/roadmap.md`); PRD §18 (flujo),
PRD §7.20-7.21 (entidades), PRD §26.24 (orden de desarrollo).

## What changes

Tras este change existe un módulo backend `reviews` con las dos entidades del PRD §7.20-7.21,
los puertos de repositorio, una pipeline de análisis de IA (sentimiento, resumen, problemas
recurrentes) y de borrador de respuesta, una ruta de aprobación humana, y una API REST para que
manager/owner cree, liste, apruebe, ignore y publique manualmente reseñas. **No** se publica
nada en OTAs: el flujo termina en `status = POSTED_MANUALLY` y el posting lo hace una persona
fuera del sistema, como prescribe PRD §18. **No** entra UI en este change — la pantalla del
manager/owner para operar la bandeja es un change aparte (mismo criterio que `messaging-ai` BE
y `conversations-inbox` FE).

La columna `reviews.recurring_issues` (JSONB libre) y los tres campos donde aterriza prosa del
huésped (`reviews.content`, `reviews.ai_summary`, `review_response_drafts.draft_content`) entran
en el censo de la regla 11 de `steering/security.md` con la forma y el escritor que esa regla
prescribe.

## Requirements

### R1 — Persistencia de `Review` y `ReviewResponseDraft` con aislamiento por tenant

**As a** manager, **I want** que las reseñas de mis viviendas vivan en tablas con la misma forma
del PRD y con aislamiento estricto por tenant, **so that** ningún módulo futuro tenga que
duplicar la política de scoping ni inventar el censo de campos sensibles.

Acceptance criteria:

1. THE SYSTEM SHALL crear las tablas `reviews` y `review_response_drafts` en una migración
   Alembic siguiendo la forma exacta de PRD §7.20 y §7.21, con `tenant_id UUID NOT NULL` en
   `reviews` (y por tanto en la join) y declaración explícita de la asimetría: `messages` no
   lleva `tenant_id` y se acota por JOIN con `conversations`; **`reviews` sí lleva `tenant_id`
   propio** porque no hay agregado padre del que colgarse, y la ausencia de la columna obligaría
   al JOIN con `properties` que aquí no tiene justificación de modelo.
2. THE SYSTEM SHALL declarar dos puertos de repositorio en `reviews` —uno por raíz de
   agregado— con los métodos que esta capability consume: `ReviewRepository` (`add`, `get`,
   `save`, `list_for_property`, `list_for_tenant`, `count_by_sentiment_for_property`,
   `aggregate_recurring_issues_for_property`) y `ReviewResponseDraftRepository` (`add`, `get`,
   `save`, `get_for_review`).
3. THE SYSTEM SHALL demostrar con test de aislamiento de tenant propio que un tenant no lee ni
   escribe reseñas de otro en **cada** vía de acceso: alta, detalle, listado por propiedad,
   listado por tenant, aprobación, ignorado, marcado como publicada manualmente y borrador de
   respuesta. La regla 1 de `steering/security.md` se aplica aquí como en cualquier otro módulo
   nuevo.
4. THE SYSTEM SHALL exigir que toda `Review` rechace en construcción un `rating` fuera de
   `1.0..5.0` (un decimal), un `channel` que no sea miembro del enum `ReviewChannel`, un
   `sentiment` que no sea miembro de `ReviewSentiment` o un `status` que no sea miembro de
   `ReviewStatus`. La restricción vive en el tipo, no en un barrido del esquema Pydantic que un
   adaptador pueda esquivar mudándose.
5. THE SYSTEM SHALL exigir `property_id` en toda `Review`, rechazándola en construcción si
   falta: la timeline (`TimelineEventFactory`) exige `property_id` no nulo para emitir los
   eventos del flujo (R6), y la misma razón que `messaging-ai` R1 da para `Conversation` aplica
   aquí — es una restricción de la capability, no del esquema.
6. THE SYSTEM SHALL tratar `reviews.content` como **prosa de tercero**: el valor no es nuestro,
   ningún código nuestro debe renderizar ahí un valor de la regla 3, y la columna se acota con
   tipo y longitud máxima sin pretender que sea estructurada. Misma excepción 4 de
   `steering/security.md` que `messages.content` cuando `sender_type = GUEST`.
7. THE SYSTEM SHALL auditar en `AuditLog` la creación, aprobación, ignorado y marcado manual de
   reseña, con el vocabulario cerrado `REVIEW_CREATED`, `REVIEW_APPROVED`, `REVIEW_IGNORED`,
   `REVIEW_POSTED_MANUALLY`. La regla 9 de `steering/security.md` no enumera aún `Review`, así
   que **la propuesta enumera aquí lo que se audita** y el design confirma que la enumeración
   cabe — si la regla 9 necesita un anexo por `Review`, queda como encargo al `/sdd:archive`.

### R2 — Pipeline de análisis de IA: sentimiento, resumen, problemas recurrentes

**As a** manager, **I want** que al crear una reseña el sistema analice sentimiento, genere
resumen y detecte problemas recurrentes de forma automática, **so that** vea la información
procesada y no la prosa cruda del huésped.

Acceptance criteria:

1. THE SYSTEM SHALL persistir `sentiment`, `ai_summary` y `recurring_issues` en cada `Review`
   creada, con `ai_summary` poblado **sólo** cuando la pipeline se completa — un fallo del
   adaptador deja la reseña con `sentiment = NEUTRAL`, `ai_summary = NULL` y `recurring_issues
   = []`, sin impedir la creación.
2. THE SYSTEM SHALL acotar `recurring_issues` a un conjunto cerrado de etiquetas —mínimo
   `wifi`, `noise`, `cleanliness`, `access`, `communication`, `location`, `value`,
   `amenities`, `other`— declarado como enum `RecurringIssueTag` en el dominio. La columna JSONB
   guarda **siempre** una lista de miembros del enum y nada más; cualquier valor no
   recognised por el tipo degrada a `other` y registra un warning, no se persiste tal cual.
3. WHEN el adaptador de análisis devuelve una confianza por debajo del umbral de tenant
   (`TenantConfig.ai_confidence_threshold`), THE SYSTEM SHALL marcar `sentiment = NEUTRAL`,
   fijar `ai_summary = NULL`, vaciar `recurring_issues` y escribir un evento `REVIEW_CLASSIFIED_LOW_CONFIDENCE`
   para que el caso sea visible sin enturbiar el resumen.
4. IF el adaptador de análisis falla, THEN THE SYSTEM SHALL dejar la reseña creada con
   `sentiment = NEUTRAL` y los tres campos de IA vacíos, registrando
   `reviews.classification_failed` con `tenant_id`, `review_id` y el tipo de error — nunca el
   contenido del huésped. La reseña vuelve a entrar en el siguiente ciclo de clasificación
   mientras `ai_summary IS NULL`, hasta tres intentos; al tercero, queda pendiente de triaje
   manual sin reintentos automáticos.
5. THE SYSTEM SHALL cubrir la pipeline con test de aislamiento por tenant (regla 1) que
   demuestre que reseñas de otro tenant no contaminan ni el agregado de `recurring_issues` ni
   el cálculo de `count_by_sentiment_for_property`.

### R3 — Borrador de respuesta generado por IA con revisión humana obligatoria

**As a** manager, **I want** que la IA proponga un borrador de respuesta que yo pueda editar y
aprobar, **so that** la respuesta al huésped sea consistente con el tono del producto y yo
mantenga el control sobre lo que se publica.

Acceptance criteria:

1. THE SYSTEM SHALL crear exactamente una fila `ReviewResponseDraft` por cada `Review`
   aprobada para responder, vinculada por `review_id UNIQUE`, con `ai_generated = TRUE`,
   `language` declarado en `SUPPORTED_LANGUAGES` y `draft_content` poblado por el adaptador de
   generación.
2. THE SYSTEM SHALL generar el borrador **desde plantillas constantes versionadas por
   sentimiento y por idioma** (`es`/`en`), **sin ningún hueco de interpolación** —ni `{...}`,
   ni `%s`, ni `f`-string— y un test recorre el catálogo y lo rechaza si aparece uno. Misma
   forma cerrada que `messaging-ai` R2 exige para `RESPONSE_VOCABULARY`: una constante es lo que
   alguien escribió, y eso lo guardan la revisión y la lista de frases prohibidas.
3. THE SYSTEM SHALL exigir que el borrador declare el **vocabulario cerrado** del que sale:
   `GeneratedDraft` rechaza en construcción un `content` que no pertenezca al vocabulario, una
   confianza fuera de `0..1` o un `language` que no esté en `SUPPORTED_LANGUAGES`. La
   comprobación vive en el tipo, no en un barrido del adaptador.
4. THE SYSTEM SHALL exigir **regla 10 de `steering/security.md` completa** sobre el borrador:
   no prometer reembolsos ni compensaciones, no admitir responsabilidad, no dar asesoría legal,
   no inventar disponibilidad ni códigos, no afirmar que un técnico va sin assignment real. Un
   test `test_no_draft_can_promise_what_rule_10_forbids` recorre el catálogo y falla en rojo si
   una frase del catálogo incumple.
5. THE SYSTEM SHALL permitir editar `draft_content` desde `status = DRAFTED` hasta `APPROVED`;
   la edición es siempre con actor del token, queda registrada en `AuditLog` con
   `REVIEW_DRAFT_EDITED` y nunca cambia `ai_generated` a `FALSE` — el campo es bitácora de
   origen, no de estado actual.
6. WHEN el manager o el owner aprueba (`PATCH /reviews/{id}/response` con
   `action = APPROVE`), THE SYSTEM SHALL fijar `approved_by` y `approved_at`, transicionar
   `Review.status` a `APPROVED` y bloquear la edición posterior del borrador.

### R4 — Aprobación humana y transición de estado explícita

**As a** propietaria, **I want** aprobar o ignorar cada reseña antes de cualquier publicación,
**so that** ninguna respuesta mía salga sin mi firma y pueda descartar reseñas que no requieren
contestación.

Acceptance criteria:

1. THE SYSTEM SHALL modelar `Review.status` con la máquina `NEW → DRAFTED → APPROVED |
   IGNORED → POSTED_MANUALLY`, transiciones vía un `ReviewStateMachine` que rechaza en
   construcción cualquier salto ilegal. La fila que ya está `POSTED_MANUALLY` o `IGNORED` no
   admite nuevas transiciones.
2. THE SYSTEM SHALL exigir permiso `APPROVE_REVIEW` para `PATCH /reviews/{id}/response` con
   `action = APPROVE` o `action = IGNORE`. La acción `POSTED_MANUALLY` requiere permiso
   `MARK_REVIEW_POSTED`; ambas se acotan por RBAC en backend (regla 2 de `steering/security.md`),
   no solo en frontend.
3. THE SYSTEM SHALL escribir `TimelineEvent REVIEW_RESPONSE_APPROVED` o `REVIEW_IGNORED` en
   la misma transacción que el cambio de estado, con `actor_user_id` del token y
   `property_id` de la reseña. Sin esa cláusula la excepción de la regla 9 sobre
   `property_state_transitions` no aplica aquí y la fila es exigible por construcción.
4. THE SYSTEM SHALL permitir transicionar `APPROVED → POSTED_MANUALLY` **sin** invocar al PMS:
   el cambio de estado lo hace una persona fuera del sistema, registrándolo después. La
   transición no desencadena ninguna llamada de red; el adapter de PMS no entra en este módulo
   y queda para `beds24-messaging-adapter` cuando proceda.

### R5 — Creación manual y listado de reseñas

**As a** manager, **I want** poder dar de alta una reseña a mano y listar las de mis
viviendas, **so that** pueda operar reseñas que no entran por PMS o que llegan por canal no
automatizado (teléfono, email, en persona).

Acceptance criteria:

1. THE SYSTEM SHALL exponer `POST /api/v1/reviews` con body validado: `property_id`,
   `channel` (obligatorio, miembro de `ReviewChannel`), `reviewer_name` (opcional hasta 200
   caracteres), `rating` (1.0–5.0), `content` (opcional hasta 4000 caracteres, sin
   validación de idioma), `language` (opcional, si falta se infiere de `content` con
   heurística de stop-words ES/EN, y un test cubre la inferencia), `reservation_id` (opcional).
2. THE SYSTEM SHALL responder `201` con la reseña creada y `sentiment = NEUTRAL`,
   `ai_summary = NULL`, `recurring_issues = []` si la pipeline de R2 aún no ha corrido — la
   pipeline se dispara asíncrono (R2.4) y la fila se actualiza sin volver a llamar al endpoint.
3. THE SYSTEM SHALL exponer `GET /api/v1/reviews` con paginación `?page&per_page`, filtros por
   `property_id`, `channel`, `sentiment`, `status`, `rating_min`/`rating_max`,
   `date_from`/`date_to`, y el envelope `{data, total, page, per_page, total_pages}` del
   PRD §23. Orden por defecto `published_at DESC` con nulos al final, igual que
   `messaging-ai` R7 para conversaciones.
4. THE SYSTEM SHALL exponer `GET /api/v1/reviews/{id}` y `GET /api/v1/reviews/{id}/response`
   con la misma política de aislamiento (regla 1) y `404` indistinguible entre "no existe",
   "es de otro tenant" y "no es accesible por tu rol".
5. THE SYSTEM SHALL exponer `GET /api/v1/properties/{id}/reviews/summary` con conteo por
   `sentiment` y top N de `recurring_issues` agregados de los últimos 90 días (N por defecto
   5, configurable por tenant en `TenantConfig.review_recurring_issues_top_n`). Este endpoint
   alimenta la card del dashboard rediseñado que `dashboard-activity-feed` o
   `dashboard-occupancy-series` ya pidieron como bloque (referencia: prospección de
   `dashboard-operational-kpis` en el roadmap, que lista "valoraciones" como candidato).

### R6 — Eventos de timeline y notificaciones

**As a** manager, **I want** que la creación, aprobación e ignorado de una reseña aparezca en
el timeline y dispare notificaciones a quien corresponde, **so that** no tenga que revisar la
bandeja de reseñas para enterarme de que algo cambió.

Acceptance criteria:

1. THE SYSTEM SHALL emitir `TimelineEvent REVIEW_CREATED` con `property_id` y
   `actor_user_id` del token en la misma transacción que la creación de la fila, y SHALL
   emitir `REVIEW_RESPONSE_DRAFTED` tras la pipeline de R3, ambos con metadata identificadora
   (`review_id`, `sentiment`) y nunca con el contenido del huésped (regla 11).
2. THE SYSTEM SHALL emitir `NotificationType.REVIEW_RESPONSE_APPROVED` al propietario del
   tenant cuando una reseña pasa a `APPROVED`, vía el `NotificationAdapter` que
   `access-notifications` ya tiene. No se introduce un emisor nuevo: se reutiliza el patrón de
   `notification-writers-gap`.
3. THE SYSTEM SHALL no emitir notificaciones en `NEW → DRAFTED` ni en `APPROVED → POSTED_MANUALLY`:
   la primera es ruido de la pipeline automática, y la segunda la ejecuta una persona que ya
   estaba mirando la fila.

## Out of scope

- **Posting automático en OTAs**. PRD §18 lo prohíbe explícitamente para el MVP. La
  transición a `POSTED_MANUALLY` la ejecuta una persona fuera del sistema y se registra después.
  Cualquier adapter de PMS que publique respuestas (`beds24-messaging-adapter` o un futuro
  `channex-review-adapter`) es otro change; este no lo hace ni lo menciona.
- **UI / frontend del manager**. La pantalla `/reviews` (listado, detalle, formulario de
  aprobación) es un change aparte, mismo criterio que `messaging-ai` BE / `conversations-inbox`
  FE. El roadmap marca esta entrada como `[BE]`; la sigue un `[FE]` que se工作计划ará cuando
  exista demanda o cuando `hardening-release` cierre la suite E2E.
- **Adaptador de IA real**. `MockReviewAnalyzer` y `MockDraftGenerator` son los únicos
  implementadores; un proveedor real implementa los mismos puertos y vive en
  `app/integrations/`. La forma exacta de los dos puertos es decisión de design (ver OQ1).
- **Importación desde PMS**. La entrada manual de R5 cubre el caso de hoy; la importación
  automática desde Beds24 / Channex la trae `beds24-messaging-adapter` o un futuro
  `pms-review-adapter`, no este change.
- **Reasignación de borrador entre managers**. Un `ReviewResponseDraft` aprobado por un
  manager no se reasigna a otro: el campo `approved_by` registra al autor y queda como
  auditoría. Si hace falta flujo de reasignación, es otro change.
- **Borradores múltiples por reseña**. Una reseña admite exactamente un borrador activo; el
  campo `review_id UNIQUE` en `ReviewResponseDraft` lo impone por esquema. Regenerar el
  borrador reemplaza la fila existente, no añade.
- **Búsqueda full-text sobre `content`**. Listado y filtros cubren el MVP; búsqueda libre es
  una mejora posterior que puede llegar con la pantalla de `/reviews` o con una entrada
  dedicada.

## Affected specs

- `sdd/specs/revenue-reviews.md` — *(no existe aún — se creará al archivar)*: el módulo, en
  la línea de `messaging-ai.md` y `maintenance.md`.
- `sdd/specs/auth-tenancy.md` — modificar: añadir los permisos `READ_REVIEWS`,
  `CREATE_REVIEW`, `APPROVE_REVIEW`, `IGNORE_REVIEW`, `MARK_REVIEW_POSTED` al `Permission` enum
  y a `ROLE_PERMISSIONS` para `TENANT_OWNER` y `PROPERTY_MANAGER` (los dos únicos roles que la
  PRD §6 enumera para esta capability; `CLEANER` y `TECHNICIAN` no tocan reseñas).
- `sdd/specs/api-contract.md` — modificar: las rutas de R5 entran en el contrato publicado.
- `sdd/specs/notifications-inbox-web.md` — modificar: añadir `REVIEW_RESPONSE_APPROVED` a la
  enumeración `NotificationType` que esa spec ya documenta como catálogo cerrado.
- `sdd/steering/security.md` — modificar: registrar las nuevas columnas en la tabla de la
  regla 11 con su forma y escritor. Las cuatro entradas (`reviews.content` prosa de tercero,
  `reviews.ai_summary` forma cerrada por sumidero, `review_response_drafts.draft_content`
  forma cerrada por plantilla, `reviews.recurring_issues` enum cerrado como array) declaran
  **solo** el nombre y el escritor; este proposal las enumera aquí para que la entrada del
  censo no aparezca huérfana al archivar.
- `sdd/specs/messaging-ai.md` — *opcional, depende de OQ1*: si el design decide reusar
  `AIAdapter` o extenderlo, esa spec cambia. Si decide un puerto nuevo, esta spec queda
  intacta y el censo de la regla 11 la ignora.

## Open questions (for `/sdd:design`)

### OQ1 — Puerto de IA: `AIReviewPort` nuevo, `AIAdapter` extendido, o `AIAdapter` reutilizado

La línea del roadmap lo señala: "hoy no hay puerto de IA compartido —`maintenance` declaró el
suyo propio (`IncidentClassifier`, su D1)— y estrenar un tercero aquí obligaría a reconciliar
los tres después". Las tres opciones que el design debe comparar:

- **(a) Reutilizar `AIAdapter` con un método nuevo `draft_review(review_id, language) -> GeneratedDraft`.**
  `messaging-ai` R2 prohíbe `classify_incident`, `validate_cleaning_photo`, `summarize_incident`
  y `draft_review_response` en `AIAdapter`, así que añadir `draft_review` contradice la decisión
  que el módulo `messaging` ya cerró en su design. Es la opción más barata en código pero más
  cara en cohesión.
- **(b) Declarar un nuevo puerto `AIReviewPort` en `reviews` con dos métodos,
  `analyze_review(*, content, language) -> ReviewAnalysis` y `generate_draft(*, review, language)
  -> GeneratedDraft`.** Respeta la decisión de `messaging-ai` y aísla la capability. Coherente
  con cómo `maintenance` resolvió lo mismo. Pero deja dos adaptadores de IA en producción
  (`MockAIAdapter` y `MockReviewAnalyzer`/`MockDraftGenerator`) cuando hay uno solo
  conceptualmente, y cualquier swap futuro a un proveedor real se hace dos veces.
- **(c) Declarar un `AIProvider` base con la firma común que las tres capabilities consumen
  (`classify_message`, `classify_incident`, `analyze_review`, `generate_response`,
  `generate_draft`) y dejar `messaging`/`maintenance`/`reviews` cada uno con su propia interfaz
  específica** que el proveedor implementa. Es el patrón hexagonal más correcto pero requiere
  un refactor de `messaging-ai` y `maintenance` que ningún change de `reviews` debería
  encabezar.

**Recomendación del proposal**: (b). Coherente con la decisión que `maintenance` ya tomó y con
la prohibición explícita de `messaging-ai` R2. Si el design decide (c), es un refactor que
debe vivir en su propio change (`ai-port-consolidation`), no aquí. La propuesta cierra
**sólo** la capability de `reviews`, no la arquitectura global de IA.

### OQ2 — Clasificación inicial: ¿síncrona al crear o por job?

R2 asume pipeline asíncrona (R2.4 dice "vuelve a entrar en el siguiente ciclo"). La
alternativa es ejecutar la pipeline dentro del `POST /api/v1/reviews` y devolver la reseña ya
analizada, asumiendo un mock O(10 ms). **Recomendación del proposal**: asíncrona — el mock es
rápido pero el adaptador real no lo será, y la diferencia entre las dos arquitecturas es
justamente lo que queremos validar antes de que un proveedor real entre en producción.

### OQ3 — Permisos por tenant o permisos globales

`auth-tenancy.md` concede permisos por rol, no por tenant. Esta capability no ve ningún caso
donde `TENANT_OWNER` o `PROPERTY_MANAGER` tengan permiso en un tenant y no en otro. **Recomendación
del proposal**: permisos por rol, sin permisos-por-tenant. Si un manager cambia de tenant
debería perder acceso, y eso es hoy del módulo de identidad — no de reseñas.

## Cómo se verificó que la propuesta es completa

Las cinco capacidades que el roadmap enuncia están cubiertas: R1 (entidades), R2 (análisis),
R3 (borrador + aprobación), R4 (máquina de estados + RBAC), R5 (alta manual + listado +
agregado), R6 (timeline + notificaciones). El posting a OTAs está en Out of scope por PRD.
La UI está en Out of scope por convención del proyecto (`messaging-ai` BE / `conversations-inbox`
FE). Las cuatro columnas de la regla 11 están declaradas en Affected specs. El OQ1 está
documentado porque es el único punto que **no** puede decidir la propuesta sin contradecir un
spec existente.

## ASSUMPTIONS

- **A1** — El catálogo de etiquetas de `recurring_issues` (R2.2) es el mínimo viable que PRD §18
  enuncia de forma no exhaustiva; el design puede ampliarlo si aparece demanda. La forma cerrada
  se mantiene siempre: añadir una etiqueta es añadir un miembro al enum, nunca meter un string
  libre.
- **A2** — El idioma de la reseña se infiere por heurística de stop-words ES/EN (R5.1); un
  resultado de baja confianza fija `language = NULL` y deja el campo para triaje humano, sin
  forzar un idioma incorrecto al catálogo de plantillas.
- **A3** — La métrica de "top N problemas recurrentes" se computa sobre los últimos 90 días
  (R5.5). Si el design prefiere 30 / 180 / configurable por tenant, es decisión suya.
- **A4** — Las cinco transiciones de `ReviewStatus` no se enumeran en la regla 9 de
  `steering/security.md` antes de este change; el design confirma que la enumeración de R1.7
  cabe como anexo o como vocabulario adicional sin reabrir la regla. Si hace falta anexo
  formal, queda como encargo al `/sdd:archive`.
