# Design: user-management

## Context

El único escritor de `users` hoy es `backend/app/cli/bootstrap.py`; `app/auth/` tiene las
cuatro capas completas (`domain/`, `application/`, `infrastructure/`, `api/`) pero su puerto
`UserRepository` (`app/auth/domain/ports.py`) solo expone lo que necesita el login:
`get_active_by_id`, `find_by_email_globally` y `touch_last_login`. `app/tenants/` es todavía
solo estructura de datos — `domain/entities.py` (dataclasses `Tenant` y `TenantConfig`) e
`infrastructure/models.py` — sin `application/` ni `api/`, igual que `app/audit/`, que tiene
la dataclass `AuditLog` y su `AuditLogModel` y **ningún escritor**.

El patrón de una capacidad de negocio con API ya está establecido por `reservations`:
router fino con `require(Permission.X)`, `api/dependencies.py` con un builder por caso de
uso, `api/errors.py` mapeando excepciones de dominio al envelope de PRD §23, puerto con
`tenant_id` explícito en cada método, `Page` en el dominio, y un caso de uso = una
transacción vía el puerto `UnitOfWork`. La matriz de autorización de `reservations`
(`backend/tests/reservations/test_authorization.py`) es el molde de R7.2. La cabeza de
Alembic es `96d526599bc1` (`domain_foundation_financial`).

## Decisions

### D1 — Los endpoints de usuarios viven en `app/auth/`; los de tenant, en `app/tenants/`

**Chosen:** ampliar `app/auth/` con los casos de uso de administración de usuarios y un
segundo router (`app/auth/api/users_router.py`, prefijo `/users`), y hacer crecer
`app/tenants/` con `application/` + `api/`. El agregado `User` —entidad, puerto y
adaptador— ya vive en `auth`; sacar sus escritores a otro módulo dejaría el agregado con
dos dueños y contradice "un repositorio por agregado raíz" de
`steering/backend-architecture.md`. Que `tenants` gane `application/`/`api/` con su primer
caso de uso es literalmente el patrón de crecimiento documentado en ese mismo doc
(«dominios que todavía son solo estructura de datos»), el mismo que siguieron `auth`,
`reservations` e `integrations`.

Rejected: módulo `app/users/` nuevo — parte el agregado `User` en dos módulos y añade un
dominio que PRD §3.2 no lista, sin la necesidad transversal que justificó `audit` y `reviews`.
Rejected: meter los endpoints de tenant en `auth` — `Tenant`/`TenantConfig` son el agregado
de `tenants`, y `auth` solo lee su `status`.

### D2 — `audit` gana puerto + adaptador, y **una fábrica de dominio** que es la única forma de construir un `AuditLog`

**Chosen:** `app/audit/domain/repositories.py` (puerto `AuditLogRepository.add(tenant_id,
entry)`), `app/audit/infrastructure/repositories.py` (adaptador SQLAlchemy) y
`app/audit/domain/services.py` con una fábrica que construye el `AuditLog` a partir de un
`ChangeSet` (D3). Sin `application/`: `audit` no tiene casos de uso propios: lo escriben los
casos de uso de otros módulos, exactamente como `timeline` (que tiene
`domain/repositories.py` + `domain/services.py::TimelineEventFactory` y a quien escribe
`reservations`). La simetría con `timeline` no es estética: es el precedente de cómo este
proyecto expresa "columna transversal con contrato propio".

Rejected: que cada caso de uso construya el `AuditLog` a mano — la regla 11 de
`steering/security.md` pasaría a ser una convención repetida en N sitios, que es como se
rompe.
Rejected: un helper en `app/core/` — `audit` ya es un dominio de pleno derecho por decisión
de `domain-foundation-financial`, y `core` no aloja entidades de negocio.

### D3 — La regla 11 se vuelve estructural: el value object `ChangeSet`, con lista de denegación

**Chosen:** un value object inmutable en `app/audit/domain/value_objects.py` con dos
constructores y ninguna otra vía:

```python
ChangeSet.diff("role", old, new)     # -> {"role": {"old": "CLEANER", "new": "TECHNICIAN"}}
ChangeSet.redacted("password")       # -> {"password": {"changed": true}}
```

Las claves son `old`/`new` y no `from`/`to`: PRD §7.25 tipa la columna como
`{field: {old: val, new: val}}` (línea 1096), la docstring de `AuditLogModel` lo repite y
`tests/audit/test_entities.py` ya lo da por hecho. La primera redacción de esta decisión dijo
`from`/`to`; se corrigió al implementar la sección 1, antes de escribir código.

`diff` **rechaza con error de dominio** cualquier campo de una lista de denegación
(`password`, `password_hash`, `document_number`, `wifi_password`, `access_code`, …): para
esos solo existe `redacted`. Y valida que los valores sean escalares serializables a JSONB,
nombrando las claves ofensivas — igual que `TimelineEventFactory` hace con su `metadata`.

**Corregido tras el panel de la sección 1** (dos hallazgos del revisor de seguridad, ambos
aceptados):

1. **Los valores son escalares y punto.** La primera implementación aceptaba `dict` y `list`
   serializándolos recursivamente, y eso abría el bypass entero: `diff` solo puede vetar el
   nombre de campo que recibe, así que
   `diff("profile_patch", …, {"wifi_password_encrypted": "gAAAA-secret"})` colaba el secreto
   verbatim. Recursar la lista de denegación por las claves anidadas habría tapado ese agujero
   dejando la forma de `changes` libre, contra PRD §7.25; rechazar compuestos cierra la
   **clase**. Un diff estructurado se registra con un campo por hoja. De paso desaparece el
   tercer hallazgo (`as_dict()` no era una copia profunda): con escalares no hay nada anidado
   que copiar.
2. **La lista de denegación lleva los nombres reales de las columnas**, no solo los
   conceptuales: faltaba `wifi_password_encrypted`
   (`app/properties/infrastructure/models.py`). Una lista de nombres exactos que no lleva los
   nombres exactos es decoración. `access_records.code_masked` queda fuera a propósito: ya es
   la forma enmascarada que la regla 4 permite.

**Segunda ronda: el `ChangeSet` va ligado a un `entity_type` y los campos son una lista de
autorización (`AUDITABLE_FIELDS`).** La re-revisión de seguridad demostró que rechazar
compuestos no cerraba la clase: `diff("profile_patch", None, json.dumps({...}))` cuela el
mismo payload como string. Y ahí se ve que **inspeccionar el valor no se puede ganar** — la
siguiente codificación es base64, o ninguna. Lo que sí es decidible es el **nombre**: un campo
auditado tiene que ser una columna real y no sensible de la entidad, así que
`ChangeSet("USER")` solo admite los campos declarados de `USER`, y `profile_patch` se rechaza
antes de que su contenido importe. Cada escritor futuro registra sus campos, lo que fuerza la
pregunta de sensibilidad en el momento de añadir una columna al rastro y no en la revisión.

Se descartó la dirección que proponía el revisor (intentar `json.loads` sobre cada string):
tapa una codificación de una forma y deja la sensación de estar cubierto.

**Lo que sigue sin cerrar, dicho en voz alta en el propio módulo en vez de sobrevendido**: un
llamante puede poner un secreto como **valor de un campo legítimo**
(`diff("name", None, "<la contraseña del WiFi>")`). Eso no lo cierra ninguna validación; lo
cierran los casos de uso, que alimentan los diffs desde atributos tipados de la entidad, y el
vocabulario cerrado de `actions.py`.

Así la regla 11 no se cumple "por cuidado del programador" sino porque la única forma de
poner un campo sensible en `changes` levanta una excepción. Es greppable y tiene test propio.

Rejected: enmascarar (`****XX`) los valores sensibles — la regla 11 dice explícitamente que
la forma estructurada es el defecto y que el valor no sobrevive "ni siquiera enmascarado"; la
única excepción del contrato es `notification_logs.subject`/`body`, que no es esta.
Rejected: un `dict` libre validado en el adaptador — el adaptador es infraestructura y la
regla es de dominio; además un caso de uso podría construir el dict y no pasar por ahí.

### D4 — Un `AuditLog` por mutación, con la acción nombrando la operación

**Chosen:** una fila por operación de API. Vocabulario en `app/audit/domain/actions.py`:
`entity_type` ∈ {`USER`, `TENANT`, `TENANT_CONFIG`} y `action` ∈ {`USER_CREATED`,
`USER_UPDATED`, `USER_ROLE_CHANGED`, `USER_DEACTIVATED`, `USER_PASSWORD_RESET`,
`TENANT_UPDATED`, `TENANT_CONFIG_UPDATED`}. Un `PATCH` que cambia el rol usa
`USER_ROLE_CHANGED` (no `USER_UPDATED`) aunque cambie también otros campos, y `changes`
lleva todos: así la regla 9 («AuditLog para … roles de User») se satisface con un filtro por
`action`, sin depender de una consulta JSONB sobre `changes`.

Rejected: dos filas cuando el `PATCH` cambia rol y perfil a la vez — una operación son dos
registros y cualquier recuento de "cuántos cambios administrativos hubo" queda mal.
Rejected: `action` siempre `USER_UPDATED`, con el rol descubierto por `changes ? 'role'` —
convierte la comprobación de la regla 9 en una consulta JSONB en vez de un índice.

### D5 — El `User` deja de ser una dataclass pasiva: gana métodos que protegen sus invariantes

**Chosen:** `User` (`app/auth/domain/entities.py`) recibe `update_profile()`,
`change_role(new_role, *, actor_user_id)`, `change_status(new_status, *, actor_user_id)` y
`set_password_hash()`. La autoprotección de R3.5 (nadie cambia su propio rol ni su propio
estado) vive **en la entidad**, porque es la invariante de un solo agregado y
`steering/backend-architecture.md` prohíbe los setters públicos arbitrarios. `role` y
`status` dejan de ser campos que un caso de uso pueda asignar.

Rejected: la comprobación en el caso de uso — es una regla de negocio, y el steering dice que
si hay una regla pertenece a `domain/`.

### D6 — La invariante "el tenant conserva un `TENANT_OWNER` activo" se serializa con un lock sobre la fila del tenant

**Chosen:** todo caso de uso que pueda cambiar la población de propietarios (cambio de rol,
cambio de estado, `DELETE`) hace primero `SELECT ... FROM tenants WHERE id = :t FOR UPDATE`,
y después cuenta los propietarios activos distintos del objetivo mediante
`count_active_owners_excluding(tenant_id, user_id)`. La regla en sí es pura y vive en
`app/auth/domain/services.py`, recibiendo el recuento como argumento, así que se testea sin
base de datos.

El lock no es ceremonia: **una sola sentencia condicional no basta aquí**. El idioma de
`SessionRepository.consume()` (un `UPDATE ... WHERE` con `rowcount`) funciona porque la
condición se evalúa sobre la fila que se está escribiendo, y Postgres la reevalúa al
desbloquear. Un `UPDATE users SET role=… WHERE id=:a AND EXISTS (otro owner activo)` mira
**otras** filas: dos degradaciones concurrentes de dos propietarios distintos ven cada una al
otro como activo, las dos pasan, y el tenant se queda sin administración. El endpoint es de
baja frecuencia; el lock cuesta nada y cierra la ventana.

Rejected: aceptar la carrera y documentarla — el daño es un tenant que ya no se puede
administrar por API, sin endpoint de vuelta.
Rejected: constraint en base de datos — "al menos una fila con estas propiedades" no se
expresa con un índice.

### D7 — Dos razones nuevas de revocación, y un método de puerto para revocar **todas** las familias de un usuario

**Chosen:** `SessionRevokedReason` gana `USER_DEACTIVATED` y `PASSWORD_RESET`; el puerto
`SessionRepository` gana `revoke_all_for_user(tenant_id, user_id, reason, now)`. Hace falta
porque `revoke_family` solo alcanza **una** familia y aquí hay que matar todas las sesiones
del usuario afectado, que no es quien hace la petición. Dos razones y no una porque
`revoked_reason` existe para diagnosticar: "te desactivaron" y "te resetearon la contraseña"
son respuestas distintas a la misma queja.

Por qué esto es necesario y no cosmético: `auth-tenancy` revalida usuario y tenant en cada
petición autenticada, así que un usuario desactivado recibe `401` con su token de acceso —
pero `POST /api/v1/auth/refresh` **no atraviesa** `get_authenticated_request`, así que sin
revocar seguiría emitiendo pares nuevos indefinidamente.

Rejected: un único valor `ADMIN_REVOKED` — pierde el diagnóstico sin ahorrar nada.
Rejected: añadir la revalidación de estado dentro de `refresh` — cambia el comportamiento de
una capacidad archivada y añade una consulta a la ruta caliente de renovación; la revocación
explícita resuelve el caso real sin tocarla.

### D8 — Cuatro permisos nuevos, siguiendo la separación lectura/gestión de `reservations`

**Chosen:** `READ_USERS`, `MANAGE_USERS`, `READ_TENANT_SETTINGS`, `MANAGE_TENANT_SETTINGS`
en `app/auth/domain/policy.py`. `MANAGE_*` incluye su `READ_*` (mismo idioma que
`_RESERVATION_MANAGE`). Mapa: `TENANT_OWNER` los cuatro; `PROPERTY_MANAGER` los dos de
lectura; `CLEANER`, `TECHNICIAN` y `SUPER_ADMIN` ninguno.

Rejected: un único `MANAGE_TENANT` para usuarios y configuración — PRD §6 concede
"configurar preferencias del tenant" y la administración de personal como capacidades
distintas, y el manager necesita leer sin poder mutar.

### D9 — La contraseña temporal se genera en el dominio con `secrets`, sin puerto

**Chosen:** una función pura en `app/auth/domain/passwords.py`: alfabeto **sin caracteres
ambiguos** (`0`/`O`, `1`/`l`/`I` fuera) y longitud fija que deja ~80 bits de entropía y muy
por debajo del límite de 72 bytes de bcrypt que `auth-tenancy` documenta. `secrets` es
biblioteca estándar, así que la pureza de `domain/` (sin `sqlalchemy`/`fastapi`/`pydantic`,
que es lo que verifica `tests/test_layering.py`) se mantiene. El alfabeto sin ambigüedades no
es estética: esta contraseña la va a dictar o pegar una persona a otra por WhatsApp.

Rejected: puerto + adaptador `PasswordGenerator` — no hay sistema externo ni segunda
implementación; sería ceremonia. Los tests comprueban forma y que el login funciona con lo
devuelto, no un valor fijo.

### D10 — La temporal se devuelve en el cuerpo de exactamente dos respuestas, con `Cache-Control: no-store`

**Chosen:** `POST /users` (201) y `POST /users/{id}/reset-password` (200) llevan
`temporary_password`; ningún `GET` lo lleva nunca, y el esquema de respuesta del listado y del
detalle es otro tipo, no el mismo con un campo opcional. Ambas respuestas se emiten con
`Cache-Control: no-store`. Un tipo distinto por respuesta hace imposible que el campo se
filtre a un `GET` por descuido.

Rejected: devolverla en una cabecera propia — las cabeceras son lo que más se registra en los
proxies.
Rejected: `Optional[str] = None` en el esquema compartido — un `None` en un listado es un
campo que alguien acabará rellenando.

### D11 — El `409` sale del índice, no de una comprobación previa

**Chosen:** el adaptador captura `IntegrityError` en el `flush`, comprueba que el nombre del
constraint es `uq_users_lower_email` y levanta `EmailAlreadyExistsError` (→ `409 CONFLICT`);
cualquier otro `IntegrityError` se re-lanza. Idéntico al patrón de
`SqlAlchemyReservationRepository.add` con `uq_reservations_tenant_id_external_pms_id`. Un
`except IntegrityError` genérico convertiría una violación de clave ajena en un `409`
mentiroso.

El mensaje dice que la dirección ya está en uso y **no** nombra el tenant. Que un `409`
revele que la dirección existe en algún sitio es inherente a la unicidad global de ADR 0005;
la alternativa —responder `201` sin crear nada— es peor.

Rejected: `find_by_email_globally` antes de insertar — dos altas simultáneas la pasan las dos
y una acaba en `500`. Sí se usa, en cambio, para nada: la comprobación previa se elimina del
camino de alta y el índice decide.

### D12 — `GET`/`PATCH /tenants/{id}`: la comparación con el token ocurre antes de cualquier consulta

**Chosen:** el caso de uso compara `path_id` con `context.tenant_id` y levanta
`TenantNotFoundError` (→ `404`) si difieren, **antes** de tocar la base de datos. Es la única
protección que hay: `tenants` no tiene columna `tenant_id` y `tenant_scoped_classes()`
(`app/core/db.py`) selecciona los mappers por esa columna, así que el filtro global de
sesión **no cubre esa tabla**. `tenant_configs` sí la lleva y sí queda cubierta — pero como
red, no como mecanismo.

Rejected: no aceptar `{id}` en la ruta y servir `/tenants/me` — desvía de PRD §23 sin
ganancia; el `404` es además el criterio R7.1 aplicado al recurso tenant.

### D13 — `TenantConfig` viaja anidada, y se crea al vuelo si falta

**Chosen:** un solo recurso: `{..., "config": {...}}` en la respuesta y en el cuerpo del
`PATCH`; `model_fields_set` se consulta también en el objeto anidado, para distinguir
"ausente" de "enviado como null". Si no existe fila en `tenant_configs`, el caso de uso la
crea con los valores por defecto antes de aplicar el parche, así la API no depende de que el
bootstrap la haya creado (R5.7).

Rejected: endpoint `/tenants/{id}/config` — PRD §23 no lo define y la relación es 1:1 por el
índice único de `tenant_configs.tenant_id`.

### D14 — Validaciones de `timezone`, `country` y `default_language`, con su alcance dicho en voz alta

**Chosen:** `timezone` se valida construyendo `zoneinfo.ZoneInfo(value)` en un value object de
`app/tenants/domain/` — `celery-jobs` calculará con esa zona las ventanas de check-in y
checkout, y una cadena inválida convertiría un error de configuración en un fallo del
scheduler. **Verificado en el contenedor**: `ZoneInfo("Europe/Madrid")` resuelve y hay 599
zonas disponibles porque el paquete PyPI `tzdata` 2026.3 está instalado — pero **por vía
transitiva** (`celery` → `kombu` → `tzdata`). Se declara explícitamente en
`backend/pyproject.toml`, siguiendo la razón que ya está escrita ahí para `anyio`: depender
de una transitiva es romperse el día que la de arriba la cambie.

`country` se valida **solo de forma** (dos letras ASCII mayúsculas), no contra la lista
ISO-3166-1 real, que exigiría una dependencia nueva (`pycountry`). Queda dicho como
limitación, no como cobertura. `default_language` y `preferred_language`: `es` o `en`, los dos
locales que existen en `frontend/locales/`.

**Corregido tras el panel de las secciones 7-8** (hallazgo del revisor de seguridad, aceptado):
los campos enteros solo comprobaban el **signo**, no la magnitud, así que
`{"sla_high_minutes": 99999999999}` llegaba a asyncpg como `DataError: value out of int32
range` — que no es un `TenantDomainError` y por tanto salía como un `500` **sin mapear** en vez
del `422` que exige R5.5. Los campos `Decimal` sí tenían su cota desde el principio; los enteros
no, y eso rompía la promesa que hace la cabecera del propio módulo. Ahora se acotan por la
**columna** (`Integer` es int32 en Postgres) y no por un techo de negocio: «un SLA no puede pasar
de una semana» sería inventar una regla que el PRD no dice. Si el negocio la quiere, la enuncia
quien la tenga.

Rejected: validar `timezone` contra una lista fija propia — envejece con la base de datos IANA.

### D15 — `PATCH` sin cambios reales no escribe nada, ni fila ni `AuditLog`

**Chosen:** mismo comportamiento que el `PATCH` de `reservations`: un cuerpo vacío o con los
valores que ya tenía no produce `UPDATE` ni registro de auditoría, y responde el recurso tal
cual. No lo pide ningún criterio del proposal; se decide por coherencia y porque un
`audit_logs` con filas de diffs vacíos deja de servir para auditar. **Se reflejará como
criterio en la spec al archivar.**

### D16 — Se consolida el `SqlAlchemyUnitOfWork` duplicado, y solo eso

**Chosen:** se borra `app/auth/infrastructure/unit_of_work.py` y
`app/auth/api/dependencies.py` pasa a importar `SqlAlchemyUnitOfWork` de
`app/core/unit_of_work.py`. El **Protocol** `UnitOfWork` de `app/auth/domain/ports.py` se
queda donde está: la capa `application/` de `auth` importa sus puertos de su propio
`domain/`, que es la disposición más pura, y el Protocol de `core` convive con un import de
`sqlalchemy` en el mismo módulo. La deuda registrada en `specs/reservations.md` nombra las
"ocho líneas duplicadas", que son la clase concreta. `reservations` no se toca.

Rejected: unificar también el Protocol — obligaría a `auth/application/` a importar un módulo
que trae `sqlalchemy` consigo, empeorando lo que la consolidación pretende limpiar.

### D17 — Orden del listado: `name` ascendente con `id` de desempate

**Chosen:** el listado de personal se lee por nombre. `id` como segundo criterio para que
paginar no repita ni omita filas (criterio ya establecido en `reservations`). No hay índice
`(tenant_id, name)` y no se añade: el listado son unidades o decenas de filas por tenant.
Queda anotado para el día que deje de ser cierto.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Dominio auth | `app/auth/domain/entities.py` | `User` gana `update_profile`, `change_role`, `change_status`, `set_password_hash` con la autoprotección de R3.5 (D5) |
| | `app/auth/domain/services.py` *(nuevo)* | Regla pura "el tenant conserva un owner activo" (D6) |
| | `app/auth/domain/passwords.py` *(nuevo)* | Generador de contraseña temporal (D9) |
| | `app/auth/domain/ports.py` | `UserRepository`: `get`, `list`, `add`, `save`, `count_active_owners_excluding`; `SessionRepository`: `revoke_all_for_user` (D7) |
| | `app/auth/domain/policy.py` | Cuatro permisos nuevos y su mapa por rol (D8) |
| | `app/auth/domain/enums.py` | `SessionRevokedReason`: `USER_DEACTIVATED`, `PASSWORD_RESET` (D7) |
| | `app/auth/domain/exceptions.py` | `UserNotFoundError`, `EmailAlreadyExistsError`, `SelfRoleChangeError`, `LastOwnerError`, `UnassignableRoleError` |
| Aplicación auth | `app/auth/application/user_admin.py` *(nuevo)* | Seis casos de uso: crear, listar, obtener, actualizar, desactivar, resetear contraseña |
| Infra auth | `app/auth/infrastructure/repositories.py` | Métodos nuevos del puerto, traducción del `409` (D11), lock de tenant (D6) |
| | `app/auth/infrastructure/unit_of_work.py` | **Se borra** (D16) |
| API auth | `app/auth/api/users_router.py` *(nuevo)* | Los cinco endpoints de PRD §23 más el reset |
| | `app/auth/api/user_schemas.py` *(nuevo)* | DTOs; respuestas con la temporal en tipo propio (D10) |
| | `app/auth/api/dependencies.py` | Builders de los casos de uso nuevos; import del UoW de `core` (D16) |
| | `app/auth/api/errors.py` | Mapeo de las excepciones nuevas al envelope |
| Dominio tenants | `app/tenants/domain/repositories.py` *(nuevo)* | Puertos `TenantRepository` y `TenantConfigRepository` |
| | `app/tenants/domain/value_objects.py` *(nuevo)* | `Timezone`, país e idioma (D14) |
| | `app/tenants/domain/entities.py` | Métodos de mutación de `Tenant`/`TenantConfig`; `status` y `storage_type` no mutables por API |
| | `app/tenants/domain/exceptions.py` *(nuevo)* | `TenantNotFoundError`, `TenantValidationError` |
| Aplicación tenants | `app/tenants/application/use_cases.py` *(nuevo)* | Obtener y actualizar tenant + config, con el upsert de D13 |
| Infra tenants | `app/tenants/infrastructure/repositories.py` *(nuevo)* | Adaptadores, incluido el `SELECT … FOR UPDATE` de D6 |
| API tenants | `app/tenants/api/{router,schemas,dependencies,errors}.py` *(nuevos)* | `GET`/`PATCH /tenants/{id}` |
| Dominio audit | `app/audit/domain/{repositories,services,value_objects,actions}.py` *(nuevos)* | Puerto, fábrica, `ChangeSet` y vocabulario (D2, D3, D4) |
| Infra audit | `app/audit/infrastructure/repositories.py` *(nuevo)* | `SqlAlchemyAuditLogRepository` |
| Migración | `alembic/versions/<rev>_session_revoked_reason_admin.py` *(nuevo)* | `ALTER TYPE session_revoked_reason ADD VALUE` ×2; `down_revision = '96d526599bc1'` |
| Registro | `app/main.py` | Alta de los dos routers y de sus handlers de error |
| Dependencias | `backend/pyproject.toml` | `tzdata` explícito (D14) |
| Tests | `tests/auth/`, `tests/tenants/`, `tests/audit/` | Ver §Riesgos y el desglose que hará `/sdd:tasks` |
| Docs | `docs/user-management.md` *(nuevo)*, `docs/auth-tenancy.md`, `.env.example` | Operación; sin variables nuevas |

## Data & interfaces

**Esquema.** Ninguna tabla ni columna nueva. Un solo cambio: dos valores nuevos en el enum
nativo `session_revoked_reason`.

**Endpoints.**

| Método | Ruta | Permiso | Éxito |
|---|---|---|---|
| `GET` | `/api/v1/users` | `READ_USERS` | `200` envelope de página |
| `POST` | `/api/v1/users` | `MANAGE_USERS` | `201` + `temporary_password` |
| `GET` | `/api/v1/users/{id}` | `READ_USERS` | `200` |
| `PATCH` | `/api/v1/users/{id}` | `MANAGE_USERS` | `200` |
| `DELETE` | `/api/v1/users/{id}` | `MANAGE_USERS` | `204` |
| `POST` | `/api/v1/users/{id}/reset-password` | `MANAGE_USERS` | `200` + `temporary_password` |
| `GET` | `/api/v1/tenants/{id}` | `READ_TENANT_SETTINGS` | `200` con `config` anidada |
| `PATCH` | `/api/v1/tenants/{id}` | `MANAGE_TENANT_SETTINGS` | `200` |

Códigos de error: `401` sin token o token inválido; `403` rol sin permiso (decidido antes de
consultar, R7.3); `404` recurso inexistente **o de otro tenant**; `409` email ya en uso;
`422` validación, rol `SUPER_ADMIN`, campo no permitido, autocambio de rol/estado, y último
propietario activo.

**Config/env.** Ninguna variable nueva. La longitud de la contraseña temporal es constante
en el dominio, no configuración: es un parámetro de seguridad, no de despliegue.

## Risks & mitigations

- **`ALTER TYPE … ADD VALUE` y la transacción de Alembic.** En Postgres 16 se puede ejecutar
  dentro de una transacción, pero el valor nuevo **no se puede usar** en esa misma
  transacción. La migración solo añade los valores y no escribe filas con ellos, así que
  pasa; `tests/test_migrations.py` ya recorre la cadena arriba y abajo y lo detectaría.
  El `downgrade` no puede quitar un valor de un enum: se documenta como irreversible en la
  propia migración, que es lo honesto, en lugar de recrear el tipo.
- **Un `IntegrityError` aborta la transacción.** Tras el `flush` fallido del `409` no queda
  trabajo parcial que salvar: la excepción sube y la sesión por petición hace `rollback`
  (`auth-tenancy` ya garantiza ese `rollback`/`close`). No hace falta savepoint. El
  `AuditLog` del alta se escribe **después** del `flush` del usuario, así que un `409` no
  deja rastro de una creación que no ocurrió.
- **El lock de D6 y `celery-jobs`.** El `SELECT … FOR UPDATE` sobre `tenants` lo toman solo
  tres endpoints administrativos de baja frecuencia. Si un job futuro escribiera la fila del
  tenant en caliente, habría contención; se anota, no se pre-optimiza.
- **`tzdata` transitivo.** Mitigado declarándolo (D14). Sin eso, un `uv lock` que deje de
  traerlo rompería la validación de `timezone` en tiempo de ejecución, no en CI.
- **Exposición de la temporal.** Vive en dos cuerpos de respuesta y en `no-store` (D10).
  Riesgo residual asumido y documentado: **no se fuerza su cambio en el primer login** —
  requiere `must_change_password` y el autoservicio de `auth-account-recovery`—, así que
  sobrevive hasta que un administrador la rote.
- **Cobertura de tests que este change debe traer** (el desglose es de `/sdd:tasks`): la
  matriz endpoint × 5 roles de R7.2 con el molde de `tests/reservations/test_authorization.py`;
  `404` cross-tenant por cada endpoint con `{id}`, incluido el de tenant (R7.9); un test que
  demuestre que `ChangeSet.diff` rechaza los campos de la lista de denegación y que ninguna
  respuesta ni fila de `audit_logs` contiene la temporal; concurrencia de D6 (dos
  degradaciones simultáneas dejan un propietario); y que un usuario desactivado no puede
  renovar por `POST /auth/refresh`.
- **Deuda que este change NO cierra**, y consta: el `AuditLog` retroactivo de las seis
  mutaciones de `reservations`/`integrations` (fuera de alcance por el proposal, ahora
  accionable porque el escritor existe).

## Open questions

Ninguna abierta. Las tres que este design levantó se resolvieron con el dueño del change el
2026-07-31, y quedan registradas como decisiones:

### D21 — El adaptador de usuarios NO recupera un `save`: escribe solo las columnas que cambiaron

**Descubierto al implementar la sección 2**, y corrige lo que decían las tareas 4.1 y 4.4
(«ampliar el puerto con … `save`»).

`tests/auth/test_repositories.py::test_no_unconditional_write_primitive_came_back` es un
guard de regresión que afirma que `SqlAlchemyUserRepository` **no tiene** `save`. No es
casualidad: `auth-tenancy` lo borró (su task 11.9, design D5, R2.1) porque «copiaba la fila
entera, así que podía revertir una suspensión commiteada a mitad de petición», y el guard
existe porque «lo que decae es la ausencia de la superficie: el siguiente que necesite
escribir la encontraría y la usaría».

**Chosen:** `apply_changes(tenant_id, user_id, values)` — un `UPDATE users SET …` con
**solo** las columnas que el caso de uso cambió, derivadas del mismo diff que alimenta el
`ChangeSet` de auditoría. Es estrictamente más seguro que un `save` con lista blanca
(el patrón que sí usa `reservations`): al no escribir una columna que no se tocó, no puede
revertir un cambio concurrente sobre ella — que es exactamente el daño que el guard
describe. El nombre `save` no vuelve, así que el test de `auth-tenancy` **no se toca**.

Rejected: añadir `save` y reescribir el guard — invierte una decisión de una capacidad
archivada para reintroducir el fallo que documentó, y "una lista blanca" no arregla el
problema: `role` y `status` estarían en ella.
Rejected: concurrencia optimista comparando `updated_at` — resuelve el mismo caso con un
reintento que nadie ha pedido, cuando la escritura parcial lo hace imposible por
construcción.

### D22 — Un `null` explícito en un `PATCH` es un `422`, no "campo ausente"

**Descubierto por el panel de seguridad de las secciones 2-6**, que lo reprodujo en vivo contra
el stack real. Dos manifestaciones del mismo error:

- `PATCH /users/{id}` con `{"email": null}` respondía `200` y escribía la cadena literal
  `"none"` como identidad de login — dejando la cuenta fuera de un producto cuya identidad
  **es** el email (ADR 0005), sin vía de vuelta salvo otra edición administrativa.
- `{"status": null}` llegaba a la base de datos y volvía como un `500` sin mapear.

**Causa**: todos los campos de un esquema de `PATCH` son `X | None` porque así se expresa "no
enviado", y `model_fields_set` no distingue eso de un `null` que el llamante **sí** envió.

**Chosen:** un `model_validator` rechaza el `null` explícito en todo campo cuya columna sea
`NOT NULL`. En `users` la única nullable es `phone`, así que solo `phone` se puede vaciar; en
`tenants` y `tenant_configs` no hay ninguna. Y las entidades comprueban además el tipo
(`isinstance`) en `change_role`, `change_status` y `update_profile`, para que la invariante no
dependa de una restricción de columna que un cambio de esquema futuro pudiera relajar — la
asimetría de haber endurecido solo `change_status` la levantó el panel de QA.

El mismo arreglo se aplicó **preventivamente** al `PATCH` de tenant (secciones 7-8), que tenía
el bug idéntico sin haber sido reportado todavía.

Rejected: tratar el `null` explícito como "sin cambio" — silencioso, y deja al llamante creyendo
que borró algo.

### D18 — `SessionRevokedReason` gana **dos** valores, no uno

**Chosen:** `USER_DEACTIVATED` y `PASSWORD_RESET`. `revoked_reason` existe para diagnosticar,
y son dos respuestas distintas a la misma queja ("se me cerró la sesión"). Un enum nativo es
más caro de cambiar después que de acertar ahora.

Rejected: un único `ADMIN_REVOKED` — obligaría a cruzar con `audit_logs` para responder algo
que la propia fila puede decir.

### D19 — `DELETE /users/{id}` sobre uno mismo se rechaza con `422`

**Chosen:** prohibido, sea o no el último propietario. R3.5 ya prohíbe cambiarse el rol y el
estado a uno mismo y un `DELETE` **es** un cambio de estado (D5, `change_status`), así que la
lectura literal lo prohíbe: la autoprotección de la entidad lo cubre sin código extra. Evita
además el camino en el que el actor se queda sin acceso a mitad de su propia petición, con la
transacción a medias.

Rejected: permitir la autobaja a quien no sea el último propietario — introduce ese camino a
cambio de una comodidad que un segundo administrador ya resuelve.

### D20 — Temporal de 16 caracteres sobre un alfabeto sin ambigüedades

**Chosen:** 16 caracteres, alfabeto sin `0`/`O` ni `1`/`l`/`I` (~80 bits de entropía), muy por
debajo del límite de 72 bytes de bcrypt. Corta de pegar y sin caracteres que se confundan al
dictarla.

Rejected: palabras separadas por guiones (`caballo-verde-rapido-42`) — más fácil de dictar por
teléfono, pero exige mantener una lista de palabras en el repositorio y decidir su idioma;
no lo compensa cuando el canal habitual es pegar la cadena en un mensaje.
