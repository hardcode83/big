# Tasks: domain-foundation-financial

**Nada preexistente.** Verificado contra el código: no existen `backend/app/{pricing,reviews,statements,notifications,audit}/`, `maintenance` solo tiene `Incident`, e `integrations` no tiene `infrastructure/models.py`. Ninguna tarea nace marcada.

**La suite queda parcialmente roja a propósito entre 1.1 y 4.1.** En cuanto exista el primer modelo nuevo, `tests/test_migrations.py::test_the_models_match_the_migrations` (que corre `alembic check`) falla, porque hay modelos sin migración. Es esperado y se cierra en 4.1 — no es una regresión que haya que investigar. El resto de la suite sí debe seguir verde tras cada tarea, y por eso **cada tarea de modelos añade su línea a `app/core/models_registry.py` en el mismo paso**: `test_models_registry.py` compara la lista contra el glob en disco y se pondría roja si se dejara para el final.

Patrón a replicar en todo el change: `backend/app/maintenance/domain/entities.py` (dataclass plano) y `backend/app/maintenance/infrastructure/models.py` (declarativo, `Enum(..., name=..., native_enum=True)`, `Uuid` explícito en FK cruzada, `server_default` en todo default del PRD).

## 1. Módulos nuevos independientes <!-- panel: PASS 2026-07-31 -->

<!-- Panel: arquitectura PASS, tenancy PASS, seguridad FAIL(3)→PASS, qa FAIL(2)→PASS.
     Arreglos de la ronda 1: contrato de cleartext en los docstrings de
     NotificationLogModel y AuditLogModel; test de aislamiento parametrizado por
     módulo en test_tenant_filter.py; RESTRICT de reviews.property_id; y el
     server_default de pricing probado con text() crudo en vez de Table.insert(). -->


Sin FK entre ellos ni hacia nada que este change cree; pueden hacerse en cualquier orden.

- [x] 1.1 `pricing` — dominio: `backend/app/pricing/{__init__,domain/__init__,domain/entities,domain/enums}.py` con los dataclasses `PricingRule` y `PriceRecommendation` y el enum `PriceRecommendationStatus` (`DRAFT`/`RECOMMENDED`/`APPROVED`/`APPLIED_EXTERNAL`/`REJECTED`), marcado `ASSUMPTION` porque PRD §7.18 lo declara inline sin nombre. Test `backend/tests/pricing/test_entities.py` que instancia ambos en Python puro. Sin métodos de mutación: la fórmula de §7.17 es de `revenue`. [R1, R2, R3]
- [x] 1.2 `pricing` — esquema: `backend/app/pricing/infrastructure/{__init__,models}.py` con `pricing_rules` (5 columnas `JSONB` con `server_default` `'{}'`/`'[]'`, `property_id` nullable con `RESTRICT`, `Numeric(10,2)` en precios y `Numeric(5,2)` en `max_daily_change_pct`) y `price_recommendations` (`UNIQUE(property_id, date)`, `Numeric(3,2)` en `confidence` con `server_default '1.00'`, solo `created_at`). Añadir la línea de `pricing` a `app/core/models_registry.py` (import + tupla). Test `backend/tests/pricing/test_models.py`: violación de `UNIQUE(property_id, date)`, `RESTRICT` al borrar una `Property` con `PricingRule`, y ida y vuelta de `Decimal` conservando escala. [R3, R4, R6]
- [x] 1.3 `reviews` — dominio: `backend/app/reviews/domain/{entities,enums}.py` con `Review` y `ReviewResponseDraft` y los enums `ReviewChannel` (`AIRBNB`/`BOOKING`/`GOOGLE`/`MANUAL`/`OTHER`), `ReviewSentiment` (`POSITIVE`/`NEUTRAL`/`NEGATIVE`) y `ReviewStatus` (`NEW`/`DRAFTED`/`APPROVED`/`POSTED_MANUALLY`/`IGNORED`), los tres `ASSUMPTION`. `ReviewResponseDraft` no lleva `tenant_id` — el PRD no se lo declara. Test `backend/tests/reviews/test_entities.py`. [R1, R2, R3]
- [x] 1.4 `reviews` — esquema: `backend/app/reviews/infrastructure/models.py` con `reviews` (tenant-scoped, `reservation_id` nullable `RESTRICT`, `rating` `Numeric(3,1)` sin `CHECK` por D12) y `review_response_drafts` (**sin** `tenant_id`, `review_id` FK obligatoria `RESTRICT` y `UNIQUE`, `approved_by` → `users.id` `SET NULL`). Línea en `models_registry.py`. Test `backend/tests/reviews/test_models.py`: violación de `UNIQUE(review_id)` y `SET NULL` al borrar el `User` que aprobó. Extender `tests/test_models_registry.py::test_the_tenant_filter_sees_the_child_tables_that_have_no_tenant_id_of_their_own` con `review_response_drafts` como cuarto hijo sin `tenant_id`. [R3, R4, R6]
- [x] 1.5 `notifications` — dominio: `backend/app/notifications/domain/{entities,enums}.py` con `NotificationLog` y los enums `NotificationChannel` (`EMAIL`/`WHATSAPP`/`PUSH`/`IN_APP`/`CONSOLE`) y `NotificationStatus` (`PENDING`/`SENT`/`FAILED`/`SKIPPED`), ambos `ASSUMPTION`. **No reutilizar `ConversationChannel`**: `PUSH`/`IN_APP`/`CONSOLE` no existen allí (D6). Test `backend/tests/notifications/test_entities.py`. [R1, R2, R3]
- [x] 1.6 `notifications` — esquema: `backend/app/notifications/infrastructure/models.py` con `notification_logs` (tenant-scoped, `recipient_user_id` nullable `SET NULL`, `related_type` **VARCHAR** y `related_id` **sin FK** con comentario de que es deliberado, `INDEX(tenant_id, status, sla_deadline_at)` e `INDEX(related_type, related_id)`, `attempts` y `sla_breached` con `server_default`). Línea en `models_registry.py`. Test `backend/tests/notifications/test_models.py`: los dos índices existen con su nombre, y `SET NULL` al borrar el destinatario. [R2, R3, R6]
- [x] 1.7 `audit` — dominio: `backend/app/audit/domain/entities.py` con `AuditLog`, sin enums (PRD tipa `action` y `entity_type` como VARCHAR). Test `backend/tests/audit/test_entities.py`. [R1, R2, R3]
- [x] 1.8 `audit` — esquema: `backend/app/audit/infrastructure/models.py` con `audit_logs` (tenant-scoped, `actor_user_id` nullable `SET NULL`, `entity_id` `Uuid` **sin FK** con comentario, solo `created_at`, `INDEX(tenant_id, entity_type, entity_id)` e `INDEX(tenant_id, actor_user_id, created_at DESC)` con `text("created_at DESC")` como hace `TimelineEventModel`). Línea en `models_registry.py`. Test `backend/tests/audit/test_models.py`: ambos índices existen y el `DESC` sobrevive a `create_all`; `SET NULL` al borrar el actor. [R3, R6]

## 2. Entidades en módulos existentes y dependientes <!-- panel: PASS 2026-07-31 -->

<!-- Panel: tenancy PASS, arquitectura FAIL(1)→PASS, qa FAIL(1)→PASS. Seguridad no se
     lanzó: sus 3 hallazgos de la sección 1 quedaron cerrados y estas tablas no
     añaden texto libre ni PII.
     Arreglos: D5 precisado para requested_at (se mantiene el server_default; la
     lectura literal de R3.1 sería contradictoria con R3.4 del mismo change), y los
     tests de RESTRICT de la FK propia de owner_approvals/owner_statements/expenses,
     que era el mismo hueco padre-hijo de la sección 1. -->


Orden obligado: `owner_statements` antes que `expenses` (FK), y `expenses` referencia `incidents`, que ya existe.

- [x] 2.1 `maintenance` — `OwnerApproval`: añadir a los ficheros existentes `backend/app/maintenance/domain/{entities,enums}.py` el dataclass y los enums `OwnerApprovalRelatedType` (`INCIDENT`/`MAINTENANCE_COST`/`OTHER`) y `OwnerApprovalStatus` (`PENDING`/`APPROVED`/`REJECTED`/`EXPIRED`), ambos `ASSUMPTION`. Test en `backend/tests/maintenance/test_entities.py`. [R1, R2, R3]
- [x] 2.2 `maintenance` — esquema de `owner_approvals` en `backend/app/maintenance/infrastructure/models.py`: tenant-scoped, `related_id` **sin FK** con comentario, `responded_by` → `users.id` `SET NULL`, `requested_at` NOT NULL con `server_default=func.now()`, `responded_at` nullable, y **sin `created_at`/`updated_at`** — fidelidad estricta a PRD §7.19 decidida en OQ1, así que no lleva `TimestampMixin`. `maintenance` ya está en `models_registry.py`: no añadir línea. Test en `backend/tests/maintenance/test_models.py`: `SET NULL` al borrar quien respondió, y que la tabla no tiene columna `updated_at`. [R3, R6]
- [x] 2.3 `statements` — dominio: `backend/app/statements/domain/{entities,enums}.py` con `OwnerStatement` y `Expense` y los enums `OwnerStatementStatus` (`DRAFT`/`READY`/`SENT`) y `ExpenseCategory` (`CLEANING`/`LAUNDRY`/`AMENITIES`/`MAINTENANCE`/`SPECIALIST`/`PLATFORM_FEE`/`OTHER`), ambos `ASSUMPTION`. Test `backend/tests/statements/test_entities.py`. [R1, R2, R3]
- [x] 2.4 `statements` — esquema: `backend/app/statements/infrastructure/models.py` con `owner_statements` (11 columnas `Numeric(10,2)` con `server_default '0'`, `UNIQUE(tenant_id, property_id, period_start, period_end)`) y `expenses` (`statement_id` e `incident_id` nullable `RESTRICT`, `approved_by` `SET NULL`, `currency` `String(3)` con `server_default 'EUR'`, solo `created_at`). Línea en `models_registry.py`. Test `backend/tests/statements/test_models.py`: violación del `UNIQUE` de 4 columnas, `RESTRICT` al borrar un `OwnerStatement` con `Expense`, y los 11 defaults a `0` verificados con un **`text("INSERT INTO ...")` crudo** — `Table.insert().values(...)` sigue aplicando el `default=` de Python y no prueba el DDL (hallazgo 2 del panel de QA en la sección 1). **Además, obligatorio por la regla 1 de `steering/security.md`**: añadir `owner_statements` y `expenses` como parámetros de `test_the_financial_tables_are_inside_the_net` y a la aserción positiva de `test_the_registry_scan_finds_the_tenant_scoped_entities` en `backend/tests/test_tenant_filter.py`; sin eso el módulo nuevo se queda sin test de aislamiento (arrastre del panel de seguridad de la sección 1). [R3, R4, R6]

## 3. `integrations` — WebhookEvent y el filtro de tenant <!-- panel: PASS 2026-07-31 -->

<!-- Panel: seguridad FAIL(3)→arreglado, qa PASS(1 hallazgo menor)→arreglado.
     Arquitectura y tenancy no se relanzaron: validaron el mismo patrón de modelo en
     las secciones 1 y 2 y aquí no cambia.
     Arreglos: WebhookEventModel añadido al test de aislamiento parametrizado (era la
     única tabla con scoping artesanal y estaba fuera); límite 2 del docstring de
     _scope_statement_to_tenant reescrito para exigir sesión NUNCA marcada y prohibir
     el pop() sobre una marcada; contrato de cleartext para payload/error; y el test
     del índice pasa a comprobar el ORDEN, verificado con sonda de mutación. -->


Es el módulo con la sutileza real del change (D4): primera tabla de `integrations` y única con `tenant_id` nullable.

- [x] 3.1 `integrations` — dominio: `backend/app/integrations/domain/entities.py` (**nuevo**; el módulo hoy solo tiene `dtos.py` y `ports.py`) con el dataclass `WebhookEvent`, sin enums — `provider` y `event_type` son VARCHAR por PRD §7.26. Test `backend/tests/integrations/test_entities.py`. [R1, R2, R3]
- [x] 3.2 `integrations` — esquema: `backend/app/integrations/infrastructure/models.py` (**nuevo**, primera tabla del módulo) con `webhook_events`. `tenant_id` se declara **a mano** —`Mapped[uuid.UUID | None]` con `Uuid`, FK a `tenants.id`, `nullable=True`, `index=True`— porque `TenantScopedMixin` fija `nullable=False`; documentar en el modelo por qué no usa el mixin. `payload` `JSONB` NOT NULL, `processed` con `server_default 'false'`, `received_at` como único timestamp, `INDEX(provider, processed, received_at)`. Línea en `models_registry.py`. Test `backend/tests/integrations/test_models.py`: se puede insertar con `tenant_id` NULL, y el índice existe. [R3, R4, R6]
- [x] 3.3 Fijar el comportamiento del filtro global sobre las filas huérfanas: test nuevo en `backend/tests/test_tenant_filter.py` que, con `bind_session_to_tenant`, demuestra que un `select(WebhookEventModel)` **no devuelve** las filas con `tenant_id NULL` aunque sí devuelva las del tenant marcado. Comprobar además que `webhook_events` **sí** aparece en `tenant_scoped_classes()` (la selección es por presencia de columna, no por el mixin). Ampliar el docstring de `_scope_statement_to_tenant` en `backend/app/core/db.py`: el límite 2 gana el caso de las filas sin tenant y el límite 5 gana `review_response_drafts`. [R4]

## 4. Migración Alembic

- [x] 4.1 Generar la revisión con `docker compose exec backend uv run alembic revision --autogenerate -m "domain foundation financial"` y revisarla a mano: `down_revision = "e1eed2e039ee"`, las 10 tablas en orden de dependencia (`pricing_rules`→`price_recommendations`, `reviews`→`review_response_drafts`, `owner_statements`→`expenses`), el `downgrade` en orden inverso, y la constante `_ENUM_TYPE_NAMES` con los 10 tipos nuevos (`price_recommendation_status`, `owner_approval_related_type`, `owner_approval_status`, `review_channel`, `review_sentiment`, `review_status`, `owner_statement_status`, `expense_category`, `notification_channel`, `notification_status`) más el bucle `postgresql.ENUM(name=...).drop(op.get_bind(), checkfirst=True)` — copiando el patrón de `a1a72da30f8e_domain_foundation_ops.py`. Tras esta tarea `alembic check` vuelve a verde. [R5]
- [x] 4.2 Extender `backend/tests/test_migrations.py` siguiendo su patrón de objetivos explícitos (nunca `downgrade -1`): la cadena sube a head, desanda **solo** la revisión nueva hasta `e1eed2e039ee` dejando intactas las tablas anteriores, y se reaplica. Comprobar por nombre al menos una tabla (`audit_logs`) y un tipo `ENUM` (`expense_category`) que aparecen al subir y desaparecen al bajar — este último es el que detecta el `DROP TYPE` olvidado que rompería el siguiente `upgrade`. [R5, R6]

## 5. Documentación

- [x] 5.1 `README.md`, sección **Estructura**: la línea de `backend/` enumera hoy las cuatro capas como si todos los dominios las tuvieran. Ajustarla para reflejar el sistema real tras el change — 15 módulos de dominio, de los cuales los que son solo estructura de datos tienen `domain/` + `infrastructure/` — y mencionar que `integrations/` pasa a tener tabla propia. Regla de `steering/documentation.md`: el README describe el sistema *actual* y el change añade 5 módulos. [R1]
- [x] 5.2 Steering: añadir `reviews` y `audit` a la lista de dominios de `sdd/steering/architecture.md`, y a `sdd/steering/backend-architecture.md` §"Cuándo simplificar" la excepción de D2 (los módulos que todavía son solo estructura de datos nacen con `domain/` + `infrastructure/`; `application/` y `api/` llegan con el primer caso de uso). **Adelantado respecto a design.md**, que lo situaba en el archivado: el panel de `/sdd:review` lee el steering, así que dejarlo sin tocar haría que el revisor de arquitectura marcara D2 como violación en un change que la tiene aprobada. [R1]

## 6. Verificación

- [x] 6.1 Suite completa del backend en verde: `docker compose exec backend uv run pytest` (con el stack parado, `docker compose run --rm backend uv run pytest`). Debe incluir los 14 ficheros de test nuevos y los 3 extendidos. [R6]
- [x] 6.2 Réplica local del gate de CI (`.github/workflows/backend-tests.yml`), en este orden y todos en verde: `uv run alembic upgrade head`, `uv run alembic check` (autogenerate vacío, R5.4) y `uv run alembic downgrade base`. [R5]
- [x] 6.3 `test_layering.py` pasa sobre los `domain/` nuevos —`sqlalchemy`/`fastapi`/`pydantic` fuera— sin excepciones ni ficheros añadidos a ninguna lista de exención; el fichero parametriza por glob, así que los módulos nuevos entran solos. Confirmar que el conteo de `_domain_modules()` ha crecido. [R1]
- [x] 6.4 Arranque limpio de extremo a extremo: `make down && make up`, y comprobar en `docker compose logs migrate` que la revisión nueva se aplica sola, sin paso manual (R5.3). Verificar en `psql` que existen las 10 tablas y los 10 tipos `ENUM`. [R5]

**No hay tarea de lint/typecheck**: el backend no tiene ruff ni mypy configurados (`backend/pyproject.toml` solo declara `pytest`, `pytest-asyncio`, `pytest-cov` y `httpx` en el grupo dev), y CI tampoco los corre. Inventar un comando aquí sería reportar una verificación que no existe.

## Cobertura de requisitos

| Req | Tareas |
|---|---|
| R1 — módulos y dominio puro | 1.1, 1.3, 1.5, 1.7, 2.1, 2.3, 3.1, 5.1, 5.2, 6.3 |
| R2 — enums exactos | 1.1, 1.3, 1.5, 1.6, 1.7, 2.1, 2.3, 3.1 |
| R3 — esquema fiel al PRD | 1.1–1.8, 2.1–2.4, 3.1, 3.2 |
| R4 — aislamiento por tenant | 1.2, 1.4, 3.2, 3.3 |
| R5 — migración Alembic | 4.1, 4.2, 6.2, 6.4 |
| R6 — tests | 1.2, 1.4, 1.6, 1.8, 2.2, 2.4, 3.2, 4.2, 6.1 |
