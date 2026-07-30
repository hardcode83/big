# 0004 — Patrón de capas del backend

## Estado

Aceptado — 2026-07-30. Establecido en el change `auth-tenancy` (design D17).

## Contexto

Hasta `auth-tenancy` el backend era **dominio puro más esquema**: `domain-foundation-core`, `domain-foundation-ops` y el `PropertyStateMachine` de `timeline-state-machine` entregaron entidades, enums, modelos SQLAlchemy y migraciones, pero `app/main.py` eran nueve líneas con un `GET /health` y **no existía ninguna capa `application/` ni `api/` en todo el proyecto**. Nada de lo construido era alcanzable por un cliente.

`sdd/steering/backend-architecture.md` ya fijaba la regla de dependencia y el vocabulario de las cuatro capas, pero no existía todavía una implementación que la materializara. `auth-tenancy` es el primer *vertical slice* —`POST /auth/login` es la rodaja completa más pequeña que atraviesa las cuatro capas— y por tanto el primero que tiene que decidir la fontanería concreta: inyección de dependencias, frontera transaccional, forma del contexto de request, manejo de errores y cobertura de autorización.

Esas decisiones no son de auth. Las hereda **todo módulo posterior**: `reservations`, `cleaning`, `maintenance`, `messaging`, `dashboard-web`. Registrarlas aquí las hace citables desde el design de cada uno sin arrastrar la spec de capacidad de auth, que es lo que motiva este ADR en lugar de dejarlo solo en `sdd/specs/auth-tenancy.md`.

## Decisión

### 1. Las cuatro capas y la regla de dependencia

```
api/  →  application/  →  domain/  ←  infrastructure/
```

`domain/` es Python puro: no importa `fastapi`, `sqlalchemy` ni `pydantic`. `infrastructure/` **implementa** los puertos que `domain/` define. `application/` orquesta puertos y no conoce ningún adaptador concreto.

**Verificado por test, no por revisión** (`backend/tests/test_layering.py`): recorre por AST cada módulo de `app/*/domain/` y de `app/*/application/`. Un grep de texto no sirve —se lo cuela un docstring— y tampoco basta mirar los `import` a secas: el test cubre alias (`import sqlalchemy.orm as sa`), imports dentro de funciones, imports relativos que suben de paquete (`from ..infrastructure import x`, que resuelve a una capa exterior) y llamadas a `importlib.import_module`, que ningún análisis estático de imports puede resolver y que por eso están prohibidas dentro de `domain/`. El propio mecanismo tiene su test, para que no pueda pasar en vacío.

### 2. Inyección de dependencias por `Depends`, casos de uso como dataclass

Cada caso de uso es una `@dataclass` cuyos campos son puertos. La capa `api/` los construye en funciones proveedoras (`get_login_use_case`, …) que reciben la sesión y los adaptadores por `Depends`. Ningún caso de uso instancia un adaptador.

### 3. La frontera transaccional es el caso de uso

`get_db_session()` (en `app/core/db.py`) cede una `AsyncSession`, hace `rollback()` si la request termina en excepción y `close()` siempre — pero **no hace `commit`**. El `commit` lo llama el caso de uso cuando la operación de negocio termina, a través del puerto `UnitOfWork`, cuyo adaptador `SqlAlchemyUnitOfWork` existe solo para que `application/` no importe SQLAlchemy.

Rechazado: commit automático en la dependencia o en un middleware al devolver 2xx — esconde la frontera y acaba confirmando escrituras a medias de un caso de uso que decidió abortar. Rechazado: commit por operación en el repositorio — rompe la atomicidad de operaciones con varias escrituras, como rotar un refresh token e insertar su hija.

### 4. Contexto de request explícito, más un filtro global como red

El `tenant_id` efectivo viaja en un `RequestContext` inmutable que la capa `api/` construye **solo** a partir de los claims verificados del token, y se pasa como parámetro explícito a los casos de uso y a los métodos de repositorio. Ningún DTO de request tiene campo `tenant_id`; los schemas usan `extra="forbid"`, así que uno enviado en el cuerpo se rechaza con 422.

Sobre eso hay una **defensa en profundidad**: un listener del evento `do_orm_execute` añade `with_loader_criteria` por cada modelo con columna `tenant_id`, activo solo en sesiones marcadas con `bind_session_to_tenant`. Los parámetros explícitos siguen siendo el mecanismo autorizado; esto es la red que impide que un olvido se convierta en fuga.

**Cinco límites de esa red, que hay que conocer antes de confiar en ella:**

1. Cubre `SELECT`/`UPDATE`/`DELETE` de ORM, no `text()` ni sentencias Core.
2. No hace nada en sesiones sin marca. Corren sin marca: las tareas de Celery, el bootstrap, la query anónima del login —que lo **necesita**— y **`POST /auth/refresh`**, que es anónimo y por tanto no pasa por `get_authenticated_request`, el único sitio que marca la sesión. Cualquier endpoint anónimo futuro que toque datos hereda el mismo aviso.
3. Los INSERT no están cubiertos: `session.add` no emite sentencia que reescribir.
4. El mapa de identidad no está cubierto: `session.get()`/`refresh()` pueden responder sin SQL.
5. Las tablas hijas sin `tenant_id` propio quedan fuera (`messages`, `cleaning_checklist_completions`, `cleaning_photos`): cuelgan de un padre con tenant, y el escaneo empareja por presencia de columna. Todo repositorio que las consulte debe unir explícitamente al padre scopado y traer su propio test de aislamiento.

El escaneo de entidades **no se memoiza**, y la lista de módulos de modelos vive en un único sitio (`app/core/models_registry.py`) que importan la aplicación, Alembic y los tests. Ambas cosas son deliberadas: `Base.registry.mappers` solo crece a medida que se importan los modelos, así que una caché —o una lista duplicada que a la app se le olvide— excluye tablas de la red en silencio. Ya pasó durante la implementación: `app/main.py` no importaba ningún modelo, la red parecía completa en la suite y en producción protegía tres tablas, dejando fuera `guests`, que guarda el `document_number` que `steering/security.md` nombra como PII.

### 5. Sobre de error por handlers globales

Todo fallo gestionado sale como `{"error": {"code", "message", "details"}}` (PRD §23). `app/core/errors.py` define `AppError` y registra tres handlers: `AppError`, `RequestValidationError` y `HTTPException`. El de `RequestValidationError` es imprescindible y fácil de olvidar: FastAPI devuelve por defecto `{"detail": [...]}`, que `frontend/lib/api/errors.ts:isApiErrorEnvelope` rechaza, degradando el error a `UNKNOWN_ERROR` y perdiendo el mensaje en silencio.

El mapeo de excepciones **de dominio** a HTTP vive en la capa `api/` de cada módulo, no en `core/` — `core` no tiene reglas de negocio, y en auth hay además una colisión de nombres real (`app.auth.domain.exceptions.InvalidTokenError` frente a `app.core.errors.InvalidTokenError`) donde un import equivocado daría 500 en vez de 401.

### 6. Autorización declarada, denegando por defecto

Cada endpoint declara su permiso con `Depends(require(Permission.X))`. Un test (`backend/tests/test_route_authorization.py`) recorre las rutas registradas y falla si alguna fuera de la lista explícita de anónimas no declara autorización.

Detalle que costó descubrir y que cualquier módulo futuro debe respetar: **esta versión de FastAPI no aplana los routers incluidos**. `app.routes` contiene un objeto `_IncludedRouter` en lugar de las rutas individuales, así que un test que recorra `app.routes` sin aplanar el árbol **inspecciona cero endpoints y pasa en vacío**. El test aplana recorriendo `original_router` e `include_context`, y tiene su propio caso que añade una ruta sin autorización para comprobar que el mecanismo la detecta.

## Consecuencias

- Todo módulo nuevo bajo `backend/app/<dominio>/` copia esta estructura: `domain/{entities,enums,ports,exceptions,value_objects}.py`, `application/use_cases.py`, `infrastructure/{models,repositories}.py`, `api/{router,schemas,dependencies,errors}.py`.
- Los designs siguientes citan este ADR en vez de redescribir la fontanería.
- El coste de la disciplina es real: un puerto por cada necesidad de infraestructura, incluido uno tan fino como `UnitOfWork`. Se acepta porque es lo que mantiene `domain/` y `application/` testeables sin base de datos.
- Los cinco límites del filtro global son deuda documentada, no resuelta. Row-Level Security de PostgreSQL se evaluó y se descartó en `auth-tenancy` (design D6) por su coste en migraciones, rol de base de datos y montaje de los tests; si el aislamiento pasa a ser crítico —fase SaaS multi-tenant— es la vía a reabrir.

## Alternativas descartadas

- **Dejar el patrón solo en `sdd/specs/auth-tenancy.md`**: obligaría a citar una spec de capacidad de auth para justificar una decisión arquitectónica que no es de auth.
- **`contextvars` como única vía para el tenant, sin parámetros explícitos**: hace imposible olvidarse del filtro, pero cambia la semántica de toda query desde un sitio invisible en la revisión y deja el aislamiento acoplado a un detalle de SQLAlchemy, sin nada legible en la firma del repositorio.
- **Row-Level Security de PostgreSQL**: la garantía más fuerte, porque la impone el motor. Exige políticas por tabla en las migraciones, que la app corra con un rol no-superusuario y replicar el montaje en el `create_all` de los tests. Ver `auth-tenancy` design D6.
