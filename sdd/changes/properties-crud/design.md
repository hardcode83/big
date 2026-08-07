# Design: properties-crud

## Context

`backend/app/properties/` tiene `domain/`, `application/` e `infrastructure/`, y **no tiene `api/`** — el único módulo de dominio en esa situación. Su puerto (`domain/repositories.py:23-111`) expone siete métodos, todos de lectura salvo dos escritores deliberadamente estrechos: `save` (`:83`), que persiste **solo** `current_operational_state`, y `set_pms_provider` (`:96`). El docstring del puerto dice literalmente que «`/api/v1/properties` still does not exist» (`:5-6`), y el de `save` veta ensancharlo (`:83-94`). No hay `PropertyNotFoundError` en `domain/exceptions.py`.

La entidad `Property` (`domain/entities.py:13-41`) es un `@dataclass` sin métodos de mutación. El modelo (`infrastructure/models.py:23-77`) ya trae `uq_properties_tenant_id_internal_code` (`:26`) y un índice **no único** sobre `(tenant_id, pms_external_id)` (`:28`). `wifi_password_encrypted` (`:69`) es `String` sin longitud y **contiene texto en claro**; la migración `c3f81a5d7e42:14` lo llama «the mistake `domain-foundation-core` made deliberately».

Los patrones a replicar están todos vivos: `reservations` es el análogo más cercano (router, envelope de paginación propio, `_MAPPING` de errores, DI por función), `user-management` aportó el rastro de auditoría con `ChangeSet`/`AuditLogFactory`, y `pms-provider-resolution` aportó `EncryptedSecret` y el único punto de descifrado del sistema. La cadena de Alembic es lineal y su HEAD es `c3f81a5d7e42`.

## Decisions

### D1 — `wifi_password` se acepta y se cifra, y nunca sale

**Chosen:** el `POST` acepta `wifi_password` en claro, el caso de uso lo cifra con `app.core.crypto.encrypt()` y lo persiste como ciphertext; **ninguna respuesta lo devuelve**, ni enmascarado — la lectura expone un booleano `has_wifi_password`. La regla 3 de `security.md:15` nombra `wifi_password` **primero** en su enumeración y dice «Nunca en texto plano», y la regla 11:86 cierra la vía de escape: «que el huésped necesite ver la contraseña WiFi no la autoriza, la regla 4 no le da forma enmascarada». No hace falta migración de datos: la tabla está vacía en todos los entornos y la columna ya es `String` nullable.

Rejected: **dejarla fuera del payload y diferirla** — defendible por el argumento de «sin lector es especulativo», pero deja el CRUD incapaz de configurar un campo que PRD §7.4 declara, y garantiza que alguien la añada más tarde sin pensar en el cifrado; hoy el patrón está fresco y cuesta tres líneas.
Rejected: **enmascararla en las respuestas** — prohibido explícitamente por `security.md:86`.
Rejected: **un `TypeDecorator` de SQLAlchemy que cifre/descifre solo** — `crypto.py:17-19` lo descartó en su día (design D3): descifra al cargar y no deja punto donde auditar.

### D2 — El secreto no viaja en la entidad: entra por el parámetro del puerto

**Chosen:** `wifi_password_encrypted` **no** se añade a lo que el caso de uso pone en la entidad `Property`. El puerto recibe el secreto como parámetro propio y tipado: `add(tenant_id, property, *, wifi_secret: EncryptedSecret | None)` y un escritor estrecho `set_wifi_password(tenant_id, property_id, secret: EncryptedSecret | None)`. Tipar el parámetro como `EncryptedSecret` da la garantía **por construcción**: su `__post_init__` (`app/core/encrypted_secret.py:43-58`) descodifica base64url y exige el byte de versión Fernet `0x80`, así que `EncryptedSecret(ciphertext=<plaintext>)` es imposible. Y mantener el secreto fuera de la entidad lo mantiene fuera de cualquier ruta de serialización, que es exactamente el accidente que la regla 3(a) prohíbe.

Rejected: **cambiar el campo de la entidad a `EncryptedSecret | None`** — obligaría a construirlo en **cada** lectura, incluido el `list_all` que usa el job de Celery, de modo que una sola fila mal formada rompería el avance de estados de todo el tenant.
Rejected: **dejarlo como `str` en la entidad** — nada impediría entonces escribir texto plano en una columna que se llama `_encrypted`.

### D3 — `PATCH` por un escritor estrecho con allowlist, no por un `update` genérico

**Chosen:** un método `update_details(tenant_id, property_id, changes: Mapping[str, Any])` cuyo conjunto de claves admisibles es una constante `PATCHABLE` compartida entre el esquema y la capa de aplicación, importada de un solo sitio. `current_operational_state` **no está en `PATCHABLE`**, así que la firma del puerto no puede expresar un cambio de estado. Esto satisface R4.2 estructuralmente y no por convención, y sigue la doctrina que `set_pms_provider` estableció (`domain/repositories.py:95-110`): «dos métodos nombrados que escriben una columna cada uno mantienen la regla intacta; uno que escribe lo que sea no».

Rejected: **`save(property)` ensanchado a persistir la entidad completa** — vetado por su propio docstring, por `celery-jobs.md:66-68` («no SHALL escribir `current_operational_state` por ninguna otra vía») y por `steering/backend.md:24`.
Rejected: **duplicar la lista de campos editables en el esquema y en el caso de uso** — `user_schemas.py:133-136` ya dejó escrito que «dos copias de una regla es como divergen».

### D4 — La entidad `Property` no gana métodos de mutación

**Chosen:** se mantiene como `@dataclass` sin métodos. El seguimiento de cambios lo hace el patrón del diccionario `written` de `user_admin.py:228-267`, que decide a la vez qué se persiste y qué se audita. `steering/backend-architecture.md:133-136` fija el criterio: «la ceremonia táctica se justifica por la invariante que protege, no por el dominio en que vive», y `Property` no tiene ninguna invariante propia que estos endpoints puedan violar — la unicidad la impone la base de datos, los rangos los impone Pydantic, y el estado operacional queda fuera de `PATCHABLE` por D3.

Rejected: **replicar el patrón de `User`** (`user-management.md:87-91`, un método por campo mutable con un test derivado de `__dataclass_fields__`) — allí protege invariantes reales (identidad de login, revocación de sesiones); aquí sería ceremonia sin invariante.

### D5 — `pms_external_id` se hace único por tenant con un índice parcial

**Chosen:** una migración añade `uq_properties_tenant_id_pms_external_id` como índice **único parcial** con `postgresql_where=sa.text('pms_external_id IS NOT NULL')`, copiando el estilo y el razonamiento de `c3f81a5d7e42:88-94` (Postgres trata los NULL como distintos, así que el parcial es lo que permite varias propiedades sin PMS). La violación se traduce a `409 CONFLICT` por nombre de constraint. Sin esto, esta vía de escritura puede **crear** la ambigüedad que `reservations.md:128-130` obliga al sync a rechazar.

Rejected: **comprobación previa en la capa de aplicación** — susceptible a carrera; `user-management.md:46-49` ya rechazó exactamente ese patrón para el email: «dos altas simultáneas pasarían las dos la comprobación y una acabaría en `500`».
Rejected: **documentar la ambigüedad y no impedirla** — deja al sync fallando por datos que la API dejó entrar.

**Consecuencia que hay que registrar**: `AmbiguousPropertyExternalIdError` (`domain/exceptions.py:5`) pasa a ser **defensiva**, inalcanzable por esta vía. No se borra —protege contra escrituras por SQL directo y contra una futura vía sin el índice— pero su test deja de poder ejercitarla sin saltarse el índice, y eso se anota en `specs/reservations.md` al archivar.

### D6 — El alta traduce el choque de constraint, no lo anticipa

**Chosen:** `add()` envuelve su `flush()` en `try/except IntegrityError` y traduce **por nombre de constraint** a dos errores de dominio distintos (`DuplicateInternalCodeError`, `DuplicatePmsExternalIdError`), re-lanzando cualquier otro `IntegrityError`. Es el patrón exacto de `SqlAlchemyReservationRepository.add` (`app/reservations/infrastructure/repositories.py:151-162`). El `flush` ocurre **antes** de construir el `AuditLog`, como en `CreateUserUseCase` (`user_admin.py:133-134`), para que un `409` no deje rastro de una creación que no ocurrió.

Rejected: **un solo error de conflicto genérico** — el cliente no sabría qué campo corregir.

### D7 — Auditoría: `ENTITY_PROPERTY` con su allowlist, y el secreto solo como «cambió»

**Chosen:** se añade `ENTITY_PROPERTY` a `ENTITY_TYPES` y `PROPERTY_CREATED`/`PROPERTY_UPDATED` a `ACTIONS` (`app/audit/domain/actions.py:49-65`), y una entrada `"PROPERTY"` en `AUDITABLE_FIELDS` (`value_objects.py:74-106`) que enumera las columnas auditables. Los tres campos de texto libre (`access_notes`, `cleaning_notes`, `emergency_notes`) y `wifi_password_encrypted` se registran con `.redacted()`, nunca con `.diff()`.

**Esto ya está medio hecho por construcción**: `REDACTED_FIELDS` (`value_objects.py:29-53`) **ya contiene `wifi_password` y `wifi_password_encrypted`** (`:41-42`), así que un `.diff()` sobre ellos revienta hoy sin que este change añada nada. Lo que falta es incluirlos en `AUDITABLE_FIELDS["PROPERTY"]` para que `.redacted()` los acepte — el precedente es `PMS_CREDENTIAL` (`:97-105`).

Una mutación = **una fila** con todos los campos en `changes` (`actions.py:9-10`), y la acción se elige a partir del diccionario `written` y no de la petición.

Rejected: **acogerse a la excepción de la regla 9** — está acotada al actor `SYSTEM` en transiciones de estado (`security.md:29`), y `security.md:49` es explícito en que su razonamiento «no es un criterio reutilizable».

### D8 — La API no puede tocar el estado operacional, y se prueba

**Chosen:** `current_operational_state` se rechaza en el cuerpo de `POST` y de `PATCH` (por `extra="forbid"` en el primero y por ausencia de `PATCHABLE` en el segundo), el alta deja que la columna tome su defecto de DDL `VACANT_READY`, y el puerto no gana ningún método capaz de escribirla. Un test afirma que crear una propiedad **no** escribe fila en `property_state_transitions` ni `TimelineEvent`: crear no es transitar, no existe tipo `PROPERTY_CREATED` en `app/timeline/domain/enums.py:17-62`, y PRD §3.1:101 ata el evento a la *transición*.

### D9 — Rechazo de nulos explícitos, con la lista de campos nullable escrita

**Chosen:** el esquema de `PATCH` lleva el validador `_reject_explicit_nulls` de `user_schemas.py:105-128`, con `NULLABLE_FIELDS` = los campos que PRD §7.4 declara nullable (`pms_external_id`, `address_line1`, `address_line2`, `city`, `province`, `postal_code`, `wifi_name`, `wifi_password`, `access_notes`, `cleaning_notes`, `emergency_notes`). `name`, `internal_code`, `country`, `timezone`, `max_guests`, `bedrooms`, `bathrooms`, los dos horarios y `status` **no** son nullable. Ese validador nació de un fallo real: un `PATCH {"email": null}` escribió la cadena `"none"` en la identidad de login (`user_schemas.py:107-117`).

### D10 — Estructura y cableado, siguiendo `reservations` al pie de la letra

**Chosen:** nuevo paquete `app/properties/api/` con `router.py`, `schemas.py`, `dependencies.py` y `errors.py`. El router se declara con `responses=AUTHENTICATED_RESPONSES` (`app/core/openapi.py:67`), los permisos como alias de módulo (`ReadDep`/`ManageDep` sobre `require(...)`), un builder por caso de uso en `dependencies.py` construyendo los adaptadores en línea con `SqlAlchemyUnitOfWork` de `app/core/unit_of_work.py`, y `register_property_error_handlers(app)` + `include_router` en `app/main.py:46-58`. El envelope de paginación es **propio del módulo** (`PropertyPageResponse.build`) porque no hay helper compartido: `reservations` y `users` tienen cada uno el suyo. Cotas: `MAX_PER_PAGE = 100`, `MAX_PAGE = 100_000`, y una cota explícita de texto para las cuatro columnas `String` sin longitud.

### D11 — Una propiedad `INACTIVE` rechaza reservas nuevas

**Chosen:** `CreateReservationUseCase` gana una guarda que rechaza crear una reserva sobre una propiedad con `status = INACTIVE`. Una reserva sobre una vivienda retirada de la operación no significa nada, y el import CSV y el sync del PMS resuelven la propiedad por código o por id externo sin mirar su estado, así que sin la guarda una propiedad retirada sigue admitiendo entradas por tres vías (decisión de Jose, 2026-08-08).

**Lo que esto implica y hay que asumir explícitamente**: la guarda vive en `app/reservations/application/use_cases.py`, que pertenece a un change **archivado**. Este change modifica por tanto el comportamiento especificado de otra capability, que es justo lo que la regla 1 vigila. Se acepta porque la pregunta **nace aquí**: antes de este change ninguna propiedad podía llegar a `INACTIVE`, porque no existía vía para escribir `status`. `specs/reservations.md` gana el criterio correspondiente al archivar, y las tres vías de entrada (API manual, CSV, sync) deben quedar cubiertas por tests, no solo la primera.

Rejected: **dejarlo como está** — sería un comportamiento por omisión y no una decisión, con la ventana abierta desde el primer `PATCH` que retire una propiedad.
Rejected: **entrada de roadmap aparte** — más limpio en propiedad, pero deja el agujero abierto mientras tanto por una frontera que este change ya cruza de todos modos al crear el estado.

### D12 — `TENANT_OWNER` lee propiedades pero no las muta

**Chosen:** `READ_PROPERTIES` para `TENANT_OWNER` y `PROPERTY_MANAGER`; `MANAGE_PROPERTIES` solo para `PROPERTY_MANAGER`. `CLEANER`, `TECHNICIAN` y `SUPER_ADMIN` reciben `403` en los cuatro endpoints. Sigue el precedente exacto de `reservations` en `policy.py:55-65` y encaja con PRD §6:297, que da a la propietaria «ver sus propiedades y reservas» y nada más (decisión de Jose, 2026-08-08).

**Consecuencia asumida y no accidental**: la propietaria no puede dar de alta su propia vivienda; lo hace el manager. `make bootstrap` crea ambos usuarios (`app/cli/bootstrap.py:80-96`), así que el recorrido no se bloquea. Es el punto donde la intuición de producto y PRD §6 divergen, y se resuelve a favor del PRD y de la simetría con `reservations`.

Rejected: **dar mutación al propietario** — rompería la simetría con `reservations` sin que PRD §6 lo respalde; §6 no concede crear ni editar propiedades a ningún rol, así que la asimetría habría que justificarla en vez de heredarla.

## Changes by area

| Area | Files | Change |
|---|---|---|
| API (nuevo) | `app/properties/api/{__init__,router,schemas,dependencies,errors}.py` | Router con los 4 endpoints de PRD §23, esquemas con `extra="forbid"`, DI por función, `_MAPPING` de errores |
| Reservas (D11) | `app/reservations/application/use_cases.py` | Guarda de `status = INACTIVE` en la creación, cubriendo también CSV y sync |
| Aplicación | `app/properties/application/use_cases.py` | 4 casos de uso nuevos junto al `AdvancePropertyStatesUseCase` existente; `_AuditWriter` como en `user_admin.py:58-88` |
| Dominio | `app/properties/domain/repositories.py` | `add`, `update_details`, `set_wifi_password`, `list` paginado + `Page` propio |
| Dominio | `app/properties/domain/exceptions.py` | `PropertyNotFoundError`, `DuplicateInternalCodeError`, `DuplicatePmsExternalIdError`, `PropertyValidationError` |
| Infraestructura | `app/properties/infrastructure/repositories.py` | Implementación de los tres escritores con guarda `CrossTenantWriteError` primero y traducción de `IntegrityError` |
| Permisos | `app/auth/domain/policy.py` | `READ_PROPERTIES`/`MANAGE_PROPERTIES` + reparto por rol (ver OQ2) |
| Auditoría | `app/audit/domain/actions.py`, `value_objects.py` | `ENTITY_PROPERTY`, dos acciones, entrada `"PROPERTY"` en `AUDITABLE_FIELDS` |
| Migración | `alembic/versions/<nuevo>_properties_pms_external_id_unique.py` | Índice único parcial; `down_revision = "c3f81a5d7e42"` |
| Arranque | `app/main.py` | Registro del router y de sus manejadores de error |
| Contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | Regenerados (`make openapi`, `npm run api:generate`) |
| Tests | `tests/properties/{conftest,test_api,test_authorization}.py`, `tests/test_route_authorization.py` | Matriz por rol, aislamiento cross-tenant, violación real de constraint, snapshot de rutas ampliado |

## Data & interfaces

**Esquema**: una sola migración, y **no toca ninguna columna** — solo añade `uq_properties_tenant_id_pms_external_id` como índice único parcial. Reversible (el `downgrade` lo borra). No hay migración de datos: la tabla está vacía en todos los entornos, lo que también es lo que hace segura la decisión D1.

**API** (PRD §23:1938-1941, sin desviaciones):

| Verbo | Ruta | Éxito | Permiso |
|---|---|---|---|
| `GET` | `/api/v1/properties` | 200 + envelope | `READ_PROPERTIES` |
| `POST` | `/api/v1/properties` | 201 | `MANAGE_PROPERTIES` |
| `GET` | `/api/v1/properties/{property_id}` | 200 | `READ_PROPERTIES` |
| `PATCH` | `/api/v1/properties/{property_id}` | 200 | `MANAGE_PROPERTIES` |

Códigos de error: 401, 403, 404 (incluido el cross-tenant, cuerpo idéntico), 409 (`CONFLICT`, los dos duplicados), 422 (`VALIDATION_ERROR`). **Ningún código nuevo** — los once de `ErrorCode` bastan.

**Cuerpo de lectura**: todas las columnas de PRD §7.4 **salvo** `wifi_password_encrypted`, que se sustituye por `has_wifi_password: bool`.

**Config/env**: ninguna nueva. `ENCRYPTION_KEY` ya es obligatoria al arrancar desde `pms-provider-resolution`.

## Risks & mitigations

- **Que el cifrado de D1 se convierta en una vía de fuga por serialización.** Mitigación: el secreto no está en la entidad (D2), el esquema de respuesta enumera campos explícitamente y no usa `from_attributes` (convención de `reservations/api/schemas.py:9-11`), y `EncryptedSecret.__str__`/`__repr__` están fijados por su propio test para que un cambio futuro no filtre.
- **Que el índice parcial de D5 falle al aplicarse** si algún entorno tuviera filas duplicadas. Mitigación: la tabla está vacía en todos; verificado antes de aplicar, y CI corre `alembic downgrade base`.
- **Que la matriz de autorización pase en vacío.** Mitigación: los tests afirman el código concreto por rol (no `!= 403`) y el snapshot de `tests/test_route_authorization.py:256-278` debe crecer en el diff; `_declared_permissions` recorre `route.dependant.dependencies`, así que etiquetar la función del endpoint no basta.
- **Olvidar una de las dos regeneraciones de contrato.** Mitigación: son dos workflows distintos (`api-contract` y `frontend-api-contract`) y ambos salen en rojo; `tests/test_openapi_contract.py:233-235` también falla.
- **Que la guarda de D11 rompa algo de `reservations`,** que es un change archivado con suite propia. Mitigación: la guarda es una condición añadida en la creación, no un cambio de las existentes; se corre la suite completa de `tests/reservations/` sin tocarla, y los tests nuevos de la guarda van en `tests/properties/` salvo los que ejerciten CSV y sync, que van donde vive su vía.
- **Trigger de revisión extra de `security.md:92`**: aplica dos veces («endpoints nuevos» y «cambios de auth/RBAC»), así que el panel de `/sdd:review` no es opcional aquí.

## Open questions

**Ninguna abierta.** Las dos que este diseño levantó se resolvieron con Jose el 2026-08-08 y viven ahora como decisiones, no como preguntas: el rechazo de reservas sobre una propiedad `INACTIVE` es **D11**, y el reparto de permisos que deja a `TENANT_OWNER` en solo lectura es **D12**. Ambas llevan escrita su consecuencia asumida, que es lo que `/sdd:tasks` tiene que implementar y `/sdd:review` verificar.
