# Administración de usuarios y configuración del tenant

## Purpose

Esta capacidad administra las cuentas del personal de un tenant —alta, listado, edición,
cambio de rol, baja y reset de contraseña— y la configuración operativa del tenant: umbral de
aprobación del propietario, SLAs, ventanas de check-in/checkout y conmutadores de notificación.
Cierra lo que `auth-tenancy` dejó fuera a propósito: los usuarios ya no entran solo por el
comando de bootstrap, así que dar de alta una limpiadora o un técnico no exige un despliegue.

Es además la primera capacidad que consume `audit_logs`, cuya entidad llegó con
`domain-foundation-financial` sin ningún consumidor —quién escribe hoy `audit_logs.changes` lo
declara la tabla de la regla 11 de [`steering/security.md`](../steering/security.md), y solo
ella—, y la primera que demuestra sobre
sus propios endpoints los dos criterios que `auth-tenancy` declaró fuera de su alcance por
tener endpoints autorreferenciales: el `404` cross-tenant y la matriz de autorización completa.

No incluye frontend (`dashboard-web`, `hardening-release`), ni el autoservicio de contraseña
—el cambio por el propio usuario, la recuperación anónima y el gate que obliga a rotar la
temporal son `auth-account-recovery` (`specs/auth-account-recovery.md`)—, ni alta o baja de
tenants, ni salida de la API a internet (`api-ingress-routing`).

## Requirements

### Alta de usuario con contraseña temporal

- WHEN se solicita `POST /api/v1/users` con datos válidos, THE SYSTEM SHALL crear el usuario en
  el tenant del token con estado `ACTIVE` y responder `201` con el recurso creado y la
  contraseña temporal generada.
- WHEN se crea el usuario, THE SYSTEM SHALL dejar `must_change_password` en verdadero, de modo
  que la temporal solo sirva para entrar y cambiarla: el gate y su `403
  PASSWORD_CHANGE_REQUIRED` los define `auth-account-recovery`.
- THE SYSTEM SHALL generar la contraseña temporal con `secrets` sobre un alfabeto **sin
  caracteres ambiguos** (sin `0`/`O` ni `1`/`l`/`I`), de 16 caracteres, garantizando al menos
  uno de cada clase (dígito, mayúscula, minúscula). La garantía de clases no responde a ninguna
  política de composición —`auth-account-recovery` no impone ninguna—, pero la longitud sí
  está atada: un test fija que 16 caracteres nunca bajen del mínimo de 12 de aquella política,
  para que este sistema no emita una contraseña que aquel rechazaría.
- THE SYSTEM SHALL devolver la temporal **exactamente una vez**, en el cuerpo del `201`, y no
  SHALL persistirla en claro, escribirla en el log de la aplicación, en `audit_logs.changes` ni
  en ningún `TimelineEvent`.
- THE SYSTEM SHALL emitir las dos respuestas que transportan la temporal con
  `Cache-Control: no-store`, y SHALL declararlas en un tipo de respuesta propio que ningún `GET`
  usa: un campo opcional en un modelo compartido es la forma que acaba rellenada por descuido.
- THE SYSTEM SHALL derivar el `tenant_id` del token y no SHALL aceptarlo en el cuerpo, la query
  ni la ruta.
- IF el email normalizado ya existe bajo **cualquier** tenant, THEN THE SYSTEM SHALL responder
  `409` con un mensaje accionable, y no SHALL nombrar el tenant al que pertenece la dirección.
  Que el `409` revele que la dirección existe en algún sitio es inherente a la unicidad global
  de ADR 0005; la alternativa —responder `201` sin crear nada— es peor.
- THE SYSTEM SHALL apoyar esa unicidad en el índice `uq_users_lower_email`, traduciendo su
  violación por nombre de constraint, y no en una comprobación previa: dos altas simultáneas con
  la misma dirección pasarían las dos la comprobación y una acabaría en `500`. Cualquier otro
  `IntegrityError` se re-lanza — un `409` por una violación de clave ajena sería una mentira que
  el cliente no puede accionar.
- IF el rol solicitado es `SUPER_ADMIN`, THEN THE SYSTEM SHALL responder `422`: sus capacidades
  en PRD §6 son globales, no operativas de un tenant, y lo cross-tenant está diferido a
  `saas-cross-tenant`. Esta restricción no se relaja por API: `GRANTABLE_ROLES` la cierra y
  `platform-admin-api` la mantiene en su propio `POST /api/v1/platform/tenants/{tenant_id}/users`
  (D2) — un campo `role=SUPER_ADMIN` en esa ruta cae por el `field_validator` del esquema
  (`backend/app/platform/api/schemas.py`), no por la entidad. La duplicación es deliberada:
  la entrada de la API de plataforma es la primera línea de defensa, no un permiso nuevo.
- **Caso de uso compartido con `platform-admin-api` (R4.3):** `POST /api/v1/platform/tenants/{tenant_id}/users`
  reutiliza `CreateUserUseCase` con `tenant_id` tomado del path, no del token; la auditoría
  resultante lleva `tenant_id=<path>` (regla D5, el actor `SUPER_ADMIN` no tiene tenant y la
  sesión no se marca). El redaction de la contraseña temporal en `audit_logs.changes` (`password: {"changed": true}`)
  es el mismo que aplica esta capacidad. No hay aquí un cambio de comportamiento: la API
  de plataforma delega, y el único contrato que expone es el de los tres campos del cuerpo
  (`email`, `full_name`, `role`) y la cabecera `Cache-Control: no-store`.
- **Primer llamante de frontend de esa ruta (`super-admin-console`, R4):** hasta esa entrada,
  `POST /api/v1/platform/tenants/{tenant_id}/users` no tenía caller de UI — el formulario de
  alta de personal de la consola de plataforma (`sdd/specs/super-admin-console.md`) es quien
  lo invoca hoy, mostrando la contraseña temporal una sola vez. El comportamiento del
  endpoint y del caso de uso no cambia; solo gana un consumidor.

### Listado y consulta

- WHEN se solicita `GET /api/v1/users`, THE SYSTEM SHALL devolver únicamente los usuarios del
  tenant del token, paginados con `page`/`per_page` y el envelope
  `{data, total, page, per_page, total_pages}` de PRD §23.
- THE SYSTEM SHALL acotar `per_page` a 100 y `page` a 100.000, respondiendo `422` fuera de esos
  rangos: `page` se convierte en un `OFFSET` de SQL y un valor sin cota desborda y produce un
  error de driver en vez de una respuesta del envelope.
- THE SYSTEM SHALL ordenar el listado por `name` ascendente con el `id` como segundo criterio,
  de modo que paginar no muestre una fila dos veces ni omita otra.
- WHEN el listado recibe un filtro por rol o por estado, THE SYSTEM SHALL aplicarlo con AND.
- THE SYSTEM SHALL NOT exponer `password_hash` en ninguna respuesta de esta capacidad, con los
  campos de respuesta enumerados y nunca volcados desde la entidad.
- WHEN se solicita `GET /api/v1/users/{id}` de un usuario del tenant, THE SYSTEM SHALL
  devolverlo **cualquiera que sea su estado**: la administración necesita ver una cuenta
  suspendida para poder reactivarla, a diferencia de la consulta de autenticación
  (`get_active_by_id`), que solo resuelve usuarios `ACTIVE` de tenants `ACTIVE`.

### Edición, cambio de rol y baja

- WHEN se solicita `PATCH /api/v1/users/{id}`, THE SYSTEM SHALL aplicar solo los campos
  presentes en el cuerpo, sobre `name`, `phone`, `preferred_language`, `email`, `role` y
  `status`, y SHALL escribir **solo las columnas que cambiaron de verdad**.
- THE SYSTEM SHALL rechazar con `422` los campos que no pertenecen a la edición (`tenant_id`,
  `password_hash`, `last_login_at`, `id`) mediante `extra="forbid"`.
- THE SYSTEM SHALL rechazar con `422` un `null` **explícito** en cualquier campo cuya columna
  sea `NOT NULL`; solo `phone` se puede vaciar. «No enviado» y «enviado como null» son
  indistinguibles en `model_fields_set` una vez llegan al caso de uso, y conflacionarlos hacía
  que `{"email": null}` respondiera `200` escribiendo la cadena `"none"` como identidad de
  login, y que `{"status": null}` volviera como un `500` sin mapear.
- WHEN un `PATCH` cambia el email, THE SYSTEM SHALL normalizarlo dentro de la entidad y aplicar
  la misma traducción a `409`: la dirección **es** la identidad de login (ADR 0005), y sin esta
  vía un typo en el email del único propietario solo se corrige por SQL.
- THE SYSTEM SHALL mutar `role`, `status`, `email`, el perfil y el hash únicamente a través de
  métodos de la entidad `User` que sostienen sus invariantes, nunca por asignación directa de
  atributo desde `application/`. Un test deriva de `User.__dataclass_fields__` el conjunto de
  campos mutables y exige que cada uno tenga su método, así que el siguiente campo que se añada
  sin uno falla en la suite.
- WHEN un `PATCH` cambia el rol, THE SYSTEM SHALL registrar un `AuditLog` con acción
  `USER_ROLE_CHANGED` y el rol anterior y el nuevo (regla 9 de `steering/security.md`), aunque
  el mismo `PATCH` cambie además otros campos: una operación es una fila, con todos los campos
  en `changes`.
- IF un actor intenta cambiar su **propio** rol o su propio estado, THEN THE SYSTEM SHALL
  rechazarlo con `422`: una autodegradación deja al tenant sin quien administre y no existe
  endpoint de vuelta. Cubre también el `DELETE`, que es un cambio de estado.
- IF la operación dejaría al tenant sin ningún `TENANT_OWNER` en estado `ACTIVE`, THEN THE
  SYSTEM SHALL rechazarla con `422`, evaluando la regla sobre el **resultado** combinado de rol
  y estado y no campo a campo.
- THE SYSTEM SHALL tomar un bloqueo de fila sobre `tenants` (`SELECT … FOR UPDATE`) antes de
  contar los propietarios activos, en toda operación que pueda cambiar esa población. Una única
  sentencia condicional no basta: la condición mira **otras** filas, evaluadas contra el
  snapshot de cada transacción, así que dos degradaciones concurrentes de dos propietarios
  distintos verían cada una al otro como activo y pasarían las dos.
- WHERE la operación no puede afectar a la población de propietarios (un `PATCH` solo de
  perfil), THE SYSTEM SHALL NOT tomar ese bloqueo.
- WHEN un usuario pasa a `INACTIVE` o `SUSPENDED`, THE SYSTEM SHALL revocar **todas** sus
  familias de tokens de refresh con razón `USER_DEACTIVATED`. La revalidación por petición de
  `auth-tenancy` ya le devuelve `401` con el token de acceso, pero `POST /api/v1/auth/refresh`
  no la atraviesa, así que sin esto una cuenta desactivada seguiría emitiendo pares nuevos
  durante los 7 días de vida del refresh.
- WHEN se solicita `DELETE /api/v1/users/{id}`, THE SYSTEM SHALL pasar el usuario a `INACTIVE`
  conservando la fila y responder `204`. Borrarla rompería el rastro que la regla 9 obliga a
  conservar: `audit_logs.actor_user_id` y `timeline_events.actor_user_id` apuntan al usuario.
- IF el usuario ya está `INACTIVE`, THEN THE SYSTEM SHALL responder `204` sin registrar un
  segundo `AuditLog` de baja.
- WHEN un `PATCH` no cambia nada —cuerpo vacío o campos con el valor que ya tenían— THE SYSTEM
  SHALL no escribir ni fila ni `AuditLog`: `audit_logs` es evidencia de cambios, no de
  peticiones.

### Reset de contraseña asistido

- WHEN se solicita `POST /api/v1/users/{id}/reset-password` sobre un usuario del tenant, THE
  SYSTEM SHALL generar una temporal nueva con las mismas garantías del alta, reemplazar el hash
  almacenado y responder con la temporal una sola vez.
- WHEN se completa un reset asistido, THE SYSTEM SHALL dejar `must_change_password` en verdadero:
  es el segundo de los dos caminos de contraseña temporal de esta capacidad, y una temporal que
  no hay que cambiar es una contraseña permanente que viajó por WhatsApp.
- WHEN se completa un reset, THE SYSTEM SHALL revocar todas las familias de refresh del usuario
  afectado con razón `PASSWORD_RESET`: un reset que deja vivas las sesiones anteriores no
  recupera la cuenta, solo añade una credencial más.
- THE SYSTEM SHALL registrar el reset en `AuditLog` sin la contraseña, sin el hash y sin ninguna
  forma reversible de ellos.
- Este endpoint **no** está en la lista de PRD §23: fue una adición deliberada, porque
  `auth-account-recovery` es opcional en PRD §24 y sin él el MVP no habría tenido ninguna vía de
  recuperación. Ya no es la única —el autoservicio anónimo existe desde entonces—, pero **sigue
  siendo la vía asistida**, y también la única que un administrador controla. Lo que ya no
  sostiene es el caso que la justificó: el único `TENANT_OWNER` activo de un tenant no puede
  resetearse por aquí, y para ese caso la salida es el comando de rescate de
  `auth-account-recovery`.

### Configuración del tenant

- WHEN se solicita `GET /api/v1/tenants/{id}` con el `id` del tenant del token, THE SYSTEM SHALL
  devolver los datos del tenant junto a su `TenantConfig` **anidada como un solo recurso**: PRD
  §23 no define endpoint propio para la config y la relación es 1:1 por el índice único de
  `tenant_configs.tenant_id`.
- IF el tenant no tiene fila en `tenant_configs`, THEN THE SYSTEM SHALL crearla con los valores
  por defecto, de modo que la API no dependa de que el bootstrap la haya creado.
- WHEN se solicita `PATCH /api/v1/tenants/{id}`, THE SYSTEM SHALL aplicar solo los campos
  presentes, sobre `name`, `billing_email`, `country`, `timezone` y `default_language` del
  tenant y los umbrales, SLAs, ventanas y conmutadores de notificación de la config, y SHALL
  consultar `model_fields_set` también en el objeto anidado.
- THE SYSTEM SHALL rechazar con `422` el campo `status` del tenant en las tres capas (esquema,
  entidad y adaptador): `auth-tenancy` revalida en cada petición que el tenant siga `ACTIVE`,
  así que suspenderse a sí mismo deja a **todos** sus usuarios en `401` sin vía de vuelta por la
  API. Cambiar el estado de un tenant es una operación de plataforma.
- THE SYSTEM SHALL rechazar con `422` el campo `storage_type` de la config, también en las tres
  capas: cambiarlo apunta las fotos ya subidas a un backend que no las tiene, y elegir `S3` sin
  credenciales rompe los uploads. Pertenece a `cleaning`, con su migración de datos.
- THE SYSTEM SHALL validar los rangos de lo que acepta y responder `422` fuera de ellos: umbral
  de aprobación no negativo y representable en `Numeric(10,2)`, umbral de confianza de IA en
  `[0,1]` con dos decimales (`Numeric(3,2)` redondearía un tercero en silencio), SLAs positivos,
  ventanas no negativas.
- THE SYSTEM SHALL acotar los campos enteros al rango de su columna (`Integer` es int32 en
  Postgres). Sin esa cota un valor mayor llegaba al driver como `DataError` a mitad de
  transacción, que no es un error de dominio y salía como `500` sin mapear.
- THE SYSTEM SHALL rechazar un booleano en un campo numérico. Pydantic convierte `true` en `1`
  en modo laxo, así que sin un guard explícito `{"sla_high_minutes": true}` se aceptaría **como
  un minuto** —un SLA incumplido al instante— y el guard del dominio no puede verlo porque
  para entonces el booleano ya es un entero.
- THE SYSTEM SHALL validar que `timezone` es una zona IANA real construyendo `ZoneInfo`:
  `celery-jobs` calculará con ella las ventanas de check-in y checkout, y una cadena inválida
  convertiría un error de configuración en un fallo del scheduler. Se valida recortando pero
  **sin** normalizar la caja, porque los nombres IANA son sensibles a ella.
- `ASSUMPTION`: `country` se valida **solo de forma** (dos letras ASCII, mayúsculas), no contra
  la lista ISO-3166-1 real, que exigiría una dependencia nueva. `ZZ` pasa. Lo mismo aplica al
  formato de los emails, que no es RFC 5322.
- WHEN se modifica el tenant o su configuración, THE SYSTEM SHALL registrar un `AuditLog` por
  entidad afectada —`TENANT_UPDATED` y/o `TENANT_CONFIG_UPDATED`— porque `audit_logs.entity_id`
  apunta a una sola fila y una entrada no podría nombrar ambas. La regla 9 no lista
  `TenantConfig`, pero `owner_approval_threshold_eur` **es** el control del principio 4 de
  `steering/product.md`: cambiarlo sin rastro cambia en silencio qué gastos necesitan aprobación.

### Rastro de auditoría

- THE SYSTEM SHALL escribir `audit_logs.changes` siempre en forma estructurada
  `{campo: {"old": …, "new": …}}` (PRD §7.25) o `{campo: {"changed": true}}`, y ningún valor de
  la regla 3 de `steering/security.md` sobrevive ahí, ni siquiera enmascarado (regla 11).
- THE SYSTEM SHALL construir todo `AuditLog` a través de una fábrica de dominio, y SHALL
  construir todo diff a través de un `ChangeSet` **ligado a un `entity_type`** que solo admite
  los campos declarados como auditables de esa entidad. El nombre es el límite que se sostiene:
  vetar solo el *valor* no cierra la clase, porque un compuesto serializado a JSON transporta
  cualquier forma dentro de un string, y vetar el contenido de los strings es una carrera que se
  pierde (la siguiente codificación es base64, o ninguna).
- THE SYSTEM SHALL rechazar un `ChangeSet` cuyo `entity_type` no coincida con el de la entrada
  que se está construyendo: auditaría los campos correctos contra el objeto equivocado, con la
  lista de autorización de la otra entidad habiéndolos vetado.
- `ASSUMPTION`: lo que esto **no** cierra es un llamante que ponga un secreto como *valor* de un
  campo legítimo. Ninguna validación puede; lo cierran los casos de uso, que alimentan los diffs
  desde atributos tipados de la entidad, y el vocabulario cerrado de acciones.
- THE SYSTEM SHALL registrar `actor_user_id` del token y `actor_ip` resuelta con el mismo
  `get_client_ip` de `auth-tenancy`, heredando su limitación documentada sobre el peer de
  confianza (que cierra `api-ingress-routing`).
- WHILE se escribe una mutación, THE SYSTEM SHALL persistir el cambio y su `AuditLog` en una
  única transacción, de modo que un fallo al escribir el rastro deje el cambio sin aplicar. En
  el alta, el `AuditLog` se construye **después** del `flush` del usuario, así que un `409` no
  deja rastro de una creación que no ocurrió.
- THE SYSTEM SHALL fijar el vocabulario de `action` y `entity_type` en constantes de dominio
  —PRD §7.25 los tipa como `VARCHAR` libre— de modo que un cambio de rol se compruebe filtrando
  por `action`, con índice, en vez de con una consulta JSONB.
- THE SYSTEM SHALL NOT exponer ninguna vía de la API que lea, edite o borre filas de
  `audit_logs`; el puerto no ofrece más que `add`.

### Aislamiento por tenant y autorización

- WHEN un usuario referencia por `id` un usuario o un tenant que **existe** pero pertenece a
  otro tenant, THE SYSTEM SHALL responder `404` y no `403`, con un cuerpo indistinguible del de
  un `id` inventado.
- THE SYSTEM SHALL decidir la autorización **antes** de consultar el recurso, de modo que un rol
  sin permiso reciba la misma respuesta para un `id` real y para uno inventado.
- WHERE el rol es `TENANT_OWNER`, THE SYSTEM SHALL permitir los ocho endpoints.
- WHERE el rol es `PROPERTY_MANAGER`, THE SYSTEM SHALL permitir `GET /api/v1/users`,
  `GET /api/v1/users/{id}` y `GET /api/v1/tenants/{id}` —necesita el personal para asignar
  tareas y los umbrales y SLAs para operar— y SHALL denegar con `403` toda mutación. Quien
  asigna roles puede escalar privilegios, así que la asignación se queda en el propietario.
- WHERE el rol es `CLEANER` o `TECHNICIAN`, THE SYSTEM SHALL denegar con `403` los ocho
  endpoints: su autoservicio es `GET /api/v1/auth/me`, y el listado expone el email y el rol de
  todo el personal del tenant.
- WHERE el rol es `SUPER_ADMIN`, THE SYSTEM SHALL denegar con `403` los ocho endpoints, por el
  mismo razonamiento con el que lo hace `reservations`.
- THE SYSTEM SHALL filtrar `tenant_id` explícitamente en cada consulta y comprobarlo en cada
  escritura, porque el filtro global de sesión no cubre los `INSERT`.
- THE SYSTEM SHALL comparar el `id` de la ruta de `GET`/`PATCH /api/v1/tenants/{id}` contra el
  tenant del token **antes de cualquier consulta**. La tabla `tenants` no tiene columna
  `tenant_id` y `tenant_scoped_classes()` selecciona los mappers por esa columna, así que el
  filtro global de sesión **no la cubre** y esa comparación es la única protección que hay.
  `tenant_configs` sí la lleva y sí queda cubierta, como red y no como mecanismo.
- THE SYSTEM SHALL demostrar con tests, para cada uno de los cinco roles y por endpoint, que un
  usuario del tenant A no obtiene ni modifica datos del tenant B.

## Estado y deuda conocida

- **R3.6 (el tenant conserva un propietario activo) es hoy inalcanzable por HTTP**, y por
  construcción: solo `TENANT_OWNER` tiene `MANAGE_USERS` y no puede tocarse a sí mismo, así que
  nunca queda un último propietario degradable por la API. Es defensa en profundidad, alcanzable
  y probada a nivel de caso de uso y de concurrencia contra Postgres real. Lo que la suite
  garantiza a nivel HTTP es la propiedad que importa: **ninguna secuencia de llamadas deja el
  tenant sin administrador**. La regla es lo que salvaría al tenant el día que `MANAGE_USERS` se
  conceda a otro rol o se permita el autoservicio.
- ~~**La contraseña temporal no se fuerza a cambiar en el primer login**~~ — **cerrado por
  `auth-account-recovery`**: la columna `users.must_change_password` y el endpoint de
  autoservicio existen, esta capacidad deja el flag en verdadero en sus dos caminos de temporal
  (alta y reset asistido), y mientras esté puesto toda petición autenticada recibe `403
  PASSWORD_CHANGE_REQUIRED` salvo `GET /auth/me`, `POST /auth/logout` y
  `POST /auth/change-password`.
- **Sin `AuditLog` retroactivo de `reservations`/`integrations`**: esta capacidad monta el
  escritor y deja accionable la deuda que `specs/reservations.md` anota para sus seis casos de
  uso mutadores, pero no vuelve a ellos.
- **La API no tiene salida a internet**: estos endpoints se verifican con tests y, en dev, por
  túnel SSH (`RUNBOOK.md` §7.4). Lo cambia `api-ingress-routing`, que es también donde se cierra
  la comprobación del peer de confianza para `actor_ip`.
- **Sin frontend**: llega con `dashboard-web` y `hardening-release`.
- El paquete `tzdata` se declara explícitamente en `backend/pyproject.toml` aunque hoy la base
  IANA la aporte el `tzdata` del sistema operativo de la imagen (`/usr/share/zoneinfo`), que
  `zoneinfo` consulta antes del paquete PyPI. La declaración es el seguro para una imagen que no
  lo traiga, y su test comprueba la metadata del paquete y no solo que las zonas resuelvan —
  eso último pasaría igual sin la dependencia.

## Key files

- Dominio de usuario: `backend/app/auth/domain/` — `entities.py` (`User` con
  `create`/`update_profile`/`change_email`/`change_role`/`change_status`/`deactivate`/
  `set_password_hash`), `services.py` (regla del último propietario, pura),
  `passwords.py` (generador de la temporal), `policy.py` (los cuatro permisos que añadió este
  change; el catálogo es común y crece con cada módulo — `cleaning` le sumó cinco y dio al
  `CLEANER` su primer permiso más allá del autoservicio),
  `repositories.py` (`UserFilters`, `UserPage`, cotas de paginación), `ports.py`,
  `exceptions.py`, `enums.py` (`SessionRevokedReason` con las dos razones administrativas).
- Aplicación: `backend/app/auth/application/user_admin.py` — los seis casos de uso.
- Infraestructura: `backend/app/auth/infrastructure/repositories.py` — `apply_changes`
  (escritura parcial), traducción del `409`, `count_active_owners_excluding`,
  `lock_tenant_for_admin`, `revoke_all_for_user`.
- API de usuarios: `backend/app/auth/api/` — `users_router.py`, `user_schemas.py`,
  `user_dependencies.py`, `errors.py`.
- Tenant: `backend/app/tenants/` — `domain/{entities,value_objects,repositories,exceptions}.py`,
  `application/use_cases.py`, `infrastructure/repositories.py`, `api/{router,schemas,dependencies,errors}.py`.
- Auditoría: `backend/app/audit/` — `domain/{value_objects,services,actions,repositories,exceptions}.py`
  (`ChangeSet`, `AuditLogFactory`, vocabulario, `AUDITABLE_FIELDS`),
  `infrastructure/repositories.py`.
- Migración: `backend/alembic/versions/b7c41d92e5a3_session_revoked_reason_administrative.py`.
- Tests: `backend/tests/auth/` (`test_user_admin_use_cases.py`, `test_user_admin_api.py`,
  `test_user_admin_authorization.py`, `test_user_admin_isolation.py`,
  `test_last_owner_concurrency.py`, `test_entities.py`, `test_services.py`, `test_passwords.py`),
  `backend/tests/tenants/`, `backend/tests/audit/`.
- Documentación: `docs/user-management.md` (operación).
