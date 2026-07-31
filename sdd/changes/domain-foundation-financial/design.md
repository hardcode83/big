# Design: domain-foundation-financial

## Context

El backend tiene hoy 10 módulos de dominio bajo `backend/app/` con 16 entidades (`domain-foundation-core` §7.1-7.8 y `-ops` §7.9-7.16), un `Base` declarativo con tres mixins compartidos en `backend/app/core/db.py` (`UUIDPrimaryKeyMixin`, `TenantScopedMixin`, `TimestampMixin`) y una cadena de 4 migraciones cuyo head es `e1eed2e039ee` (`globally_unique_lower_email`). El patrón a replicar está fijado literalmente en `backend/app/maintenance/{domain/entities.py,infrastructure/models.py}`: dataclass plano en `domain/`, modelo declarativo en `infrastructure/` con `Enum(..., name=..., native_enum=True)`, `Uuid` explícito en toda FK cruzada y `server_default` en todo default del PRD.

Tres piezas transversales condicionan el diseño más que el esquema en sí:

- **`backend/app/core/models_registry.py`** es el único sitio donde se enumeran los módulos con modelos; `alembic/env.py` y `tests/conftest.py` lo importan en vez de mantener su propia lista, y `tests/test_models_registry.py::test_the_registry_lists_every_domain_that_has_models` compara esa lista contra el glob `app/*/infrastructure/models.py` en disco — así que **olvidarse de registrar un módulo nuevo rompe un test, no pasa en silencio**.
- **`_scope_statement_to_tenant`** (`app/core/db.py`) engancha `with_loader_criteria` por cada clase con columna `tenant_id`, en **cada** sentencia ORM de una sesión marcada. Su docstring enumera cinco límites conocidos; el quinto (tablas hijas sin `tenant_id`) está pineado en `tests/test_models_registry.py`.
- **`tests/test_migrations.py`** ejecuta `alembic upgrade head`, desanda **revisión por revisión** contra objetivos explícitos (no `-1`) y corre `alembic check` para exigir un autogenerate vacío.

Tres hallazgos de la investigación que la propuesta no contemplaba:

1. **`backend/app/integrations/` no tiene `infrastructure/models.py` hoy** — es el único módulo con `api/`, `application/`, `cli/` y adapters (`csv_parser.py`, `mock_pms.py`) pero **cero tablas**, y su `domain/` contiene `dtos.py`/`ports.py`, no `entities.py`. `WebhookEvent` será su primera entidad persistida.
2. **`TenantScopedMixin` declara `nullable=False`**, así que `WebhookEvent` (nullable por PRD §7.26) **no puede usar el mixin** — hay que declarar la columna a mano.
3. **`backend-architecture.md` nombra explícitamente `NotificationLog` y `AuditLog`** como el ejemplo canónico de "dominio sin invariante real → dataclass simple, sin value objects ni eventos". El steering respalda R1.3 por su nombre.

## Decisions

### D1 — Siete módulos; `reviews` y `audit` son dominios nuevos

**Chosen:** el reparto confirmado en `/sdd:new`: `pricing` (`PricingRule`, `PriceRecommendation`), `maintenance` (`OwnerApproval`), `reviews` (`Review`, `ReviewResponseDraft`), `statements` (`OwnerStatement`, `Expense`), `notifications` (`NotificationLog`), `audit` (`AuditLog`), `integrations` (`WebhookEvent`). Cuatro directorios nuevos (`pricing`, `statements`, `notifications`, `reviews`, `audit` — cinco), `maintenance` e `integrations` ya existen. La divergencia con PRD §3.2 se limita a `reviews` y `audit`, y se justifica en que `audit` es transversal igual que `timeline`, que §3.2 sí lista como dominio.

Rejected: `Review`/`ReviewResponseDraft` dentro de `statements` — mezclaría reporting financiero con contenido de OTAs.
Rejected: `AuditLog` en `app/core/` — `core/` es infraestructura compartida (`db.py`, `config.py`), no alojamiento de entidades de negocio.
Rejected: un módulo `webhooks` propio para `WebhookEvent` — `integrations` ya es el dominio de adapters externos en §3.2 y es donde `reservations-webhooks` va a aterrizar su router; darle su primera tabla no rompe nada (hallazgo 1).

### D2 — Solo `domain/` e `infrastructure/`; se aparta a propósito de una regla del steering

**Chosen:** los módulos nuevos nacen con `domain/` (`entities.py`, `enums.py`) e `infrastructure/` (`models.py`) y **sin** `application/` ni `api/`.

Esto **contradice explícitamente** `backend-architecture.md` §"Cuándo simplificar", que dice: *"Lo que sí se mantiene igual en todos los dominios, con o sin invariantes: la carpeta `domain/application/infrastructure/api/`"*. Se aparta de forma consciente, no por descuido, y por dos razones: (a) es el precedente literal de los dos changes hermanos — `specs/domain-foundation-ops.md` lo fija como comportamiento vivo del sistema, y `specs/domain-foundation-core.md` documenta que `application/`/`api/` solo existen en `auth/` porque `auth-tenancy` los introdujo cuando hubo un caso de uso real; (b) `tests/test_layering.py::test_there_are_application_modules_to_check` sería lo único que viera esas carpetas — paquetes vacíos que ningún test puede verificar y que invitan a colocar mal el primer caso de uso.

Consecuencia registrada, **resuelta en el gate de design (OQ2: matizar el steering)**: al archivar se añade a `steering/backend-architecture.md` la excepción explícita — los módulos que todavía son solo estructura de datos nacen con `domain/` + `infrastructure/`, y las otras dos capas llegan con el primer caso de uso. Se descartó crear paquetes vacíos (no arreglaría la violación de los 16 hermanos, solo la de este change) y se descartó dejar la divergencia viva como deuda (una regla vinculante incumplida a sabiendas en 26 entidades la vuelve a levantar cada revisor).

Rejected: crear `application/`/`api/` vacíos con `__init__.py` — ceremonia no verificable, y rompería el precedente de los 16 hermanos.

### D3 — Las 10 entidades son `@dataclass` planos

**Chosen:** dataclass con campos obligatorios primero y opcionales con `= None`, sin métodos de mutación, replicando `app/maintenance/domain/entities.py`. Ninguna de las 10 tiene todavía una invariante que proteger: los guardrails de `PricingRule` (`min_price`/`max_price`/`max_daily_change_pct`) son reglas **del cálculo**, que vive en `revenue`, no del registro.

Respaldo directo del steering: `backend-architecture.md` §"Cuándo simplificar" nombra `NotificationLog` y `AuditLog` como el ejemplo de *"dominio sin invariante real… un `dataclass` simple sin métodos"*.

Rejected: métodos como `PricingRule.recommend(...)` — arrastraría la fórmula de PRD §7.17 a un change que declara no tener lógica de negocio.

### D4 — `WebhookEventModel` declara `tenant_id` a mano, fuera de `TenantScopedMixin`

**Chosen:** `TenantScopedMixin` fija `nullable=False`, y PRD §7.26 quiere la columna nullable. `WebhookEventModel` la declara directamente, conservando el tipo `Uuid`, la FK a `tenants.id` y el `index=True` que el mixin habría dado:

```python
tenant_id: Mapped[uuid.UUID | None] = mapped_column(
    Uuid, ForeignKey("tenants.id"), nullable=True, index=True, default=None
)
```

**Lo importante es que sigue teniendo la columna**, así que `tenant_scoped_classes()` —que selecciona por presencia, no por herencia del mixin— la incluye igual, y el filtro global le aplica `tenant_id == X` en sesión marcada, **escondiendo justo las filas `NULL`** que `reservations-webhooks` tendrá que procesar. Confirmado en `/sdd:new`: se mantiene así y se fija con test.

Rejected: excluir la clase del filtro con una lista de exención — abriría un bypass de la regla 1 de `steering/security.md` que hoy no existe.
Rejected: `nullable=False` — obligaría a resolver el tenant antes de persistir y perdería los payloads no atribuibles, que es exactamente lo que el PRD evita.

### D5 — Tres patrones de timestamp, según lo que declare el PRD

**Chosen:** no se homogeneiza; cada tabla lleva lo que PRD §7.17-7.26 le declara.

| Patrón | Tablas |
|---|---|
| `TimestampMixin` (`created_at` + `updated_at`) | `pricing_rules`, `reviews`, `review_response_drafts`, `owner_statements`, `notification_logs` |
| Solo timestamp de creación, declarado a mano con `server_default=func.now()` | `price_recommendations.created_at`, `expenses.created_at`, `audit_logs.created_at`, `webhook_events.received_at` |
| Ninguno de los dos | `owner_approvals` (tiene `requested_at` NOT NULL y `responded_at` nullable) |

**Precisión sobre `owner_approvals.requested_at`**, añadida tras el panel de la sección 2, que la señaló como contradicción entre esta tabla y el código: la columna **sí lleva `server_default=func.now()`**. "Ninguno de los dos" significa que la tabla no gana las columnas `created_at`/`updated_at` que el PRD no le declara — no que su timestamp de creación reciba un trato distinto al del resto del esquema. `requested_at` **es** el timestamp de creación de la fila; §7.19 no declara `created_at` precisamente porque ese papel ya lo cumple. El argumento decisivo no es el precedente sino **la coherencia interna de esta propia propuesta**: R3.4 exige `TimestampMixin` para las tablas a las que el PRD declara `created_at`/`updated_at`, y el mixin (`app/core/db.py`) lleva `server_default=func.now()` hardcodeado. Es decir, R3.4 ordena exactamente el patrón "el PRD no muestra `DEFAULT`, el ORM lo pone igual" para otras tablas de este mismo esquema — así que la lectura literal de R3.1 que condenaría a `requested_at` **es contradictoria con R3.4 dentro del mismo change**, no solo incoherente con lo ya archivado. El precedente lo corrobora: el PRD declara `created_at TIMESTAMPTZ NOT NULL` sin `DEFAULT` en las 23 tablas de §7 y el mixin las defaultea todas, así que la lectura literal condenaría también a las 16 entidades archivadas. Quitárselo solo a esta columna sería la incoherencia, no la fidelidad.

Precedente del patrón intermedio: `TimelineEventModel` y `PropertyStateTransitionModel`, que ya declaran `created_at` sin mixin por ser inmutables.

`owner_approvals` es el caso incómodo — su `status` **sí muta** (`PENDING`→`APPROVED`/`REJECTED`/`EXPIRED`), así que es la única tabla editable del esquema sin `updated_at`, y una expiración automática por job no dejará rastro temporal (`responded_at` se quedaría NULL). **Resuelto en el gate de design (OQ1: fidelidad estricta)**: se queda como el PRD lo declara. Si `maintenance` necesita `updated_at` al implementar el flujo de aprobación, lo añade entonces con una migración barata — nadie escribe esta tabla hasta ese change, así que estará vacía. Se descartó `TimestampMixin` con divergencia documentada al estilo ADR 0005: allí la divergencia era forzosa (el login solo recibe email), aquí es evitable.

Rejected: dar `TimestampMixin` a las diez — añade columnas que el PRD no pide y rompe la regla "reproduce exactamente el esquema del PRD" que el revisor de arquitectura aplica contra §7.

### D6 — Diez tipos `ENUM` nativos nuevos, nombrados `<Entidad><Campo>`

**Chosen:** los 10 enums de §7.17-7.26 son todos inline y sin nombre en el PRD, así que se nombran con la convención ya usada en `domain-foundation-ops` y se marcan `ASSUMPTION` en el código.

| Entidad.campo | Enum Python | Tipo Postgres |
|---|---|---|
| `PriceRecommendation.status` | `PriceRecommendationStatus` | `price_recommendation_status` |
| `OwnerApproval.related_type` | `OwnerApprovalRelatedType` | `owner_approval_related_type` |
| `OwnerApproval.status` | `OwnerApprovalStatus` | `owner_approval_status` |
| `Review.channel` | `ReviewChannel` | `review_channel` |
| `Review.sentiment` | `ReviewSentiment` | `review_sentiment` |
| `Review.status` | `ReviewStatus` | `review_status` |
| `OwnerStatement.status` | `OwnerStatementStatus` | `owner_statement_status` |
| `Expense.category` | `ExpenseCategory` | `expense_category` |
| `NotificationLog.channel` | `NotificationChannel` | `notification_channel` |
| `NotificationLog.status` | `NotificationStatus` | `notification_status` |

Ninguno colisiona con los 14 tipos ya existentes. `notification_channel`, `review_channel` y el existente `conversation_channel` son **tres tipos distintos** con conjuntos de valores distintos — mismo criterio con el que `-ops` separó `incident_severity` de `timeline_severity`.

Quedan como `VARCHAR` por fidelidad al PRD, aunque parezcan enumerables: `webhook_events.provider`, `webhook_events.event_type`, `notification_logs.notification_type`, `notification_logs.related_type`, `audit_logs.action`, `audit_logs.entity_type`.

Rejected: reutilizar `ConversationChannel` para `NotificationLog.channel` — `PUSH`/`IN_APP`/`CONSOLE` no existen en el de conversaciones.

### D7 — Las tres referencias polimórficas van sin FK, con comentario

**Chosen:** `owner_approvals.related_id`, `notification_logs.related_id` y `audit_logs.entity_id` son `Uuid` sin `ForeignKey`, porque apuntan a tablas distintas según su columna de tipo acompañante (`related_type` enum, `related_type` varchar, `entity_type` varchar). Cada una lleva comentario en el modelo diciendo que la ausencia de FK es deliberada, no un olvido — si no, el primer revisor que pase lo marcará como bug.

Los índices del PRD ya cubren el acceso por par: `INDEX(related_type, related_id)` en `notification_logs`, `INDEX(tenant_id, entity_type, entity_id)` en `audit_logs`. `owner_approvals` no lleva índice sobre el par porque el PRD no se lo declara.

Rejected: tablas de enlace por tipo — sobreingeniería para un change de estructura de datos, y divergiría del esquema del PRD.

### D8 — `SET NULL` solo en las FK nullable hacia `users`, `RESTRICT` en todo lo demás

**Chosen:** mantiene la regla de `domain-foundation-core`/`-ops` (el borrado se modela por `status`, nunca `DELETE` real; el histórico no se pierde si se purga un `User`).

- `ON DELETE SET NULL`: `owner_approvals.responded_by`, `review_response_drafts.approved_by`, `expenses.approved_by`, `notification_logs.recipient_user_id`, `audit_logs.actor_user_id`.
- `ON DELETE RESTRICT`: el resto, **incluidas las nullable hacia no-`User`** — `pricing_rules.property_id`, `reviews.reservation_id`, `expenses.statement_id`, `expenses.incident_id`.
- `tenant_id`: sin `ondelete` explícito, igual que el mixin.

### D9 — El índice `DESC` de `audit_logs` con `text("created_at DESC")`

**Chosen:** `INDEX(tenant_id, actor_user_id, created_at DESC)` de PRD §7.25 se declara en `__table_args__` con `Index("ix_audit_logs_tenant_id_actor_user_id_created_at", "tenant_id", "actor_user_id", text("created_at DESC"))`. Precedente exacto y ya probado contra `alembic check`: las tres del `TimelineEventModel` y la de `PropertyStateTransitionModel`.

### D10 — Una sola revisión Alembic sobre `e1eed2e039ee`

**Chosen:** `alembic revision --autogenerate` produce una revisión con `down_revision = "e1eed2e039ee"` (head actual), revisada a mano para: orden de creación por dependencia (`pricing_rules`→`price_recommendations`, `reviews`→`review_response_drafts`, `owner_statements`→`expenses`), orden inverso en el `downgrade`, y la lista `_ENUM_TYPE_NAMES` con los 10 tipos de D6 más el bucle `postgresql.ENUM(name=...).drop(op.get_bind(), checkfirst=True)` — Alembic no emite `DROP TYPE` solo, y dejar tipos huérfanos rompe el siguiente `upgrade` con *"type already exists"*.

Rejected: una revisión por módulo — cinco revisiones para un único cambio atómico complicaría el desandado sin ganar nada.

### D11 — El registro se toca en un solo fichero

**Chosen:** los 6 módulos con tabla nueva (`pricing`, `reviews`, `statements`, `notifications`, `audit`, `integrations`) se añaden a `app/core/models_registry.py` — a los dos sitios, el bloque de `import` y la tupla `DOMAIN_MODEL_MODULES`. **No** se tocan `alembic/env.py` ni `tests/conftest.py`, que importan el registro. `test_the_registry_lists_every_domain_that_has_models` compara contra el glob en disco, así que un olvido falla el test en vez de dejar tablas fuera del filtro de tenant.

Nota: `maintenance` ya está en la lista (tiene `incidents`), así que `owner_approvals` no añade entrada.

### D12 — Sin `CHECK` constraints ni validación de JSONB

**Chosen:** el PRD documenta rangos en comentarios (`rating` 1.0-5.0, `confidence` 0-1) y schemas de JSONB (§7.17) pero **no declara ninguna constraint**, así que el esquema tampoco. Los `JSONB` se persisten sin validar su forma; los schemas se validarán donde se consuman (`revenue`).

**Resuelto en el gate de design (OQ3: sin CHECK)**. El argumento de "barato ahora, caro sobre tabla poblada" no aplica: nadie escribe estas tablas hasta `revenue`, así que añadirlos después sigue siendo barato. Se descartó añadir `rating BETWEEN 1.0 AND 5.0`, `confidence BETWEEN 0 AND 1` y no-negatividad en importes porque obligaría a decidir aquí si un importe negativo es legítimo (un abono, un ajuste) — que es precisamente la discusión que le toca a `revenue`, con el caso de uso delante.

### D13 — Tests: dos ficheros por módulo, más tres transversales existentes

**Chosen:** replica el layout de `tests/maintenance/` y `tests/timeline/`: `tests/<módulo>/test_entities.py` (instanciación en Python puro, sin DB) y `tests/<módulo>/test_models.py` (integración contra Postgres real). Además se extienden tres ficheros que ya existen:

- `tests/test_models_registry.py::test_the_tenant_filter_sees_the_child_tables_that_have_no_tenant_id_of_their_own` — añadir `review_response_drafts` como cuarto hijo sin `tenant_id`.
- `tests/test_tenant_filter.py` — el test nuevo de D4: en sesión marcada, las filas de `webhook_events` con `tenant_id NULL` no son visibles.
- `tests/test_migrations.py` — la nueva revisión se desanda sola contra `e1eed2e039ee`, con una tabla y un tipo `ENUM` comprobados por nombre, siguiendo el patrón de objetivos explícitos que el fichero ya usa.

Los casos de DB que exige R6.2 se reparten: `UNIQUE(property_id, date)` y `UNIQUE(tenant_id, property_id, period_start, period_end)` y `UNIQUE(review_id)`; un `RESTRICT` (borrar una `Property` con `PricingRule`); un `SET NULL` (borrar un `User` que respondió un `OwnerApproval`); y la ida y vuelta de `Decimal` con escala (R6.3).

## Changes by area

| Area | Files | Change |
|---|---|---|
| `pricing` (nuevo) | `backend/app/pricing/{__init__.py,domain/{__init__,entities,enums}.py,infrastructure/{__init__,models}.py}` | `PricingRule`, `PriceRecommendation` + `PriceRecommendationStatus` |
| `maintenance` (existe) | `backend/app/maintenance/domain/{entities,enums}.py`, `infrastructure/models.py` | Añadir `OwnerApproval` + `OwnerApprovalRelatedType`/`OwnerApprovalStatus` a los ficheros existentes de `Incident` |
| `reviews` (nuevo) | `backend/app/reviews/{…}` | `Review`, `ReviewResponseDraft` + `ReviewChannel`/`ReviewSentiment`/`ReviewStatus` |
| `statements` (nuevo) | `backend/app/statements/{…}` | `OwnerStatement`, `Expense` + `OwnerStatementStatus`/`ExpenseCategory` |
| `notifications` (nuevo) | `backend/app/notifications/{…}` | `NotificationLog` + `NotificationChannel`/`NotificationStatus` |
| `audit` (nuevo) | `backend/app/audit/{…}` | `AuditLog`, sin enums |
| `integrations` (existe) | `backend/app/integrations/domain/entities.py` (nuevo), `infrastructure/models.py` (**nuevo** — hallazgo 1) | `WebhookEvent`, sin enums; primera tabla del módulo |
| Registro | `backend/app/core/models_registry.py` | +6 imports, +6 entradas en `DOMAIN_MODEL_MODULES` (D11) |
| Migración | `backend/alembic/versions/<rev>_domain_foundation_financial.py` | 10 tablas, 10 tipos `ENUM`, `down_revision = "e1eed2e039ee"` (D10) |
| Tests nuevos | `backend/tests/{pricing,reviews,statements,notifications,audit}/{__init__,test_entities,test_models}.py`, `backend/tests/{maintenance,integrations}/test_*` | D13 |
| Tests existentes | `backend/tests/{test_models_registry,test_tenant_filter,test_migrations}.py` | D13 |
| Steering | `sdd/steering/architecture.md`, `sdd/steering/backend-architecture.md` | Lista de dominios (+`reviews`, +`audit`) y la excepción de D2. **Ya hecho en el commit del change (tarea 5.2)**, adelantado desde el archivado para que el panel de `/sdd:review` no marcara D2 como violación |
| Tests transversales | `backend/tests/test_session_marking.py` (nuevo) | Escáner AST que prohíbe a `app/` tocar `session.info`, con su meta-test. No estaba en D13: lo exigió el panel de seguridad al ver que la prohibición del límite 2 era solo prosa y que el único ejemplo ejecutable era un test en verde. Fichero propio, no `test_tenant_filter.py`, que es todo integración async contra Postgres — misma forma y vecindario que `test_layering.py` |
| Roadmap | `sdd/roadmap.md`, entrada `celery-jobs` | Anotar el coste del filtro global (~13 → ~22 clases, OQ4) — **al archivar** |
| Roadmap | `sdd/roadmap.md`, entrada `access-notifications` | Anotar el contrato de cleartext que hereda: `notification_logs.subject`/`body` solo admiten la forma enmascarada `****XX` de un **código de acceso** — la regla 4 no concede forma enmascarada al `document_number` (le exige ausencia de los listados) ni a la `wifi_password`; esas dos, y `last_error`, van en forma estructurada (panel de seguridad, sección 1) — **al archivar** |
| Roadmap | `sdd/roadmap.md`, entrada `reservations-webhooks` | Anotar el contrato equivalente para `webhook_events.payload`/`error` (regla 3/4 redactadas antes de persistir; `error` nunca devuelve el cuerpo crudo) **y** que las filas con `tenant_id NULL` solo se leen desde una sesión **nunca marcada**, jamás quitándole la marca a una que la tenga (panel de seguridad, sección 3) — **al archivar** |
| Roadmap | `sdd/roadmap.md`, entrada `user-management` | Anotar el contrato de `audit_logs.changes`: los campos de las reglas 3/4 se registran como `{"changed": true}`, nunca por su valor ni enmascarados. Es el primer escritor real de la tabla (cambios de rol), y era la única de las tres anclas que faltaba (panel de `/sdd:review`) — **al archivar** |

Sin cambios en: `docker-compose.yml` (el servicio `migrate` ya aplica `upgrade head`), `.env.example`, `alembic/env.py`, `tests/conftest.py`, frontend, workflows de CI.

## Data & interfaces

**10 tablas nuevas**, todas con PK `UUID`; 8 con `tenant_id` obligatorio vía `TenantScopedMixin`, `webhook_events` con `tenant_id` nullable a mano (D4) y `review_response_drafts` sin `tenant_id` (hijo de `reviews` por FK única).

| Tabla | Constraints/índices propios |
|---|---|
| `pricing_rules` | 5 columnas `JSONB` con `server_default` `'{}'`/`'[]'`; `property_id` nullable |
| `price_recommendations` | `UNIQUE(property_id, date)` |
| `owner_approvals` | sin índices propios; `related_id` sin FK (D7) |
| `reviews` | sin índices propios |
| `review_response_drafts` | `UNIQUE(review_id)`; sin `tenant_id` |
| `owner_statements` | `UNIQUE(tenant_id, property_id, period_start, period_end)`; 11 `Numeric(10,2)` con `server_default '0'` |
| `expenses` | `statement_id` e `incident_id` nullable; `currency` `server_default 'EUR'` |
| `notification_logs` | `INDEX(tenant_id, status, sla_deadline_at)`, `INDEX(related_type, related_id)` |
| `audit_logs` | `INDEX(tenant_id, entity_type, entity_id)`, `INDEX(tenant_id, actor_user_id, created_at DESC)` |
| `webhook_events` | `INDEX(provider, processed, received_at)` |

**Tipos Postgres nuevos:** los 10 de D6. **API, eventos, variables de entorno y config:** ninguno — este change no expone nada.

## Risks & mitigations

- **El filtro global de tenant se encarece un 70 %.** `_scope_statement_to_tenant` no está memoizado a propósito (docstring de `tenant_scoped_classes`) y adjunta un `with_loader_criteria` **por clase scopeada y por sentencia ORM**. Hoy son ~13; con este change pasan a ~22. El docstring justifica el coste como *"un escaneo sobre un par de docenas de mappers"* — este change acerca esa cifra a su límite. *Mitigación*, **resuelta en el gate de design (OQ4: anotar y seguir)**: al archivar se registra la cifra real (~13 → ~22) en `specs/domain-foundation-financial.md` y en la entrada de roadmap de `celery-jobs`, que será el primer consumidor con volumen al leer `notification_logs` cada minuto. Se descartó añadir aquí una prueba de rendimiento (no existe todavía ninguna query de negocio sobre estas 10 tablas, así que mediría un escenario inventado, con el riesgo habitual de intermitencia en CI) y se descartó reabrir la decisión D16 de `auth-tenancy` (su docstring explica por escrito por qué no está memoizado — excluiría tablas importadas tarde; rehacerlo merece change propio, no un rincón de éste).
- **`alembic check` falla si autogenerate no reproduce el índice `DESC`.** *Mitigación*: `test_the_models_match_the_migrations` ya lo ejerce y el patrón está probado por las cuatro índices `DESC` existentes; si divergiera, se ajusta la revisión a mano.
- **Downgrade que deja tipos `ENUM` huérfanos** → el siguiente `upgrade` peta con *"type already exists"*. *Mitigación*: `_ENUM_TYPE_NAMES` con los 10 tipos y el test de reaplicación (`test_the_revisions_can_be_reapplied_after_a_downgrade`) extendido a la revisión nueva.
- **Orden de creación de tablas con FK cruzadas** (`expenses`→`incidents` de otro módulo, `expenses`→`owner_statements`). *Mitigación*: autogenerate lo resuelve por dependencia, pero la revisión se revisa a mano y el test de migraciones lo ejerce sobre una DB vacía.
- **Una tabla `webhook_events` que esconde filas.** Un desarrollador futuro que consulte desde una sesión marcada verá cero resultados sin error. *Mitigación*: el test de D4 lo deja escrito, y el docstring de `_scope_statement_to_tenant` gana el caso en su límite 2 (sesiones sin marcar) además del cuarto hijo en el límite 5.
- **Change grande: 10 entidades, 10 tablas, 5 módulos nuevos.** *Mitigación*: es estructura de datos pura y repetitiva, con dos hermanos de 8 entidades ya archivados como plantilla; `/sdd:tasks` lo trocea por módulo para que cada sección sea verificable por separado.

## Open questions

Ninguna abierta. Las cuatro que planteó este design se resolvieron en su gate; cada una queda registrada en la decisión que la motivó, con las alternativas descartadas y su motivo.

| # | Pregunta | Resolución | Dónde vive |
|---|---|---|---|
| OQ1 | `owner_approvals` sin `updated_at` | Fidelidad estricta al PRD; `maintenance` lo añadirá si lo necesita, sobre tabla vacía | D5 |
| OQ2 | La frase de `backend-architecture.md` que D2 incumple | Se matiza el steering al archivar, con la excepción explícita | D2 + *Changes by area* |
| OQ3 | `CHECK` de rango y no-negatividad | No se añaden; la validación pertenece al `domain/` de `revenue` | D12 |
| OQ4 | Coste del filtro global (~13 → ~22 clases) | Se anota la cifra en la spec y en la entrada de `celery-jobs`; sin prueba de rendimiento aquí | *Risks* + *Changes by area* |

**Cuatro acciones diferidas al archivado** (recogidas en *Changes by area* para que `/sdd:archive` no dependa de esta conversación). Las cuatro son anotaciones en `sdd/roadmap.md`; **los dos ficheros de steering ya no están en esta lista** — se editaron en el propio commit del change (tarea 5.2), y dejarlos aquí habría hecho que `/sdd:archive` los reintentara:

1. La anotación del coste del filtro en `sdd/roadmap.md` → entrada `celery-jobs`.
2. La anotación del contrato de cleartext en `sdd/roadmap.md` → entrada `access-notifications`: `notification_logs.subject`/`body` solo admiten la forma enmascarada `****XX` de un **código de acceso** — la regla 4 no concede forma enmascarada al `document_number` (le exige ausencia de los listados) ni a la `wifi_password`; esas dos, y `last_error`, van en forma estructurada. Es la mitad duradera del arreglo del hallazgo 1 del panel de seguridad — el docstring del modelo es la otra mitad.
3. La anotación equivalente en `sdd/roadmap.md` → entrada `reservations-webhooks`, con las **dos** obligaciones que hereda: redactar los campos de las reglas 3/4 antes de persistir `webhook_events.payload` (y no devolver el cuerpo crudo en `error`), y leer las filas con `tenant_id NULL` desde una sesión **nunca marcada** — nunca quitándole la marca a una sesión que la tenga, porque `session.info` es por sesión y desactivaría el filtro para las 23 tablas.
4. La anotación en `sdd/roadmap.md` → entrada `user-management` con el contrato de `audit_logs.changes`. Faltaba: era la única de las tres sin ancla, y este texto llegó a afirmar lo contrario hasta que el panel de `/sdd:review` lo detectó.

**Los tres sumideros de texto en claro del change**, para que se lean juntos: `notification_logs.subject`/`body`/`last_error`, `audit_logs.changes` y `webhook_events.payload`/`error`. Ninguno lo escribe nadie todavía; los tres llevan el contrato en el docstring de su modelo y una anotación en la entrada de roadmap de su futuro escritor (`access-notifications`, `user-management` y `reservations-webhooks` respectivamente).

**Y son dos formas del contrato, no una** — el panel las encontró descritas con tres verbos distintos y una referencia cruzada que las declaraba equivalentes. La segunda ronda del panel corrigió además **dónde** se corta la línea: no es "¿es prosa?" sino **¿el propósito de la columna exige enseñarle el valor a una persona?**

- **Estructurado, la regla por defecto** (`audit_logs.changes`, `webhook_events.payload`, `webhook_events.error`, `notification_logs.last_error`): el valor no sobrevive en absoluto — `{"changed": true}` o se elimina la clave. Los dos `error` son la misma clase de dato (un diagnóstico de proveedor que puede traer el cuerpo incrustado) y por eso van juntos; en la primera redacción quedaron en buckets opuestos.
- **Excepción única** (`notification_logs.subject`/`body`), y **solo para códigos de acceso**: se admite la forma enmascarada `****XX` de la regla 4. **El eje no concede nada por sí solo** — solo la regla 4 concede, y concede exactamente eso. Que el huésped necesite ver la contraseña WiFi no la autoriza: la regla 4 no le da forma enmascarada, así que el cuerpo persiste una plantilla o una referencia, nunca la credencial renderizada. Idem el `document_number`, al que la regla 4 exige ausencia de los listados.

Dos redacciones anteriores fallaron aquí y conviene que consten: la primera generalizaba a "cualquier valor de la regla 3" —lo que autorizaba un `document_number` enmascarado en una tabla con índice que hace barato listarla—, y la segunda dejaba el eje como criterio autónomo, que respondía "sí" para la contraseña WiFi y contradecía su propia enumeración.
