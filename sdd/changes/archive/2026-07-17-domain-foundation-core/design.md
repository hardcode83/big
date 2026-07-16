# Design: domain-foundation-core

## Context

`backend/` hoy solo tiene el esqueleto de `local-environment`: `app/main.py` (FastAPI + `/health`), `app/core/config.py` (`Settings`), `app/worker.py` (Celery vacío), sin ningún modelo de dominio, sin SQLAlchemy ni Alembic configurados todavía (`backend/pyproject.toml` solo trae `fastapi`, `celery`, `redis`, `pydantic-settings`). `docker-compose.yml` ya tiene `postgres:16` sano con healthcheck, pero nada lo usa: `backend`/`worker` no declaran `DATABASE_URL`. `.env.example` ya prevé esto ("Postgres... consumed by the postgres service + future backend DB connection"). Este change es el primer código que toca `SQLAlchemy`/`Alembic`/entidades — todo lo que sigue (`domain-foundation-ops`, `domain-foundation-financial`, `auth-tenancy`, ...) construye encima de los patrones que se fijan aquí.

`sdd/steering/architecture.md` ya declara la lista de dominios de negocio: `auth, tenants, properties, reservations, guests, cleaning, maintenance, messaging, access, pricing, statements, notifications, timeline, integrations`. Las 8 entidades de este change mapean a 6 de esos dominios ya nombrados — no se inventa ningún nombre de módulo nuevo.

## Decisions

### D1 — Mapeo de entidades a módulos de dominio existentes

**Chosen:** usando los nombres de dominio ya fijados en `architecture.md`:

| Entidad(es) | Módulo |
|---|---|
| `Tenant`, `TenantConfig` | `backend/app/tenants/` |
| `User` | `backend/app/auth/` |
| `Property`, `PropertyStateTransition` | `backend/app/properties/` |
| `TimelineEvent` | `backend/app/timeline/` |
| `Guest` | `backend/app/guests/` |
| `Reservation` | `backend/app/reservations/` |

`User` va en `auth/` (no en `tenants/`) porque `architecture.md` ya reserva ese nombre para el dominio de identidad — aunque la lógica de autenticación real llega con `auth-tenancy`, el dato `User` pertenece conceptualmente a ese dominio desde ya.

Rejected: crear un módulo `users/` nuevo — divergiría de la lista de dominios ya fijada en steering sin necesidad.

### D2 — Solo `domain/` + `infrastructure/` por módulo en este change

**Chosen:** cada módulo de este change solo tiene `domain/` (entidades + enums) e `infrastructure/` (modelos SQLAlchemy). No se crean `application/` (casos de uso) ni `api/` (routers) todavía — no existe ningún caso de uso real que orquestar (misma lógica YAGNI que la decisión ya tomada de diferir los puertos de repositorio).

Rejected: scaffoldear las 4 carpetas vacías (`domain/application/infrastructure/api/`) por adelantarse a la estructura "objetivo" — carpetas vacías sin contenido no aportan nada y `git` ni siquiera las trackea sin un `.gitkeep` artificial.

### D3 — Enums de dominio en `domain/enums.py` por módulo, sin módulo `shared/`

**Chosen:** cada enum vive en `domain/enums.py` del módulo dueño de la entidad que lo usa primero (p.ej. `PropertyOperationalState` en `properties/domain/enums.py`, aunque `cleaning`/`maintenance` lo consulten más adelante — importarlo de `properties.domain.enums` no viola la regla de dependencia de capas, que es sobre `domain→infra/api`, no sobre domain-a-domain).

Comprobado contra las 8 entidades de este change: **ningún enum se usa realmente en más de un dominio dentro de este subconjunto** (`PropertyOperationalState` solo lo usan `Property` y `PropertyStateTransition`, ambas ya en `properties/`). La condición R1.2 del proposal ("si un enum se usa en más de un dominio, va en un módulo compartido") no se dispara todavía — se resuelve así: no crear `shared/` de forma especulativa.

Rejected: `backend/app/shared/domain/enums.py` desde ya — sería un cajón de sastre sin un caso real que lo justifique hoy; se crea el día que un enum lo necesite de verdad (p.ej. si `cleaning` necesitara *definir*, no solo consultar, un enum común).

### D4 — Las 8 entidades como dataclasses simples en este change

**Chosen:** ninguna de las 8 entidades protege una invariante real *todavía* — las invariantes que el PRD sí define (transiciones de `PropertyOperationalState` vía `PropertyStateMachine`, ciclo de vida de `Reservation`, hash de contraseña de `User`) pertenecen explícitamente a changes posteriores (`timeline-state-machine`, `reservations`, `auth-tenancy`). Modelar hoy una "invariante" en, p.ej., `Property.transition_to(...)` sería adelantar lógica de negocio que ese change todavía no ha diseñado. Por tanto las 8 son `@dataclass` simples (atributos + `__post_init__` solo para validaciones de forma, p.ej. `check_out_date > check_in_date` en `Reservation`, que es un invariante estructural, no de negocio).

Rejected: dar ya métodos ricos a `Property`/`Reservation`/`User` anticipando invariantes de changes futuros — el diseño de esos changes podría decidir una forma distinta (p.ej. `PropertyStateMachine` como servicio de dominio externo a `Property`, no un método `Property.transition_to()`), y este change no debe prejuzgarlo.

### D5 — Sin mapeo ORM↔dominio todavía

**Chosen:** no se escribe ninguna función `to_domain()`/`from_domain()` en este change. Sin repositorio que las llame (D del proposal: puertos diferidos), escribirlas ahora sería código muerto. El change que introduzca el primer repositorio real de cada entidad (`auth-tenancy` para `User`/`Tenant`, `reservations` para `Reservation`, ...) añade el mapper junto con el puerto que lo necesita.

Rejected: escribir los mappers ya "para no repetir el viaje" — mismo argumento YAGNI ya aceptado para los puertos; un mapper sin consumidor es tan especulativo como un puerto sin consumidor.

### D6 — Infra de DB compartida en `backend/app/core/db.py`

**Chosen:** `backend/app/core/db.py` (junto a `config.py`, ya existente) define: `Base` (declarative base de SQLAlchemy 2.x), el engine async (`create_async_engine`, URL desde `Settings.database_url`), `async_session_factory`, y tres mixins reutilizables para `infrastructure/models.py` de cada módulo: `UUIDPrimaryKeyMixin` (`id: Mapped[UUID]`), `TimestampMixin` (`created_at`/`updated_at` `TIMESTAMPTZ`), `TenantScopedMixin` (`tenant_id` FK `NOT NULL` a `tenants.id`). Evita repetir las mismas 4 columnas en las 7 tablas que las llevan (todas salvo `tenants`).

`core/` ya es, por convención de `local-environment`, el sitio de plumbing transversal (ahí vive `Settings`) — `db.py` encaja sin inventar una carpeta nueva. Solo `infrastructure/models.py` importa de aquí; `domain/entities.py` nunca lo toca (mantiene la regla de dependencia de `backend-architecture.md`).

Rejected: un `Base`/mixin por módulo — rompe el autogenerate de Alembic, que necesita un único `MetaData` para diffear todas las tablas a la vez (D9).

### D7 — Postgres ENUM nativo vía `sa.Enum(PyEnum)`

**Chosen:** cada enum de dominio (`enum.Enum` de Python puro en `domain/enums.py`) se mapea en `infrastructure/models.py` con `sa.Enum(MiEnumPython, name="mi_enum", native_enum=True)` — Postgres ENUM real, tal y como el PRD §7 escribe literalmente `ENUM(...)` en cada esquema.

Riesgo conocido (ver Risks): los ENUM nativos de Postgres son más costosos de evolucionar (`ALTER TYPE ... ADD VALUE`) que un `VARCHAR`+`CHECK`. Se acepta porque el PRD lo pide explícitamente y porque los enums de este change son ya el catálogo cerrado del PRD (cambiar sus valores es raro y, cuando pase, ya será una migración explícita de todos modos).

Rejected: `VARCHAR` + `CHECK constraint` — más fácil de evolucionar pero diverge de lo que el PRD especifica literalmente sin necesidad real todavía.

### D8 — Política de borrado de FKs: `RESTRICT` por defecto, `SET NULL` en referencias nullable a `User`

**Chosen:** el PRD no especifica `ON DELETE` para ninguna FK de estas 8 entidades. El propio esquema del PRD modela el borrado como *soft delete vía `status`* (`Tenant.status=CANCELLED`, `Property.status=INACTIVE`, `User.status=INACTIVE`) — nunca se espera un `DELETE` real sobre estas filas en operación normal. Por eso: `RESTRICT` (comportamiento por defecto de SQLAlchemy/Postgres) en toda FK `NOT NULL` — protege contra borrar accidentalmente un `Tenant`/`Property` que todavía tiene hijos. En las FKs nullable que apuntan a `User` (`PropertyStateTransition.triggered_by_user_id`), `SET NULL` — si algún día se purga un `User` por GDPR, el histórico (`PropertyStateTransition`) no debe perderse, solo perder la atribución.

Rejected: `CASCADE` en cualquier FK — borraría en cascada historial (`PropertyStateTransition`, `TimelineEvent`, `Reservation`) que el propio PRD marca como inmutable/auditable; nunca es lo que se quiere aquí.

### D9 — Alembic con el template async oficial, en `backend/alembic/`

**Chosen:** `alembic init -t async` (soportado oficialmente por SQLAlchemy 2.x) — `env.py` reutiliza el mismo engine async de `core/db.py` vía `connectable.run_sync(...)`, sin añadir un segundo driver síncrono. `target_metadata = Base.metadata`; `env.py` importa explícitamente el módulo `infrastructure/models.py` de cada uno de los 6 módulos de este change (registra sus tablas en `Base.metadata` antes del autogenerate) — futuros changes añaden su propio import ahí, un patrón explícito y sin magia.

Rejected: driver síncrono adicional (`psycopg2`) solo para Alembic — dependencia extra sin necesidad, existiendo ya el template async soportado oficialmente.

### D10 — Una única migración baseline (no una por tabla)

**Chosen:** una sola revisión Alembic (`baseline_domain_foundation_core`) crea las 8 tablas en orden de dependencia (`tenants` → `tenant_configs`/`users`/`properties`/`guests` → `property_state_transitions`/`reservations` → `timeline_events`). Es la primera migración del proyecto sobre una DB vacía — no hay historial incremental que preservar todavía.

Rejected: una migración por tabla — ceremonia sin beneficio para un baseline desde cero; tiene sentido cuando el esquema evoluciona con el tiempo, no aquí.

### D11 — Migraciones aplicadas por un servicio `migrate` dedicado en compose, no desde el entrypoint de `backend`/`worker`

**Chosen:** nuevo servicio `migrate` en `docker-compose.yml`: mismo `build` que `backend`, `command: uv run alembic upgrade head`, `depends_on: {postgres: condition: service_healthy}`, sin `restart` (one-shot, termina tras aplicar). `backend` y `worker` añaden `depends_on: {migrate: condition: service_completed_successfully}` (Compose v2.20+, ya en uso desde `local-environment`). Mantiene el DX de "cero pasos manuales" (`make up` ya aplica migraciones solo) sin que dos contenedores (`backend` y `worker`) compitan corriendo `alembic upgrade head` a la vez.

Rejected: correr la migración en el entrypoint de `backend` (y/o `worker`) — con las dos réplicas actuales (`backend`+`worker`, misma imagen) arrancando a la vez, ambas intentarían migrar simultáneamente; Alembic tiene cierto locking pero añade una carrera innecesaria que un servicio dedicado evita por diseño. Rejected también: paso manual (`make migrate`) — rompe el DX de cero-pasos ya establecido en `local-environment` (commit `56d92c7`).

### D12 — `DATABASE_URL` fijado en `docker-compose.yml`, no en `.env`

**Chosen:** igual que `REDIS_URL`/`BACKEND_INTERNAL_URL` (decisión ya sentada en `local-environment`), `DATABASE_URL` se compone en `docker-compose.yml` → `environment:` de `backend`/`worker`/`migrate`: `postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}` — determinado por la topología de red de compose (host `postgres`, puerto `5432` fijo), no algo que un desarrollador deba configurar aparte. `.env.example` no cambia (ya trae `POSTGRES_DB/USER/PASSWORD`, con el comentario "consumed by... future backend DB connection" ya anticipando esto).

Rejected: pedir `DATABASE_URL` completa en `.env.example` — duplicaría información que ya vive en `POSTGRES_*` y podría desincronizarse de la topología real de compose.

### D13 — Tests en subcarpetas `backend/tests/<dominio>/`

**Chosen:** `backend/tests/tenants/`, `backend/tests/auth/`, `backend/tests/properties/`, `backend/tests/timeline/`, `backend/tests/guests/`, `backend/tests/reservations/` — cada una con `test_entities.py` (unit, Python puro, sin DB — `testing.md`: "domain/: unit tests puros, sin mocks") y `test_models.py` (integration, contra el Postgres real del stack — verifica que el modelo SQLAlchemy + la migración producen el esquema esperado). `backend/tests/test_health.py` (de `local-environment`) se queda donde está, plano — es transversal, no de un dominio.

Rejected: ficheros planos `test_tenants_entities.py`, `test_tenants_models.py`, ... en `backend/tests/` — con 6 módulos × 2 tipos de test ya son 12 ficheros; anidar por dominio escala mejor y refleja `app/`.

### D14 — `Settings.database_url`: fallback a `localhost:5432` para ejecución en host (deviation, añadida durante `/sdd:run`)

**Chosen:** implementando D6/D12 surgió un hueco no cubierto por el diseño original: `postgres` (el hostname que D12 fija en `docker-compose.yml`) no resuelve fuera de la red de compose, pero `project.md` ya fija el comando de tests como `cd backend && uv run pytest` — ejecución en host. Además `Settings.model_config.env_file=".env"` era relativo al cwd, así que nunca encontraba el `.env` real (raíz del repo, no `backend/`) al correr desde `backend/`. Se resuelve con: (a) `env_file` calculado como ruta absoluta desde `Path(__file__)` hasta la raíz del repo, y (b) un `model_validator` que rellena `database_url` con `postgresql+asyncpg://{user}:{password}@localhost:5432/{db}` **solo si** la env var `DATABASE_URL` no vino ya fijada (Docker Compose la sigue sobreescribiendo con el hostname `postgres`, D12 intacto). Esto también corrige un bug latente de `local-environment`: los campos `postgres_*` de `Settings` nunca se cargaban realmente desde `.env` en ejecución host-side (no se notó porque hasta ahora nada los usaba).

Rejected: exigir que los tests de integración corran siempre dentro del contenedor (`docker compose exec backend uv run pytest`) — contradice el comando ya establecido en `project.md` y añade fricción sin necesidad, existiendo ya el puerto de Postgres publicado al host (`ports: 5432:5432`, de `local-environment`).

### D15 — `TenantScopedMixin.tenant_id` necesita tipo `Uuid` explícito (deviation, añadida durante `/sdd:run`)

**Chosen:** `TenantScopedMixin` (D6) usa `@declared_attr` para que cada módulo obtenga su propia columna `tenant_id` (necesario para que un `ForeignKey` definido en un mixin no se comparta entre subclases). Se descubrió implementando `auth/infrastructure/models.py` que, sin un tipo explícito (`mapped_column(Uuid, ForeignKey("tenants.id"), ...)`), SQLAlchemy resuelve `tenant_id` como `NullType` si el módulo que importa `UserModel` no importó antes `TenantModel` (la tabla `tenants` aún no registrada en `Base.metadata` en el momento en que se evalúa el `declared_attr`) — un bug de orden de import silencioso y peligroso (columna sin tipo real, DDL inválido). Se soluciona pasando `Uuid` explícito a `mapped_column`, que elimina la dependencia del orden de import por completo (verificado registrando `UserModel` sin importar `TenantModel` primero).

Rejected: confiar en que Alembic siempre importe los módulos en el orden correcto (D9 ya lo hace, en orden de dependencia) — cierto para la migración, pero cualquier test o script que importe un solo módulo de dominio de forma aislada (p. ej. `pytest tests/auth/` sin correr `tests/tenants/` antes) seguiría expuesto al bug sin el tipo explícito.

**Alcance ampliado**: el mismo problema reaparece en cualquier `mapped_column(ForeignKey(...))` que referencia una tabla de *otro* módulo sin tipo explícito (reproducido en `PropertyStateTransitionModel.triggered_by_user_id` → `users.id`) — no es exclusivo de `TenantScopedMixin`. Regla general aplicada desde aquí en adelante: toda columna FK a una tabla de otro módulo lleva `Uuid` explícito en `mapped_column(Uuid, ForeignKey(...))`, no solo las de los mixins compartidos.

### D16 — Correcciones del panel de revisión de las secciones 1-3 (deviation, añadida durante `/sdd:run`)

El panel de revisión (architect + security + qa) sobre las secciones 1-3 encontró 4 problemas reales, todos corregidos:

1. **`TimestampMixin` no generaba `TIMESTAMPTZ`** (architect, referente R3.2/`backend.md`): `Mapped[datetime]` sin `DateTime(timezone=True)` compilaba a `TIMESTAMP WITHOUT TIME ZONE`. Corregido en `core/db.py` y en el `created_at` manual de `PropertyStateTransitionModel` (que no usa el mixin, por no llevar `updated_at`).
2. **Enums sin nombre de tipo Postgres explícito** (architect, referente D7 y la sección Data & interfaces de este documento): sin `name=`, SQLAlchemy autogenera nombres (`tenantstatus`, no `tenant_status`) que no coinciden con los ya documentados aquí. Corregido pasando `sa.Enum(X, name="...", native_enum=True)` explícito en cada columna enum; la instancia de `PropertyOperationalState` se comparte entre `current_operational_state`/`to_state`/`from_state` para no duplicar el tipo Postgres.
3. **`DEFAULT`s del PRD solo a nivel Python, ausentes del DDL** (qa, referente R3.1): `default=` sin `server_default=` deja el `CREATE TABLE` sin cláusula `DEFAULT`, así que un INSERT que no pase por el ORM (una migración de datos, un script, `psql` directo) viola `NOT NULL` en columnas que el PRD sí define con default. Corregido añadiendo `server_default=` junto a `default=` en toda columna donde el PRD especifica un valor por defecto — verificado con `CreateTable(...).compile(dialect=postgresql.dialect())`.
4. **Motor de test compartido con pool de conexiones + bucles de evento por test** (qa, referente R6): `tests/conftest.py` reutilizaba el `engine` global de la app; con el event loop por-test de pytest-asyncio, la segunda prueba que toca DB en una misma sesión de test fallaba (`another operation is in progress` / `attached to a different loop`) porque las conexiones agrupadas por el pool quedaban ligadas al primer loop. Corregido: `db_session` crea su propio engine con `poolclass=NullPool` (sin conexiones persistentes entre usos) y lo dispone al finalizar cada test — desacopla el ciclo de vida de conexión de test del engine de la app.

Adicionalmente (mismo pase): los tests "roundtrip" de `tenants`/`auth` no ejercían de verdad las constraints `UNIQUE` que su nombre sugería. Se añadieron `test_tenant_config_tenant_id_is_unique` y `test_user_email_unique_per_tenant_but_reusable_across_tenants` (el segundo también confirma que el mismo email en dos tenants distintos SÍ está permitido, comportamiento correcto de R3.3).

### D17 — `downgrade()` debe dropear explícitamente los tipos ENUM de Postgres (deviation, añadida durante `/sdd:run`)

**Chosen:** Alembic autogenerate crea los 17 tipos `ENUM` de Postgres implícitamente (como efecto colateral del primer `CREATE TABLE` que referencia cada uno) pero **no genera `DROP TYPE`** en `downgrade()` — verificado ejecutando `alembic downgrade base` y comprobando `SELECT typname FROM pg_type WHERE typtype='e'`: los 17 tipos seguían ahí tras el downgrade, violando R4.2 ("sin dejar tablas, tipos ENUM ni índices huérfanos"). Se añade a mano, al final de `downgrade()`, un loop que dropea cada tipo con `postgresql.ENUM(name=...).drop(op.get_bind(), checkfirst=True)`. Verificado: `upgrade head` → `downgrade base` → `SELECT ... pg_type` vacío → `upgrade head` de nuevo sin errores de tipo duplicado.

Rejected: dejar que Alembic regenere el archivo — el propio autogenerate de SQLAlchemy no soporta esto de forma nativa (limitación conocida con `sa.Enum`/`native_enum=True`); hay que añadirlo a mano en cada migración baseline que introduzca tipos ENUM nuevos.

### D18 — Índices `created_at DESC` en tablas de historial/auditoría (fix del panel de revisión, sección 4-7)

El panel de revisión (architect) sobre las secciones 4-7 encontró que `PropertyStateTransitionModel` y `TimelineEventModel` declaraban sus índices por `created_at` en orden ascendente (`sa.Index("...", "property_id", "created_at")`), cuando tasks.md §4.3/§7.3 (derivado de R3.1/R3.3) especifica `INDEX(property_id, created_at DESC)` — estas son tablas de historial/auditoría donde el patrón de acceso típico es "los N eventos más recientes primero". **Chosen:** usar `sa.text("created_at DESC")` como elemento de la tupla de columnas del `Index(...)` (patrón estándar de SQLAlchemy para expresiones de orden en `__table_args__`, ya que en ese punto de la definición de clase las columnas heredadas de mixins no son fiables de referenciar como objetos). Verificado con `\d property_state_transitions`/`\d timeline_events` en Postgres real: los 4 índices afectados muestran `btree (..., created_at DESC)`.

La migración baseline se regeneró desde cero (`alembic revision --autogenerate`) en vez de editar a mano el SQL ya generado — todavía no estaba archivada ni tenía nada construido encima, así que no hay coste de mantener un historial incremental todavía. El nuevo archivo (`4a5faad7796b_baseline_domain_foundation_core.py`) reemplaza a `069f2e1f14d3_...` (borrado) y conserva el fix D17 (drop explícito de los 17 tipos ENUM en `downgrade()`).

Rejected: dejar el orden ascendente con el argumento de que "un btree se puede escanear al revés" — cierto para corrección funcional (el architect lo marcó severidad baja por esto), pero diverge de lo que tasks.md pide literalmente sin ninguna razón documentada; es más barato arreglarlo ahora que dejarlo como una divergencia silenciosa.

### D19 — Tests aislados en su propia base de datos (`<db>_test`), no la de `make up` (fix crítico del panel, sección 4-7)

El panel de revisión (qa) sobre las secciones 4-7 encontró un bug crítico: `backend/tests/conftest.py`'s `db_session` fixture apuntaba a `settings.database_url` — que, por D14 (fallback a `localhost:5432` para ejecución en host), es la **misma base de datos** que gestiona `make up`/`migrate`. Correr `cd backend && uv run pytest` (el comando exacto de `sdd/project.md`) dropeaba las 8 tablas de la BD de desarrollo (`Base.metadata.drop_all` al final de cada test) dejando `alembic_version` apuntando a la revisión head — un estado inconsistente que rompe `alembic downgrade`/`upgrade` posteriores y dejaba el stack de desarrollo silenciosamente corrupto. Reproducido en vivo por el reviewer: `make up` → `pytest` → `\dt` solo muestra `alembic_version` → `alembic downgrade base` falla con `UndefinedObjectError`.

**Chosen:** `conftest.py` calcula `_TEST_DB_URL` (nombre de la BD dev + sufijo `_test`, mismo host/user/password) y, antes de cada test, `_ensure_test_database_exists()` la crea si no existe (vía `asyncpg.connect` directo a la BD de mantenimiento `postgres`, fuera de cualquier transacción — `CREATE DATABASE` no puede ir dentro de una). El fixture `db_session` ahora crea su engine contra esa BD de test, nunca contra la de desarrollo.

**Bug encontrado al implementar el fix**: `_TEST_DB_URL = str(url.set(database=...))` usaba `str()` sobre el objeto `URL` de SQLAlchemy, que por diseño enmascara la contraseña como `***` en su representación por defecto (para no filtrarla en logs) — causaba `InvalidPasswordError` real al conectar. Corregido con `.render_as_string(hide_password=False)`.

**Adicionalmente** (mismo hallazgo del panel, severidad media): se añadieron tests que sí ejercen las constraints `UNIQUE` que las tareas 4.3/6.3 ya reclamaban cubiertas pero no probaban con una violación real — `test_internal_code_unique_per_tenant` (properties) y `test_external_pms_id_unique_per_tenant_but_multiple_nulls_allowed` (reservations, confirma también que Postgres trata múltiples `NULL` como distintos entre sí).

Rejected: mockear/parchear la conexión en tests — rompería el propósito de que estos sean tests de integración contra Postgres real (`testing.md`). Rejected también: usar transacciones con rollback en vez de una BD separada — no resuelve el problema de fondo (tests y stack de desarrollo compartiendo un recurso), solo lo mitiga parcialmente.

### D20 — R3.2 no nombraba `TimelineEvent` como excepción sin `updated_at` (DESIGN-CONFLICT del panel a escala feature, resuelto)

El panel a escala de feature (architect) encontró que `proposal.md` R3.2 solo nombraba `PropertyStateTransition` como excepción a "toda entidad tiene `created_at`/`updated_at`", pero `TimelineEvent` **también** carece de `updated_at` — correctamente, según PRD §7.8 y `architecture.md` ("Timeline inmutable"). El código ya era correcto; el texto del requirement no reflejaba completamente el PRD que se supone que refleja. **Chosen:** ampliar R3.2 para nombrar ambas excepciones. Sin cambios de código — solo alinea el requirement con el comportamiento correcto ya implementado, evitando que un change futuro "corrija" `TimelineEvent` añadiéndole un `updated_at` que no debería tener.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Core / DB compartida | `backend/app/core/db.py` | Nuevo — `Base`, engine async, `async_session_factory`, mixins `UUIDPrimaryKeyMixin`/`TimestampMixin`/`TenantScopedMixin` (D6) |
| Core / Settings | `backend/app/core/config.py` | Añade `database_url: str` a `Settings` (leído de env `DATABASE_URL`, fijada en compose per D12) |
| Deps | `backend/pyproject.toml`, `backend/uv.lock` | Añade `sqlalchemy[asyncio]`, `asyncpg`, `alembic` |
| Alembic | `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`, `backend/alembic/versions/<rev>_baseline_domain_foundation_core.py` | Nuevo — bootstrap Alembic (template async, D9) + migración baseline de las 8 tablas (D10) |
| `tenants/` | `backend/app/tenants/domain/{entities.py,enums.py}`, `backend/app/tenants/infrastructure/models.py` | Nuevo — `Tenant`, `TenantConfig` (D1, D4) |
| `auth/` | `backend/app/auth/domain/{entities.py,enums.py}`, `backend/app/auth/infrastructure/models.py` | Nuevo — `User` (D1, D4) |
| `properties/` | `backend/app/properties/domain/{entities.py,enums.py}`, `backend/app/properties/infrastructure/models.py` | Nuevo — `Property`, `PropertyStateTransition`, incluye `PropertyOperationalState` completo (D1, D3, D4) |
| `timeline/` | `backend/app/timeline/domain/{entities.py,enums.py}`, `backend/app/timeline/infrastructure/models.py` | Nuevo — `TimelineEvent`, incluye `TimelineEventType` completo (D1, D4) |
| `guests/` | `backend/app/guests/domain/{entities.py,enums.py}`, `backend/app/guests/infrastructure/models.py` | Nuevo — `Guest` (D1, D4) |
| `reservations/` | `backend/app/reservations/domain/{entities.py,enums.py}`, `backend/app/reservations/infrastructure/models.py` | Nuevo — `Reservation`, incluye `ReservationStatus` (D1, D4) |
| Compose | `docker-compose.yml` | Nuevo servicio `migrate`; `backend`/`worker` añaden `depends_on.migrate.condition: service_completed_successfully` y `DATABASE_URL` (D11, D12) |
| Tests | `backend/tests/{tenants,auth,properties,timeline,guests,reservations}/{test_entities.py,test_models.py}` | Nuevo — unit (dominio) + integration (ORM/migración) por módulo (D13) |

## Data & interfaces

- **Esquema DB**: 8 tablas nuevas — `tenants`, `tenant_configs`, `users`, `properties`, `property_state_transitions`, `guests`, `reservations`, `timeline_events` — columnas/constraints/índices exactos de PRD §7.1-7.8 (ver proposal R3 y R5 para el detalle).
- **Enums Postgres nativos** (D7): `tenant_status`, `user_role`, `user_status`, `property_operational_state` (los 11 estados de PRD §8.1), `property_status`, `state_transition_triggered_by`, `guest_document_type`, `guest_document_status`, `legal_registration_status` (compartido entre `Guest` y `Reservation` — mismo enum, mismos valores, ver PRD §7.6/§7.7), `reservation_channel`, `reservation_status`, `payment_status`, `access_status`, `timeline_actor_type`, `timeline_event_type` (43 valores, PRD §7.8), `timeline_severity`.
- **Variable de entorno nueva**: `DATABASE_URL`, fijada en `docker-compose.yml` (no en `.env.example`, D12).
- **Ningún endpoint HTTP nuevo** — sin cambios en `api/` (D2).
- **Ningún puerto/repositorio ni caso de uso** — diferido (decisión ya tomada en `/sdd:new`).

## Risks & mitigations

- **ENUMs nativos de Postgres son costosos de evolucionar** (D7): añadir un valor futuro requiere `ALTER TYPE ... ADD VALUE` (no siempre transaccional según versión/uso). Mitigación: el catálogo de valores de este change es el cerrado del PRD; si cambia, será una migración Alembic explícita y documentada, no una sorpresa.
- **`legal_registration_status` duplicado entre `Guest` y `Reservation`**: el PRD define el mismo enum en las dos entidades (7.6 y 7.7) con los mismos valores. Se modela una sola vez (en `guests/domain/enums.py`, dueño conceptual del dato legal del huésped) e importado desde `reservations/` — mismo razonamiento que D3, aplicado aquí porque este caso sí cumple la condición "usado por más de un dominio".
- **Migración baseline larga y monolítica** (D10): si falla a mitad, Alembic revierte la transacción completa (Postgres soporta DDL transaccional) — no deja el esquema a medias. Mitigación: `alembic downgrade base` + `upgrade head` limpio se verifica explícitamente en tasks (R4.2 del proposal).
- **Servicio `migrate` nuevo en compose** (D11): si `migrate` falla, `backend`/`worker` no arrancan (`service_completed_successfully` no se cumple) — comportamiento deseado (fail-fast), pero hay que verificarlo explícitamente (mensaje de error visible en `docker compose up`, no un cuelgue silencioso).

## Open questions

Ninguna pendiente — las dos decisiones de alcance que requerían tu input (split en 3 changes, puertos de repositorio diferidos) ya se resolvieron en `/sdd:new`. El resto de decisiones de este documento (FKs, Alembic, estructura de módulos) tienen una respuesta clara justificada arriba; si alguna te chirría, la reabrimos antes de `/sdd:tasks`.
