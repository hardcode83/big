# Modelos de dominio y esquema DB — pricing, financiero y logs de sistema

## Purpose

Entidades de dominio y esquema de base de datos para las 10 entidades del PRD (§7.17-7.26) que cierran §7: pricing y financiero (`PricingRule`, `PriceRecommendation`, `OwnerApproval`, `Review`, `ReviewResponseDraft`, `OwnerStatement`, `Expense`) más los tres registros de sistema (`NotificationLog`, `AuditLog`, `WebhookEvent`). Construye sobre `domain-foundation-core` y `domain-foundation-ops` — solo estructura de datos (entidades + esquema + migraciones), sin lógica de negocio, repositorios, casos de uso ni endpoints. **Con este tercio las 26 entidades del PRD §7 existen**, y con ellas las tablas que `reservations-webhooks`, `celery-jobs`, `user-management`, `maintenance` y `revenue` necesitan para arrancar.

## Requirements

### Estructura por módulo de dominio

- Las 10 entidades se reparten en 7 módulos: `pricing` (`PricingRule`, `PriceRecommendation`), `maintenance` (`OwnerApproval`), `reviews` (`Review`, `ReviewResponseDraft`), `statements` (`OwnerStatement`, `Expense`), `notifications` (`NotificationLog`), `audit` (`AuditLog`) e `integrations` (`WebhookEvent`).
- `reviews` y `audit` son dominios que **no** aparecen en la lista de PRD §3.2; están añadidos a `steering/architecture.md` con su justificación — `audit` es transversal igual que `timeline`, que §3.2 sí lista. Se descartaron plegar las reviews en `statements` (mezclaría reporting financiero con contenido de OTAs) y alojar `AuditLog` en `app/core/` (infraestructura compartida, no entidades de negocio).
- `webhook_events` es la primera tabla que tiene el módulo `integrations`, hasta entonces solo adapters (`csv_parser.py`, `mock_pms.py`) y su `cli/`.
- Los módulos que son solo estructura de datos tienen `domain/` (entidades + enums) e `infrastructure/` (modelos SQLAlchemy) y **no** `application/` ni `api/`; esas dos capas llegan con el primer caso de uso. La excepción está escrita en `steering/backend-architecture.md` §"Cuándo simplificar". De los 16 dominios, solo `auth`, `reservations` e `integrations` tienen las cuatro capas.
- Las 10 entidades son `@dataclass` planos sin métodos de mutación: ninguna tiene todavía una invariante que proteger — los guardrails de `PricingRule` son reglas del cálculo, que vive en `revenue`.
- Ninguna tiene puertos de repositorio ni casos de uso; se difieren al change que primero la persista.
- `backend/tests/test_layering.py` verifica por glob que ningún `domain/` importa `sqlalchemy`, `fastapi` ni `pydantic`.

### Enums de dominio

- Los 10 enums de §7.17-7.26 los declara el PRD inline, sin bloque de valores propio, así que todos llevan nombre inventado con la convención `<Entidad><Campo>` y marca `ASSUMPTION` en el código: `PriceRecommendationStatus`, `OwnerApprovalRelatedType`, `OwnerApprovalStatus`, `ReviewChannel`, `ReviewSentiment`, `ReviewStatus`, `OwnerStatementStatus`, `ExpenseCategory`, `NotificationChannel`, `NotificationStatus`.
- `NotificationChannel` (`EMAIL`/`WHATSAPP`/`PUSH`/`IN_APP`/`CONSOLE`), `ReviewChannel` (`AIRBNB`/`BOOKING`/`GOOGLE`/`MANUAL`/`OTHER`) y el existente `ConversationChannel` son tres enums distintos con conjuntos de valores distintos; no se reutilizan entre sí, y un test lo fija.
- `WebhookEvent.provider`/`event_type`, `NotificationLog.notification_type`/`related_type` y `AuditLog.action`/`entity_type` son `VARCHAR`, no enums — el PRD los tipa así porque su conjunto es abierto.

### Esquema DB — modelos SQLAlchemy 2.x async

- Cada entidad tiene un modelo declarativo en `infrastructure/models.py` que reproduce columnas, tipos, nullability, `DEFAULT` e índices del PRD. Los importes son `Numeric(10,2)`; nunca `float`.
- Todo `DEFAULT` del PRD existe también como `server_default` en el DDL, verificado con `INSERT` en SQL crudo — `Table.insert().values(...)` no sirve para probarlo, porque SQLAlchemy Core sigue aplicando el `default=` de Python al compilar.
- Constraints e índices propios: `UNIQUE(property_id, date)` en `price_recommendations`; `UNIQUE(tenant_id, property_id, period_start, period_end)` en `owner_statements`, con el nombre acortado a `uq_owner_statements_tenant_property_period` porque la forma literal de la convención supera los 63 caracteres de Postgres; `UNIQUE` sobre `review_response_drafts.review_id`; los dos índices de `notification_logs`; los dos de `audit_logs`, incluido el `created_at DESC` declarado con `text("created_at DESC")`; y el de `webhook_events`, cuyo test comprueba el **orden** de las columnas, no solo su presencia.
- Tres patrones de timestamp, según lo que declare el PRD: `TimestampMixin` en `pricing_rules`, `reviews`, `review_response_drafts`, `owner_statements` y `notification_logs`; solo timestamp de creación en `price_recommendations`, `expenses`, `audit_logs` y `webhook_events`; y ninguno de los dos en `owner_approvals`, que tiene `requested_at`/`responded_at` y es la única tabla editable del esquema sin `updated_at` — fidelidad estricta a §7.19, con el coste registrado de que una expiración por job no deja rastro temporal.
- `owner_approvals.requested_at` **sí** lleva `server_default=func.now()`: es el timestamp de creación de la fila —§7.19 no declara `created_at` porque ese papel ya lo cumple— y el PRD declara `created_at TIMESTAMPTZ NOT NULL` sin `DEFAULT` en sus 23 tablas mientras `TimestampMixin` las defaultea todas.
- `owner_approvals.related_id`, `notification_logs.related_id` y `audit_logs.entity_id` son referencias polimórficas **sin FK**, apuntadas por su columna de tipo asociada, con comentario de que la ausencia es deliberada.
- `ON DELETE SET NULL` en las 5 FK nullable hacia `users` (`owner_approvals.responded_by`, `review_response_drafts.approved_by`, `expenses.approved_by`, `notification_logs.recipient_user_id`, `audit_logs.actor_user_id`); `RESTRICT` en el resto, incluidas las nullable hacia no-`User`.
- **Sin `CHECK` constraints**: el PRD documenta rangos en comentarios (`rating` 1.0-5.0, `confidence` 0-1) pero no declara ninguna constraint, y la validación de rango pertenece al dominio de `revenue`.
- Las columnas `JSONB` se persisten sin validar su estructura interna; los schemas de §7.17 se validarán donde se consuman.

### Aislamiento por tenant

- 8 de las 10 entidades llevan `tenant_id` obligatorio vía `TenantScopedMixin`. El esquema tiene 27 tablas, de las que **22 están dentro del filtro global** de `app/core/db.py` (eran 13 antes de este change).
- `webhook_events` es la única tabla con `tenant_id` **nullable** (§7.26: un payload no atribuible se registra en vez de perderse), así que declara la columna a mano —`TenantScopedMixin` fija `nullable=False`— conservando tipo `Uuid`, FK a `tenants.id` e índice. Sigue dentro del filtro, porque `tenant_scoped_classes()` selecciona por presencia de columna: en una sesión marcada, `tenant_id == X` **esconde las filas `NULL`**, sin error. `reservations-webhooks` debe leerlas desde una sesión **nunca marcada**. El comportamiento está fijado en `tests/test_tenant_filter.py`, con sus dos mitades.
- `review_response_drafts` no tiene `tenant_id`: se scopea transitivamente por su FK obligatoria y única `review_id`. Es el cuarto hijo en esa situación, junto a `messages`, `cleaning_checklist_completions` y `cleaning_photos`, y consta en el límite 5 del docstring de `_scope_statement_to_tenant`.
- `bind_session_to_tenant` rechaza un tenant nulo y rechaza remarcar una sesión ya marcada con otro tenant. Enmienda la decisión D16 de `auth-tenancy`, que lo dejó como asignación desnuda: la función era su propio unbind —`None` apaga el filtro para las 22 clases el resto de la sesión— y remarcar era peor, porque lo reapunta a un tenant ajeno. La anotación de tipo no protegía nada: el backend no tiene mypy ni ruff.
- `backend/tests/test_session_marking.py` prohíbe por AST que `app/` acceda a `session.info` fuera de `core/db.py`. Rechaza el acceso, no una lista de mutaciones, así que cubre `pop`, `clear`, `update`, `setdefault`, la asignación por subíndice, el `del` y la creación de alias (`d = session.info`) — y deja legal `logger.info(...)`. Lleva su propio meta-test, como `test_layering.py`.
- Los 6 módulos con tabla están en `app/core/models_registry.py`, único sitio donde se mantiene la lista; `tests/test_models_registry.py` la compara contra el glob en disco, así que olvidar uno rompe un test en vez de dejar la tabla fuera del filtro.
- Cada módulo nuevo tiene su caso en el test parametrizado de aislamiento (`steering/security.md` regla 1), incluido `webhook_events`, que es la tabla cuyo scoping es artesanal y por tanto la que más lo necesita.

### Datos sensibles en columnas de texto libre

- Seis columnas del esquema son texto o JSON libre por el que puede colarse un valor sensible sin que la columna lo anuncie: `notification_logs.subject`/`body`/`last_error`, `audit_logs.changes` y `webhook_events.payload`/`error`.
- El contrato que las gobierna es **la regla 11 de `steering/security.md`**, y vive solo ahí: forma estructurada por defecto (el valor no sobrevive, ni enmascarado) y una única excepción —`subject`/`body` admiten el `****XX` de la regla 4 para un **código de acceso**, porque renderizan un mensaje que el huésped debe recibir—. Los tres docstrings la citan sin repetirla.
- `audit_logs.changes` **ya tiene escritor**: `user-management` (`specs/user-management.md`) heredó ahí el contrato y lo hizo estructural en vez de convencional — un value object `ChangeSet` ligado a un `entity_type`, con lista de campos auditables por entidad, de forma que la única manera de registrar un campo sensible es la forma `{"changed": true}`. Costó tres iteraciones: vetar el nombre no bastaba (un valor compuesto colaba el secreto), vetar el valor compuesto tampoco (un compuesto serializado a JSON viaja dentro de un string), y lo que cierra la clase es vetar el **nombre** contra una lista de columnas reales de la entidad. Lo que sigue sin cerrar, y consta en el propio módulo, es un llamante que ponga un secreto como valor de un campo legítimo: eso lo cierran los casos de uso, que alimentan los diffs desde atributos tipados.
- **Quién escribe cada una de las seis lo dice la tabla de la regla 11 en `steering/security.md`, y solo ella.** Esta spec no la repite a propósito: la propiedad de estos sumideros llegó a estar reafirmada en seis artefactos y cada revisión encontraba uno más desincronizado — la entrada de roadmap `rule11-ownership-single-source` existe para quitar esa duplicación de raíz. Lo que sí es información local y se queda aquí: estas columnas son sumideros de texto en claro y su contrato es la regla 11.

### Migraciones Alembic

- Una migración (`backend/alembic/versions/96d526599bc1_domain_foundation_financial.py`) encadenada sobre `e1eed2e039ee` crea las 10 tablas en orden de dependencia, reversible.
- El `downgrade` las borra en orden inverso y hace `DROP TYPE` explícito de los 10 tipos `ENUM` nuevos vía `_ENUM_TYPE_NAMES`: Alembic no lo emite solo, y un tipo huérfano rompe el siguiente `upgrade` con *"type already exists"*.
- Al arrancar el stack local (`make up`), el servicio `migrate` la aplica automáticamente.
- `alembic check` no detecta diferencias entre modelos y migraciones.

### Tests

- Cada entidad tiene un test unitario que la instancia en Python puro, y cada modelo un test de integración contra Postgres real que ejerce comportamiento a nivel de DB: las violaciones de `UNIQUE`, el `RESTRICT` de **su propia** FK obligatoria (no solo la de sus hijos), el `SET NULL` de las FK nullable hacia `User`, y la ida y vuelta de `Decimal` conservando escala.
- `tests/test_migrations.py` sube a head, desanda **solo** esta revisión contra su objetivo explícito dejando intactas las cuatro anteriores, y la reaplica — comprobando por nombre una tabla y un tipo `ENUM`. El round-trip cubre las 10 tablas y los 10 tipos de rebote, porque un `DROP` olvidado revienta el re-`upgrade`.
- Los tests de integración corren contra la base de datos de test aislada por proceso, nunca contra la que gestiona `make up`.

## Key files

- `backend/app/pricing/{domain,infrastructure}/` — `PricingRule`, `PriceRecommendation`.
- `backend/app/maintenance/{domain,infrastructure}/` — `OwnerApproval`, junto a `Incident`.
- `backend/app/reviews/{domain,infrastructure}/` — `Review`, `ReviewResponseDraft`.
- `backend/app/statements/{domain,infrastructure}/` — `OwnerStatement`, `Expense`.
- `backend/app/notifications/{domain,infrastructure}/` — `NotificationLog`.
- `backend/app/audit/{domain,infrastructure}/` — `AuditLog`.
- `backend/app/integrations/{domain/entities.py,infrastructure/models.py}` — `WebhookEvent`.
- `backend/app/core/db.py` — `bind_session_to_tenant` y sus guardas, `_scope_statement_to_tenant` y sus cinco límites documentados.
- `backend/app/core/models_registry.py` — la lista única de módulos con modelos.
- `backend/alembic/versions/96d526599bc1_domain_foundation_financial.py`.
- `backend/tests/{pricing,reviews,statements,notifications,audit}/`, `backend/tests/{maintenance,integrations}/test_{entities,models}.py`.
- `backend/tests/test_session_marking.py`, `backend/tests/test_tenant_filter.py`, `backend/tests/test_models_registry.py`, `backend/tests/test_migrations.py`.
- `sdd/steering/security.md` regla 11 — el contrato de las columnas de texto libre.
