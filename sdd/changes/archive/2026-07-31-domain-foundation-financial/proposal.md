# Proposal: domain-foundation-financial

## Why

El PRD §7 define 26 entidades de dominio. `domain-foundation-core` (§7.1-7.8) y `domain-foundation-ops` (§7.9-7.16) cerraron los dos primeros tercios; **quedan las 10 de §7.17-7.26**: pricing/financiero (`PricingRule`, `PriceRecommendation`, `OwnerApproval`, `Review`, `ReviewResponseDraft`, `OwnerStatement`, `Expense`) más los tres registros de sistema (`NotificationLog`, `AuditLog`, `WebhookEvent`).

No es solo completitud: **hay tres entradas del roadmap bloqueadas por entidades que solo existen aquí**.

- `reservations-webhooks` no pudo entrar en `reservations` precisamente porque `WebhookEvent` (§7.26) no existe — su nota lo dice con todas las letras: *"implementar una recepción que no persista lo que el PRD exige persistir habría sido peor que no tenerla"*.
- `celery-jobs` necesita `NotificationLog` (§7.24) para el SLA enforcement cada minuto (`steering/architecture.md`, PRD §8.3, §14).
- `user-management` declara dependencia explícita de `AuditLog` (§7.25) para registrar los cambios de rol, y `specs/reservations.md` dejó anotada como deuda con dueño el `AuditLog` de sus mutaciones.

Además `maintenance` (`OwnerApproval`) y `revenue` (pricing, statements, reviews) arrancan sobre estas tablas. Fuente: `docs/AutoHostAI_PRD_v5_Claude.md` §7.17-7.26 y §26.2-3.

Como en los dos changes hermanos, esto es **solo estructura de datos**: entidades Python puras, enums, modelos SQLAlchemy y una migración Alembic. Sin lógica de negocio.

## What changes

Existirán las 10 entidades de PRD §7.17-7.26 como dataclasses de dominio puras con sus enums, sus modelos SQLAlchemy 2.x fieles al esquema del PRD, y una migración Alembic encadenada sobre `e1eed2e039ee` (head actual) que crea sus 10 tablas y sus tipos `ENUM` nativos, reversible. Se reparten en **7 módulos de dominio**: `pricing`, `statements`, `notifications`, `reviews` y `audit` (nuevos), más `maintenance` e `integrations` (existentes). Con esto **el PRD §7 queda cubierto entero** y las tres entradas bloqueadas del roadmap se desbloquean.

No habrá repositorios, casos de uso, endpoints, cálculo de precios, consolidación de statements, envío de notificaciones ni escritura real de `AuditLog` — cada uno llega con el change que primero los necesite.

## Requirements

### R1 — Las 10 entidades como dominio puro, en su módulo

**As a** desarrollador del backend, **I want** cada entidad de §7.17-7.26 en el módulo de dominio que le corresponde y sin dependencias de framework, **so that** la regla de dependencia de `backend-architecture.md` se mantenga y los changes posteriores encuentren las entidades donde esperan.

Acceptance criteria:

1. WHEN se listan los módulos de dominio del backend, THE SYSTEM SHALL ubicar las entidades así: `pricing` → `PricingRule`, `PriceRecommendation`; `maintenance` → `OwnerApproval`; `reviews` → `Review`, `ReviewResponseDraft`; `statements` → `OwnerStatement`, `Expense`; `notifications` → `NotificationLog`; `audit` → `AuditLog`; `integrations` → `WebhookEvent`.
2. WHEN se crea un módulo nuevo, THE SYSTEM SHALL darle solo `domain/` (entidades + enums) e `infrastructure/` (modelos SQLAlchemy), sin `application/` ni `api/`, porque ningún caso de uso ni router los necesita todavía.
3. THE SYSTEM SHALL definir cada una de las 10 entidades como `@dataclass` simple sin métodos de mutación custom, igual que las 16 entidades de `domain-foundation-core`/`-ops`.
4. WHEN se ejecuta `backend/tests/test_layering.py`, THE SYSTEM SHALL demostrar que ningún `domain/entities.py` ni `domain/enums.py` de los módulos tocados importa `sqlalchemy`, `fastapi` ni `pydantic`.
5. THE SYSTEM SHALL no definir para ninguna de las 10 entidades puertos de repositorio (`Protocol`/ABC) ni casos de uso — se difieren al change que primero necesite persistirla.
6. WHEN se añadan los módulos `reviews` y `audit`, THE SYSTEM SHALL registrarlos como extensión explícita de la lista de dominios de `steering/architecture.md`, que hoy replica PRD §3.2 y no los contiene. **Decisión tomada en `/sdd:new`**, no un supuesto: se descartaron plegar `Review`/`ReviewResponseDraft` en `statements` (mezclaría reporting financiero con contenido de OTAs) y alojar `AuditLog` en `app/core/` (rompería la convención de que toda entidad de negocio vive en un módulo de dominio). Justificación de la divergencia con el PRD: `audit` es transversal exactamente igual que `timeline`, que el propio §3.2 ya lista como dominio de pleno derecho.

### R2 — Enums exactos del PRD, con nombre explícito para los inline

**As a** desarrollador, **I want** los enums con los valores literales del PRD y un nombre predecible, **so that** el código y la DB usen el vocabulario canónico sin traducciones ni colisiones.

Acceptance criteria:

1. THE SYSTEM SHALL reproducir literalmente los valores de los 10 enums de §7.17-7.26, sin traducir ni renombrar miembros.
2. WHERE el PRD declara el enum inline en la columna sin darle nombre (los 10 lo son), THE SYSTEM SHALL nombrarlo siguiendo la convención `<Entidad><Campo>` ya usada en `domain-foundation-ops`: `PriceRecommendationStatus`, `OwnerApprovalRelatedType`, `OwnerApprovalStatus`, `ReviewChannel`, `ReviewSentiment`, `ReviewStatus`, `OwnerStatementStatus`, `ExpenseCategory`, `NotificationChannel`, `NotificationStatus` — y marcarlo `ASSUMPTION` en el código.
3. THE SYSTEM SHALL mantener `NotificationChannel` (`EMAIL`/`WHATSAPP`/`PUSH`/`IN_APP`/`CONSOLE`), `ReviewChannel` (`AIRBNB`/`BOOKING`/`GOOGLE`/`MANUAL`/`OTHER`) y el ya existente `ConversationChannel` como tres enums distintos, sin reutilizarlos entre sí pese al nombre parecido — conjuntos de valores distintos, mismo criterio con el que `domain-foundation-ops` separó `IncidentSeverity` de `TimelineSeverity`.
4. THE SYSTEM SHALL dejar como `VARCHAR` y no como enum los campos que el PRD tipa así: `WebhookEvent.provider`, `WebhookEvent.event_type`, `NotificationLog.notification_type`, `NotificationLog.related_type`, `AuditLog.action`, `AuditLog.entity_type`.
5. IF un enum lo usa más de un módulo, THEN THE SYSTEM SHALL definirlo una sola vez en el módulo dueño de la entidad que lo usa primero e importarlo desde ahí, nunca duplicarlo.

### R3 — Esquema DB fiel a PRD §7.17-7.26

**As a** desarrollador, **I want** modelos SQLAlchemy que reproduzcan exactamente el esquema del PRD, **so that** los changes que persistan estas entidades no descubran divergencias entre el contrato documentado y la tabla real.

Acceptance criteria:

1. THE SYSTEM SHALL reproducir para cada entidad las columnas, tipos, nullability y `DEFAULT` del PRD, con los `DECIMAL` a la precisión declarada (`DECIMAL(10,2)` en importes, `DECIMAL(5,2)` en `max_daily_change_pct`, `DECIMAL(3,2)` en `confidence`, `DECIMAL(3,1)` en `rating`) y sin usar `float` en ningún campo monetario.
2. THE SYSTEM SHALL emitir todo `DEFAULT` del PRD también como `server_default` en el DDL, no solo como default de Python en el ORM (misma regla que `domain-foundation-core`).
3. THE SYSTEM SHALL crear las constraints e índices declarados: `UNIQUE(property_id, date)` en `price_recommendations`; `UNIQUE(tenant_id, property_id, period_start, period_end)` en `owner_statements`; `UNIQUE` sobre `review_response_drafts.review_id`; `INDEX(tenant_id, status, sla_deadline_at)` e `INDEX(related_type, related_id)` en `notification_logs`; `INDEX(tenant_id, entity_type, entity_id)` e `INDEX(tenant_id, actor_user_id, created_at DESC)` en `audit_logs`; `INDEX(provider, processed, received_at)` en `webhook_events`.
4. WHERE el PRD declara `created_at`/`updated_at`, THE SYSTEM SHALL usar `TimestampMixin` (`pricing_rules`, `reviews`, `review_response_drafts`, `owner_statements`, `notification_logs`); WHERE declara solo un timestamp de creación, THE SYSTEM SHALL declararlo a mano sin `updated_at` (`price_recommendations.created_at`, `expenses.created_at`, `audit_logs.created_at`, `webhook_events.received_at`); y WHERE no declara ninguno (`owner_approvals`, que tiene `requested_at`/`responded_at`), THE SYSTEM SHALL no añadir columnas que el PRD no pide.
5. THE SYSTEM SHALL mapear todo enum de dominio a un tipo `ENUM` nativo de Postgres con nombre explícito (`sa.Enum(X, name="...", native_enum=True)`), nunca autogenerado.
6. THE SYSTEM SHALL usar un tipo `Uuid` explícito en `mapped_column` para toda FK que referencie una tabla de otro módulo (`property_id`, `reservation_id`, `incident_id`, `pricing_rule_id`, `statement_id`, `review_id`, FKs a `users.id`), no solo la anotación `Mapped[uuid.UUID]` — mismo fix que `domain-foundation-core` D15.
7. THE SYSTEM SHALL usar `ON DELETE SET NULL` en las FKs nullable hacia `User` (`owner_approvals.responded_by`, `review_response_drafts.approved_by`, `expenses.approved_by`, `notification_logs.recipient_user_id`, `audit_logs.actor_user_id`) y `ON DELETE RESTRICT` en el resto, incluidas las nullable hacia no-`User` (`pricing_rules.property_id`, `reviews.reservation_id`, `expenses.statement_id`, `expenses.incident_id`).
8. THE SYSTEM SHALL declarar sin FK las tres referencias polimórficas del PRD (`owner_approvals.related_id`, `notification_logs.related_id`, `audit_logs.entity_id`), apuntadas por su columna de tipo textual asociada, y documentar en el código que la ausencia de FK es deliberada.
9. THE SYSTEM SHALL persistir las columnas `JSONB` (`weekday_modifiers`, `lead_time_rules`, `occupancy_rules`, `seasonality_rules`, `event_rules`, `recurring_issues`, `changes`, `payload`) sin validar su estructura interna en este change — los schemas de PRD §7.17 se validarán donde se consuman (`revenue`).

### R4 — Compatibilidad explícita con el aislamiento por tenant

**As a** responsable de seguridad, **I want** que las dos entidades que se salen del patrón `tenant_id NOT NULL` queden documentadas y probadas, **so that** el filtro global de `app/core/db.py` no genere una falsa sensación de cobertura ni oculte filas.

Acceptance criteria:

1. THE SYSTEM SHALL dar `tenant_id` FK obligatoria a `tenants.id` (vía `TenantScopedMixin`) a las 8 entidades a las que el PRD se lo declara así, y `UUIDPrimaryKeyMixin` a las 10.
2. WHERE el PRD declara `WebhookEvent.tenant_id` **nullable** (§7.26, *"nullable si no está autenticado aún"*), THE SYSTEM SHALL mantenerlo nullable y documentar la consecuencia: `tenant_scoped_classes()` selecciona por presencia de columna, así que en una sesión marcada con tenant el filtro `tenant_id == X` **excluye las filas con `tenant_id NULL`** — exactamente las que `reservations-webhooks` tendrá que procesar.
3. WHEN se consulta `webhook_events` desde una sesión marcada con un tenant, THE SYSTEM SHALL demostrar con un test de integración que las filas de `tenant_id NULL` no son visibles, dejando el comportamiento fijado antes de que `reservations-webhooks` construya encima.
   - **Decisión tomada en `/sdd:new`**: se descartó excluir `WebhookEventModel` del filtro con una lista de exención, porque abriría un mecanismo de bypass de la regla 1 de `steering/security.md` que hoy no existe; y se descartó hacer la columna `NOT NULL`, porque obligaría a resolver el tenant antes de persistir y un payload no atribuible se perdería en vez de quedar registrado para reproceso — justo lo que el PRD evita. El caso de uso real (leer los `NULL` para procesarlos) se resuelve donde aparezca, con una sesión sin marcar, igual que ya hacen Celery y el login anónimo (límite 2 del docstring de `_scope_statement_to_tenant`).
4. WHERE `ReviewResponseDraft` no tiene `tenant_id` propio (§7.21), THE SYSTEM SHALL scopearlo transitivamente por su FK obligatoria y única `review_id`, y documentarlo junto a los otros tres hijos ya conocidos (`messages`, `cleaning_checklist_completions`, `cleaning_photos`) en el límite 5 del docstring de `_scope_statement_to_tenant`.
5. THE SYSTEM SHALL añadir los módulos nuevos a `app/core/models_registry.py` (una línea por módulo, en el único sitio donde se mantiene la lista), de modo que el filtro global vea las tablas nuevas también en el proceso de la app y no solo en el de los tests.

### R5 — Migración Alembic encadenada y reversible

**As a** desarrollador, **I want** una migración que cree las 10 tablas sobre el esquema existente y sepa deshacerse, **so that** `make up` deje la DB al día sin pasos manuales y el esquema siga siendo reproducible desde cero.

Acceptance criteria:

1. THE SYSTEM SHALL añadir una sola migración con `down_revision = "e1eed2e039ee"` (head actual, `globally_unique_lower_email`) que cree las 10 tablas en orden de dependencia.
2. WHEN se ejecuta `alembic downgrade` hasta `e1eed2e039ee`, THE SYSTEM SHALL revertir exactamente esas 10 tablas y los tipos `ENUM` nuevos con `DROP TYPE` explícito, sin tocar nada de las migraciones anteriores ni dejar tipos huérfanos.
3. WHEN se ejecuta `make up`, THE SYSTEM SHALL aplicar la migración automáticamente a través del servicio `migrate` ya existente, sin paso manual adicional.
4. WHEN se ejecuta `alembic upgrade head` sobre una base de datos vacía, THE SYSTEM SHALL producir un esquema sin diferencias frente a los modelos declarados (autogenerate en vacío).

### R6 — Cobertura de tests

**As a** desarrollador, **I want** las 10 entidades cubiertas al mismo nivel que las 16 anteriores, **so that** la fidelidad al PRD sea verificable y no una afirmación.

Acceptance criteria:

1. THE SYSTEM SHALL tener por cada una de las 10 entidades un test unitario que la instancie en Python puro, sin base de datos.
2. THE SYSTEM SHALL tener por cada modelo SQLAlchemy un test de integración contra Postgres real que ejerza al menos un comportamiento a nivel de DB y no solo el camino feliz: la violación de `UNIQUE(property_id, date)` y de `UNIQUE(tenant_id, property_id, period_start, period_end)`, la de `review_response_drafts.review_id`, el `RESTRICT` de una FK obligatoria y el `SET NULL` de una FK nullable hacia `User`.
3. WHEN se persiste un importe `DECIMAL(10,2)` y se relee, THE SYSTEM SHALL devolver un `Decimal` con la escala declarada, sin pérdida por coma flotante.
4. THE SYSTEM SHALL ejecutar los tests de integración contra la base de datos de test aislada por proceso (`<nombre-dev>_test_<pid>`), nunca contra la que gestiona `make up`/`migrate`.

## Out of scope

- **Toda la lógica de negocio de pricing**: la fórmula `calculate_recommended_price` de PRD §7.17, los guardrails min/max y `max_daily_change_pct` → change `revenue`.
- **Consolidación de statements y exports**, generación de drafts de respuesta con IA y clasificación de sentiment de reviews → change `revenue`.
- **Envío real de notificaciones y SLA enforcement** sobre `NotificationLog` → changes `access-notifications` y `celery-jobs`.
- **Escritura real de `AuditLog`** en cualquier mutación: ni las de `reservations` (deuda anotada en `specs/reservations.md`), ni los cambios de rol (`user-management`), ni las 8 fuentes que enumera PRD §7.25. Aquí solo nace la tabla. **Decisión tomada en `/sdd:new`**: se planteó saldar aquí la deuda de `reservations` y se descartó — exigiría repositorio, caso de uso y elegir el punto de escritura, convirtiendo un change de estructura de datos en otra cosa y rompiendo la simetría con `domain-foundation-core`/`-ops`.
- **Recepción de webhooks** (`POST /api/v1/webhooks/{provider}`, firma HMAC) y el job `process_webhook_events` → change `reservations-webhooks`, que es justamente el que esta entidad desbloquea.
- **El flujo de aprobación del propietario** sobre `OwnerApproval` (umbral de 100 EUR, notificación, respuesta) → change `maintenance`.
- **Repositorios, casos de uso, endpoints y schemas Pydantic** para cualquiera de las 10 entidades.
- **Validación de la estructura interna de los JSONB** (R3.9).
- **Cifrado Fernet** de cualquier campo. Ninguna de las 10 declara una columna cifrada, pero **seis pueden acabar transportando un valor de la regla 3** de `security.md` sin anunciarlo en su nombre: `notification_logs.subject`/`body`/`last_error`, `audit_logs.changes` y `webhook_events.payload`/`error`. Lo levantaron los paneles de seguridad, y el contrato que las gobierna vive en **la regla 11 de `steering/security.md`** — un solo sitio, citado desde los tres docstrings. **Este change no cifra ni enmascara nada**: no hay todavía ningún escritor, así que cada tabla hereda la restricción con el change que primero escriba en ella.
- **Frontend**: ninguna de estas entidades tiene UI en este change.

## Affected specs

- `sdd/specs/domain-foundation-financial.md` — *(no existe aún — se creará al archivar)*.
- `sdd/steering/architecture.md` — la lista de dominios (hoy réplica de PRD §3.2) gana `reviews` y `audit` con su justificación (R1.6). Es steering, no spec: la decisión se tomó aquí y se aplica al archivar.
- `sdd/specs/domain-foundation-core.md` y `sdd/specs/domain-foundation-ops.md` — no se modifican; ambas ya anuncian este change como el tercer tercio de PRD §7. Se citan como base.
- `sdd/specs/auth-tenancy.md` — no se modifica, pero el límite 5 de su filtro global gana un cuarto hijo sin `tenant_id` (`review_response_drafts`) y el caso nuevo de `tenant_id` nullable (R4.2-4.4); si al archivar el texto de esa spec resulta impreciso, se corrige allí.
